# -*- coding: utf-8 -*-
"""P6-G4 Direct Create & Collision Evidence Integrity：REF-01 ～ REF-10。

真碰撞 suffix 后 Evidence / processing 必须使用最终 id。
同逻辑 retry 仍 skip。create_* 保持 internal/legacy suffix。
"""

from __future__ import annotations

import inspect
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decision_engine import DECISION_ENGINE_ENABLED, DecisionEngine
from decision_store import DecisionStore
from decision_store import RELATION_CREATED_BY as D_CREATED
from decision_store import RELATION_RELATED as D_RELATED
from decision_store import make_dlink_id
from risk_engine import RISK_ENGINE_ENABLED, RiskEngine
from risk_store import RiskStore
from risk_store import RELATION_CREATED_BY as R_CREATED
from risk_store import RELATION_RELATED as R_RELATED
from risk_store import RELATION_UPDATED_BY as R_UPDATED
from risk_store import make_rlink_id
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED, TaskEngine
from task_store import TaskStore, make_tlink_id
from task_store import RELATION_CREATED_BY as T_CREATED
from task_store import RELATION_RELATED as T_RELATED
from task_store import RELATION_UPDATED_BY as T_UPDATED
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_store import RELATION_CREATED_BY as TOPIC_CREATED
from topic_store import TopicStore

CONV = {
    "id": "conv_p6g4ref01",
    "platform": "WECHAT",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
}
TOPIC_ID = "topic_p6g4ref01"
SHARED_TASK = "task_forcedref01"
SHARED_DEC = "dec_forcedref001"
SHARED_RISK = "risk_forcedref01"
MSG_A = "msg_p6g4_a"
MSG_B = "msg_p6g4_b"
MSG_C = "msg_p6g4_c"
PRIOR = "msg_p6g4_prior"
NOW = "2026-09-22T21:10:00+08:00"


class ScriptedTask:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        evidence = [current_id]
        for item in engine_input.get("recent_topic_messages") or []:
            if item.get("id") and item["id"] not in evidence:
                evidence.append(item["id"])
                break
        return {
            "decisions": [
                {
                    "decision": "NEW_TASK",
                    "title": "修权限",
                    "description": "李娜把权限问题修一下",
                    "assignee_text": "李娜",
                    "due_text": "",
                    "confidence": "HIGH",
                    "evidence_message_ids": evidence,
                    "reason": "scripted new task",
                }
            ]
        }


class ScriptedDecision:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        evidence = [current_id]
        for item in engine_input.get("recent_topic_messages") or []:
            if item.get("id") and item["id"] not in evidence:
                evidence.append(item["id"])
                break
        return {
            "decisions": [
                {
                    "decision": "NEW_DECISION",
                    "title": "采用异常池方案",
                    "decision_text": "就按照异常池方案执行。",
                    "confidence": "HIGH",
                    "evidence_message_ids": evidence,
                    "reason": "scripted new decision",
                }
            ]
        }


class ScriptedRisk:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        evidence = [current_id]
        for item in engine_input.get("recent_topic_messages") or []:
            if item.get("id") and item["id"] not in evidence:
                evidence.append(item["id"])
                break
        return {
            "risks": [
                {
                    "decision": "NEW_RISK",
                    "title": "演示受阻",
                    "condition_text": "如果今天还修不好",
                    "impact_text": "会影响明天现场演示",
                    "confidence": "HIGH",
                    "evidence_message_ids": evidence,
                    "reason": "scripted new risk",
                }
            ]
        }


def _seed_topic(topic_store, cid, topic_id):
    atomic_write_json(
        os.path.join(topic_store.conversation_dir(cid), "topics.json"),
        {
            "topics": [
                {
                    "id": topic_id,
                    "conversation_id": cid,
                    "title": "权限整改",
                    "summary": "质检员仍能看到采购价格",
                    "status": "ACTIVE",
                    "confidence": "HIGH",
                    "created_at": NOW,
                    "updated_at": NOW,
                    "last_message_at": NOW,
                    "message_count": 0,
                    "schema_version": 1,
                }
            ]
        },
    )


def _seed_message(topic_store, msg_id, content):
    record = topic_store.upsert_message(
        {
            "id": msg_id,
            "conversation_id": CONV["id"],
            "platform_message_id": msg_id,
            "sender_name": "周敏",
            "content": content,
            "created_at": NOW,
            "direction": "INBOUND",
            "message_type": "text",
        }
    )
    topic_store.add_link(CONV["id"], TOPIC_ID, record["id"], TOPIC_CREATED)
    return record


def _created_by(links, entity_key, entity_id):
    return [
        item.get("message_id")
        for item in links
        if item.get(entity_key) == entity_id and item.get("relation") == "CREATED_BY"
    ]


def _related(links, entity_key, entity_id):
    return [
        item.get("message_id")
        for item in links
        if item.get(entity_key) == entity_id and item.get("relation") == "RELATED"
    ]


def _updated_by(links, entity_key, entity_id):
    return [
        item.get("message_id")
        for item in links
        if item.get(entity_key) == entity_id and item.get("relation") == "UPDATED_BY"
    ]


class P6G4CollisionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.topic_store = TopicStore(self.root)
        _seed_topic(self.topic_store, CONV["id"], TOPIC_ID)
        _seed_message(self.topic_store, PRIOR, "权限问题还在。")
        _seed_message(self.topic_store, MSG_A, "李娜把权限问题修一下。")
        _seed_message(self.topic_store, MSG_B, "王强也把权限问题修一下。")
        _seed_message(self.topic_store, MSG_C, "补充：改成明天。")
        self.task_store = TaskStore(self.root, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.root, topic_store=self.topic_store)
        self.risk_store = RiskStore(self.root, topic_store=self.topic_store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _task_payload(self, msg_id, title):
        return {
            "id": SHARED_TASK,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": title,
            "description": title,
            "status": "OPEN",
            "assignee_text": "李娜",
            "due_text": "",
            "due_at": "",
            "created_msg_id": msg_id,
            "confidence": "HIGH",
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }

    def _task_links(self, msg_id, include_updated=False):
        rows = [
            {
                "id": make_tlink_id(SHARED_TASK, msg_id, T_CREATED),
                "task_id": SHARED_TASK,
                "message_id": msg_id,
                "relation": T_CREATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
            {
                "id": make_tlink_id(SHARED_TASK, PRIOR, T_RELATED),
                "task_id": SHARED_TASK,
                "message_id": PRIOR,
                "relation": T_RELATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
        ]
        if include_updated:
            rows.append(
                {
                    "id": make_tlink_id(SHARED_TASK, msg_id, T_UPDATED),
                    "task_id": SHARED_TASK,
                    "message_id": msg_id,
                    "relation": T_UPDATED,
                    "confidence": "HIGH",
                    "created_at": NOW,
                }
            )
        return rows

    def _dec_payload(self, msg_id, title):
        return {
            "id": SHARED_DEC,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": title,
            "decision_text": title,
            "summary": title,
            "status": "RECORDED",
            "confidence": "HIGH",
            "created_msg_id": msg_id,
            "supersedes_decision_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }

    def _dec_links(self, msg_id):
        return [
            {
                "id": make_dlink_id(SHARED_DEC, msg_id, D_CREATED),
                "decision_id": SHARED_DEC,
                "message_id": msg_id,
                "relation": D_CREATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
            {
                "id": make_dlink_id(SHARED_DEC, PRIOR, D_RELATED),
                "decision_id": SHARED_DEC,
                "message_id": PRIOR,
                "relation": D_RELATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
        ]

    def _risk_payload(self, msg_id, title):
        return {
            "id": SHARED_RISK,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": title,
            "description": "",
            "condition_text": "如果今天还修不好",
            "impact_text": "会影响明天现场演示",
            "status": "OPEN",
            "confidence": "HIGH",
            "created_msg_id": msg_id,
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }

    def _risk_links(self, msg_id, include_updated=False):
        rows = [
            {
                "id": make_rlink_id(SHARED_RISK, msg_id, R_CREATED),
                "risk_id": SHARED_RISK,
                "message_id": msg_id,
                "relation": R_CREATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
            {
                "id": make_rlink_id(SHARED_RISK, PRIOR, R_RELATED),
                "risk_id": SHARED_RISK,
                "message_id": PRIOR,
                "relation": R_RELATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
        ]
        if include_updated:
            rows.append(
                {
                    "id": make_rlink_id(SHARED_RISK, msg_id, R_UPDATED),
                    "risk_id": SHARED_RISK,
                    "message_id": msg_id,
                    "relation": R_UPDATED,
                    "confidence": "HIGH",
                    "created_at": NOW,
                }
            )
        return rows

    def test_ref_01_task_true_collision_created_by(self):
        first = self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_A, "第一条")],
            new_links=self._task_links(MSG_A),
        )
        second = self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_B, "第二条")],
            new_links=self._task_links(MSG_B),
        )
        ids = [item.get("id") for item in self.task_store.list_tasks(CONV["id"])]
        suffix = SHARED_TASK + "_2"
        self.assertEqual(ids, [SHARED_TASK, suffix])
        self.assertEqual(first["task_ids"], [SHARED_TASK])
        self.assertEqual(second["task_ids"], [suffix])
        links = self.task_store.list_links(CONV["id"])
        self.assertEqual(_created_by(links, "task_id", SHARED_TASK), [MSG_A])
        self.assertEqual(_created_by(links, "task_id", suffix), [MSG_B])
        self.assertNotIn(MSG_B, _created_by(links, "task_id", SHARED_TASK))

    def test_ref_02_decision_true_collision_created_by(self):
        first = self.decision_store.commit_apply(
            CONV["id"],
            new_decisions=[self._dec_payload(MSG_A, "第一条")],
            new_links=self._dec_links(MSG_A),
        )
        second = self.decision_store.commit_apply(
            CONV["id"],
            new_decisions=[self._dec_payload(MSG_B, "第二条")],
            new_links=self._dec_links(MSG_B),
        )
        ids = [item.get("id") for item in self.decision_store.list_decisions(CONV["id"])]
        suffix = SHARED_DEC + "_2"
        self.assertEqual(ids, [SHARED_DEC, suffix])
        self.assertEqual(first["decision_ids"], [SHARED_DEC])
        self.assertEqual(second["decision_ids"], [suffix])
        links = self.decision_store.list_links(CONV["id"])
        self.assertEqual(_created_by(links, "decision_id", SHARED_DEC), [MSG_A])
        self.assertEqual(_created_by(links, "decision_id", suffix), [MSG_B])
        self.assertEqual(len(_created_by(links, "decision_id", SHARED_DEC)), 1)
        self.assertEqual(len(_created_by(links, "decision_id", suffix)), 1)

    def test_ref_03_risk_true_collision_created_by(self):
        first = self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_A, "第一条")],
            new_links=self._risk_links(MSG_A),
        )
        second = self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_B, "第二条")],
            new_links=self._risk_links(MSG_B),
        )
        ids = [item.get("id") for item in self.risk_store.list_risks(CONV["id"])]
        suffix = SHARED_RISK + "_2"
        self.assertEqual(ids, [SHARED_RISK, suffix])
        self.assertEqual(first["risk_ids"], [SHARED_RISK])
        self.assertEqual(second["risk_ids"], [suffix])
        links = self.risk_store.list_links(CONV["id"])
        self.assertEqual(_created_by(links, "risk_id", SHARED_RISK), [MSG_A])
        self.assertEqual(_created_by(links, "risk_id", suffix), [MSG_B])
        self.assertNotIn(MSG_B, _created_by(links, "risk_id", SHARED_RISK))

    def test_ref_04_related_remap_to_suffix(self):
        self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_A, "第一条")],
            new_links=self._task_links(MSG_A),
        )
        self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_B, "第二条")],
            new_links=self._task_links(MSG_B),
        )
        self.decision_store.commit_apply(
            CONV["id"],
            new_decisions=[self._dec_payload(MSG_A, "第一条")],
            new_links=self._dec_links(MSG_A),
        )
        self.decision_store.commit_apply(
            CONV["id"],
            new_decisions=[self._dec_payload(MSG_B, "第二条")],
            new_links=self._dec_links(MSG_B),
        )
        self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_A, "第一条")],
            new_links=self._risk_links(MSG_A),
        )
        self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_B, "第二条")],
            new_links=self._risk_links(MSG_B),
        )
        task_links = self.task_store.list_links(CONV["id"])
        dec_links = self.decision_store.list_links(CONV["id"])
        risk_links = self.risk_store.list_links(CONV["id"])
        self.assertEqual(_related(task_links, "task_id", SHARED_TASK + "_2"), [PRIOR])
        self.assertEqual(_related(dec_links, "decision_id", SHARED_DEC + "_2"), [PRIOR])
        self.assertEqual(_related(risk_links, "risk_id", SHARED_RISK + "_2"), [PRIOR])
        self.assertEqual(_related(task_links, "task_id", SHARED_TASK), [PRIOR])

    def test_ref_05_updated_by_remap_task_and_risk(self):
        self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_A, "第一条")],
            new_links=self._task_links(MSG_A),
        )
        self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_B, "第二条")],
            new_links=self._task_links(MSG_B, include_updated=True),
        )
        self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_A, "第一条")],
            new_links=self._risk_links(MSG_A),
        )
        self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_B, "第二条")],
            new_links=self._risk_links(MSG_B, include_updated=True),
        )
        task_links = self.task_store.list_links(CONV["id"])
        risk_links = self.risk_store.list_links(CONV["id"])
        self.assertEqual(_updated_by(task_links, "task_id", SHARED_TASK + "_2"), [MSG_B])
        self.assertEqual(_updated_by(risk_links, "risk_id", SHARED_RISK + "_2"), [MSG_B])
        self.assertEqual(_updated_by(task_links, "task_id", SHARED_TASK), [])
        self.assertEqual(_updated_by(risk_links, "risk_id", SHARED_RISK), [])

        suffix_task = SHARED_TASK + "_2"
        suffix_risk = SHARED_RISK + "_2"
        self.task_store.commit_apply(
            CONV["id"],
            updates=[{"id": suffix_task, "fields": {"title": "修权限-更新"}, "updated_at": NOW}],
            new_links=[
                {
                    "id": make_tlink_id(suffix_task, MSG_C, T_UPDATED),
                    "task_id": suffix_task,
                    "message_id": MSG_C,
                    "relation": T_UPDATED,
                    "confidence": "HIGH",
                    "created_at": NOW,
                }
            ],
        )
        self.risk_store.commit_apply(
            CONV["id"],
            updates=[{"id": suffix_risk, "fields": {"title": "演示受阻-更新"}, "updated_at": NOW}],
            new_links=[
                {
                    "id": make_rlink_id(suffix_risk, MSG_C, R_UPDATED),
                    "risk_id": suffix_risk,
                    "message_id": MSG_C,
                    "relation": R_UPDATED,
                    "confidence": "HIGH",
                    "created_at": NOW,
                }
            ],
        )
        self.assertIn(MSG_C, _updated_by(self.task_store.list_links(CONV["id"]), "task_id", suffix_task))
        self.assertIn(MSG_C, _updated_by(self.risk_store.list_links(CONV["id"]), "risk_id", suffix_risk))

    def test_ref_06_same_logical_retry_still_skip(self):
        payload = self._task_payload(MSG_A, "第一条")
        links = self._task_links(MSG_A)
        self.task_store.commit_apply(CONV["id"], new_tasks=[payload], new_links=links)
        again = self.task_store.commit_apply(CONV["id"], new_tasks=[dict(payload)], new_links=list(links))
        self.assertEqual(len(self.task_store.list_tasks(CONV["id"])), 1)
        self.assertEqual(again["task_ids"], [SHARED_TASK])
        self.assertFalse(any(item.get("id", "").endswith("_2") for item in self.task_store.list_tasks(CONV["id"])))

        d_payload = self._dec_payload(MSG_A, "第一条")
        d_links = self._dec_links(MSG_A)
        self.decision_store.commit_apply(CONV["id"], new_decisions=[d_payload], new_links=d_links)
        d_again = self.decision_store.commit_apply(
            CONV["id"], new_decisions=[dict(d_payload)], new_links=list(d_links)
        )
        self.assertEqual(len(self.decision_store.list_decisions(CONV["id"])), 1)
        self.assertEqual(d_again["decision_ids"], [SHARED_DEC])

        r_payload = self._risk_payload(MSG_A, "第一条")
        r_links = self._risk_links(MSG_A)
        self.risk_store.commit_apply(CONV["id"], new_risks=[r_payload], new_links=r_links)
        r_again = self.risk_store.commit_apply(CONV["id"], new_risks=[dict(r_payload)], new_links=list(r_links))
        self.assertEqual(len(self.risk_store.list_risks(CONV["id"])), 1)
        self.assertEqual(r_again["risk_ids"], [SHARED_RISK])

    def test_ref_07_processing_records_final_id(self):
        topic = self.topic_store.get_topic(CONV["id"], TOPIC_ID)
        msg_a = self.topic_store.get_message(CONV["id"], MSG_A)
        msg_b = self.topic_store.get_message(CONV["id"], MSG_B)
        task_engine = TaskEngine(
            self.task_store, self.topic_store, extractor=ScriptedTask(), root_dir=ROOT, enabled=True
        )
        with patch("task_engine.make_task_id", return_value=SHARED_TASK):
            first = task_engine.process_record(CONV, topic, msg_a)
            second = task_engine.process_record(CONV, topic, msg_b)
        self.assertEqual(first.decision, "NEW_TASK")
        self.assertEqual(second.decision, "NEW_TASK")
        proc_a = self.task_store.get_processing(CONV["id"], MSG_A)
        proc_b = self.task_store.get_processing(CONV["id"], MSG_B)
        self.assertEqual(proc_a.get("task_ids"), [SHARED_TASK])
        self.assertEqual(proc_b.get("task_ids"), [SHARED_TASK + "_2"])

        decision_engine = DecisionEngine(
            self.decision_store, self.topic_store, extractor=ScriptedDecision(), root_dir=ROOT, enabled=True
        )
        with patch("decision_engine.make_decision_id", return_value=SHARED_DEC):
            d_first = decision_engine.process_record(CONV, topic, msg_a)
            d_second = decision_engine.process_record(CONV, topic, msg_b)
        self.assertEqual(d_first.decision, "NEW_DECISION")
        self.assertEqual(d_second.decision, "NEW_DECISION")
        self.assertEqual(self.decision_store.get_processing(CONV["id"], MSG_A).get("decision_ids"), [SHARED_DEC])
        self.assertEqual(
            self.decision_store.get_processing(CONV["id"], MSG_B).get("decision_ids"),
            [SHARED_DEC + "_2"],
        )

        risk_engine = RiskEngine(
            self.risk_store,
            self.topic_store,
            task_store=self.task_store,
            extractor=ScriptedRisk(),
            root_dir=ROOT,
            enabled=True,
        )
        with patch("risk_engine.make_risk_id", return_value=SHARED_RISK):
            r_first = risk_engine.process_record(CONV, topic, msg_a)
            r_second = risk_engine.process_record(CONV, topic, msg_b)
        self.assertEqual(r_first.decision, "NEW_RISK")
        self.assertEqual(r_second.decision, "NEW_RISK")
        self.assertEqual(self.risk_store.get_processing(CONV["id"], MSG_A).get("risk_ids"), [SHARED_RISK])
        self.assertEqual(self.risk_store.get_processing(CONV["id"], MSG_B).get("risk_ids"), [SHARED_RISK + "_2"])

    def test_ref_08_suffix_entity_evidence_complete(self):
        self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_A, "第一条")],
            new_links=self._task_links(MSG_A),
        )
        self.task_store.commit_apply(
            CONV["id"],
            new_tasks=[self._task_payload(MSG_B, "第二条")],
            new_links=self._task_links(MSG_B),
        )
        self.decision_store.commit_apply(
            CONV["id"],
            new_decisions=[self._dec_payload(MSG_A, "第一条")],
            new_links=self._dec_links(MSG_A),
        )
        self.decision_store.commit_apply(
            CONV["id"],
            new_decisions=[self._dec_payload(MSG_B, "第二条")],
            new_links=self._dec_links(MSG_B),
        )
        self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_A, "第一条")],
            new_links=self._risk_links(MSG_A),
        )
        self.risk_store.commit_apply(
            CONV["id"],
            new_risks=[self._risk_payload(MSG_B, "第二条")],
            new_links=self._risk_links(MSG_B),
        )
        task_links = self.task_store.list_links(CONV["id"])
        dec_links = self.decision_store.list_links(CONV["id"])
        risk_links = self.risk_store.list_links(CONV["id"])
        for entity_id in (SHARED_TASK, SHARED_TASK + "_2"):
            self.assertEqual(len(_created_by(task_links, "task_id", entity_id)), 1)
            self.assertEqual(len(_related(task_links, "task_id", entity_id)), 1)
        for entity_id in (SHARED_DEC, SHARED_DEC + "_2"):
            self.assertEqual(len(_created_by(dec_links, "decision_id", entity_id)), 1)
            self.assertEqual(len(_related(dec_links, "decision_id", entity_id)), 1)
        for entity_id in (SHARED_RISK, SHARED_RISK + "_2"):
            self.assertGreaterEqual(len(_created_by(risk_links, "risk_id", entity_id)), 1)
            self.assertEqual(len(_related(risk_links, "risk_id", entity_id)), 1)
        hanging = [
            item
            for item in task_links
            if item.get("task_id") == SHARED_TASK and item.get("message_id") == MSG_B
        ]
        self.assertEqual(hanging, [])

    def test_ref_09_create_star_direct_legacy_suffix(self):
        first = self.task_store.create_task(
            {
                "id": SHARED_TASK,
                "conversation_id": CONV["id"],
                "topic_id": TOPIC_ID,
                "title": "直连一",
                "created_msg_id": MSG_A,
                "created_at": NOW,
            }
        )
        second = self.task_store.create_task(
            {
                "id": SHARED_TASK,
                "conversation_id": CONV["id"],
                "topic_id": TOPIC_ID,
                "title": "直连二",
                "created_msg_id": MSG_B,
                "created_at": NOW,
            }
        )
        self.assertEqual(first["id"], SHARED_TASK)
        self.assertEqual(second["id"], SHARED_TASK + "_2")
        task_links = self.task_store.list_links(CONV["id"])
        self.assertEqual(_created_by(task_links, "task_id", first["id"]), [MSG_A])
        self.assertEqual(_created_by(task_links, "task_id", second["id"]), [MSG_B])

        d_first = self.decision_store.create_decision(
            {
                "id": SHARED_DEC,
                "conversation_id": CONV["id"],
                "topic_id": TOPIC_ID,
                "title": "直连决策一",
                "decision_text": "按异常池执行",
                "created_msg_id": MSG_A,
                "created_at": NOW,
            }
        )
        d_second = self.decision_store.create_decision(
            {
                "id": SHARED_DEC,
                "conversation_id": CONV["id"],
                "topic_id": TOPIC_ID,
                "title": "直连决策二",
                "decision_text": "另一条也按异常池",
                "created_msg_id": MSG_B,
                "created_at": NOW,
            }
        )
        self.assertEqual(d_second["id"], SHARED_DEC + "_2")
        dec_links = self.decision_store.list_links(CONV["id"])
        self.assertEqual(_created_by(dec_links, "decision_id", d_first["id"]), [MSG_A])
        self.assertEqual(_created_by(dec_links, "decision_id", d_second["id"]), [MSG_B])

        r_first = self.risk_store.create_risk(
            {
                "id": SHARED_RISK,
                "conversation_id": CONV["id"],
                "topic_id": TOPIC_ID,
                "title": "直连风险一",
                "condition_text": "如果今天还修不好",
                "impact_text": "会影响明天现场演示",
                "created_msg_id": MSG_A,
                "created_at": NOW,
            }
        )
        r_second = self.risk_store.create_risk(
            {
                "id": SHARED_RISK,
                "conversation_id": CONV["id"],
                "topic_id": TOPIC_ID,
                "title": "直连风险二",
                "condition_text": "如果明天也修不好",
                "impact_text": "会影响后天演示",
                "created_msg_id": MSG_B,
                "created_at": NOW,
            }
        )
        self.assertEqual(r_second["id"], SHARED_RISK + "_2")
        risk_links = self.risk_store.list_links(CONV["id"])
        self.assertEqual(_created_by(risk_links, "risk_id", r_first["id"]), [MSG_A])
        self.assertEqual(_created_by(risk_links, "risk_id", r_second["id"]), [MSG_B])

        import bot
        import decision_engine
        import decision_sidepath
        import risk_engine
        import risk_sidepath
        import task_engine
        import task_sidepath
        import webui_data

        for mod in (
            task_engine,
            decision_engine,
            risk_engine,
            task_sidepath,
            decision_sidepath,
            risk_sidepath,
            bot,
            webui_data,
        ):
            source = inspect.getsource(mod)
            self.assertNotIn("create_task(", source, mod.__name__)
            self.assertNotIn("create_decision(", source, mod.__name__)
            self.assertNotIn("create_risk(", source, mod.__name__)

    def test_ref_10_engine_flags_remain_false(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def test_id_generators_unchanged(self):
        import task_store
        import decision_store
        import risk_store

        self.assertIn("conversation_id or \"\"", inspect.getsource(task_store.make_task_id))
        self.assertIn("created_msg_id or \"\"", inspect.getsource(task_store.make_task_id))
        self.assertIn("conversation_id or \"\"", inspect.getsource(decision_store.make_decision_id))
        self.assertIn("conversation_id or \"\"", inspect.getsource(risk_store.make_risk_id))
        self.assertIn("id_map", inspect.getsource(task_store.TaskStore.commit_apply))
        self.assertIn("id_map", inspect.getsource(decision_store.DecisionStore.commit_apply))
        self.assertIn("id_map", inspect.getsource(risk_store.RiskStore.commit_apply))


if __name__ == "__main__":
    unittest.main()
