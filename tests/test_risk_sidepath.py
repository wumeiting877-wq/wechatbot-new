# -*- coding: utf-8 -*-
"""P5-G4 Gate 1：Risk Side-path 自动测试 RS1 ～ RS13。"""

from __future__ import annotations

import inspect
import logging
import os
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_extractor_client import HeuristicDecisionExtractor
from decision_sidepath import SKIP_DISABLED as DECISION_SKIP_DISABLED
from decision_sidepath import DecisionSidepath, reset_decision_sidepath
from message.bind import bind_host
from message.identity import InboundMessage
from message.listener import message_listener
from message.trigger import NO_ACTION
from risk_engine import RiskEngine
from risk_extractor_client import HeuristicRiskExtractor
from risk_sidepath import (
    EVENT_QUEUE_FULL,
    SKIP_DISABLED,
    SKIP_TOPIC_NOT_ELIGIBLE,
    RiskSidepath,
    reset_risk_sidepath,
    sidepath_source_forbids_wechat_send,
    topic_result_allows_risk,
    try_enqueue_risk_after_topic,
)
from risk_store import RiskStore
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import SKIP_DISABLED as TASK_SKIP_DISABLED
from task_sidepath import TaskSidepath, reset_task_sidepath
from topic_engine import EngineResult
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import TopicSidepath, reset_sidepath, try_enqueue_topic_sidepath
from topic_store import TopicStore


CONV = {
    "id": "conv_g4risk01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_g4risk@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
    "agent_config_id": "agt_g4risk",
}

BOT_WXID = "wxid_bot_g4risk"
BOT_NAME = "测试助手"
EXPLICIT_RISK = "如果今天还修不好，会影响明天现场演示。"


class FakeMsg:
    def __init__(self, content, **kwargs):
        self.content = content
        self.type = kwargs.get("type", "text")
        self.sender = kwargs.get("sender", "周敏")
        self.attr = kwargs.get("attr", "friend")
        self.sender_id = kwargs.get("sender_id", 88)
        self.sender_wxid = kwargs.get("sender_wxid", "wxid_zhoumin")
        self.local_id = kwargs.get("local_id", 2001)
        self.create_time = kwargs.get("create_time", 1710000000)
        self.sort_seq = kwargs.get("sort_seq", 1)
        self.platform_message_id = kwargs.get("platform_message_id", "")
        self.quote_content = kwargs.get("quote_content", "")
        self.direction = kwargs.get("direction", "INBOUND")

    def to_text(self):
        return self.content

    def get_url(self):
        return "https://example.invalid"

    def get_messages(self):
        return []


class FakeChat:
    def __init__(self, who="测试群", wxid="room_g4risk@chatroom"):
        self.who = who
        self._wxid = wxid


class FakeHost:
    def __init__(self, runtime, root_dir, is_group=True):
        self.runtime = runtime
        self.logger = logging.getLogger("test_risk_sidepath")
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
        self._is_group = is_group
        self.conversations = [dict(CONV)]
        self.root_dir = root_dir
        self.can_send_messages = True

    def is_user_group_chat(self, _who):
        return self._is_group

    def handle_wxauto_message(self, msg, who):
        self.replies.append((who, getattr(msg, "content", "")))

    def handle_emoji_message(self, msg, who):
        self.replies.append((who, "emoji"))

    def recognize_image_with_moonshot(self, *_a, **_k):
        return ""


def _inbound(**kwargs):
    data = {
        "platform_message_id": kwargs.pop("platform_message_id", "pid-risk-1"),
        "conversation_id": kwargs.pop("conversation_id", "room_g4risk@chatroom"),
        "chat_name": kwargs.pop("chat_name", "测试群"),
        "chat_wxid": kwargs.pop("chat_wxid", "room_g4risk@chatroom"),
        "sender_id": kwargs.pop("sender_id", 88),
        "sender_wxid": kwargs.pop("sender_wxid", "wxid_zhoumin"),
        "sender_name": kwargs.pop("sender_name", "周敏"),
        "content": kwargs.pop("content", EXPLICIT_RISK),
        "raw_type": kwargs.pop("raw_type", "text"),
        "direction": kwargs.pop("direction", "INBOUND"),
        "create_time": kwargs.pop("create_time", 1710000000),
        "attr": kwargs.pop("attr", "friend"),
    }
    data.update(kwargs)
    return InboundMessage(**data)


class _BlockingRiskExtractor:
    def __init__(self, gate: threading.Event):
        self.gate = gate
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        self.gate.wait(timeout=8)
        current = (engine_input or {}).get("current_message") or {}
        return {
            "risks": [
                {
                    "decision": "UNRELATED",
                    "risk_id": None,
                    "title": "",
                    "condition_text": "",
                    "impact_text": "",
                    "task_id": None,
                    "confidence": "LOW",
                    "evidence_message_ids": [current.get("id")] if current.get("id") else [],
                    "reason": "blocked-test",
                }
            ]
        }


class _BoomRiskEngine:
    def process_record(self, *_a, **_k):
        raise RuntimeError("risk worker boom")


class _BoomTaskEngine:
    def process_record(self, *_a, **_k):
        raise RuntimeError("task worker boom")


class _BoomDecisionEngine:
    def process_record(self, *_a, **_k):
        raise RuntimeError("decision worker boom")


class _BoomTopicExtractor:
    def extract(self, *_a, **_k):
        raise TimeoutError("topic boom")


class _BoomTaskStore:
    def list_open_tasks(self, *_a, **_k):
        raise RuntimeError("task store down")


class RiskSidepathTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.runtime.set_identity(bot_wxid=BOT_WXID, bot_name=BOT_NAME, login_account=BOT_NAME)
        self.host = FakeHost(self.runtime, self.root, is_group=True)
        bind_host(self.host)
        self.task_path = TaskSidepath(
            root_dir=self.root,
            extractor=HeuristicTaskExtractor(),
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
        )
        self.decision_path = DecisionSidepath(
            root_dir=self.root,
            extractor=HeuristicDecisionExtractor(),
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
        )
        self.risk_path = RiskSidepath(
            root_dir=self.root,
            extractor=HeuristicRiskExtractor(),
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
        )
        self.sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=HeuristicTopicExtractor(),
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

    def _enqueue(self, content, pid, **kwargs):
        inbound = _inbound(platform_message_id=pid, content=content, **kwargs)
        verdict = self._eval(inbound)
        return try_enqueue_topic_sidepath(inbound, verdict, runtime=self.runtime), inbound, verdict

    def _wait(self, timeout=3.0):
        self.assertTrue(self.sidepath.wait_idle(timeout), "Topic worker did not finish")
        self.assertTrue(self.task_path.wait_idle(timeout), "Task worker did not finish")
        self.assertTrue(self.decision_path.wait_idle(timeout), "Decision worker did not finish")
        self.assertTrue(self.risk_path.wait_idle(timeout), "Risk worker did not finish")

    def test_listener_has_no_second_risk_sidepath(self):
        source = inspect.getsource(message_listener)
        self.assertIn("try_enqueue_topic_sidepath", source)
        self.assertNotIn("try_enqueue_risk", source)
        self.assertNotIn("risk_sidepath", source)
        self.assertNotIn("try_enqueue_task", source)
        self.assertNotIn("try_enqueue_decision", source)
        self.assertTrue(sidepath_source_forbids_wechat_send())
        import risk_engine
        import risk_extractor_client
        import risk_sidepath
        import risk_store
        for module in (risk_engine, risk_extractor_client, risk_store, risk_sidepath):
            text = inspect.getsource(module)
            self.assertNotIn("send_reply" + "(", text)
            self.assertNotIn("wx.SendMsg" + "(", text)
            self.assertNotIn("SendMsg" + "(", text)

    def test_rs1_new_topic_enqueues_risk(self):
        result, _, _ = self._enqueue("ERP 同步今天还是有问题。", "rs1")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.risk_path.enqueued_count, 1)
        self.assertIn(self.sidepath.last_result.decision, ("NEW_TOPIC",))
        self.assertTrue(self.sidepath.last_result.topic_id)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertTrue(topics)

    def test_rs2_existing_topic_enqueues_risk(self):
        self._enqueue("ERP 同步今天还是有问题。", "rs2-seed")
        self._wait()
        before = self.risk_path.enqueued_count
        result, _, _ = self._enqueue("ERP 同步供应商编码还是空。", "rs2")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "EXISTING_TOPIC")
        self.assertEqual(self.risk_path.enqueued_count, before + 1)

    def test_rs3_topic_update_enqueues_risk(self):
        self._enqueue("ERP 同步今天还是有问题。", "rs3-seed")
        self._wait()
        before = self.risk_path.enqueued_count
        result, _, _ = self._enqueue("ERP 同步规则需要修复。", "rs3")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "TOPIC_UPDATE")
        self.assertEqual(self.risk_path.enqueued_count, before + 1)

    def test_rs4_unrelated_does_not_enqueue_risk(self):
        result, _, _ = self._enqueue("中午吃什么", "rs4")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertIn(self.sidepath.last_result.decision, ("UNRELATED", "SKIPPED"))
        self.assertEqual(self.risk_path.enqueued_count, 0)
        self.assertEqual(self.risk_path.last_skip_reason, SKIP_TOPIC_NOT_ELIGIBLE)

    def test_rs5_failed_does_not_enqueue_risk(self):
        self.sidepath.extractor = _BoomTopicExtractor()
        result, _, _ = self._enqueue("ERP 同步今天还是有问题。", "rs5")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "FAILED")
        self.assertEqual(self.risk_path.enqueued_count, 0)

    def test_rs6_skipped_does_not_enqueue_risk(self):
        result, _, _ = self._enqueue("", "rs6")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "SKIPPED")
        self.assertEqual(self.risk_path.enqueued_count, 0)
        self.assertFalse(topic_result_allows_risk(self.sidepath.last_result))

    def test_rs7_risk_disabled_topic_task_decision_still_work(self):
        disabled = RiskSidepath(
            root_dir=self.root,
            extractor=HeuristicRiskExtractor(),
            enabled=False,
            prompt_root=ROOT,
        )
        topic = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=HeuristicTopicExtractor(),
            enabled=True,
            prompt_root=ROOT,
            task_sidepath=self.task_path,
            decision_sidepath=self.decision_path,
            risk_sidepath=disabled,
        )
        reset_sidepath(topic)
        reset_risk_sidepath(disabled)
        self.sidepath = topic
        self.risk_path = disabled
        result, _, verdict = self._enqueue("ERP 同步今天还是有问题。", "rs7")
        self.assertTrue(result["enqueued"])
        self.assertEqual(verdict["action"], NO_ACTION)
        self._wait()
        self.assertTrue(topic.last_result.topic_id)
        self.assertGreaterEqual(self.task_path.enqueued_count, 1)
        self.assertGreaterEqual(self.decision_path.enqueued_count, 1)
        self.assertEqual(disabled.enqueued_count, 0)
        self.assertEqual(disabled.last_skip_reason, SKIP_DISABLED)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertTrue(topics)
        self.assertEqual(
            RiskStore(self.root, topic_store=TopicStore(self.root)).list_risks(CONV["id"]),
            [],
        )

    def test_rs8_task_failed_does_not_block_risk(self):
        self.task_path.engine = _BoomTaskEngine()
        result, _, _ = self._enqueue(EXPLICIT_RISK, "rs8")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertTrue(self.sidepath.last_result.topic_id)
        self.assertEqual(self.risk_path.enqueued_count, 1)
        self.assertGreaterEqual(self.task_path.failed_count, 1)
        self.assertGreaterEqual(self.risk_path.processed_count, 1)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertEqual(len(topics), 1)
        risks = self.risk_path.store.list_risks(CONV["id"])
        self.assertTrue(risks)
        rec = self.task_path.store.get_processing(CONV["id"], self.sidepath.last_result.message_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["decision_summary"], "FAILED")

    def test_rs9_decision_failed_does_not_block_risk(self):
        self.decision_path.engine = _BoomDecisionEngine()
        result, _, _ = self._enqueue(EXPLICIT_RISK, "rs9")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertTrue(self.sidepath.last_result.topic_id)
        self.assertEqual(self.risk_path.enqueued_count, 1)
        self.assertGreaterEqual(self.decision_path.failed_count, 1)
        self.assertGreaterEqual(self.risk_path.processed_count, 1)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertEqual(len(topics), 1)
        risks = self.risk_path.store.list_risks(CONV["id"])
        self.assertTrue(risks)
        rec = self.decision_path.store.get_processing(CONV["id"], self.sidepath.last_result.message_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["decision_summary"], "FAILED")

    def test_rs10_taskstore_unavailable_still_creates_risk(self):
        topic_store = TopicStore(self.root)
        risk_store = RiskStore(self.root, topic_store=topic_store, task_store=_BoomTaskStore())
        engine = RiskEngine(
            risk_store,
            topic_store,
            task_store=_BoomTaskStore(),
            extractor=HeuristicRiskExtractor(),
            root_dir=ROOT,
            enabled=True,
        )
        self.risk_path.engine = engine
        self.risk_path.store = risk_store
        result, _, _ = self._enqueue(EXPLICIT_RISK, "rs10")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.risk_path.enqueued_count, 1)
        self.assertGreaterEqual(self.risk_path.processed_count, 1)
        risks = risk_store.list_risks(CONV["id"])
        self.assertTrue(risks)
        self.assertEqual(risks[0].get("task_id") or "", "")
        self.assertEqual(self.risk_path.last_result.candidate_tasks_error.split(":")[0], "RuntimeError")
        self.assertNotEqual(self.risk_path.last_result.decision, "FAILED")

    def test_rs11_risk_queue_full_does_not_block_topic_worker(self):
        gate = threading.Event()
        slow_risk = RiskSidepath(
            root_dir=self.root,
            extractor=_BlockingRiskExtractor(gate),
            enabled=True,
            maxsize=2,
            prompt_root=ROOT,
        )
        topic = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=HeuristicTopicExtractor(),
            enabled=True,
            maxsize=16,
            prompt_root=ROOT,
            task_sidepath=self.task_path,
            decision_sidepath=self.decision_path,
            risk_sidepath=slow_risk,
        )
        reset_sidepath(topic)
        reset_risk_sidepath(slow_risk)
        self.sidepath = topic
        self.risk_path = slow_risk
        started = time.perf_counter()
        try:
            for index in range(6):
                self._enqueue("ERP 同步今天还是有问题 %s。" % index, "rs11-%s" % index)
            self.assertTrue(topic.wait_idle(3), "Topic worker blocked by Risk queue")
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 1.5)
            self.assertGreaterEqual(slow_risk.queue_full_count, 1)
            events = [item.get("event") for item in slow_risk.audit_events]
            self.assertIn(EVENT_QUEUE_FULL, events)
        finally:
            gate.set()
            slow_risk.wait_idle(4)
            self.task_path.wait_idle(4)
            self.decision_path.wait_idle(4)

    def test_rs12_risk_worker_exception_preserves_topic_task_decision(self):
        self.risk_path.engine = _BoomRiskEngine()
        result, _, _ = self._enqueue("ERP 同步今天还是有问题。", "rs12")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertTrue(self.sidepath.last_result.topic_id)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertEqual(len(topics), 1)
        self.assertGreaterEqual(self.task_path.enqueued_count, 1)
        self.assertGreaterEqual(self.decision_path.enqueued_count, 1)
        self.assertGreaterEqual(self.risk_path.failed_count, 1)
        rec = self.risk_path.store.get_processing(CONV["id"], self.sidepath.last_result.message_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["decision_summary"], "FAILED")
        self.assertEqual(self.risk_path.store.list_risks(CONV["id"]), [])

    def test_rs13_stop_bot_stops_topic_task_decision_and_risk(self):
        result, _, _ = self._enqueue(EXPLICIT_RISK, "rs13-seed")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertGreaterEqual(self.risk_path.enqueued_count, 1)
        topics_before = len(TopicStore(self.root).list_topics(CONV["id"]))
        tasks_before = len(self.task_path.store.list_tasks(CONV["id"]))
        decisions_before = len(self.decision_path.store.list_decisions(CONV["id"]))
        risks_before = len(self.risk_path.store.list_risks(CONV["id"]))
        self.runtime.begin_graceful_stop("test-stop")
        after, _, _ = self._enqueue("如果今晚处理不完，会影响明天演示。", "rs13-after")
        self.assertFalse(after["enqueued"])
        self._listen_stopped("Stop之后还有风险吗？", "rs13-listen")
        self.assertEqual(len(self.host.replies), 0)
        self.assertEqual(len(TopicStore(self.root).list_topics(CONV["id"])), topics_before)
        self.assertEqual(len(self.task_path.store.list_tasks(CONV["id"])), tasks_before)
        self.assertEqual(len(self.decision_path.store.list_decisions(CONV["id"])), decisions_before)
        self.assertEqual(len(self.risk_path.store.list_risks(CONV["id"])), risks_before)

    def _listen_stopped(self, content, pid):
        msg = FakeMsg(content, platform_message_id=pid)
        message_listener(msg, FakeChat())


class RiskSidepathIsolationTests(unittest.TestCase):
    def test_try_enqueue_never_raises(self):
        result = try_enqueue_risk_after_topic(None)
        self.assertFalse(result["enqueued"])

    def test_forbidden_decisions_rejected(self):
        for decision in ("UNRELATED", "SKIPPED", "FAILED", "DISABLED", "CONVERSATION_NOT_RESOLVED"):
            self.assertFalse(
                topic_result_allows_risk(
                    EngineResult(decision=decision, topic_id="topic_x", conversation_id="conv_x")
                )
            )
        self.assertFalse(topic_result_allows_risk(EngineResult(decision="NEW_TOPIC", topic_id=None)))
        self.assertFalse(
            topic_result_allows_risk(
                EngineResult(decision="NEW_TOPIC", topic_id="topic_x", error_code="EXTRACTOR_TIMEOUT")
            )
        )
        self.assertTrue(
            topic_result_allows_risk(
                EngineResult(decision="NEW_TOPIC", topic_id="topic_x", conversation_id="conv_x")
            )
        )

    def test_four_switches_are_independent(self):
        self.assertEqual(TASK_SKIP_DISABLED, "TASK_ENGINE_DISABLED")
        self.assertEqual(DECISION_SKIP_DISABLED, "DECISION_ENGINE_DISABLED")
        self.assertEqual(SKIP_DISABLED, "RISK_ENGINE_DISABLED")
        self.assertNotEqual(SKIP_DISABLED, TASK_SKIP_DISABLED)
        self.assertNotEqual(SKIP_DISABLED, DECISION_SKIP_DISABLED)


if __name__ == "__main__":
    unittest.main()
