# -*- coding: utf-8 -*-
"""P6-G5 Topic Failure Recovery：TOPIC-RETRY-01 ～ TOPIC-RETRY-14。

Topic FAILED → 显式 retry Topic → SUCCESS 则复用既有 fan-out。
不得破坏 P6-G1 replay、P6-G2 downstream retry、N2、P0 DUPLICATE。
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
from downstream_retry import DownstreamRetryService, retry_downstream
from message.bind import bind_host
from message.identity import InboundMessage
from message.trigger import NO_ACTION
from risk_engine import RISK_ENGINE_ENABLED, RiskEngine
from risk_extractor_client import HeuristicRiskExtractor
from risk_sidepath import RiskSidepath, reset_risk_sidepath
from task_engine import TASK_ENGINE_ENABLED, TaskEngine
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import TaskSidepath, reset_task_sidepath
from topic_engine import TOPIC_ENGINE_ENABLED, resolve_topic_conversation
from topic_extractor_client import HeuristicTopicExtractor
from topic_retry import (
    EVENT_FAILED,
    EVENT_REJECTED,
    EVENT_REQUESTED,
    EVENT_SUCCESS,
    ERROR_ENGINE_DISABLED,
    ERROR_NOT_FOUND,
    ERROR_NOT_RETRYABLE,
    ERROR_STOPPED,
    TopicRetryService,
    retry_topic,
)
from topic_sidepath import (
    EVENT_TOPIC_REPLAY,
    SKIP_DUPLICATE,
    TopicSidepath,
    reset_sidepath,
    try_enqueue_topic_sidepath,
)

CONV = {
    "id": "conv_p6g5retry01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_p6g5@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
    "agent_config_id": "agt_p6g5",
}
BOT_WXID = "wxid_bot_p6g5"
BOT_NAME = "测试助手"
NEW_TOPIC_TEXT = "ERP 同步今天还是有问题。"
EXISTING_TEXT = "ERP 同步供应商编码还是空。"
UPDATE_TEXT = "ERP 同步规则需要修复。"
UNRELATED_TEXT = "中午吃什么"


class CountingExtractor:
    def __init__(self, inner=None, *, boom=False):
        self.inner = inner
        self.boom = boom
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        if self.boom:
            raise TimeoutError("p6g5 boom")
        if self.inner is None:
            raise RuntimeError("missing inner extractor")
        return self.inner.extract(engine_input, prompt_content)


class ScriptedTask:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        return {
            "decisions": [
                {
                    "decision": "NEW_TASK",
                    "title": "修同步",
                    "description": "ERP 同步今天还是有问题",
                    "assignee_text": "李娜",
                    "due_text": "",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current_id],
                    "reason": "scripted new task",
                }
            ]
        }


class ScriptedTopic:
    def __init__(self, decision="NEW_TOPIC"):
        self.decision = decision

    def extract(self, engine_input, prompt_content):
        current_id = (engine_input.get("current_message") or {}).get("id")
        if self.decision == "UNRELATED":
            return {
                "decision": "UNRELATED",
                "topic_id": None,
                "proposed_title": "",
                "summary_update": "",
                "confidence": "HIGH",
                "evidence_message_ids": [current_id] if current_id else [],
                "reason": "scripted unrelated",
            }
        active = list(engine_input.get("active_topics") or [])
        topic_id = active[0]["id"] if active else None
        if self.decision in ("EXISTING_TOPIC", "TOPIC_UPDATE"):
            return {
                "decision": self.decision,
                "topic_id": topic_id,
                "proposed_title": "",
                "summary_update": "规则修复" if self.decision == "TOPIC_UPDATE" else "",
                "confidence": "HIGH",
                "evidence_message_ids": [current_id] if current_id else [],
                "reason": "scripted " + self.decision,
            }
        return {
            "decision": "NEW_TOPIC",
            "topic_id": None,
            "proposed_title": "ERP同步异常",
            "summary_update": NEW_TOPIC_TEXT,
            "confidence": "HIGH",
            "evidence_message_ids": [current_id] if current_id else [],
            "reason": "scripted new topic",
        }


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p6g5_retry")
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
        "platform_message_id": kwargs.pop("platform_message_id", "pid-p6g5-1"),
        "conversation_id": kwargs.pop("conversation_id", "room_p6g5@chatroom"),
        "chat_name": kwargs.pop("chat_name", "测试群"),
        "chat_wxid": kwargs.pop("chat_wxid", "room_p6g5@chatroom"),
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


class P6G5TopicRetryTests(unittest.TestCase):
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
        self.service = TopicRetryService(
            topic_sidepath=self.sidepath,
            runtime=self.runtime,
            conversation=CONV,
        )

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
        self.sidepath.engine = None
        self.sidepath._process({"inbound": inbound, "conversation": conversation, "enqueued_at": 0})
        self._wait()
        return self.sidepath.last_result

    def _fanout(self):
        return (
            self.task_path.enqueued_count,
            self.decision_path.enqueued_count,
            self.risk_path.enqueued_count,
        )

    def _counts(self):
        return {
            "topic": self.topic_ext.calls,
            "task": self.task_ext.calls,
            "decision": self.decision_ext.calls,
            "risk": self.risk_ext.calls,
            "chat": len(self.host.replies),
        }

    def _retry(self, message_id, **kwargs):
        return retry_topic(
            CONV["id"],
            message_id,
            service=self.service,
            runtime=kwargs.get("runtime", self.runtime),
            version=kwargs.get("version", 0),
        )

    def _fail_then_arm(self, inbound):
        fanout_before = self._fanout()
        self.topic_ext.boom = True
        first = self._direct_process(inbound)
        self.assertEqual(first.decision, "FAILED")
        self.assertFalse(first.replayed)
        self.assertEqual(self._fanout(), fanout_before)
        rec = self.sidepath.store.get_processing(CONV["id"], first.message_id)
        self.assertEqual(rec["decision"], "FAILED")
        self.assertFalse(self.sidepath.store.has_successful_processing(CONV["id"], first.message_id))
        self.topic_ext.boom = False
        return first

    def test_topic_retry_01_failed_then_new_topic_fans_out(self):
        inbound = _inbound(platform_message_id="retry-01", content=NEW_TOPIC_TEXT)
        first = self._fail_then_arm(inbound)
        before = self._counts()
        fanout_before = self._fanout()
        outcome = self._retry(first.message_id)
        self._wait()
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.result, "SUCCESS")
        self.assertEqual(outcome.previous_status, "FAILED")
        self.assertEqual(outcome.decision, "NEW_TOPIC")
        self.assertFalse(outcome.replayed)
        self.assertTrue(outcome.topic_id)
        after = self._counts()
        self.assertEqual(after["topic"], before["topic"] + 1)
        self.assertEqual(after["task"], before["task"] + 1)
        self.assertEqual(after["decision"], before["decision"] + 1)
        self.assertEqual(after["risk"], before["risk"] + 1)
        self.assertEqual(after["chat"], 0)
        self.assertEqual(
            self._fanout(),
            (fanout_before[0] + 1, fanout_before[1] + 1, fanout_before[2] + 1),
        )
        rec = self.sidepath.store.get_processing(CONV["id"], first.message_id)
        self.assertEqual(rec["decision"], "NEW_TOPIC")
        self.assertTrue(self.sidepath.store.has_successful_processing(CONV["id"], first.message_id))
        events = [item.get("event") for item in self.service.audit_events]
        self.assertIn(EVENT_REQUESTED, events)
        self.assertIn(EVENT_SUCCESS, events)
        again = self._retry(first.message_id)
        self.assertTrue(again.rejected)
        self.assertFalse(again.executed)
        self.assertEqual(again.error_code, ERROR_NOT_RETRYABLE)
        self.assertEqual(self.topic_ext.calls, after["topic"])
        self.assertEqual(self._fanout(), (1, 1, 1))

    def test_topic_retry_02_failed_then_existing_topic_fans_out(self):
        seed = self._direct_process(_inbound(platform_message_id="retry-02-seed", content=NEW_TOPIC_TEXT))
        self.assertEqual(seed.decision, "NEW_TOPIC")
        self.assertEqual(self._fanout(), (1, 1, 1))
        inbound = _inbound(platform_message_id="retry-02", content=EXISTING_TEXT)
        first = self._fail_then_arm(inbound)
        self.assertEqual(self._fanout(), (1, 1, 1))
        before = self._counts()
        outcome = self._retry(first.message_id)
        self._wait()
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.decision, "EXISTING_TOPIC")
        self.assertFalse(outcome.replayed)
        after = self._counts()
        self.assertEqual(after["topic"], before["topic"] + 1)
        self.assertEqual(self._fanout(), (2, 2, 2))
        self.assertEqual(after["chat"], 0)

    def test_topic_retry_03_failed_then_topic_update_fans_out(self):
        seed = self._direct_process(_inbound(platform_message_id="retry-03-seed", content=NEW_TOPIC_TEXT))
        self.assertEqual(seed.decision, "NEW_TOPIC")
        inbound = _inbound(platform_message_id="retry-03", content=UPDATE_TEXT)
        first = self._fail_then_arm(inbound)
        before = self._fanout()
        outcome = self._retry(first.message_id)
        self._wait()
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.decision, "TOPIC_UPDATE")
        self.assertFalse(outcome.replayed)
        self.assertEqual(self._fanout(), (before[0] + 1, before[1] + 1, before[2] + 1))

    def test_topic_retry_04_failed_then_unrelated_zero_fanout(self):
        inbound = _inbound(platform_message_id="retry-04", content=NEW_TOPIC_TEXT)
        first = self._fail_then_arm(inbound)
        self.topic_ext.inner = ScriptedTopic("UNRELATED")
        before = self._counts()
        outcome = self._retry(first.message_id)
        self._wait()
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.decision, "UNRELATED")
        self.assertFalse(outcome.replayed)
        after = self._counts()
        self.assertEqual(after["topic"], before["topic"] + 1)
        self.assertEqual(after["task"], before["task"])
        self.assertEqual(after["decision"], before["decision"])
        self.assertEqual(after["risk"], before["risk"])
        self.assertEqual(self._fanout(), (0, 0, 0))
        rec = self.sidepath.store.get_processing(CONV["id"], first.message_id)
        self.assertEqual(rec["decision"], "UNRELATED")
        second = self._retry(first.message_id)
        self.assertTrue(second.rejected)
        self.assertEqual(second.error_code, ERROR_NOT_RETRYABLE)
        self.assertEqual(self.topic_ext.calls, after["topic"])

    def test_topic_retry_05_failed_then_failed_no_recursion(self):
        inbound = _inbound(platform_message_id="retry-05", content=NEW_TOPIC_TEXT)
        first = self._fail_then_arm(inbound)
        self.topic_ext.boom = True
        before = self._counts()
        outcome = self._retry(first.message_id)
        self._wait()
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.result, "FAILED")
        self.assertEqual(outcome.previous_status, "FAILED")
        after = self._counts()
        self.assertEqual(after["topic"], before["topic"] + 1)
        self.assertEqual(after["task"], before["task"])
        self.assertEqual(after["decision"], before["decision"])
        self.assertEqual(after["risk"], before["risk"])
        self.assertEqual(self._fanout(), (0, 0, 0))
        rec = self.sidepath.store.get_processing(CONV["id"], first.message_id)
        self.assertEqual(rec["decision"], "FAILED")
        events = [item.get("event") for item in self.service.audit_events]
        self.assertEqual(events.count(EVENT_REQUESTED), 1)
        self.assertEqual(events.count(EVENT_FAILED), 1)
        self.assertNotIn(EVENT_SUCCESS, events)
        self.assertEqual(len(self.sidepath.store.list_topics(CONV["id"])), 0)

    def test_topic_retry_06_success_not_retryable(self):
        inbound = _inbound(platform_message_id="retry-06", content=NEW_TOPIC_TEXT)
        first = self._direct_process(inbound)
        self.assertEqual(first.decision, "NEW_TOPIC")
        before = self._counts()
        fanout_before = self._fanout()
        outcome = self._retry(first.message_id)
        self.assertTrue(outcome.rejected)
        self.assertFalse(outcome.executed)
        self.assertEqual(outcome.error_code, ERROR_NOT_RETRYABLE)
        self.assertEqual(outcome.previous_status, "NEW_TOPIC")
        self.assertEqual(self._counts(), before)
        self.assertEqual(self._fanout(), fanout_before)
        events = [item.get("event") for item in self.service.audit_events]
        self.assertEqual(events, [EVENT_REJECTED])

    def test_topic_retry_07_missing_processing_not_found(self):
        before = self._counts()
        outcome = self._retry("msg_does_not_exist")
        self.assertTrue(outcome.rejected)
        self.assertFalse(outcome.executed)
        self.assertEqual(outcome.error_code, ERROR_NOT_FOUND)
        self.assertIsNone(self.sidepath.store.get_processing(CONV["id"], "msg_does_not_exist"))
        self.assertEqual(self._counts(), before)

    def test_topic_retry_08_stopped_rejects(self):
        inbound = _inbound(platform_message_id="retry-08", content=NEW_TOPIC_TEXT)
        first = self._fail_then_arm(inbound)
        before = self._counts()
        for state in ("STOPPING", "STOPPED", "ERROR", "STARTING"):
            self.runtime.set_state(state, "retry-08")
            outcome = self._retry(first.message_id)
            self.assertTrue(outcome.rejected)
            self.assertFalse(outcome.executed)
            self.assertEqual(outcome.error_code, ERROR_STOPPED)
            self.assertEqual(outcome.previous_status, "FAILED")
        self.assertEqual(self._counts(), before)
        self.runtime.set_state("RUNNING", "retry-08-restore")
        restored = self._retry(first.message_id)
        self._wait()
        self.assertTrue(restored.ok)
        self.assertEqual(restored.decision, "NEW_TOPIC")

    def test_topic_retry_09_engine_disabled(self):
        inbound = _inbound(platform_message_id="retry-09", content=NEW_TOPIC_TEXT)
        first = self._fail_then_arm(inbound)
        self.sidepath._enabled_override = False
        before = self.topic_ext.calls
        outcome = self._retry(first.message_id)
        self.assertTrue(outcome.rejected)
        self.assertFalse(outcome.executed)
        self.assertEqual(outcome.error_code, ERROR_ENGINE_DISABLED)
        self.assertEqual(self.topic_ext.calls, before)
        self.assertEqual(self._fanout(), (0, 0, 0))

    def test_topic_retry_10_downstream_disabled_respected(self):
        self.task_path._enabled_override = False
        inbound = _inbound(platform_message_id="retry-10", content=NEW_TOPIC_TEXT)
        first = self._fail_then_arm(inbound)
        before = self._counts()
        outcome = self._retry(first.message_id)
        self._wait()
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.decision, "NEW_TOPIC")
        after = self._counts()
        self.assertEqual(after["topic"], before["topic"] + 1)
        self.assertEqual(after["task"], before["task"])
        self.assertEqual(after["decision"], before["decision"] + 1)
        self.assertEqual(after["risk"], before["risk"] + 1)
        self.assertEqual(self._fanout(), (0, 1, 1))
        self.assertEqual(self.task_path.last_skip_reason, "TASK_ENGINE_DISABLED")

    def test_topic_retry_11_success_replay_zero_fanout(self):
        inbound = _inbound(platform_message_id="retry-11", content=NEW_TOPIC_TEXT)
        first = self._direct_process(inbound)
        self.assertFalse(first.replayed)
        self.assertEqual(self._fanout(), (1, 1, 1))
        before = self._counts()
        fanout_before = self._fanout()
        second = self._direct_process(inbound)
        self.assertTrue(second.replayed)
        self.assertEqual(self.topic_ext.calls, before["topic"])
        self.assertEqual(self.task_ext.calls, before["task"])
        self.assertEqual(self.decision_ext.calls, before["decision"])
        self.assertEqual(self.risk_ext.calls, before["risk"])
        self.assertEqual(self._fanout(), fanout_before)
        replay_events = [item for item in self.sidepath.audit_events if item.get("event") == EVENT_TOPIC_REPLAY]
        self.assertEqual(len(replay_events), 1)
        self.assertTrue(replay_events[0].get("fanout_skipped"))

    def test_topic_retry_12_n2_same_text_different_pid(self):
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

    def test_topic_retry_13_p0_duplicate(self):
        inbound = _inbound(platform_message_id="p0-dup", content=NEW_TOPIC_TEXT)
        first = try_enqueue_topic_sidepath(inbound, self._eval(inbound), runtime=self.runtime)
        self.assertTrue(first["enqueued"])
        self._wait()
        again = _inbound(platform_message_id="p0-dup", content=NEW_TOPIC_TEXT)
        verdict = self._eval(again)
        skipped = try_enqueue_topic_sidepath(again, verdict, runtime=self.runtime)
        self.assertEqual(verdict["action"], NO_ACTION)
        self.assertFalse(skipped["enqueued"])
        self.assertEqual(skipped["reason"], SKIP_DUPLICATE)
        self.assertEqual(self.sidepath.enqueued_count, 1)
        self.assertEqual(self._fanout(), (1, 1, 1))

    def test_topic_retry_14_downstream_retry_still_independent(self):
        self.task_ext.boom = True
        inbound = _inbound(
            platform_message_id="retry-14",
            content="李娜把 ERP 同步今天还是有问题修一下。",
        )
        first = self._direct_process(inbound)
        self.assertEqual(first.decision, "NEW_TOPIC")
        self.assertEqual(self._fanout(), (1, 1, 1))
        self.assertGreaterEqual(self.task_path.failed_count, 1)
        self.assertGreaterEqual(self.decision_path.processed_count, 1)
        self.assertGreaterEqual(self.risk_path.processed_count, 1)
        topic_retry = self._retry(first.message_id)
        self.assertTrue(topic_retry.rejected)
        self.assertEqual(topic_retry.error_code, ERROR_NOT_RETRYABLE)
        self.task_ext.boom = False
        self.task_ext.inner = ScriptedTask()
        task_engine = TaskEngine(
            self.task_path.store,
            self.sidepath.store,
            extractor=self.task_ext,
            root_dir=ROOT,
            enabled=True,
        )
        decision_engine = DecisionEngine(
            self.decision_path.store,
            self.sidepath.store,
            extractor=self.decision_ext,
            root_dir=ROOT,
            enabled=True,
        )
        risk_engine = RiskEngine(
            self.risk_path.store,
            self.sidepath.store,
            task_store=self.task_path.store,
            extractor=self.risk_ext,
            root_dir=ROOT,
            enabled=True,
        )
        downstream = DownstreamRetryService(
            topic_store=self.sidepath.store,
            task_engine=task_engine,
            decision_engine=decision_engine,
            risk_engine=risk_engine,
            runtime=self.runtime,
            conversation=CONV,
        )
        before = self._counts()
        outcome = retry_downstream(
            "task",
            CONV["id"],
            first.message_id,
            first.topic_id,
            service=downstream,
            runtime=self.runtime,
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.engine_decision, "NEW_TASK")
        after = self._counts()
        self.assertEqual(after["task"], before["task"] + 1)
        self.assertEqual(after["topic"], before["topic"])
        self.assertEqual(after["decision"], before["decision"])
        self.assertEqual(after["risk"], before["risk"])
        self.assertEqual(after["chat"], 0)

    def test_flags_remain_disabled(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def test_source_is_sync_internal_capability(self):
        import topic_retry as mod

        source = inspect.getsource(mod)
        self.assertNotIn("queue.Queue", source)
        self.assertNotIn("threading.Thread", source)
        self.assertNotIn("send_reply(", source)
        self.assertNotIn("wx.SendMsg", source)
        self.assertNotIn("topic_result_allows_task", source)
        self.assertNotIn("topic_result_allows_decision", source)
        self.assertNotIn("topic_result_allows_risk", source)
        self.assertIn("EVENT_REQUESTED", source)
        self.assertIn("one-shot", source.lower())


if __name__ == "__main__":
    unittest.main()
