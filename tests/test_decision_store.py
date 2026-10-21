# -*- coding: utf-8 -*-
"""P5-G1 Gate 1：Decision Store 数据层。不调用 LLM。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decision_store import (
    DECISION_FAILED,
    DECISION_NEW_DECISION,
    DECISION_UNRELATED,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    DecisionStore,
    DecisionStoreError,
    make_decision_id,
)
from store_io import atomic_write_json
from topic_store import RELATION_CREATED_BY as TOPIC_CREATED_BY
from topic_store import TopicStore


def _seed_topic(topic_store, cid, topic_id, title="ERP 数据同步异常", conversation_id=None):
    topics = list(topic_store.list_topics(cid))
    if any(item.get("id") == topic_id for item in topics):
        return
    topics.append(
        {
            "id": topic_id,
            "conversation_id": conversation_id or cid,
            "title": title,
            "summary": title,
            "status": "ACTIVE",
            "confidence": "HIGH",
            "created_at": "2026-09-22T09:00:00+08:00",
            "updated_at": "2026-09-22T09:00:00+08:00",
            "last_message_at": "2026-09-22T09:00:00+08:00",
            "message_count": 0,
            "schema_version": 1,
        }
    )
    atomic_write_json(os.path.join(topic_store.conversation_dir(cid), "topics.json"), {"topics": topics})


class DecisionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.store = DecisionStore(self.tmpdir.name, topic_store=self.topic_store)
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
                "created_at": "2026-09-22T10:21:00+08:00",
            }
        )

    def _ready(self, cid=None, topic_id=None, msg_id="msg_seed_000001"):
        cid = cid or self.cid_a
        topic_id = topic_id or self.topic_a
        _seed_topic(self.topic_store, cid, topic_id)
        msg = self._msg(cid, msg_id)
        self.topic_store.add_link(cid, topic_id, msg["id"], TOPIC_CREATED_BY)
        return msg

    def test_decision_create_normal_and_ids_correct(self):
        msg = self._ready()
        decision = self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "采用异常池方案",
                "decision_text": "可以，就按照异常池方案执行。",
                "created_msg_id": msg["id"],
                "created_at": "2026-09-22T10:21:00+08:00",
            }
        )
        self.assertTrue(decision["id"].startswith("dec_"))
        self.assertEqual(decision["conversation_id"], self.cid_a)
        self.assertEqual(decision["topic_id"], self.topic_a)
        self.assertEqual(decision["status"], "RECORDED")
        self.assertIsNone(decision["supersedes_decision_id"])
        self.assertNotIn("task_id", decision)
        self.assertEqual(
            decision["id"],
            make_decision_id(self.cid_a, self.topic_a, msg["id"], 0, "2026-09-22T10:21:00+08:00"),
        )
        links = self.store.links_for_decision(self.cid_a, decision["id"])
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["relation"], RELATION_CREATED_BY)
        self.assertEqual(links[0]["message_id"], msg["id"])

    def test_missing_topic_forbids_decision_write(self):
        msg = self._msg(self.cid_a, "msg_no_topic")
        with self.assertRaises(DecisionStoreError) as ctx:
            self.store.create_decision(
                {
                    "conversation_id": self.cid_a,
                    "topic_id": "topic_doesnotexist",
                    "title": "x",
                    "decision_text": "x",
                    "created_msg_id": msg["id"],
                }
            )
        self.assertEqual(ctx.exception.code, "TOPIC_NOT_FOUND")
        self.assertEqual(self.store.list_decisions(self.cid_a), [])

    def test_topic_from_other_conversation_forbids_write(self):
        _seed_topic(self.topic_store, self.cid_a, self.topic_a, conversation_id=self.cid_b)
        msg = self._msg(self.cid_a, "msg_mismatch")
        with self.assertRaises(DecisionStoreError) as ctx:
            self.store.create_decision(
                {
                    "conversation_id": self.cid_a,
                    "topic_id": self.topic_a,
                    "title": "x",
                    "decision_text": "x",
                    "created_msg_id": msg["id"],
                }
            )
        self.assertEqual(ctx.exception.code, "TOPIC_CONVERSATION_MISMATCH")
        self.assertEqual(self.store.list_decisions(self.cid_a), [])

    def test_nickname_conversation_id_rejected(self):
        with self.assertRaises(DecisionStoreError) as ctx:
            self.store.create_decision(
                {
                    "conversation_id": "智群Demo",
                    "topic_id": self.topic_a,
                    "title": "x",
                    "decision_text": "x",
                    "created_msg_id": "msg_x",
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_CONVERSATION_ID")

    def test_created_by_is_required_and_related_not_duplicated(self):
        confirm = self._ready(msg_id="msg_confirm")
        suggest = self._msg(self.cid_a, "msg_suggest", "我建议先进异常池。")
        decision = self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "采用异常池方案",
                "decision_text": "就按照异常池方案执行。",
                "created_msg_id": confirm["id"],
            },
            related_message_ids=[suggest["id"]],
        )
        links = self.store.links_for_decision(self.cid_a, decision["id"])
        by_rel = {item["relation"]: item for item in links}
        self.assertEqual(by_rel[RELATION_CREATED_BY]["message_id"], confirm["id"])
        self.assertEqual(by_rel[RELATION_RELATED]["message_id"], suggest["id"])
        first = self.store.add_link(self.cid_a, decision["id"], suggest["id"], RELATION_RELATED)
        second = self.store.add_link(self.cid_a, decision["id"], suggest["id"], RELATION_RELATED)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.links_for_decision(self.cid_a, decision["id"])), 2)

    def test_decision_without_created_by_cannot_persist(self):
        self._ready()
        with self.assertRaises(DecisionStoreError) as ctx:
            self.store.create_decision(
                {
                    "conversation_id": self.cid_a,
                    "topic_id": self.topic_a,
                    "title": "x",
                    "decision_text": "x",
                    "created_msg_id": "",
                }
            )
        self.assertEqual(ctx.exception.code, "EVIDENCE_REQUIRED")
        with self.assertRaises(DecisionStoreError) as ctx:
            self.store.commit_apply(
                self.cid_a,
                new_decisions=[
                    {
                        "id": "dec_noby000000",
                        "conversation_id": self.cid_a,
                        "topic_id": self.topic_a,
                        "title": "x",
                        "decision_text": "x",
                        "status": "RECORDED",
                        "created_msg_id": "msg_seed_000001",
                    }
                ],
                new_links=[],
            )
        self.assertEqual(ctx.exception.code, "CREATED_BY_REQUIRED")
        self.assertEqual(self.store.list_decisions(self.cid_a), [])

    def test_same_message_multiple_decision_ids_do_not_collide(self):
        msg = self._ready(msg_id="msg_multi_00001")
        first = self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "采用异常池方案",
                "decision_text": "按异常池执行",
                "created_msg_id": msg["id"],
                "created_at": "2026-09-22T10:21:00+08:00",
            },
            ordinal=0,
        )
        second = self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "使用 demo-viewer",
                "decision_text": "现场演示使用 demo-viewer",
                "created_msg_id": msg["id"],
                "created_at": "2026-09-22T10:21:00+08:00",
            },
            ordinal=1,
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_decisions(self.cid_a)), 2)

    def test_legal_supersedes_keeps_old_text(self):
        old_msg = self._ready(msg_id="msg_old_incr")
        old = self.store.create_decision(
            {
                "id": "dec_demo_incr",
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "采用增量同步",
                "decision_text": "决定使用增量同步。",
                "created_msg_id": old_msg["id"],
            }
        )
        new_msg = self._msg(self.cid_a, "msg_new_full", "改成全量同步。")
        self.topic_store.add_link(self.cid_a, self.topic_a, new_msg["id"], TOPIC_CREATED_BY)
        new = self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "改用全量同步",
                "decision_text": "改成全量同步。",
                "created_msg_id": new_msg["id"],
                "supersedes_decision_id": old["id"],
            }
        )
        persisted_old = self.store.get_decision(self.cid_a, old["id"])
        self.assertEqual(persisted_old["decision_text"], "决定使用增量同步。")
        self.assertEqual(persisted_old["status"], "RECORDED")
        self.assertEqual(new["supersedes_decision_id"], "dec_demo_incr")
        self.assertEqual(new["status"], "RECORDED")
        self.assertEqual(new["decision_text"], "改成全量同步。")

    def test_illegal_supersedes_id_forbids_write(self):
        msg = self._ready()
        with self.assertRaises(DecisionStoreError) as ctx:
            self.store.create_decision(
                {
                    "conversation_id": self.cid_a,
                    "topic_id": self.topic_a,
                    "title": "x",
                    "decision_text": "x",
                    "created_msg_id": msg["id"],
                    "supersedes_decision_id": "dec_doesnotexist",
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_SUPERSEDES_DECISION_ID")
        self.assertEqual(self.store.list_decisions(self.cid_a), [])

    def test_processing_success_replay_skips_and_failed_can_retry(self):
        msg_id = "msg_proc_000001"
        success = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_NEW_DECISION,
                "decision_ids": ["dec_abc"],
            }
        )
        replay = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_UNRELATED,
            }
        )
        self.assertEqual(replay["decision_summary"], DECISION_NEW_DECISION)
        self.assertEqual(replay["decision_ids"], success["decision_ids"])
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

    def test_conversations_are_isolated(self):
        msg_a = self._ready(self.cid_a, self.topic_a, "msg_iso_a")
        msg_b = self._ready(self.cid_b, self.topic_b, "msg_iso_b")
        self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "A",
                "decision_text": "A 方案",
                "created_msg_id": msg_a["id"],
            }
        )
        self.store.create_decision(
            {
                "conversation_id": self.cid_b,
                "topic_id": self.topic_b,
                "title": "B",
                "decision_text": "B 方案",
                "created_msg_id": msg_b["id"],
            }
        )
        self.assertEqual(len(self.store.list_decisions(self.cid_a)), 1)
        self.assertEqual(len(self.store.list_decisions(self.cid_b)), 1)
        self.assertEqual(self.store.list_decisions(self.cid_a)[0]["topic_id"], self.topic_a)
        self.assertEqual(self.store.list_decisions(self.cid_b)[0]["topic_id"], self.topic_b)

    def test_delete_conversation_decision_data_removes_all(self):
        msg_a = self._ready(self.cid_a, self.topic_a, "msg_del_a")
        self._ready(self.cid_b, self.topic_b, "msg_keep_b")
        self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "待删",
                "decision_text": "待删方案",
                "created_msg_id": msg_a["id"],
            }
        )
        self.store.write_processing(
            {
                "message_id": msg_a["id"],
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_NEW_DECISION,
            }
        )
        keep_msg = self.topic_store.get_message(self.cid_b, "msg_keep_b")
        self.store.create_decision(
            {
                "conversation_id": self.cid_b,
                "topic_id": self.topic_b,
                "title": "保留",
                "decision_text": "保留方案",
                "created_msg_id": keep_msg["id"],
            }
        )
        self.assertTrue(self.store.delete_conversation_decision_data(self.cid_a))
        self.assertEqual(self.store.list_decisions(self.cid_a), [])
        self.assertEqual(self.store.list_links(self.cid_a), [])
        self.assertIsNone(self.store.get_processing(self.cid_a, msg_a["id"]))
        self.assertEqual(len(self.store.list_decisions(self.cid_b)), 1)

    def test_v1_cannot_write_superseded_status(self):
        msg = self._ready()
        with self.assertRaises(DecisionStoreError) as ctx:
            self.store.create_decision(
                {
                    "conversation_id": self.cid_a,
                    "topic_id": self.topic_a,
                    "title": "x",
                    "decision_text": "x",
                    "created_msg_id": msg["id"],
                    "status": "SUPERSEDED",
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_STATUS")

    def test_forbidden_relations_rejected(self):
        msg = self._ready()
        decision = self.store.create_decision(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "x",
                "decision_text": "x",
                "created_msg_id": msg["id"],
            }
        )
        for relation in ("UPDATED_BY", "CONFIRMED_BY", "SUPERSEDED_BY"):
            with self.assertRaises(DecisionStoreError) as ctx:
                self.store.add_link(self.cid_a, decision["id"], msg["id"], relation)
            self.assertEqual(ctx.exception.code, "INVALID_RELATION")


if __name__ == "__main__":
    unittest.main()
