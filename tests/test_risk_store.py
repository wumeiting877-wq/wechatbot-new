# -*- coding: utf-8 -*-
"""P5-G3 Gate 1：Risk Store 数据层。不调用 LLM。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from risk_store import (
    DECISION_FAILED,
    DECISION_NEW_RISK,
    DECISION_UNRELATED,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    RELATION_UPDATED_BY,
    RiskStore,
    RiskStoreError,
    make_risk_id,
)
from store_io import atomic_write_json
from task_store import TaskStore
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


class RiskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.store = RiskStore(self.tmpdir.name, topic_store=self.topic_store, task_store=self.task_store)
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
                "created_at": "2026-09-22T14:10:00+08:00",
            }
        )

    def _ready(self, cid=None, topic_id=None, msg_id="msg_seed_000001"):
        cid = cid or self.cid_a
        topic_id = topic_id or self.topic_a
        _seed_topic(self.topic_store, cid, topic_id)
        msg = self._msg(cid, msg_id)
        self.topic_store.add_link(cid, topic_id, msg["id"], TOPIC_CREATED_BY)
        return msg

    def _new_payload(self, msg, **overrides):
        payload = {
            "conversation_id": self.cid_a,
            "topic_id": self.topic_a,
            "title": "今日未修复将影响明日演示",
            "condition_text": "如果今天还修不好",
            "impact_text": "会影响明天现场演示",
            "created_msg_id": msg["id"],
            "created_at": "2026-09-22T14:10:00+08:00",
        }
        payload.update(overrides)
        return payload

    def test_new_risk_normal_and_ids_correct(self):
        msg = self._ready()
        risk = self.store.create_risk(self._new_payload(msg))
        self.assertTrue(risk["id"].startswith("risk_"))
        self.assertEqual(risk["conversation_id"], self.cid_a)
        self.assertEqual(risk["topic_id"], self.topic_a)
        self.assertEqual(risk["status"], "OPEN")
        self.assertEqual(risk["task_id"], "")
        self.assertNotIn("severity", risk)
        self.assertEqual(
            risk["id"],
            make_risk_id(self.cid_a, self.topic_a, msg["id"], 0, "2026-09-22T14:10:00+08:00"),
        )
        links = self.store.links_for_risk(self.cid_a, risk["id"])
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["relation"], RELATION_CREATED_BY)
        self.assertEqual(links[0]["message_id"], msg["id"])

    def test_missing_topic_forbids_risk_write(self):
        msg = self._msg(self.cid_a, "msg_no_topic")
        with self.assertRaises(RiskStoreError) as ctx:
            self.store.create_risk(self._new_payload(msg, topic_id="topic_doesnotexist"))
        self.assertEqual(ctx.exception.code, "TOPIC_NOT_FOUND")
        self.assertEqual(self.store.list_risks(self.cid_a), [])

    def test_topic_from_other_conversation_forbids_write(self):
        _seed_topic(self.topic_store, self.cid_a, self.topic_a, conversation_id=self.cid_b)
        msg = self._msg(self.cid_a, "msg_mismatch")
        with self.assertRaises(RiskStoreError) as ctx:
            self.store.create_risk(self._new_payload(msg))
        self.assertEqual(ctx.exception.code, "TOPIC_CONVERSATION_MISMATCH")
        self.assertEqual(self.store.list_risks(self.cid_a), [])

    def test_task_id_optional_empty(self):
        msg = self._ready()
        risk = self.store.create_risk(self._new_payload(msg, task_id=""))
        self.assertEqual(risk["task_id"], "")

    def test_legal_task_id_can_be_written(self):
        msg = self._ready()
        task = self.task_store.create_task(
            {
                "conversation_id": self.cid_a,
                "topic_id": self.topic_a,
                "title": "处理供应商编码空值",
                "assignee_text": "王强",
                "created_msg_id": msg["id"],
            }
        )
        risk = self.store.create_risk(self._new_payload(msg, task_id=task["id"]))
        self.assertEqual(risk["task_id"], task["id"])

    def test_illegal_task_id_is_not_forged(self):
        msg = self._ready()
        risk = self.store.create_risk(self._new_payload(msg, task_id="not_a_task"))
        self.assertEqual(risk["task_id"], "")
        other = self.store.create_risk(
            self._new_payload(msg, created_msg_id=msg["id"], task_id="task_doesnotexist", title="另一条"),
            ordinal=1,
        )
        self.assertEqual(other["task_id"], "")

    def test_created_by_required_and_related_not_duplicated(self):
        confirm = self._ready(msg_id="msg_confirm")
        context = self._msg(self.cid_a, "msg_context", "现场 Wi-Fi 现在不稳定。")
        risk = self.store.create_risk(
            self._new_payload(confirm),
            related_message_ids=[context["id"]],
        )
        links = self.store.links_for_risk(self.cid_a, risk["id"])
        by_rel = {item["relation"]: item for item in links}
        self.assertEqual(by_rel[RELATION_CREATED_BY]["message_id"], confirm["id"])
        self.assertEqual(by_rel[RELATION_RELATED]["message_id"], context["id"])
        first = self.store.add_link(self.cid_a, risk["id"], context["id"], RELATION_RELATED)
        second = self.store.add_link(self.cid_a, risk["id"], context["id"], RELATION_RELATED)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.links_for_risk(self.cid_a, risk["id"])), 2)

    def test_updated_by_is_correct_and_not_duplicated(self):
        msg = self._ready(msg_id="msg_created")
        risk = self.store.create_risk(self._new_payload(msg))
        later = self._msg(self.cid_a, "msg_update", "如果今晚 8 点前还修不好，明早客户演示会受影响。")
        first = self.store.add_link(self.cid_a, risk["id"], later["id"], RELATION_UPDATED_BY)
        second = self.store.add_link(self.cid_a, risk["id"], later["id"], RELATION_UPDATED_BY)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["relation"], RELATION_UPDATED_BY)
        relations = [item["relation"] for item in self.store.links_for_risk(self.cid_a, risk["id"])]
        self.assertEqual(relations.count(RELATION_UPDATED_BY), 1)
        self.assertEqual(relations.count(RELATION_CREATED_BY), 1)

    def test_status_can_only_be_open(self):
        msg = self._ready()
        for status in ("MITIGATED", "RESOLVED", "CLOSED"):
            with self.assertRaises(RiskStoreError) as ctx:
                self.store.create_risk(self._new_payload(msg, status=status))
            self.assertEqual(ctx.exception.code, "INVALID_STATUS")
        self.assertEqual(self.store.list_risks(self.cid_a), [])

    def test_severity_is_stripped(self):
        msg = self._ready()
        risk = self.store.create_risk(self._new_payload(msg, severity="CRITICAL", severity_text="非常严重"))
        self.assertNotIn("severity", risk)
        self.assertNotIn("severity_text", risk)
        persisted = self.store.get_risk(self.cid_a, risk["id"])
        self.assertNotIn("severity", persisted)
        self.assertEqual(persisted["status"], "OPEN")

    def test_update_cannot_change_status(self):
        msg = self._ready()
        risk = self.store.create_risk(self._new_payload(msg))
        with self.assertRaises(RiskStoreError) as ctx:
            self.store.update_risk(self.cid_a, risk["id"], status="RESOLVED")
        self.assertEqual(ctx.exception.code, "INVALID_STATUS")
        self.assertEqual(self.store.get_risk(self.cid_a, risk["id"])["status"], "OPEN")

    def test_risk_without_created_by_cannot_persist(self):
        self._ready()
        with self.assertRaises(RiskStoreError) as ctx:
            self.store.create_risk(self._new_payload({"id": ""}, created_msg_id=""))
        self.assertEqual(ctx.exception.code, "EVIDENCE_REQUIRED")
        with self.assertRaises(RiskStoreError) as ctx:
            self.store.commit_apply(
                self.cid_a,
                new_risks=[
                    {
                        "id": "risk_noby000000",
                        "conversation_id": self.cid_a,
                        "topic_id": self.topic_a,
                        "title": "x",
                        "condition_text": "如果今天修不好",
                        "impact_text": "影响演示",
                        "status": "OPEN",
                        "created_msg_id": "msg_seed_000001",
                    }
                ],
                new_links=[],
            )
        self.assertEqual(ctx.exception.code, "CREATED_BY_REQUIRED")
        self.assertEqual(self.store.list_risks(self.cid_a), [])

    def test_processing_success_replay_skips_and_failed_can_retry(self):
        msg_id = "msg_proc_000001"
        success = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_NEW_RISK,
                "risk_ids": ["risk_abc"],
            }
        )
        replay = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_UNRELATED,
            }
        )
        self.assertEqual(replay["decision_summary"], DECISION_NEW_RISK)
        self.assertEqual(replay["risk_ids"], success["risk_ids"])
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

    def test_same_message_multiple_risk_ids_do_not_collide(self):
        msg = self._ready(msg_id="msg_multi_00001")
        first = self.store.create_risk(self._new_payload(msg), ordinal=0)
        second = self.store.create_risk(
            self._new_payload(
                msg,
                title="断网无法演示",
                condition_text="如果断网",
                impact_text="系统无法演示",
            ),
            ordinal=1,
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_risks(self.cid_a)), 2)

    def test_conversations_are_isolated(self):
        msg_a = self._ready(self.cid_a, self.topic_a, "msg_iso_a")
        msg_b = self._ready(self.cid_b, self.topic_b, "msg_iso_b")
        self.store.create_risk(self._new_payload(msg_a, conversation_id=self.cid_a, topic_id=self.topic_a))
        self.store.create_risk(
            self._new_payload(
                msg_b,
                conversation_id=self.cid_b,
                topic_id=self.topic_b,
                title="B",
                condition_text="如果断网",
                impact_text="无法演示",
            )
        )
        self.assertEqual(len(self.store.list_risks(self.cid_a)), 1)
        self.assertEqual(len(self.store.list_risks(self.cid_b)), 1)
        self.assertEqual(self.store.list_risks(self.cid_a)[0]["topic_id"], self.topic_a)
        self.assertEqual(self.store.list_risks(self.cid_b)[0]["topic_id"], self.topic_b)

    def test_delete_conversation_risk_data_removes_all(self):
        msg_a = self._ready(self.cid_a, self.topic_a, "msg_del_a")
        self._ready(self.cid_b, self.topic_b, "msg_keep_b")
        self.store.create_risk(self._new_payload(msg_a))
        self.store.write_processing(
            {
                "message_id": msg_a["id"],
                "conversation_id": self.cid_a,
                "decision_summary": DECISION_NEW_RISK,
            }
        )
        keep_msg = self.topic_store.get_message(self.cid_b, "msg_keep_b")
        self.store.create_risk(
            self._new_payload(
                keep_msg,
                conversation_id=self.cid_b,
                topic_id=self.topic_b,
                title="保留",
                condition_text="如果断网",
                impact_text="无法演示",
            )
        )
        self.assertTrue(self.store.delete_conversation_risk_data(self.cid_a))
        self.assertEqual(self.store.list_risks(self.cid_a), [])
        self.assertEqual(self.store.list_links(self.cid_a), [])
        self.assertIsNone(self.store.get_processing(self.cid_a, msg_a["id"]))
        self.assertEqual(len(self.store.list_risks(self.cid_b)), 1)

    def test_forbidden_relations_rejected(self):
        msg = self._ready()
        risk = self.store.create_risk(self._new_payload(msg))
        for relation in ("MITIGATION_EVIDENCE", "RESOLUTION_EVIDENCE"):
            with self.assertRaises(RiskStoreError) as ctx:
                self.store.add_link(self.cid_a, risk["id"], msg["id"], relation)
            self.assertEqual(ctx.exception.code, "INVALID_RELATION")

    def test_missing_condition_or_impact_forbids_create(self):
        msg = self._ready()
        with self.assertRaises(RiskStoreError) as ctx:
            self.store.create_risk(self._new_payload(msg, impact_text=""))
        self.assertEqual(ctx.exception.code, "INVALID_RISK_DECISION")


if __name__ == "__main__":
    unittest.main()
