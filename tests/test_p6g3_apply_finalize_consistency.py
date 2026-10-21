# -*- coding: utf-8 -*-
"""P6-G3 Apply / Finalize Consistency：CONSIST-01 ～ CONSIST-10。

apply 已成功 + finalize / processing SUCCESS 写入失败
→ 显式 retry 不得复制 Task / Decision / Risk，Evidence 不重复，
processing 必须恢复到确定成功状态。
"""

from __future__ import annotations

import inspect
import logging
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED, DecisionEngine
from decision_extractor_client import HeuristicDecisionExtractor
from decision_sidepath import DecisionSidepath, reset_decision_sidepath
from decision_store import DecisionStore
from decision_store import RELATION_CREATED_BY as D_CREATED
from decision_store import RELATION_RELATED as D_RELATED
from downstream_retry import (
    EVENT_REJECTED,
    EVENT_REQUESTED,
    EVENT_SUCCESS,
    ERROR_ENGINE_DISABLED,
    ERROR_NOT_RETRYABLE,
    ERROR_STOPPED,
    DownstreamRetryService,
    retry_downstream,
)
from message.bind import bind_host
from message.identity import InboundMessage
from risk_engine import RISK_ENGINE_ENABLED, RiskEngine
from risk_extractor_client import HeuristicRiskExtractor
from risk_sidepath import RiskSidepath, reset_risk_sidepath
from risk_store import RiskStore
from risk_store import RELATION_CREATED_BY as R_CREATED
from risk_store import RELATION_RELATED as R_RELATED
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED, TaskEngine
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import TaskSidepath, reset_task_sidepath
from task_store import TaskStore, make_task_id, make_tlink_id
from task_store import RELATION_CREATED_BY as T_CREATED
from task_store import RELATION_RELATED as T_RELATED
from topic_engine import TOPIC_ENGINE_ENABLED, resolve_topic_conversation
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import EVENT_TOPIC_REPLAY, TopicSidepath, reset_sidepath, try_enqueue_topic_sidepath
from topic_store import RELATION_CREATED_BY as TOPIC_CREATED
from topic_store import TopicStore

CONV = {
    "id": "conv_p6g3consist01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_p6g3@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
    "agent_config_id": "agt_p6g3",
}
TOPIC_ID = "topic_p6g3consist01"
BOT_WXID = "wxid_bot_p6g3"
BOT_NAME = "测试助手"
NEW_TOPIC_TEXT = "ERP 同步今天还是有问题。"
TASK_TEXT = "李娜把权限问题修一下。"
PRIOR_TEXT = "权限问题还在。"


class CountingExtractor:
    def __init__(self, inner=None, *, boom=False):
        self.inner = inner
        self.boom = boom
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        if self.boom:
            raise TimeoutError("p6g3 extractor boom")
        if self.inner is None:
            raise RuntimeError("missing inner extractor")
        return self.inner.extract(engine_input, prompt_content)


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


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p6g3_consist")
        self.user_names = ["测试群"]
        self.ACCEPT_ALL_GROUP_CHAT_MESSAGES = False
        self.ENABLE_GROUP_AT_REPLY = True
        self.ENABLE_GROUP_KEYWORD_REPLY = False
        self.GROUP_KEYWORD_LIST = []
        self.GROUP_CHAT_RESPONSE_PROBABILITY = 100
        self.GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY = True
        self.ENABLE_EMOJI_RECOGNITION = False
        self.bot_last_sent_msg = {}
        self.user_last_msg = {}
        self.replies = []
        self.conversations = [dict(CONV)]
        self.root_dir = root_dir
        self.can_send_messages = True

    def is_user_group_chat(self, _who):
        return True

    def handle_wxauto_message(self, msg, who):
        self.replies.append((who, getattr(msg, "content", "")))

    def handle_emoji_message(self, msg, who):
        self.replies.append((who, "emoji"))

    def recognize_image_with_moonshot(self, *_a, **_k):
        return ""


def _inbound(**kwargs):
    data = {
        "platform_message_id": kwargs.pop("platform_message_id", "pid-p6g3-1"),
        "conversation_id": kwargs.pop("conversation_id", "room_p6g3@chatroom"),
        "chat_name": kwargs.pop("chat_name", "测试群"),
        "chat_wxid": kwargs.pop("chat_wxid", "room_p6g3@chatroom"),
        "sender_id": kwargs.pop("sender_id", 88),
        "sender_wxid": kwargs.pop("sender_wxid", "wxid_zhangsan"),
        "sender_name": kwargs.pop("sender_name", "张三"),
        "content": kwargs.pop("content", NEW_TOPIC_TEXT),
        "raw_type": kwargs.pop("raw_type", "text"),
        "direction": kwargs.pop("direction", "INBOUND"),
        "create_time": kwargs.pop("create_time", 1710000000),
        "attr": kwargs.pop("attr", "friend"),
    }
    data.update(kwargs)
    return InboundMessage(**data)


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
                    "created_at": "2026-09-22T20:00:00+08:00",
                    "updated_at": "2026-09-22T20:00:00+08:00",
                    "last_message_at": "2026-09-22T20:00:00+08:00",
                    "message_count": 0,
                    "schema_version": 1,
                }
            ]
        },
    )


def _is_suffix_id(entity_id: str) -> bool:
    value = str(entity_id or "")
    return value.endswith("_2") or value.endswith("_3")


class P6G3ApplyFinalizeTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.runtime.set_identity(bot_wxid=BOT_WXID, bot_name=BOT_NAME, login_account=BOT_NAME)
        self.host = FakeHost(self.runtime, self.root)
        bind_host(self.host)
        self.topic_store = TopicStore(self.root)
        _seed_topic(self.topic_store, CONV["id"], TOPIC_ID)
        self.task_store = TaskStore(self.root, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.root, topic_store=self.topic_store)
        self.risk_store = RiskStore(self.root, topic_store=self.topic_store)
        self.task_ext = CountingExtractor(ScriptedTask(), boom=False)
        self.decision_ext = CountingExtractor(ScriptedDecision(), boom=False)
        self.risk_ext = CountingExtractor(ScriptedRisk(), boom=False)
        self.task_engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=self.task_ext,
            root_dir=ROOT,
            enabled=True,
        )
        self.decision_engine = DecisionEngine(
            self.decision_store,
            self.topic_store,
            extractor=self.decision_ext,
            root_dir=ROOT,
            enabled=True,
        )
        self.risk_engine = RiskEngine(
            self.risk_store,
            self.topic_store,
            task_store=self.task_store,
            extractor=self.risk_ext,
            root_dir=ROOT,
            enabled=True,
        )
        self.service = DownstreamRetryService(
            topic_store=self.topic_store,
            task_engine=self.task_engine,
            decision_engine=self.decision_engine,
            risk_engine=self.risk_engine,
            runtime=self.runtime,
            conversation=CONV,
        )

    def tearDown(self):
        bind_host(types.SimpleNamespace())
        from message import bind as bind_mod
        bind_mod._host = None
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass
        clear_stop_request()
        clear_emergency_stop()

    def _upsert_msg(self, msg_id, content):
        return self.topic_store.upsert_message(
            {
                "id": msg_id,
                "conversation_id": CONV["id"],
                "platform_message_id": msg_id,
                "sender_name": "周敏",
                "content": content,
                "created_at": "2026-09-22T20:10:00+08:00",
                "direction": "INBOUND",
                "message_type": "text",
            }
        )

    def _seed_current(self, msg_id, content=TASK_TEXT, *, with_prior=True):
        if with_prior:
            prior = self._upsert_msg(msg_id + "_prior", PRIOR_TEXT)
            self.topic_store.add_link(CONV["id"], TOPIC_ID, prior["id"], TOPIC_CREATED)
        record = self._upsert_msg(msg_id, content)
        self.topic_store.add_link(CONV["id"], TOPIC_ID, record["id"], TOPIC_CREATED)
        self.topic_store.write_processing(
            {
                "message_id": record["id"],
                "conversation_id": CONV["id"],
                "decision": "NEW_TOPIC",
                "topic_id": TOPIC_ID,
            }
        )
        self.msg_id = record["id"]
        return self.topic_store.get_topic(CONV["id"], TOPIC_ID), self.topic_store.get_message(CONV["id"], record["id"])

    def _engine_bundle(self, name):
        return {
            "task": (self.task_engine, self.task_store, self.task_ext),
            "decision": (self.decision_engine, self.decision_store, self.decision_ext),
            "risk": (self.risk_engine, self.risk_store, self.risk_ext),
        }[name]

    def _list_entities(self, name):
        store = self._engine_bundle(name)[1]
        if name == "task":
            return store.list_tasks(CONV["id"])
        if name == "decision":
            return store.list_decisions(CONV["id"])
        return store.list_risks(CONV["id"])

    def _entity_id_key(self, name):
        return {"task": "task_id", "decision": "decision_id", "risk": "risk_id"}[name]

    def _created_rel(self, name):
        return {"task": T_CREATED, "decision": D_CREATED, "risk": R_CREATED}[name]

    def _related_rel(self, name):
        return {"task": T_RELATED, "decision": D_RELATED, "risk": R_RELATED}[name]

    def _snapshot(self, name):
        _engine, store, _ext = self._engine_bundle(name)
        entities = self._list_entities(name)
        links = store.list_links(CONV["id"])
        proc = store.get_processing(CONV["id"], self.msg_id)
        id_key = self._entity_id_key(name)
        created = [item for item in links if item.get("relation") == self._created_rel(name)]
        related = [item for item in links if item.get("relation") == self._related_rel(name)]
        return {
            "entities": entities,
            "ids": [item.get("id") for item in entities],
            "fields": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "created_msg_id": item.get("created_msg_id"),
                    "created_at": item.get("created_at"),
                    "assignee_text": item.get("assignee_text"),
                    "decision_text": item.get("decision_text"),
                    "condition_text": item.get("condition_text"),
                    "impact_text": item.get("impact_text"),
                }
                for item in entities
            ],
            "link_count": len(links),
            "created_by": len(created),
            "related": len(related),
            "created_triples": [
                (item.get(id_key), item.get("message_id"), item.get("relation")) for item in created
            ],
            "related_triples": [
                (item.get(id_key), item.get("message_id"), item.get("relation")) for item in related
            ],
            "processing": proc,
            "has_success": store.has_successful_processing(CONV["id"], self.msg_id),
        }

    def _inject_post_apply_failure(self, name, msg_id, content):
        topic, message = self._seed_current(msg_id, content)
        engine = self._engine_bundle(name)[0]
        original = engine._finalize

        def boom(*_a, **_k):
            raise RuntimeError("P6-G3 post-apply finalize boom")

        engine._finalize = boom
        first = engine.process_record(CONV, topic, message)
        engine._finalize = original
        self.assertEqual(first.decision, "FAILED")
        self.assertEqual(first.error_code, "RuntimeError")
        after = self._snapshot(name)
        self.assertEqual(len(after["ids"]), 1)
        self.assertFalse(after["has_success"])
        self.assertEqual((after["processing"] or {}).get("decision_summary"), "FAILED")
        self.assertFalse(any(_is_suffix_id(item) for item in after["ids"]))
        self.assertEqual(after["created_by"], 1)
        self.assertGreaterEqual(after["related"], 1)
        return first, after

    def _retry(self, name):
        return retry_downstream(
            name,
            CONV["id"],
            self.msg_id,
            TOPIC_ID,
            service=self.service,
            runtime=self.runtime,
        )

    def _assert_recovered_single(self, name, before, outcome, expected_decision):
        after = self._snapshot(name)
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.result, "SUCCESS")
        self.assertEqual(outcome.engine_decision, expected_decision)
        self.assertEqual(after["ids"], before["ids"])
        self.assertEqual(len(after["ids"]), 1)
        self.assertFalse(any(_is_suffix_id(item) for item in after["ids"]))
        self.assertEqual(after["fields"], before["fields"])
        self.assertEqual(after["created_by"], 1)
        self.assertEqual(after["related"], before["related"])
        self.assertEqual(after["created_triples"], before["created_triples"])
        self.assertEqual(after["related_triples"], before["related_triples"])
        self.assertEqual(after["link_count"], before["link_count"])
        self.assertTrue(after["has_success"])
        self.assertEqual((after["processing"] or {}).get("decision_summary"), expected_decision)
        entity_ids_key = {
            "task": "task_ids",
            "decision": "decision_ids",
            "risk": "risk_ids",
        }[name]
        self.assertEqual((after["processing"] or {}).get(entity_ids_key), before["ids"])
        return after

    def test_consist_01_task_post_apply_failure(self):
        _first, before = self._inject_post_apply_failure("task", "msg_p6g3_c01", TASK_TEXT)
        extractor_before = self.task_ext.calls
        outcome = self._retry("task")
        after = self._assert_recovered_single("task", before, outcome, "NEW_TASK")
        self.assertEqual(after["fields"][0]["assignee_text"], "李娜")
        self.assertEqual(self.task_ext.calls, extractor_before + 1)
        events = [item.get("event") for item in self.service.audit_events]
        self.assertIn(EVENT_REQUESTED, events)
        self.assertIn(EVENT_SUCCESS, events)

    def test_consist_02_decision_post_apply_failure(self):
        _first, before = self._inject_post_apply_failure(
            "decision", "msg_p6g3_c02", "就按照异常池方案执行。"
        )
        outcome = self._retry("decision")
        after = self._assert_recovered_single("decision", before, outcome, "NEW_DECISION")
        self.assertEqual(after["fields"][0]["decision_text"], "就按照异常池方案执行。")

    def test_consist_03_risk_post_apply_failure(self):
        _first, before = self._inject_post_apply_failure(
            "risk", "msg_p6g3_c03", "如果今天还修不好会影响明天现场演示。"
        )
        outcome = self._retry("risk")
        after = self._assert_recovered_single("risk", before, outcome, "NEW_RISK")
        self.assertEqual(after["fields"][0]["condition_text"], "如果今天还修不好")
        self.assertEqual(after["fields"][0]["impact_text"], "会影响明天现场演示")

    def test_consist_04_evidence_not_duplicated_across_three_engines(self):
        for name, msg_id, content, decision in (
            ("task", "msg_p6g3_c04t", TASK_TEXT, "NEW_TASK"),
            ("decision", "msg_p6g3_c04d", "就按照异常池方案执行。", "NEW_DECISION"),
            ("risk", "msg_p6g3_c04r", "如果今天还修不好会影响明天现场演示。", "NEW_RISK"),
        ):
            _first, before = self._inject_post_apply_failure(name, msg_id, content)
            outcome = self._retry(name)
            self._assert_recovered_single(name, before, outcome, decision)
            self.assertEqual(before["created_by"], 1)
            self.assertEqual(before["related"], 1)

    def test_consist_05_processing_not_stuck_failed(self):
        for name, msg_id, content in (
            ("task", "msg_p6g3_c05t", TASK_TEXT),
            ("decision", "msg_p6g3_c05d", "就按照异常池方案执行。"),
            ("risk", "msg_p6g3_c05r", "如果今天还修不好会影响明天现场演示。"),
        ):
            self._inject_post_apply_failure(name, msg_id, content)
            outcome = self._retry(name)
            self.assertTrue(outcome.ok)
            store = self._engine_bundle(name)[1]
            self.assertTrue(store.has_successful_processing(CONV["id"], self.msg_id))
            rec = store.get_processing(CONV["id"], self.msg_id)
            self.assertNotEqual(rec.get("decision_summary"), "FAILED")
            self.assertEqual(rec.get("error") or "", "")

    def test_consist_06_extractor_failure_then_retry_success(self):
        self._seed_current("msg_p6g3_c06", TASK_TEXT)
        self.task_ext.boom = True
        topic = self.topic_store.get_topic(CONV["id"], TOPIC_ID)
        message = self.topic_store.get_message(CONV["id"], self.msg_id)
        first = self.task_engine.process_record(CONV, topic, message)
        self.assertEqual(first.decision, "FAILED")
        self.assertEqual(self._list_entities("task"), [])
        self.assertEqual(self.task_store.list_links(CONV["id"]), [])
        self.task_ext.boom = False
        before_calls = self.task_ext.calls
        outcome = self._retry("task")
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.engine_decision, "NEW_TASK")
        self.assertEqual(self.task_ext.calls, before_calls + 1)
        self.assertEqual(len(self._list_entities("task")), 1)
        self.assertTrue(self.task_store.has_successful_processing(CONV["id"], self.msg_id))

    def test_consist_07_success_processing_rejects_retry(self):
        self._seed_current("msg_p6g3_c07", TASK_TEXT)
        topic = self.topic_store.get_topic(CONV["id"], TOPIC_ID)
        message = self.topic_store.get_message(CONV["id"], self.msg_id)
        first = self.task_engine.process_record(CONV, topic, message)
        self.assertEqual(first.decision, "NEW_TASK")
        before_calls = self.task_ext.calls
        before_n = len(self._list_entities("task"))
        outcome = self._retry("task")
        self.assertTrue(outcome.rejected)
        self.assertFalse(outcome.executed)
        self.assertEqual(outcome.error_code, ERROR_NOT_RETRYABLE)
        self.assertEqual(self.task_ext.calls, before_calls)
        self.assertEqual(len(self._list_entities("task")), before_n)
        events = [item.get("event") for item in self.service.audit_events]
        self.assertEqual(events, [EVENT_REJECTED])

    def test_consist_10_stop_and_engine_disabled(self):
        self._inject_post_apply_failure("task", "msg_p6g3_c10", TASK_TEXT)
        before_calls = self.task_ext.calls
        before_n = len(self._list_entities("task"))
        for state in ("STOPPING", "STOPPED"):
            self.runtime.set_state(state, "consist-10")
            outcome = self._retry("task")
            self.assertTrue(outcome.rejected)
            self.assertFalse(outcome.executed)
            self.assertEqual(outcome.error_code, ERROR_STOPPED)
        self.runtime.set_state("RUNNING", "consist-10-restore")
        self.task_engine.enabled = False
        disabled = self._retry("task")
        self.assertTrue(disabled.rejected)
        self.assertEqual(disabled.error_code, ERROR_ENGINE_DISABLED)
        self.assertEqual(self.task_ext.calls, before_calls)
        self.assertEqual(len(self._list_entities("task")), before_n)
        self.task_engine.enabled = True
        restored = self._retry("task")
        self.assertTrue(restored.ok)
        self.assertEqual(len(self._list_entities("task")), 1)

    def test_true_collision_different_message_still_suffixes(self):
        self._seed_current("msg_p6g3_col", TASK_TEXT, with_prior=True)
        other = self._upsert_msg("msg_p6g3_col_other", "另一条消息也要建任务")
        self.topic_store.add_link(CONV["id"], TOPIC_ID, other["id"], TOPIC_CREATED)
        now = "2026-09-22T20:10:00+08:00"
        shared = make_task_id(CONV["id"], TOPIC_ID, self.msg_id, 0, now)
        first = {
            "id": shared,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": "第一条",
            "description": "",
            "status": "OPEN",
            "assignee_text": "李娜",
            "due_text": "",
            "due_at": "",
            "created_msg_id": self.msg_id,
            "confidence": "HIGH",
            "created_at": now,
            "updated_at": now,
            "schema_version": 1,
        }
        second = dict(first)
        second["title"] = "第二条"
        second["created_msg_id"] = other["id"]
        link1 = {
            "id": make_tlink_id(shared, self.msg_id, T_CREATED),
            "task_id": shared,
            "message_id": self.msg_id,
            "relation": T_CREATED,
            "confidence": "HIGH",
            "created_at": now,
        }
        self.task_store.commit_apply(CONV["id"], new_tasks=[first], new_links=[link1])
        link2 = {
            "id": make_tlink_id(shared, other["id"], T_CREATED),
            "task_id": shared,
            "message_id": other["id"],
            "relation": T_CREATED,
            "confidence": "HIGH",
            "created_at": now,
        }
        applied = self.task_store.commit_apply(CONV["id"], new_tasks=[second], new_links=[link2])
        ids = [item.get("id") for item in self.task_store.list_tasks(CONV["id"])]
        self.assertEqual(ids[0], shared)
        self.assertTrue(any(_is_suffix_id(item) for item in ids))
        self.assertIn(shared + "_2", applied["task_ids"])

    def test_flags_remain_disabled(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def test_retry_source_still_one_shot(self):
        import downstream_retry as mod

        source = inspect.getsource(mod)
        self.assertNotIn("queue.Queue", source)
        self.assertNotIn("threading.Thread", source)
        self.assertNotIn("send_reply(", source)


class P6G3ReplayAndN2Tests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.runtime.set_identity(bot_wxid=BOT_WXID, bot_name=BOT_NAME, login_account=BOT_NAME)
        self.host = FakeHost(self.runtime, self.root)
        bind_host(self.host)
        self.topic_ext = CountingExtractor(HeuristicTopicExtractor())
        self.task_ext = CountingExtractor(HeuristicTaskExtractor())
        self.decision_ext = CountingExtractor(HeuristicDecisionExtractor())
        self.risk_ext = CountingExtractor(HeuristicRiskExtractor())
        self.task_path = TaskSidepath(
            root_dir=self.root,
            extractor=self.task_ext,
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
        )
        self.decision_path = DecisionSidepath(
            root_dir=self.root,
            extractor=self.decision_ext,
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
        )
        self.risk_path = RiskSidepath(
            root_dir=self.root,
            extractor=self.risk_ext,
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
        )
        self.sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=self.topic_ext,
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
            task_sidepath=self.task_path,
            decision_sidepath=self.decision_path,
            risk_sidepath=self.risk_path,
        )
        reset_sidepath(self.sidepath)
        reset_task_sidepath(self.task_path)
        reset_decision_sidepath(self.decision_path)
        reset_risk_sidepath(self.risk_path)

    def tearDown(self):
        try:
            self.sidepath.shutdown()
            self.task_path.shutdown()
            self.decision_path.shutdown()
            self.risk_path.shutdown()
            self.sidepath.wait_idle(0.4)
            self.task_path.wait_idle(0.4)
            self.decision_path.wait_idle(0.4)
            self.risk_path.wait_idle(0.4)
        except Exception:
            pass
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
        reset_task_sidepath(TaskSidepath(enabled=False, root_dir=self.root, maxsize=1))
        reset_decision_sidepath(DecisionSidepath(enabled=False, root_dir=self.root, maxsize=1))
        reset_risk_sidepath(RiskSidepath(enabled=False, root_dir=self.root, maxsize=1))
        bind_host(types.SimpleNamespace())
        from message import bind as bind_mod
        bind_mod._host = None
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass
        clear_stop_request()
        clear_emergency_stop()

    def _eval(self, inbound, **kwargs):
        return self.runtime.evaluate_inbound(
            inbound,
            listen_users=["测试群"],
            is_group=True,
            accept_all=False,
            enable_at=True,
            enable_keyword=False,
            **kwargs,
        )

    def _wait(self, timeout=3.0):
        self.assertTrue(self.sidepath.wait_idle(timeout), "Topic worker did not finish")
        self.assertTrue(self.task_path.wait_idle(timeout), "Task worker did not finish")
        self.assertTrue(self.decision_path.wait_idle(timeout), "Decision worker did not finish")
        self.assertTrue(self.risk_path.wait_idle(timeout), "Risk worker did not finish")

    def _direct_process(self, inbound):
        conversation = resolve_topic_conversation(inbound, [dict(CONV)])
        self.assertIsNotNone(conversation)
        self.sidepath._process({"inbound": inbound, "conversation": conversation, "enqueued_at": 0})
        self._wait()
        return self.sidepath.last_result

    def _fanout(self):
        return (
            self.task_path.enqueued_count,
            self.decision_path.enqueued_count,
            self.risk_path.enqueued_count,
        )

    def test_consist_08_topic_replay_zero_fanout(self):
        inbound = _inbound(platform_message_id="consist-08", content=NEW_TOPIC_TEXT)
        first = self._direct_process(inbound)
        self.assertFalse(first.replayed)
        self.assertEqual(self._fanout(), (1, 1, 1))
        before = {
            "topic": self.topic_ext.calls,
            "task": self.task_ext.calls,
            "decision": self.decision_ext.calls,
            "risk": self.risk_ext.calls,
            "fanout": self._fanout(),
            "chat": len(self.host.replies),
        }
        second = self._direct_process(inbound)
        self.assertTrue(second.replayed)
        self.assertEqual(self.topic_ext.calls, before["topic"])
        self.assertEqual(self.task_ext.calls, before["task"])
        self.assertEqual(self.decision_ext.calls, before["decision"])
        self.assertEqual(self.risk_ext.calls, before["risk"])
        self.assertEqual(self._fanout(), before["fanout"])
        self.assertEqual(self._fanout(), (1, 1, 1))
        self.assertEqual(len(self.host.replies), before["chat"])
        replay_events = [item for item in self.sidepath.audit_events if item.get("event") == EVENT_TOPIC_REPLAY]
        self.assertEqual(len(replay_events), 1)
        self.assertTrue(replay_events[0].get("fanout_skipped"))

    def test_consist_09_n2_same_text_different_pid(self):
        first = _inbound(platform_message_id="n2-C", content="同一句话 ERP 同步失败了")
        second = _inbound(platform_message_id="n2-D", content="同一句话 ERP 同步失败了")
        r1 = try_enqueue_topic_sidepath(first, self._eval(first), runtime=self.runtime)
        r2 = try_enqueue_topic_sidepath(second, self._eval(second), runtime=self.runtime)
        self.assertTrue(r1["enqueued"])
        self.assertTrue(r2["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.enqueued_count, 2)
        self.assertEqual(self.topic_ext.calls, 2)
        self.assertEqual(self._fanout(), (2, 2, 2))
        messages = self.sidepath.store.list_messages(CONV["id"])
        self.assertEqual(len(messages), 2)
        self.assertEqual(len({item.get("id") for item in messages}), 2)


if __name__ == "__main__":
    unittest.main()
