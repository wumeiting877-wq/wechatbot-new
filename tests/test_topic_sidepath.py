# -*- coding: utf-8 -*-
"""P3-G2 Gate 1：Topic Side-path 自动测试 CASE-S1 ～ CASE-S10。"""

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
from message.bind import bind_host
from message.identity import InboundMessage
from message.listener import message_listener
from message.trigger import NO_ACTION, REPLY
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import (
    EVENT_QUEUE_FULL,
    SKIP_DISABLED,
    SKIP_DUPLICATE,
    SKIP_OUTBOUND,
    SKIP_SELF,
    SKIP_STOPPED,
    SKIP_SYSTEM,
    TopicSidepath,
    reset_sidepath,
    sidepath_source_forbids_wechat_send,
    try_enqueue_topic_sidepath,
)
from topic_store import TopicStore


CONV = {
    "id": "conv_g2sidepath01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_g2@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
    "agent_config_id": "agt_g2",
}

BOT_WXID = "wxid_bot_g2"
BOT_NAME = "测试助手"


class FakeMsg:
    def __init__(self, content, **kwargs):
        self.content = content
        self.type = kwargs.get("type", "text")
        self.sender = kwargs.get("sender", "张三")
        self.attr = kwargs.get("attr", "friend")
        self.sender_id = kwargs.get("sender_id", 88)
        self.sender_wxid = kwargs.get("sender_wxid", "wxid_zhangsan")
        self.local_id = kwargs.get("local_id", 1001)
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
    def __init__(self, who="测试群", wxid="room_g2@chatroom"):
        self.who = who
        self._wxid = wxid


class FakeHost:
    def __init__(self, runtime, root_dir, is_group=True):
        self.runtime = runtime
        self.logger = logging.getLogger("test_topic_sidepath")
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
        "platform_message_id": kwargs.pop("platform_message_id", "pid-g2-1"),
        "conversation_id": kwargs.pop("conversation_id", "room_g2@chatroom"),
        "chat_name": kwargs.pop("chat_name", "测试群"),
        "chat_wxid": kwargs.pop("chat_wxid", "room_g2@chatroom"),
        "sender_id": kwargs.pop("sender_id", 88),
        "sender_wxid": kwargs.pop("sender_wxid", "wxid_zhangsan"),
        "sender_name": kwargs.pop("sender_name", "张三"),
        "content": kwargs.pop("content", "ERP 同步今天还是有问题"),
        "raw_type": kwargs.pop("raw_type", "text"),
        "direction": kwargs.pop("direction", "INBOUND"),
        "create_time": kwargs.pop("create_time", 1710000000),
        "attr": kwargs.pop("attr", "friend"),
    }
    data.update(kwargs)
    return InboundMessage(**data)


class _BlockingExtractor:
    def __init__(self, gate: threading.Event):
        self.gate = gate
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        self.gate.wait(timeout=5)
        current = (engine_input or {}).get("current_message") or {}
        return {
            "decision": "UNRELATED",
            "topic_id": None,
            "proposed_title": "",
            "summary_update": "",
            "confidence": "LOW",
            "evidence_message_ids": [current.get("id")] if current.get("id") else [],
            "reason": "blocked-test",
        }


class _BoomEngine:
    def process_inbound(self, *_a, **_k):
        raise RuntimeError("topic worker boom")


class TopicSidepathTests(unittest.TestCase):
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
        self.sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=HeuristicTopicExtractor(),
            enabled=True,
            maxsize=8,
        )
        reset_sidepath(self.sidepath)

    def tearDown(self):
        try:
            self.sidepath.shutdown()
            self.sidepath.wait_idle(0.4)
        except Exception:
            pass
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
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

    def _listen(self, content, **msg_kwargs):
        msg = FakeMsg(content, **msg_kwargs)
        chat = FakeChat()
        message_listener(msg, chat)
        return msg

    def test_insert_is_after_evaluate_inbound_before_reply_check(self):
        source = inspect.getsource(message_listener)
        admit = source.split("STEP_ADMIT", 1)[1]
        before_reply = admit.split('verdict.get("action") != REPLY', 1)[0]
        self.assertIn("evaluate_inbound", before_reply)
        self.assertIn("try_enqueue_topic_sidepath", before_reply)
        after_reply = admit.split('verdict.get("action") != REPLY', 1)[1]
        self.assertNotIn("try_enqueue_topic_sidepath", after_reply.split("STEP_NORMALIZE")[0])
        self.assertTrue(sidepath_source_forbids_wechat_send())

    def test_s1_group_without_at_enqueues_and_no_reply(self):
        self._listen("ERP 同步今天还是有问题。", platform_message_id="s1")
        self.assertEqual(len(self.host.replies), 0)
        self.assertEqual(self.sidepath.enqueued_count, 1)
        self.assertTrue(self.sidepath.wait_idle(2), "Topic worker did not finish")
        store = TopicStore(self.root)
        topics = store.list_topics(CONV["id"])
        self.assertTrue(topics, "expected Topic after un-@ group message; last=%s audit=%s" % (
            getattr(self.sidepath.last_result, "as_dict", lambda: self.sidepath.last_result)(),
            self.sidepath.audit_events[-3:],
        ))

    def test_s2_group_at_enqueues_and_one_chat_reply(self):
        self._listen("@测试助手 ERP 同步还是有问题", platform_message_id="s2")
        self.assertEqual(len(self.host.replies), 1)
        self.assertEqual(self.sidepath.enqueued_count, 1)
        self.assertTrue(self.sidepath.wait_idle(2))
        self.assertEqual(len(self.host.replies), 1)

    def test_s3_self_no_enqueue_no_reply(self):
        self._listen(
            "机器人自己的话",
            platform_message_id="s3",
            sender_wxid=BOT_WXID,
            sender="测试助手",
        )
        self.assertEqual(len(self.host.replies), 0)
        self.assertEqual(self.sidepath.enqueued_count, 0)
        self.assertEqual(self.sidepath.last_skip_reason, SKIP_SELF)

    def test_s4_outbound_no_enqueue(self):
        self.runtime.register_outbound("room_g2@chatroom", "机器人刚回的内容")
        inbound = _inbound(platform_message_id="s4", content="机器人刚回的内容", sender_id=2)
        verdict = self._eval(inbound)
        result = try_enqueue_topic_sidepath(inbound, verdict, runtime=self.runtime)
        self.assertFalse(result["enqueued"])
        self.assertEqual(result["reason"], SKIP_OUTBOUND)
        self.assertEqual(self.sidepath.enqueued_count, 0)

    def test_s5_duplicate_no_enqueue(self):
        first = _inbound(platform_message_id="s5-dup", content="同一条消息")
        v1 = self._eval(first)
        r1 = try_enqueue_topic_sidepath(first, v1, runtime=self.runtime)
        self.assertTrue(r1["enqueued"])
        second = _inbound(platform_message_id="s5-dup", content="同一条消息")
        v2 = self._eval(second)
        r2 = try_enqueue_topic_sidepath(second, v2, runtime=self.runtime)
        self.assertEqual(v2["action"], NO_ACTION)
        self.assertFalse(r2["enqueued"])
        self.assertEqual(r2["reason"], SKIP_DUPLICATE)

    def test_n2_same_text_different_platform_id_enqueues_twice(self):
        first = _inbound(platform_message_id="n2-A", content="同一句话")
        second = _inbound(platform_message_id="n2-B", content="同一句话")
        r1 = try_enqueue_topic_sidepath(first, self._eval(first), runtime=self.runtime)
        r2 = try_enqueue_topic_sidepath(second, self._eval(second), runtime=self.runtime)
        self.assertTrue(r1["enqueued"])
        self.assertTrue(r2["enqueued"])
        self.assertEqual(self.sidepath.enqueued_count, 2)

    def test_s6_system_and_recall_no_enqueue(self):
        for raw_type, pid in (("system", "s6-sys"), ("recall", "s6-recall")):
            inbound = _inbound(platform_message_id=pid, raw_type=raw_type, content="系统消息")
            verdict = self._eval(inbound)
            result = try_enqueue_topic_sidepath(inbound, verdict, runtime=self.runtime)
            self.assertEqual(verdict["reason"], "bot_or_system")
            self.assertFalse(result["enqueued"])
            self.assertEqual(result["reason"], SKIP_SYSTEM)
        self.assertEqual(self.sidepath.enqueued_count, 0)

    def test_s7_stopped_no_enqueue_no_reply(self):
        self.runtime.set_state("STOPPED", "test-stop")
        self._listen("Stop 之后还在说话", platform_message_id="s7")
        self.assertEqual(len(self.host.replies), 0)
        self.assertEqual(self.sidepath.enqueued_count, 0)

    def test_s8_worker_exception_does_not_affect_chat(self):
        self.sidepath.engine = _BoomEngine()
        self._listen("@测试助手 请回复我", platform_message_id="s8")
        self.assertEqual(len(self.host.replies), 1)
        self.assertEqual(self.sidepath.enqueued_count, 1)
        self.assertTrue(self.sidepath.wait_idle(2))
        self.assertEqual(len(self.host.replies), 1)
        self.assertGreaterEqual(self.sidepath.failed_count, 1)

    def test_s9_queue_full_does_not_block_listener(self):
        gate = threading.Event()
        slow = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=_BlockingExtractor(gate),
            enabled=True,
            maxsize=2,
        )
        reset_sidepath(slow)
        self.sidepath = slow
        started = time.perf_counter()
        results = []
        try:
            for index in range(6):
                inbound = _inbound(
                    platform_message_id="s9-%s" % index,
                    content="ERP 同步问题 %s" % index,
                )
                verdict = self._eval(inbound)
                results.append(try_enqueue_topic_sidepath(inbound, verdict, runtime=self.runtime))
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.5)
            self.assertTrue(any(item.get("reason") == EVENT_QUEUE_FULL for item in results))
            self.assertGreaterEqual(slow.queue_full_count, 1)
            events = [item.get("event") for item in slow.audit_events]
            self.assertIn(EVENT_QUEUE_FULL, events)
        finally:
            gate.set()
            self.assertTrue(slow.wait_idle(3))

    def test_s10_disabled_means_no_enqueue(self):
        disabled = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=HeuristicTopicExtractor(),
            enabled=False,
        )
        reset_sidepath(disabled)
        self.sidepath = disabled
        self._listen("ERP 同步今天还是有问题。", platform_message_id="s10-off")
        self._listen("@测试助手 你好", platform_message_id="s10-at")
        self.assertEqual(disabled.enqueued_count, 0)
        self.assertEqual(disabled.last_skip_reason, SKIP_DISABLED)
        self.assertEqual(len(self.host.replies), 1)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "data", "topic_store", "conversations")))

    def test_unauthorized_verdict_is_not_rewritten(self):
        inbound = _inbound(platform_message_id="s-unauth", content="未艾特的群消息")
        verdict = self._eval(inbound)
        self.assertEqual(verdict["action"], NO_ACTION)
        self.assertEqual(verdict["reason"], "unauthorized")
        snapshot = dict(verdict)
        result = try_enqueue_topic_sidepath(inbound, verdict, runtime=self.runtime)
        self.assertTrue(result["enqueued"])
        self.assertEqual(verdict, snapshot)
        self.assertEqual(verdict["action"], NO_ACTION)


if __name__ == "__main__":
    unittest.main()
