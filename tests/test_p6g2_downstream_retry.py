# -*- coding: utf-8 -*-
"""P6-G2 Downstream Failure Recovery：RETRY-01 ～ RETRY-12。

Topic SUCCESS + 某一路 FAILED → 只显式重试失败的 Engine。
不重跑 Topic，不 fan-out 另外两路，不走 Chat。
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
from downstream_retry import (
    EVENT_FAILED,
    EVENT_REJECTED,
    EVENT_REQUESTED,
    EVENT_SUCCESS,
    ERROR_ENGINE_DISABLED,
    ERROR_INVALID_ENGINE,
    ERROR_NOT_FOUND,
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
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED, TaskEngine
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import TaskSidepath, reset_task_sidepath
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED, resolve_topic_conversation
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import EVENT_TOPIC_REPLAY, TopicSidepath, reset_sidepath, try_enqueue_topic_sidepath
from topic_store import RELATION_CREATED_BY, TopicStore

CONV = {
    "id": "conv_p6g2retry01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_p6g2@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
    "agent_config_id": "agt_p6g2",
}
TOPIC_ID = "topic_p6g2retry01"
BOT_WXID = "wxid_bot_p6g2"
BOT_NAME = "测试助手"
NEW_TOPIC_TEXT = "ERP 同步今天还是有问题。"
TASK_TEXT = "李娜把权限问题修一下。"


class CountingExtractor:
    def __init__(self, inner=None, *, boom=False):
        self.inner = inner
        self.boom = boom
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        if self.boom:
            raise TimeoutError("p6g2 boom")
        if self.inner is None:
            raise RuntimeError("missing inner extractor")
        return self.inner.extract(engine_input, prompt_content)


class ScriptedTask:
    def __init__(self, decision="NEW_TASK"):
        self.decision = decision

    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        if self.decision == "UNRELATED":
            return {
                "decisions": [
                    {
                        "decision": "UNRELATED",
                        "confidence": "HIGH",
                        "evidence_message_ids": [current_id],
                        "reason": "scripted unrelated",
                    }
                ]
            }
        return {
            "decisions": [
                {
                    "decision": "NEW_TASK",
                    "title": "修权限",
                    "description": "李娜把权限问题修一下",
                    "assignee_text": "李娜",
                    "due_text": "",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current_id],
                    "reason": "scripted new task",
                }
            ]
        }


class ScriptedDecision:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        return {
            "decisions": [
                {
                    "decision": "NEW_DECISION",
                    "title": "采用异常池方案",
                    "decision_text": "就按照异常池方案执行。",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current_id],
                    "reason": "scripted new decision",
                }
            ]
        }


class ScriptedRisk:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        return {
            "risks": [
                {
                    "decision": "NEW_RISK",
                    "title": "演示受阻",
                    "condition_text": "如果今天还修不好",
                    "impact_text": "会影响明天现场演示",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current_id],
                    "reason": "scripted new risk",
                }
            ]
        }


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p6g2_retry")
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
        "platform_message_id": kwargs.pop("platform_message_id", "pid-p6g2-1"),
        "conversation_id": kwargs.pop("conversation_id", "room_p6g2@chatroom"),
        "chat_name": kwargs.pop("chat_name", "测试群"),
        "chat_wxid": kwargs.pop("chat_wxid", "room_p6g2@chatroom"),
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


class P6G2DownstreamRetryTests(unittest.TestCase):
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
        self.topic_ext = CountingExtractor(HeuristicTopicExtractor())
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

    def _seed_message(self, msg_id, content=TASK_TEXT):
        record = self.topic_store.upsert_message(
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
        self.topic_store.add_link(CONV["id"], TOPIC_ID, record["id"], RELATION_CREATED_BY)
        self.topic_store.write_processing(
            {
                "message_id": record["id"],
                "conversation_id": CONV["id"],
                "decision": "NEW_TOPIC",
                "topic_id": TOPIC_ID,
            }
        )
        return self.topic_store.get_topic(CONV["id"], TOPIC_ID), self.topic_store.get_message(CONV["id"], record["id"])

    def _counts(self):
        return {
            "topic": self.topic_ext.calls,
            "task": self.task_ext.calls,
            "decision": self.decision_ext.calls,
            "risk": self.risk_ext.calls,
            "chat": len(self.host.replies),
        }

    def _process(self, engine_name):
        topic = self.topic_store.get_topic(CONV["id"], TOPIC_ID)
        message = self.topic_store.get_message(CONV["id"], self.msg_id)
        engines = {
            "task": self.task_engine,
            "decision": self.decision_engine,
            "risk": self.risk_engine,
        }
        return engines[engine_name].process_record(CONV, topic, message)

    def _fail_then_arm(self, engine_name):
        ext = {"task": self.task_ext, "decision": self.decision_ext, "risk": self.risk_ext}[engine_name]
        ext.boom = True
        first = self._process(engine_name)
        self.assertEqual(first.decision, "FAILED")
        ext.boom = False
        return first

    def _retry(self, engine_name, **kwargs):
        return retry_downstream(
            engine_name,
            CONV["id"],
            self.msg_id,
            TOPIC_ID,
            service=self.service,
            runtime=kwargs.get("runtime", self.runtime),
        )

    def _prepare_topic_success_and_others(self, fail_engine, msg_id):
        self.msg_id = msg_id
        self._seed_message(msg_id)
        others = [name for name in ("task", "decision", "risk") if name != fail_engine]
        for name in others:
            result = self._process(name)
            self.assertNotEqual(result.decision, "FAILED")
            self.assertFalse(result.replayed)
        self._fail_then_arm(fail_engine)

    def test_retry_01_task_failed_then_success(self):
        self._prepare_topic_success_and_others("task", "msg_p6g2_r01")
        before = self._counts()
        tasks_before = len(self.task_store.list_tasks(CONV["id"]))
        links_before = len(self.task_store.list_links(CONV["id"]))
        outcome = self._retry("task")
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.result, "SUCCESS")
        self.assertEqual(outcome.previous_status, "FAILED")
        self.assertEqual(outcome.engine_decision, "NEW_TASK")
        after = self._counts()
        self.assertEqual(after["task"], before["task"] + 1)
        self.assertEqual(after["decision"], before["decision"])
        self.assertEqual(after["risk"], before["risk"])
        self.assertEqual(after["topic"], before["topic"])
        self.assertEqual(after["chat"], 0)
        self.assertEqual(len(self.task_store.list_tasks(CONV["id"])), tasks_before + 1)
        self.assertEqual(len(self.task_store.list_links(CONV["id"])), links_before + 1)
        rec = self.task_store.get_processing(CONV["id"], self.msg_id)
        self.assertEqual(rec["decision_summary"], "NEW_TASK")
        self.assertTrue(self.task_store.has_successful_processing(CONV["id"], self.msg_id))
        events = [item.get("event") for item in self.service.audit_events]
        self.assertIn(EVENT_REQUESTED, events)
        self.assertIn(EVENT_SUCCESS, events)
        third = self._retry("task")
        self.assertTrue(third.rejected)
        self.assertFalse(third.executed)
        self.assertEqual(third.error_code, ERROR_NOT_RETRYABLE)
        self.assertEqual(self.task_ext.calls, after["task"])
        self.assertEqual(len(self.task_store.list_tasks(CONV["id"])), tasks_before + 1)

    def test_retry_02_decision_failed_then_success(self):
        self._prepare_topic_success_and_others("decision", "msg_p6g2_r02")
        before = self._counts()
        outcome = self._retry("decision")
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.engine_decision, "NEW_DECISION")
        after = self._counts()
        self.assertEqual(after["decision"], before["decision"] + 1)
        self.assertEqual(after["task"], before["task"])
        self.assertEqual(after["risk"], before["risk"])
        self.assertEqual(after["topic"], before["topic"])
        self.assertEqual(after["chat"], 0)
        self.assertEqual(len(self.decision_store.list_decisions(CONV["id"])), 1)
        self.assertTrue(self.decision_store.has_successful_processing(CONV["id"], self.msg_id))

    def test_retry_03_risk_failed_then_success(self):
        self._prepare_topic_success_and_others("risk", "msg_p6g2_r03")
        before = self._counts()
        outcome = self._retry("risk")
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.engine_decision, "NEW_RISK")
        after = self._counts()
        self.assertEqual(after["risk"], before["risk"] + 1)
        self.assertEqual(after["task"], before["task"])
        self.assertEqual(after["decision"], before["decision"])
        self.assertEqual(after["topic"], before["topic"])
        self.assertEqual(after["chat"], 0)
        self.assertEqual(len(self.risk_store.list_risks(CONV["id"])), 1)
        self.assertTrue(self.risk_store.has_successful_processing(CONV["id"], self.msg_id))

    def test_retry_04_failed_then_retry_failed_no_recursion(self):
        self.msg_id = "msg_p6g2_r04"
        self._seed_message(self.msg_id)
        self._process("decision")
        self._process("risk")
        self.task_ext.boom = True
        first = self._process("task")
        self.assertEqual(first.decision, "FAILED")
        before = self._counts()
        outcome = self._retry("task")
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.result, "FAILED")
        self.assertEqual(outcome.previous_status, "FAILED")
        after = self._counts()
        self.assertEqual(after["task"], before["task"] + 1)
        self.assertEqual(after["decision"], before["decision"])
        self.assertEqual(after["risk"], before["risk"])
        self.assertEqual(after["topic"], 0)
        rec = self.task_store.get_processing(CONV["id"], self.msg_id)
        self.assertEqual(rec["decision_summary"], "FAILED")
        events = [item.get("event") for item in self.service.audit_events]
        self.assertEqual(events.count(EVENT_REQUESTED), 1)
        self.assertEqual(events.count(EVENT_FAILED), 1)
        self.assertNotIn(EVENT_SUCCESS, events)

    def test_retry_05_success_not_retryable(self):
        self.msg_id = "msg_p6g2_r05"
        self._seed_message(self.msg_id)
        result = self._process("task")
        self.assertEqual(result.decision, "NEW_TASK")
        before = self.task_ext.calls
        outcome = self._retry("task")
        self.assertTrue(outcome.rejected)
        self.assertFalse(outcome.executed)
        self.assertEqual(outcome.error_code, ERROR_NOT_RETRYABLE)
        self.assertEqual(self.task_ext.calls, before)
        events = [item.get("event") for item in self.service.audit_events]
        self.assertEqual(events, [EVENT_REJECTED])

    def test_retry_06_unrelated_not_retryable(self):
        self.task_ext.inner = ScriptedTask("UNRELATED")
        self.msg_id = "msg_p6g2_r06"
        self._seed_message(self.msg_id)
        result = self._process("task")
        self.assertEqual(result.decision, "UNRELATED")
        before = self.task_ext.calls
        outcome = self._retry("task")
        self.assertTrue(outcome.rejected)
        self.assertFalse(outcome.executed)
        self.assertEqual(outcome.error_code, ERROR_NOT_RETRYABLE)
        self.assertEqual(outcome.previous_status, "UNRELATED")
        self.assertEqual(self.task_ext.calls, before)

    def test_retry_07_missing_processing_not_found(self):
        self.msg_id = "msg_p6g2_r07"
        self._seed_message(self.msg_id)
        before = self._counts()
        outcome = self._retry("task")
        self.assertTrue(outcome.rejected)
        self.assertFalse(outcome.executed)
        self.assertEqual(outcome.error_code, ERROR_NOT_FOUND)
        self.assertIsNone(self.task_store.get_processing(CONV["id"], self.msg_id))
        self.assertEqual(self._counts(), before)

    def test_retry_08_invalid_engine(self):
        self.msg_id = "msg_p6g2_r08"
        self._seed_message(self.msg_id)
        for name in ("topic", "chat", "foo", ""):
            outcome = self._retry(name)
            self.assertTrue(outcome.rejected)
            self.assertEqual(outcome.error_code, ERROR_INVALID_ENGINE)
            self.assertFalse(outcome.executed)
        self.assertEqual(self.task_ext.calls, 0)
        self.assertEqual(self.decision_ext.calls, 0)
        self.assertEqual(self.risk_ext.calls, 0)
        self.assertEqual(self.topic_ext.calls, 0)

    def test_retry_11_failure_isolation(self):
        self._prepare_topic_success_and_others("task", "msg_p6g2_r11")
        self.task_ext.boom = True
        before = self._counts()
        decision_n = len(self.decision_store.list_decisions(CONV["id"]))
        risk_n = len(self.risk_store.list_risks(CONV["id"]))
        topic_n = len(self.topic_store.list_topics(CONV["id"]))
        outcome = self._retry("task")
        self.assertEqual(outcome.result, "FAILED")
        after = self._counts()
        self.assertEqual(after["task"], before["task"] + 1)
        self.assertEqual(after["decision"], before["decision"])
        self.assertEqual(after["risk"], before["risk"])
        self.assertEqual(after["topic"], before["topic"])
        self.assertEqual(len(self.decision_store.list_decisions(CONV["id"])), decision_n)
        self.assertEqual(len(self.risk_store.list_risks(CONV["id"])), risk_n)
        self.assertEqual(len(self.topic_store.list_topics(CONV["id"])), topic_n)
        self.assertEqual(self.host.replies, [])

    def test_retry_12_stopped_rejects(self):
        self._prepare_topic_success_and_others("task", "msg_p6g2_r12")
        before = self._counts()
        for state in ("STOPPING", "STOPPED"):
            self.runtime.set_state(state, "retry-12")
            outcome = self._retry("task")
            self.assertTrue(outcome.rejected)
            self.assertFalse(outcome.executed)
            self.assertEqual(outcome.error_code, ERROR_STOPPED)
            self.assertEqual(outcome.previous_status, "FAILED")
        self.assertEqual(self._counts(), before)
        self.runtime.set_state("RUNNING", "retry-12-restore")
        self.task_ext.boom = False
        restored = self._retry("task")
        self.assertTrue(restored.ok)

    def test_retry_engine_disabled_rejects(self):
        self._prepare_topic_success_and_others("task", "msg_p6g2_dis")
        self.task_engine.enabled = False
        before = self.task_ext.calls
        outcome = self._retry("task")
        self.assertTrue(outcome.rejected)
        self.assertEqual(outcome.error_code, ERROR_ENGINE_DISABLED)
        self.assertEqual(self.task_ext.calls, before)

    def test_flags_remain_disabled(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def test_source_is_sync_internal_capability(self):
        import downstream_retry as mod

        source = inspect.getsource(mod)
        self.assertNotIn("queue.Queue", source)
        self.assertNotIn("threading.Thread", source)
        self.assertNotIn("send_reply(", source)
        self.assertNotIn("wx.SendMsg", source)
        self.assertNotIn("get_user_prompt(", source)
        self.assertIn("EVENT_REQUESTED", source)
        self.assertIn("one-shot", source.lower())


class P6G2ReplayAndN2Tests(unittest.TestCase):
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

    def test_retry_09_topic_replay_still_zero_fanout(self):
        inbound = _inbound(platform_message_id="retry-09", content=NEW_TOPIC_TEXT)
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

    def test_retry_10_n2_same_text_different_pid(self):
        first = _inbound(platform_message_id="n2-A", content="同一句话 ERP 同步失败了")
        second = _inbound(platform_message_id="n2-B", content="同一句话 ERP 同步失败了")
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
