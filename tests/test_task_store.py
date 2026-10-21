# -*- coding: utf-8 -*-
"""P4-G1 Gate 1：Task Store 数据层。不调用 LLM。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from store_io import atomic_write_json
from task_store import (
    DECISION_FAILED,
    DECISION_NEW_TASK,
    DECISION_UNRELATED,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    TaskStore,
    TaskStoreError,
    make_task_id,
)
from topic_store import RELATION_CREATED_BY as TOPIC_CREATED_BY
from topic_store import TopicStore


def _seed_topic(topic_store, cid, topic_id, title="ERP 数据同步异常"):
    topics = list(topic_store.list_topics(cid))
    if any(item.get("id") == topic_id for item in topics):
        return
    topics.append(
        {
            "id": topic_id,
            "conversation_id": cid,
            "title": title,
            "summary": title,
            "status": "ACTIVE",
            "confidence": "HIGH",
            "created_at": "2026-09-20T09:00:00+08:00",
            "updated_at": "2026-09-20T09:00:00+08:00",
            "last_message_at": "2026-09-20T09:00:00+08:00",
            "message_count": 0,
            "schema_version": 1,
        }
    )
    atomic_write_json(os.path.join(topic_store.conversation_dir(cid), "topics.json"), {"topics": topics})


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.cid_a = "conv_aaaaaaaaaaaa"
        self.cid_b = "conv_bbbbbbbbbbbb"
        self.topic_a = "topic_aaaaaaaaaa"
        self.topic_b = "topic_bbbbbbbbbb"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _msg(self, cid, msg_id, content="x"):
        return self.topic_store.upsert_message(
            {
                "id": msg_id,
                "conversation_id": cid,
                "platform_message_id": msg_id,
                "sender_name": "周敏",
                "content": content,
                "created_at": "2026-09-20T09:08:00+08:00",
            }
        )

    def _ready(self, cid=None, topic_id=None, msg_id="msg_seed_000001"):
        cid = cid or self.cid_a
        topic_id = topic_id or self.topic_a
        _seed_topic(self.topic_store, cid, topic_id)
        msg = self._msg(cid, msg_id)
        self.topic_store.add_link(cid, topic_id, msg["id"], TOPIC_CREATED_BY)
        return msg

    def test_task_create_normal_and_ids_correct(self):
        msg = self._ready()
        task = self.store.create_task(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "处理供应商编码空值规则",
                "assignee_text": "王强",
                "due_text": "今天 16 点前",
                "created_msg_id": msg["id"],
                "created_at": "2026-09-20T09:08:00+08:00",
            }
        )
        self.assertTrue(task["id"].startswith("task_"))
        self.assertEqual(task["conversation_id"], self.cid_a)
        self.assertEqual(task["topic_id"], self.topic_a)
        self.assertEqual(task["status"], "OPEN")
        self.assertEqual(task["due_at"], "")
        self.assertEqual(task["id"], make_task_id(self.cid_a, self.topic_a, msg["id"], 0, "2026-09-20T09:08:00+08:00"))
        links = self.store.links_for_task(self.cid_a, task["id"])
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["relation"], RELATION_CREATED_BY)

    def test_missing_topic_forbids_task_write(self):
        msg = self._msg(self.cid_a, "msg_no_topic")
        with self.assertRaises(TaskStoreError) as ctx:
            self.store.create_task(
                {
                    "conversation_id": self.cid_a,
                    "topic_id": "topic_doesnotexist",
                    "title": "x",
                    "created_msg_id": msg["id"],
                }
            )
        self.assertEqual(ctx.exception.code, "TOPIC_NOT_FOUND")
        self.assertEqual(self.store.list_tasks(self.cid_a), [])

    def test_nickname_conversation_id_rejected(self):
        with self.assertRaises(TaskStoreError) as ctx:
            self.store.create_task(
                {
                    "conversation_id": "智群Demo",
                    "topic_id": self.topic_a,
                    "title": "x",
                    "created_msg_id": "msg_x",
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_CONVERSATION_ID")

    def test_link_not_duplicated(self):
        msg = self._ready()
        task = self.store.create_task(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "处理空值规则",
                "assignee_text": "王强",
                "created_msg_id": msg["id"],
            }
        )
        first = self.store.add_link(self.cid_a, task["id"], msg["id"], RELATION_CREATED_BY)
        second = self.store.add_link(self.cid_a, task["id"], msg["id"], RELATION_CREATED_BY)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_links(self.cid_a)), 1)
        self.store.add_link(self.cid_a, task["id"], msg["id"], RELATION_RELATED)
        self.assertEqual(len(self.store.list_links(self.cid_a)), 2)

    def test_processing_success_replay_skips_and_failed_can_retry(self):
        msg_id = "msg_proc_000001"
        success = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_NEW_TASK,
                "task_ids": ["task_abc"],
            }
        )
        replay = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_UNRELATED,
            }
        )
        self.assertEqual(replay["decision_summary"], DECISION_NEW_TASK)
        self.assertEqual(replay["task_ids"], success["task_ids"])
        self.assertTrue(self.store.has_successful_processing(self.cid_a, msg_id))

        fail_id = "msg_proc_failed01"
        self.store.write_processing(
            {
                "message_id": fail_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_FAILED,
                "error": "timeout",
            }
        )
        self.assertFalse(self.store.has_successful_processing(self.cid_a, fail_id))
        retried = self.store.write_processing(
            {
                "message_id": fail_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_UNRELATED,
            }
        )
        self.assertEqual(retried["decision_summary"], DECISION_UNRELATED)
        self.assertTrue(self.store.has_successful_processing(self.cid_a, fail_id))

    def test_same_message_multiple_task_ids_do_not_collide(self):
        msg = self._ready(msg_id="msg_multi_00001")
        first = self.store.create_task(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "处理供应商编码",
                "assignee_text": "王强",
                "created_msg_id": msg["id"],
                "created_at": "2026-09-20T09:08:10+08:00",
            },
            ordinal=0,
        )
        second = self.store.create_task(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "修复权限问题",
                "assignee_text": "李娜",
                "created_msg_id": msg["id"],
                "created_at": "2026-09-20T09:08:10+08:00",
            },
            ordinal=1,
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_tasks(self.cid_a)), 2)

    def test_task_update_does_not_create_duplicate(self):
        msg = self._ready()
        task = self.store.create_task(
            {
                "id": "task_demo_nullrule",
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "处理供应商编码空值规则",
                "assignee_text": "王强",
                "due_text": "今天 16 点前",
                "created_msg_id": msg["id"],
            }
        )
        updated = self.store.update_task(self.cid_a, task["id"], due_text="17 点前", assignee_text="")
        self.assertEqual(len(self.store.list_tasks(self.cid_a)), 1)
        self.assertEqual(updated["due_text"], "17 点前")
        self.assertEqual(updated["assignee_text"], "王强")
        self.assertEqual(updated["status"], "OPEN")

    def test_delete_conversation_task_data_removes_all(self):
        msg_a = self._ready(self.cid_a, self.topic_a, "msg_del_a")
        self._ready(self.cid_b, self.topic_b, "msg_keep_b")
        self.store.create_task(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "待删",
                "assignee_text": "王强",
                "created_msg_id": msg_a["id"],
            }
        )
        self.store.write_processing(
            {
                "message_id": msg_a["id"],
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_NEW_TASK,
            }
        )
        keep_msg = self.topic_store.get_message(self.cid_b, "msg_keep_b")
        self.store.create_task(
            {
                "conversation_id": self.cid_b,
                "topic_id": self.topic_b,
                "title": "保留",
                "assignee_text": "李娜",
                "created_msg_id": keep_msg["id"],
            }
        )
        self.assertTrue(self.store.delete_conversation_task_data(self.cid_a))
        self.assertEqual(self.store.list_tasks(self.cid_a), [])
        self.assertEqual(self.store.list_links(self.cid_a), [])
        self.assertIsNone(self.store.get_processing(self.cid_a, msg_a["id"]))
        self.assertEqual(len(self.store.list_tasks(self.cid_b)), 1)

    def test_conversations_are_isolated(self):
        msg_a = self._ready(self.cid_a, self.topic_a, "msg_iso_a")
        msg_b = self._ready(self.cid_b, self.topic_b, "msg_iso_b")
        self.store.create_task(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "A",
                "assignee_text": "王强",
                "created_msg_id": msg_a["id"],
            }
        )
        self.store.create_task(
            {
                "conversation_id": self.cid_b,
                "topic_id": self.topic_b,
                "title": "B",
                "assignee_text": "李娜",
                "created_msg_id": msg_b["id"],
            }
        )
        self.assertEqual(len(self.store.list_tasks(self.cid_a)), 1)
        self.assertEqual(len(self.store.list_tasks(self.cid_b)), 1)
        self.assertEqual(self.store.list_tasks(self.cid_a)[0]["topic_id"], self.topic_a)
        self.assertEqual(self.store.list_tasks(self.cid_b)[0]["topic_id"], self.topic_b)

    def test_v1_cannot_write_done_status(self):
        msg = self._ready()
        with self.assertRaises(TaskStoreError) as ctx:
            self.store.create_task(
                {
                    "conversation_id": self.cid_a,
                    "topic_id": self.topic_a,
                    "title": "x",
                    "assignee_text": "王强",
                    "created_msg_id": msg["id"],
                    "status": "DONE",
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_STATUS")


if __name__ == "__main__":
    unittest.main()
