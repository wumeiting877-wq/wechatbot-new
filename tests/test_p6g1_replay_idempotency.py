# -*- coding: utf-8 -*-
"""P6-G1 Replay / Fan-out Idempotency：REPLAY-01 ～ REPLAY-08。

Topic replay ≠ P0 DUPLICATE，也 ≠ N2 同正文不同 platform_message_id。
"""

from __future__ import annotations

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
from decision_engine import DECISION_ENGINE_ENABLED
from decision_extractor_client import HeuristicDecisionExtractor
from decision_sidepath import DecisionSidepath, reset_decision_sidepath
from message.bind import bind_host
from message.identity import InboundMessage
from message.trigger import NO_ACTION
from risk_engine import RISK_ENGINE_ENABLED
from risk_extractor_client import HeuristicRiskExtractor
from risk_sidepath import RiskSidepath, reset_risk_sidepath
from task_engine import TASK_ENGINE_ENABLED
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import TaskSidepath, reset_task_sidepath
from topic_engine import TOPIC_ENGINE_ENABLED, resolve_topic_conversation
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import (
    EVENT_TOPIC_REPLAY,
    SKIP_DUPLICATE,
    TopicSidepath,
    reset_sidepath,
    try_enqueue_topic_sidepath,
)
from topic_store import TopicStore


CONV = {
    "id": "conv_p6g1replay01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_p6g1@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
    "agent_config_id": "agt_p6g1",
}

BOT_WXID = "wxid_bot_p6g1"
BOT_NAME = "测试助手"
NEW_TOPIC_TEXT = "ERP 同步今天还是有问题。"
EXISTING_TEXT = "ERP 同步供应商编码还是空。"
UPDATE_TEXT = "ERP 同步规则需要修复。"
UNRELATED_TEXT = "中午吃什么"


class CountingExtractor:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        return self.inner.extract(engine_input, prompt_content)


class BoomExtractor:
    def extract(self, *_a, **_k):
        raise TimeoutError("topic boom")


class BoomEngine:
    def process_record(self, *_a, **_k):
        raise RuntimeError("downstream boom")


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p6g1_replay")
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
        "platform_message_id": kwargs.pop("platform_message_id", "pid-p6g1-1"),
        "conversation_id": kwargs.pop("conversation_id", "room_p6g1@chatroom"),
        "chat_name": kwargs.pop("chat_name", "测试群"),
        "chat_wxid": kwargs.pop("chat_wxid", "room_p6g1@chatroom"),
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


class P6G1ReplayIdempotencyTests(unittest.TestCase):
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
        self.sidepath._process(
            {"inbound": inbound, "conversation": conversation, "enqueued_at": 0}
        )
        self._wait()
        return self.sidepath.last_result

    def _fanout(self):
        return (
            self.task_path.enqueued_count,
            self.decision_path.enqueued_count,
            self.risk_path.enqueued_count,
        )

    def _store_snapshot(self, message_id):
        cid = CONV["id"]
        store = self.sidepath.store
        return {
            "topics": len(store.list_topics(cid)),
            "links": len(store.list_links(cid)),
            "processing": store.get_processing(cid, message_id),
            "task_links": len(self.task_path.store.list_links(cid)),
            "decision_links": len(self.decision_path.store.list_links(cid)),
            "risk_links": len(self.risk_path.store.list_links(cid)),
            "tasks": len(self.task_path.store.list_tasks(cid)),
            "decisions": len(self.decision_path.store.list_decisions(cid)),
            "risks": len(self.risk_path.store.list_risks(cid)),
        }

    def test_replay_01_first_success_fans_out_once(self):
        inbound = _inbound(platform_message_id="replay-01", content=NEW_TOPIC_TEXT)
        result = self._direct_process(inbound)
        self.assertEqual(result.decision, "NEW_TOPIC")
        self.assertFalse(result.replayed)
        self.assertTrue(result.topic_id)
        self.assertEqual(self.topic_ext.calls, 1)
        self.assertEqual(self._fanout(), (1, 1, 1))
        events = [item.get("event") for item in self.sidepath.audit_events]
        self.assertNotIn(EVENT_TOPIC_REPLAY, events)

    def test_replay_02_same_message_replay_skips_fanout(self):
        inbound = _inbound(platform_message_id="replay-02", content=NEW_TOPIC_TEXT)
        first = self._direct_process(inbound)
        self.assertFalse(first.replayed)
        self.assertEqual(self._fanout(), (1, 1, 1))
        before = {
            "topic_ext": self.topic_ext.calls,
            "task_ext": self.task_ext.calls,
            "decision_ext": self.decision_ext.calls,
            "risk_ext": self.risk_ext.calls,
            "fanout": self._fanout(),
            "task_processed": self.task_path.processed_count,
            "decision_processed": self.decision_path.processed_count,
            "risk_processed": self.risk_path.processed_count,
        }
        snap = self._store_snapshot(first.message_id)
        second = self._direct_process(inbound)
        self.assertTrue(second.replayed)
        self.assertEqual(second.decision, first.decision)
        self.assertEqual(second.message_id, first.message_id)
        self.assertEqual(second.topic_id, first.topic_id)
        self.assertEqual(self.topic_ext.calls, before["topic_ext"])
        self.assertEqual(self.topic_ext.calls, 1)
        self.assertEqual(self.task_ext.calls, before["task_ext"])
        self.assertEqual(self.decision_ext.calls, before["decision_ext"])
        self.assertEqual(self.risk_ext.calls, before["risk_ext"])
        self.assertEqual(self._fanout(), before["fanout"])
        self.assertEqual(self._fanout(), (1, 1, 1))
        self.assertEqual(self.task_path.processed_count, before["task_processed"])
        self.assertEqual(self.decision_path.processed_count, before["decision_processed"])
        self.assertEqual(self.risk_path.processed_count, before["risk_processed"])
        after = self._store_snapshot(second.message_id)
        self.assertEqual(after["topics"], snap["topics"])
        self.assertEqual(after["links"], snap["links"])
        self.assertEqual(after["task_links"], snap["task_links"])
        self.assertEqual(after["decision_links"], snap["decision_links"])
        self.assertEqual(after["risk_links"], snap["risk_links"])
        self.assertEqual(after["tasks"], snap["tasks"])
        self.assertEqual(after["decisions"], snap["decisions"])
        self.assertEqual(after["risks"], snap["risks"])
        self.assertEqual(
            (after["processing"] or {}).get("decision"),
            (snap["processing"] or {}).get("decision"),
        )
        replay_events = [
            item for item in self.sidepath.audit_events if item.get("event") == EVENT_TOPIC_REPLAY
        ]
        self.assertEqual(len(replay_events), 1)
        self.assertEqual(replay_events[0].get("message_id"), second.message_id)
        self.assertEqual(replay_events[0].get("topic_id"), second.topic_id)
        self.assertTrue(replay_events[0].get("fanout_skipped"))

    def test_replay_03_first_topic_update_still_fans_out(self):
        self._direct_process(_inbound(platform_message_id="replay-03-seed", content=NEW_TOPIC_TEXT))
        before = self._fanout()
        result = self._direct_process(
            _inbound(platform_message_id="replay-03", content=UPDATE_TEXT)
        )
        self.assertEqual(result.decision, "TOPIC_UPDATE")
        self.assertFalse(result.replayed)
        self.assertEqual(
            self._fanout(),
            (before[0] + 1, before[1] + 1, before[2] + 1),
        )

    def test_replay_04_first_existing_topic_is_not_replay(self):
        self._direct_process(_inbound(platform_message_id="replay-04-seed", content=NEW_TOPIC_TEXT))
        before = self._fanout()
        result = self._direct_process(
            _inbound(platform_message_id="replay-04", content=EXISTING_TEXT)
        )
        self.assertEqual(result.decision, "EXISTING_TOPIC")
        self.assertFalse(result.replayed)
        self.assertEqual(
            self._fanout(),
            (before[0] + 1, before[1] + 1, before[2] + 1),
        )

    def test_replay_05_failed_still_zero_fanout(self):
        self.sidepath.extractor = BoomExtractor()
        self.sidepath.engine = None
        result = self._direct_process(
            _inbound(platform_message_id="replay-05", content=NEW_TOPIC_TEXT)
        )
        self.assertEqual(result.decision, "FAILED")
        self.assertFalse(result.replayed)
        self.assertEqual(self._fanout(), (0, 0, 0))

    def test_replay_06_unrelated_and_skipped_zero_fanout(self):
        unrelated = self._direct_process(
            _inbound(platform_message_id="replay-06-u", content=UNRELATED_TEXT)
        )
        self.assertIn(unrelated.decision, ("UNRELATED", "SKIPPED"))
        self.assertFalse(unrelated.replayed)
        self.assertEqual(self._fanout(), (0, 0, 0))
        skipped = self._direct_process(_inbound(platform_message_id="replay-06-s", content=""))
        self.assertEqual(skipped.decision, "SKIPPED")
        self.assertFalse(skipped.replayed)
        self.assertEqual(self._fanout(), (0, 0, 0))

    def test_replay_07_n2_same_text_different_pid_two_non_replay(self):
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
        cid = CONV["id"]
        messages = self.sidepath.store.list_messages(cid)
        self.assertEqual(len(messages), 2)
        ids = {item.get("id") for item in messages}
        self.assertEqual(len(ids), 2)
        for message in messages:
            rec = self.sidepath.store.get_processing(cid, message["id"])
            self.assertIsNotNone(rec)
            self.assertNotEqual(rec.get("decision"), "FAILED")

    def test_replay_08_one_downstream_failure_does_not_block_others(self):
        self.task_path.engine = BoomEngine()
        result = self._direct_process(
            _inbound(platform_message_id="replay-08", content=NEW_TOPIC_TEXT)
        )
        self.assertEqual(result.decision, "NEW_TOPIC")
        self.assertFalse(result.replayed)
        self.assertEqual(self._fanout(), (1, 1, 1))
        self.assertGreaterEqual(self.task_path.failed_count, 1)
        self.assertGreaterEqual(self.decision_path.processed_count, 1)
        self.assertGreaterEqual(self.risk_path.processed_count, 1)
        self.decision_path.engine = BoomEngine()
        self.task_path.engine = None
        second = self._direct_process(
            _inbound(platform_message_id="replay-08b", content=EXISTING_TEXT)
        )
        self.assertFalse(second.replayed)
        self.assertEqual(self.decision_path.enqueued_count, 2)
        self.assertEqual(self.risk_path.enqueued_count, 2)
        self.assertEqual(self.task_path.enqueued_count, 2)
        self.assertGreaterEqual(self.decision_path.failed_count, 1)
        self.assertGreaterEqual(self.risk_path.processed_count, 2)

    def test_p0_duplicate_does_not_enter_topic_replay_path(self):
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

    def test_engine_flags_remain_false(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)


if __name__ == "__main__":
    unittest.main()
