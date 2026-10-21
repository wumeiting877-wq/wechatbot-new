# -*- coding: utf-8 -*-
"""P4-G2 Gate 1：Task Side-path 自动测试 TS1 ～ TS10。"""

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
from message.trigger import NO_ACTION
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import (
    EVENT_QUEUE_FULL,
    SKIP_DISABLED,
    SKIP_TOPIC_NOT_ELIGIBLE,
    TaskSidepath,
    reset_task_sidepath,
    sidepath_source_forbids_wechat_send,
    topic_result_allows_task,
    try_enqueue_task_after_topic,
)
from task_store import TaskStore
from topic_engine import EngineResult
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import TopicSidepath, reset_sidepath, try_enqueue_topic_sidepath
from topic_store import TopicStore


CONV = {
    "id": "conv_g2task01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_g2task@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
    "agent_config_id": "agt_g2task",
}

BOT_WXID = "wxid_bot_g2task"
BOT_NAME = "测试助手"


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
    def __init__(self, who="测试群", wxid="room_g2task@chatroom"):
        self.who = who
        self._wxid = wxid


class FakeHost:
    def __init__(self, runtime, root_dir, is_group=True):
        self.runtime = runtime
        self.logger = logging.getLogger("test_task_sidepath")
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
        "platform_message_id": kwargs.pop("platform_message_id", "pid-task-1"),
        "conversation_id": kwargs.pop("conversation_id", "room_g2task@chatroom"),
        "chat_name": kwargs.pop("chat_name", "测试群"),
        "chat_wxid": kwargs.pop("chat_wxid", "room_g2task@chatroom"),
        "sender_id": kwargs.pop("sender_id", 88),
        "sender_wxid": kwargs.pop("sender_wxid", "wxid_zhoumin"),
        "sender_name": kwargs.pop("sender_name", "周敏"),
        "content": kwargs.pop("content", "王强今天 16 点前把空值处理规则做完，再跑一次回归。"),
        "raw_type": kwargs.pop("raw_type", "text"),
        "direction": kwargs.pop("direction", "INBOUND"),
        "create_time": kwargs.pop("create_time", 1710000000),
        "attr": kwargs.pop("attr", "friend"),
    }
    data.update(kwargs)
    return InboundMessage(**data)


class _BlockingTaskExtractor:
    def __init__(self, gate: threading.Event):
        self.gate = gate
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        self.gate.wait(timeout=8)
        current = (engine_input or {}).get("current_message") or {}
        return {
            "decisions": [
                {
                    "decision": "UNRELATED",
                    "task_id": None,
                    "title": "",
                    "assignee_text": "",
                    "due_text": "",
                    "confidence": "LOW",
                    "evidence_message_ids": [current.get("id")] if current.get("id") else [],
                    "reason": "blocked-test",
                }
            ]
        }


class _BoomTaskEngine:
    def process_record(self, *_a, **_k):
        raise RuntimeError("task worker boom")


class _BoomTopicExtractor:
    def extract(self, *_a, **_k):
        raise TimeoutError("topic boom")


class _ScriptedTopicEngine:
    def __init__(self, decision, topic_id=None, error_code=""):
        self.decision = decision
        self.topic_id = topic_id
        self.error_code = error_code

    def process_inbound(self, inbound, conversations=None):
        conversation = (conversations or [{}])[0]
        return EngineResult(
            decision=self.decision,
            topic_id=self.topic_id,
            message_id="msg_scripted",
            conversation_id=str((conversation or {}).get("id") or ""),
            error_code=self.error_code,
            skipped=self.decision in ("SKIPPED", "DISABLED"),
        )


class TaskSidepathTests(unittest.TestCase):
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
        self.sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=HeuristicTopicExtractor(),
            enabled=True,
            maxsize=8,
            prompt_root=ROOT,
            task_sidepath=self.task_path,
        )
        reset_sidepath(self.sidepath)
        reset_task_sidepath(self.task_path)

    def tearDown(self):
        try:
            self.sidepath.shutdown()
            self.task_path.shutdown()
            self.sidepath.wait_idle(0.4)
            self.task_path.wait_idle(0.4)
        except Exception:
            pass
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
        reset_task_sidepath(TaskSidepath(enabled=False, root_dir=self.root, maxsize=1))
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

    def test_listener_has_no_second_task_sidepath(self):
        source = inspect.getsource(message_listener)
        self.assertIn("try_enqueue_topic_sidepath", source)
        self.assertNotIn("try_enqueue_task", source)
        self.assertNotIn("task_sidepath", source)
        self.assertTrue(sidepath_source_forbids_wechat_send())
        import task_engine
        import task_extractor_client
        import task_sidepath
        import task_store
        for module in (task_engine, task_extractor_client, task_store, task_sidepath):
            text = inspect.getsource(module)
            self.assertNotIn("send_reply" + "(", text)
            self.assertNotIn("wx.SendMsg" + "(", text)
            self.assertNotIn("SendMsg" + "(", text)

    def test_ts1_new_topic_enqueues_task(self):
        result, _, _ = self._enqueue("ERP 同步今天还是有问题。", "ts1")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.task_path.enqueued_count, 1)
        self.assertIn(self.sidepath.last_result.decision, ("NEW_TOPIC",))
        self.assertTrue(self.sidepath.last_result.topic_id)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertTrue(topics)

    def test_ts2_existing_topic_enqueues_task(self):
        self._enqueue("ERP 同步今天还是有问题。", "ts2-seed")
        self._wait()
        before = self.task_path.enqueued_count
        result, _, _ = self._enqueue("ERP 同步供应商编码还是空。", "ts2")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "EXISTING_TOPIC")
        self.assertEqual(self.task_path.enqueued_count, before + 1)

    def test_ts3_topic_update_enqueues_task(self):
        self._enqueue("ERP 同步今天还是有问题。", "ts3-seed")
        self._wait()
        before = self.task_path.enqueued_count
        result, _, _ = self._enqueue("ERP 同步规则需要修复。", "ts3")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "TOPIC_UPDATE")
        self.assertEqual(self.task_path.enqueued_count, before + 1)

    def test_ts4_unrelated_does_not_enqueue_task(self):
        result, _, _ = self._enqueue("中午吃什么", "ts4")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertIn(self.sidepath.last_result.decision, ("UNRELATED", "SKIPPED"))
        self.assertEqual(self.task_path.enqueued_count, 0)
        self.assertEqual(self.task_path.last_skip_reason, SKIP_TOPIC_NOT_ELIGIBLE)

    def test_ts5_failed_does_not_enqueue_task(self):
        self.sidepath.extractor = _BoomTopicExtractor()
        result, _, _ = self._enqueue("ERP 同步今天还是有问题。", "ts5")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "FAILED")
        self.assertEqual(self.task_path.enqueued_count, 0)

    def test_ts6_skipped_does_not_enqueue_task(self):
        result, _, _ = self._enqueue("", "ts6")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertEqual(self.sidepath.last_result.decision, "SKIPPED")
        self.assertEqual(self.task_path.enqueued_count, 0)
        self.assertFalse(topic_result_allows_task(self.sidepath.last_result))

    def test_ts7_task_disabled_topic_still_works(self):
        disabled = TaskSidepath(
            root_dir=self.root,
            extractor=HeuristicTaskExtractor(),
            enabled=False,
            prompt_root=ROOT,
        )
        topic = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=HeuristicTopicExtractor(),
            enabled=True,
            prompt_root=ROOT,
            task_sidepath=disabled,
        )
        reset_sidepath(topic)
        reset_task_sidepath(disabled)
        self.sidepath = topic
        self.task_path = disabled
        result, _, verdict = self._enqueue("ERP 同步今天还是有问题。", "ts7")
        self.assertTrue(result["enqueued"])
        self.assertEqual(verdict["action"], NO_ACTION)
        self._wait()
        self.assertTrue(topic.last_result.topic_id)
        self.assertEqual(disabled.enqueued_count, 0)
        self.assertEqual(disabled.last_skip_reason, SKIP_DISABLED)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertTrue(topics)
        self.assertEqual(TaskStore(self.root, topic_store=TopicStore(self.root)).list_tasks(CONV["id"]), [])

    def test_ts8_task_worker_exception_preserves_topic(self):
        self.task_path.engine = _BoomTaskEngine()
        result, _, _ = self._enqueue("ERP 同步今天还是有问题。", "ts8")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertTrue(self.sidepath.last_result.topic_id)
        topics = TopicStore(self.root).list_topics(CONV["id"])
        self.assertEqual(len(topics), 1)
        links = TopicStore(self.root).list_links(CONV["id"])
        self.assertTrue(links)
        self.assertGreaterEqual(self.task_path.failed_count, 1)
        rec = self.task_path.store.get_processing(CONV["id"], self.sidepath.last_result.message_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["decision_summary"], "FAILED")
        self.assertEqual(self.task_path.store.list_tasks(CONV["id"]), [])

    def test_ts9_task_queue_full_does_not_block_topic_worker(self):
        gate = threading.Event()
        slow_task = TaskSidepath(
            root_dir=self.root,
            extractor=_BlockingTaskExtractor(gate),
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
            task_sidepath=slow_task,
        )
        reset_sidepath(topic)
        reset_task_sidepath(slow_task)
        self.sidepath = topic
        self.task_path = slow_task
        started = time.perf_counter()
        try:
            for index in range(6):
                self._enqueue("ERP 同步今天还是有问题 %s。" % index, "ts9-%s" % index)
            self.assertTrue(topic.wait_idle(3), "Topic worker blocked by Task queue")
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 1.5)
            self.assertGreaterEqual(slow_task.queue_full_count, 1)
            events = [item.get("event") for item in slow_task.audit_events]
            self.assertIn(EVENT_QUEUE_FULL, events)
        finally:
            gate.set()
            slow_task.wait_idle(4)

    def test_ts10_stop_bot_stops_topic_and_task(self):
        result, _, _ = self._enqueue("ERP 同步今天还是有问题。", "ts10-seed")
        self.assertTrue(result["enqueued"])
        self._wait()
        self.assertGreaterEqual(self.task_path.enqueued_count, 1)
        topics_before = len(TopicStore(self.root).list_topics(CONV["id"]))
        tasks_before = len(self.task_path.store.list_tasks(CONV["id"]))
        self.runtime.begin_graceful_stop("test-stop")
        after, _, _ = self._enqueue("王强今天把空值处理规则做完。", "ts10-after")
        self.assertFalse(after["enqueued"])
        self._listen_stopped("Stop 之后还在说话", "ts10-listen")
        self.assertEqual(len(self.host.replies), 0)
        self.assertEqual(len(TopicStore(self.root).list_topics(CONV["id"])), topics_before)
        self.assertEqual(len(self.task_path.store.list_tasks(CONV["id"])), tasks_before)

    def _listen_stopped(self, content, pid):
        msg = FakeMsg(content, platform_message_id=pid)
        message_listener(msg, FakeChat())


class TaskSidepathIsolationTests(unittest.TestCase):
    def test_try_enqueue_never_raises(self):
        result = try_enqueue_task_after_topic(None)
        self.assertFalse(result["enqueued"])

    def test_forbidden_decisions_rejected(self):
        for decision in ("UNRELATED", "SKIPPED", "FAILED", "DISABLED", "CONVERSATION_NOT_RESOLVED"):
            self.assertFalse(
                topic_result_allows_task(EngineResult(decision=decision, topic_id="topic_x", conversation_id="conv_x"))
            )
        self.assertFalse(topic_result_allows_task(EngineResult(decision="NEW_TOPIC", topic_id=None)))
        self.assertFalse(
            topic_result_allows_task(
                EngineResult(decision="NEW_TOPIC", topic_id="topic_x", error_code="EXTRACTOR_TIMEOUT")
            )
        )
        self.assertTrue(
            topic_result_allows_task(EngineResult(decision="NEW_TOPIC", topic_id="topic_x", conversation_id="conv_x"))
        )


if __name__ == "__main__":
    unittest.main()
