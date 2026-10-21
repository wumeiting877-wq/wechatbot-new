# -*- coding: utf-8 -*-
"""P8-G3 查询忙时不丢失。分类器与规则仍在 session 之前完成，Store 在发送前重读。"""

from __future__ import annotations

import inspect
import json
import logging
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_reply_delivery import (
    PENDING_LIMIT,
    PENDING_TTL_SECONDS,
    notify_session_released,
    pending_count,
    pending_snapshot,
)
from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from collaboration_query import handle_collaboration_route
from decision_engine import DECISION_ENGINE_ENABLED
from message.bind import bind_host
from message.identity import inbound_from_wx_message
from message.listener import message_listener
from message.processor import check_inactive_users, process_user_messages
from message.trigger import REPLY
from query_formatter import CLASSIFIER_FAILURE_REPLY, COMMAND_REPLY
from query_intent_classifier import CALLS, reset_completer, use_completer
from query_router import LIST_RISKS, LIST_TASKS, OPEN_RISKS
from query_service import QueryService
from risk_engine import RISK_ENGINE_ENABLED
from task_engine import TASK_ENGINE_ENABLED
from topic_engine import TOPIC_ENGINE_ENABLED

CHAT = "项目群A"
OTHER = "项目群B"
BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p8g3"
CONV_A = {
    "id": "conv_a",
    "platform": "WECHAT",
    "platform_conversation_id": "room_a@chatroom",
    "conversation_type": "GROUP",
    "display_name": CHAT,
    "enabled": True,
}
CONV_B = {
    "id": "conv_b",
    "platform": "WECHAT",
    "platform_conversation_id": "room_b@chatroom",
    "conversation_type": "GROUP",
    "display_name": OTHER,
    "enabled": True,
}


class FakeMsg:
    def __init__(self, content, **kwargs):
        self.content = content
        self.type = kwargs.get("type", "text")
        self.sender = kwargs.get("sender", "李明")
        self.attr = kwargs.get("attr", "friend")
        self.sender_id = kwargs.get("sender_id", 88)
        self.sender_wxid = kwargs.get("sender_wxid", "wxid_liming")
        self.local_id = kwargs.get("local_id", 1001)
        self.create_time = kwargs.get("create_time", 1710000000)
        self.sort_seq = kwargs.get("sort_seq", 1)
        self.platform_message_id = kwargs.get("platform_message_id", "")
        self.quote_content = ""
        self.direction = "INBOUND"

    def to_text(self):
        return self.content

    def get_url(self):
        return ""

    def get_messages(self):
        return []


class FakeChat:
    def __init__(self, who=CHAT, wxid="room_a@chatroom"):
        self.who = who
        self._wxid = wxid


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p8g3")
        self.user_names = [CHAT, OTHER, "李明"]
        self.ACCEPT_ALL_GROUP_CHAT_MESSAGES = False
        self.ENABLE_GROUP_AT_REPLY = True
        self.ENABLE_GROUP_KEYWORD_REPLY = False
        self.GROUP_KEYWORD_LIST = []
        self.GROUP_CHAT_RESPONSE_PROBABILITY = 100
        self.GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY = True
        self.ENABLE_EMOJI_RECOGNITION = False
        self.ENABLE_ONLINE_API = False
        self.QUEUE_WAITING_TIME = 7
        self.can_send_messages = True
        self.is_sending_message = False
        self.queue_lock = threading.Lock()
        self.bot_last_sent_msg = {}
        self.user_last_msg = {}
        self.conversations = [dict(CONV_A), dict(CONV_B)]
        self.root_dir = root_dir
        self.sent = []
        self.handled = []
        self.memory_logs = []
        self.deepseek_calls = []
        self.chat_contexts = {}
        self.user_queues = {}

    def is_user_group_chat(self, _who):
        return True

    def send_reply(self, user_id, sender_name, username, original, reply, is_system_message=False, _direct=False):
        self.sent.append(reply)

    def handle_wxauto_message(self, msg, who):
        self.handled.append((who, getattr(msg, "content", "")))

    def handle_emoji_message(self, msg, who):
        self.handled.append((who, "emoji"))

    def log_user_message_to_memory(self, username, content):
        self.memory_logs.append((username, content))

    def get_deepseek_response(self, *args, **kwargs):
        self.deepseek_calls.append((args, kwargs))
        raise AssertionError("query path must not call chat")


def _forbid_classifier(_messages):
    raise AssertionError("classifier should not run")


def _task(cid, task_id, title):
    return {
        "id": task_id,
        "conversation_id": cid,
        "topic_id": "top_1",
        "title": title,
        "description": "",
        "status": "OPEN",
        "assignee_text": "李明",
        "due_text": "",
        "created_msg_id": "m1",
        "created_at": "2026-09-02T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
    }


def _risk(cid, risk_id, title):
    return {
        "id": risk_id,
        "conversation_id": cid,
        "topic_id": "top_1",
        "task_id": "",
        "title": title,
        "description": "",
        "condition_text": "测试环境频繁重启",
        "impact_text": "周五验收可能推迟",
        "status": "OPEN",
        "created_msg_id": "m1",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


def _dump(root, store_name, cid, filename, key, rows):
    path = os.path.join(root, "data", store_name, "conversations", cid, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({key: rows}, handle, ensure_ascii=False)
        handle.write("\n")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        CALLS.calls = 0
        reset_completer()
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.runtime.set_identity(bot_wxid=BOT_WXID, bot_name=BOT_NAME, login_account=BOT_NAME)
        self.host = FakeHost(self.runtime, self.root)
        bind_host(self.host)
        _dump(self.root, "topic_store", "conv_a", "topics.json", "topics", [{
            "id": "top_1",
            "conversation_id": "conv_a",
            "title": "接口联调",
            "summary": "",
            "status": "ACTIVE",
            "message_count": 1,
            "last_message_at": "2026-09-02T00:00:00Z",
            "created_at": "2026-09-01T00:00:00Z",
        }])
        _dump(self.root, "task_store", "conv_a", "tasks.json", "tasks", [
            _task("conv_a", "task_1", "完成接口联调"),
        ])
        _dump(self.root, "task_store", "conv_b", "tasks.json", "tasks", [
            _task("conv_b", "task_b", "B的任务"),
        ])
        _dump(self.root, "risk_store", "conv_a", "risks.json", "risks", [
            _risk("conv_a", "risk_open", "联调环境不稳定"),
        ])
        self.executes = []
        original = QueryService.execute

        def _wrapped(service, request):
            self.executes.append(request.query_type)
            return original(service, request)

        self._execute_patch = patch.object(QueryService, "execute", _wrapped)
        self._execute_patch.start()
        self._completer = use_completer(_forbid_classifier)
        self._completer.__enter__()

    def tearDown(self):
        try:
            self.runtime.send_queue.stop()
        except Exception:
            pass
        self._execute_patch.stop()
        self._completer.__exit__(None, None, None)
        reset_completer()
        bind_host(types.SimpleNamespace())
        from message import bind as bind_mod
        bind_mod._host = None
        self.tmpdir.cleanup()
        clear_stop_request()
        clear_emergency_stop()
        CALLS.calls = 0
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def _listen(self, content, pid, who=CHAT, wxid="room_a@chatroom"):
        message_listener(FakeMsg(content, platform_message_id=pid), FakeChat(who, wxid))

    def _hold(self, chat_id=CHAT):
        self.assertTrue(self.runtime.try_acquire_session(chat_id))

    def _release_without_flush(self, chat_id=CHAT):
        self.runtime.release_session(chat_id)

    def _flush(self, chat_id=CHAT):
        self._release_without_flush(chat_id)
        notify_session_released(self.runtime, chat_id)

    def test_delivery_01_busy_query_is_pending(self):
        self._hold()
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 现在有哪些任务", "d01")
        enqueued.assert_not_called()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.user_queues, {})
        self.assertEqual(self.host.deepseek_calls, [])
        self.assertEqual(self.executes, [])
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        snap = pending_snapshot(self.runtime, CHAT)[0]
        self.assertEqual(snap["kind"], "QUERY")
        self.assertEqual(snap["query_type"], LIST_TASKS)
        self.assertEqual(snap["conversation_id"], "conv_a")
        self.assertEqual(snap["message_id"], "d01")

    def test_delivery_02_release_flushes_query(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "d02")
        self.assertEqual(self.executes, [])
        self._release_without_flush()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self.host.conversations = [dict(CONV_B)]
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(self.executes, [LIST_TASKS])
        self.assertEqual(pending_count(self.runtime, CHAT), 0)
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertNotIn("B的任务", self.host.sent[0])

    def test_delivery_02_processor_finally_flushes(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "d02b")
        self._release_without_flush()
        self.host.user_queues[CHAT] = {
            "messages": ["你好"],
            "last_message_time": time.time(),
            "sender_name": "李明",
            "username": CHAT,
        }

        def _chat(*args, **kwargs):
            self.host.deepseek_calls.append((args, kwargs))
            return "聊天回复"

        self.host.get_deepseek_response = _chat
        process_user_messages(CHAT)
        self.assertEqual(len(self.host.deepseek_calls), 1)
        self.assertIn("你好", self.host.deepseek_calls[0][0][0])
        self.assertEqual(self.host.sent[0], "聊天回复")
        self.assertIn("完成接口联调", self.host.sent[1])
        self.assertEqual(self.executes, [LIST_TASKS])
        self.assertEqual(pending_count(self.runtime), 0)
        self.assertEqual(self.host.user_queues, {})

    def test_delivery_03_store_reread_at_send(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "d03")
        self.assertEqual(self.executes, [])
        _dump(self.root, "task_store", "conv_a", "tasks.json", "tasks", [
            _task("conv_a", "task_1", "完成接口联调"),
            _task("conv_a", "task_new", "补充回归用例"),
        ])
        self._flush()
        self.assertEqual(self.executes, [LIST_TASKS])
        self.assertIn("补充回归用例", self.host.sent[0])
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertNotIn("B的任务", self.host.sent[0])

    def test_delivery_04_classifier_not_repeated(self):
        def _stub(_messages):
            return json.dumps({"query_type": "LIST_TASKS", "answer": "任务A"}, ensure_ascii=False)

        self._hold()
        with use_completer(_stub):
            self._listen("@智群Agent 帮我盘一下现在手上的待办", "d04")
            self.assertEqual(CALLS.calls, 1)
            self.assertEqual(self.executes, [])
            self.assertEqual(pending_snapshot(self.runtime, CHAT)[0]["query_type"], LIST_TASKS)
            self._flush()
        self.assertEqual(CALLS.calls, 1)
        self.assertEqual(self.executes, [LIST_TASKS])
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertNotIn("任务A", self.host.sent[0])

    def test_delivery_05_fifo_two_queries(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "d05a")
        self._listen("@智群Agent 目前有哪些风险", "d05b")
        snap = pending_snapshot(self.runtime, CHAT)
        self.assertEqual([item["query_type"] for item in snap], [LIST_TASKS, OPEN_RISKS])
        self._flush()
        self.assertEqual(self.executes, [LIST_TASKS, OPEN_RISKS])
        self.assertIn("个任务", self.host.sent[0])
        self.assertIn("联调环境不稳定", self.host.sent[1])
        self.assertEqual(pending_count(self.runtime, CHAT), 0)

    def test_delivery_06_message_identity_dedupe(self):
        self._hold()
        inbound = inbound_from_wx_message(FakeMsg("现在有哪些任务", platform_message_id="d06"), FakeChat())
        verdict = {"action": REPLY}
        handle_collaboration_route(inbound, verdict, runtime=self.runtime, host=self.host, chat_id=CHAT)
        handle_collaboration_route(inbound, verdict, runtime=self.runtime, host=self.host, chat_id=CHAT)
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        other = inbound_from_wx_message(FakeMsg("现在有哪些任务", platform_message_id="d06b"), FakeChat())
        handle_collaboration_route(other, verdict, runtime=self.runtime, host=self.host, chat_id=CHAT)
        self.assertEqual(pending_count(self.runtime, CHAT), 2)
        ids = [item["message_id"] for item in pending_snapshot(self.runtime, CHAT)]
        self.assertEqual(ids, ["d06", "d06b"])

    def test_delivery_07_stop_clears_pending(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "d07a")
        self._listen("@智群Agent 目前有哪些风险", "d07b")
        self.assertEqual(pending_count(self.runtime), 2)
        self.runtime.begin_graceful_stop("delivery-07")
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(pending_count(self.runtime), 0)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.executes, [])

    def test_delivery_08_restart_does_not_restore(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "d08")
        self.runtime.begin_graceful_stop("delivery-08")
        self.assertEqual(pending_count(self.runtime), 0)
        fresh = BotRuntime()
        fresh.set_state("RUNNING", "fresh")
        self.assertEqual(pending_count(fresh), 0)
        self.runtime.set_state("STARTING", "restart")
        self.runtime.set_state("RUNNING", "restart")
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(pending_count(self.runtime), 0)
        self._listen("@智群Agent 目前有哪些风险", "d08b")
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("联调环境不稳定", self.host.sent[0])
        self.assertNotIn("完成接口联调", self.host.sent[0])

    def test_delivery_09_emergency_stop_does_not_send(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "d09")
        self.assertEqual(pending_count(self.runtime), 1)
        self.runtime.activate_emergency("delivery-09")
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(pending_count(self.runtime), 0)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.executes, [])

    def test_delivery_10_ttl_drops_without_notice(self):
        self._hold()
        with patch("agent_reply_delivery.time.time", return_value=1_000.0):
            self._listen("@智群Agent 现在有哪些任务", "d10")
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self._release_without_flush()
        with patch("agent_reply_delivery.time.time", return_value=1_000.0 + PENDING_TTL_SECONDS):
            with self.assertLogs("agent_reply_delivery", level="INFO") as captured:
                notify_session_released(self.runtime, CHAT)
        self.assertTrue(any("PENDING_QUERY_EXPIRED" in line for line in captured.output))
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.executes, [])
        self.assertEqual(pending_count(self.runtime, CHAT), 0)

    def test_delivery_11_normal_chat_unchanged(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 你好", "d11")
        enqueued.assert_called_once()
        self.assertEqual(len(self.host.handled), 1)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.user_queues, {})
        self.assertEqual(self.host.deepseek_calls, [])
        self.assertEqual(pending_count(self.runtime), 0)
        self.assertEqual(self.executes, [])

    def test_delivery_12_idle_sends_immediately(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 现在有哪些任务", "d12")
        enqueued.assert_not_called()
        self.assertEqual(pending_count(self.runtime), 0)
        self.assertEqual(self.executes, [LIST_TASKS])
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertEqual(self.host.handled, [])
        self.assertFalse(self.runtime.session_busy(CHAT))

    def test_delivery_13_command_fixed_reply_waits(self):
        self._hold()
        self._listen("@智群Agent 帮我创建一个任务", "d13")
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self.assertEqual(pending_snapshot(self.runtime, CHAT)[0]["kind"], "FIXED")
        self.assertEqual(self.executes, [])
        self._flush()
        self.assertEqual(self.host.sent, [COMMAND_REPLY])
        self.assertEqual(self.executes, [])
        self.assertEqual(pending_count(self.runtime), 0)

    def test_delivery_14_classifier_failure_waits(self):
        def _bad(_messages):
            return "不是 JSON"

        self._hold()
        with use_completer(_bad):
            self._listen("@智群Agent 帮我盘一下现在手上的待办", "d14")
            self.assertEqual(CALLS.calls, 1)
            self.assertEqual(self.host.sent, [])
            self.assertEqual(pending_snapshot(self.runtime, CHAT)[0]["kind"], "FIXED")
            self._flush()
        self.assertEqual(CALLS.calls, 1)
        self.assertEqual(self.host.sent, [CLASSIFIER_FAILURE_REPLY])
        self.assertEqual(self.executes, [])
        self.assertEqual(self.host.handled, [])

    def test_flush_does_not_cross_chats(self):
        self._hold(CHAT)
        self._listen("@智群Agent 现在有哪些任务", "cross")
        notify_session_released(self.runtime, OTHER)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self._flush(CHAT)
        self.assertEqual(len(self.host.sent), 1)

    def test_cooldown_keeps_pending_until_allow(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "cool")
        self._release_without_flush()
        self.runtime.note_replied(CHAT)
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self.assertEqual(self.executes, [])
        self.runtime._reply_times[CHAT].clear()
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(len(self.host.sent), 1)
        self.assertEqual(pending_count(self.runtime, CHAT), 0)

    def test_overflow_drops_newest(self):
        self._hold()
        phrases = [
            ("@智群Agent 现在有哪些任务", "q1"),
            ("@智群Agent 目前有哪些风险", "q2"),
            ("@智群Agent 有哪些决定", "q3"),
            ("@智群Agent 现在有哪些主题", "q4"),
        ]
        for content, pid in phrases:
            self._listen(content, pid)
        ids = [item["message_id"] for item in pending_snapshot(self.runtime, CHAT)]
        self.assertEqual(ids, ["q1", "q2", "q3"])
        self.assertEqual(pending_count(self.runtime, CHAT), PENDING_LIMIT)
        self.assertNotIn("q4", ids)

    def test_idle_flush_skips_busy_chat(self):
        from agent_reply_delivery import flush_idle_pending

        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "idle")
        flush_idle_pending(self.runtime)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self._release_without_flush()
        flush_idle_pending(self.runtime)
        self.assertEqual(len(self.host.sent), 1)
        self.assertEqual(pending_count(self.runtime, CHAT), 0)

    def test_single_flight_flush(self):
        self._hold()
        self._listen("@智群Agent 现在有哪些任务", "flight")
        self._release_without_flush()
        barrier = threading.Barrier(2)

        def _go():
            barrier.wait(2)
            notify_session_released(self.runtime, CHAT)

        threads = [threading.Thread(target=_go), threading.Thread(target=_go)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertEqual(len(self.host.sent), 1)
        self.assertEqual(pending_count(self.runtime, CHAT), 0)
        self.assertEqual(self.executes, [LIST_TASKS])

    def test_release_session_has_no_delivery_hook(self):
        source = inspect.getsource(BotRuntime.release_session)
        self.assertNotIn("pending", source)
        self.assertNotIn("flush", source)
        self.assertNotIn("agent_reply", source)

    def test_source_constraints_and_checker_hooks(self):
        import agent_reply_delivery
        import collaboration_query

        for module in (agent_reply_delivery, collaboration_query):
            text = inspect.getsource(module)
            for banned in (
                "Engine(",
                "Extractor",
                "write_processing",
                "commit_apply",
                "retry_topic",
                "retry_downstream",
                "SendMsg",
                "get_deepseek",
                "operations_action_audit",
            ):
                self.assertNotIn(banned, text, module.__name__ + " " + banned)
        self.assertIn("send_reply", inspect.getsource(collaboration_query))
        checker = inspect.getsource(check_inactive_users)
        processor = inspect.getsource(process_user_messages)
        self.assertIn("_clear_pending_agent_replies", checker)
        self.assertIn("_flush_idle_agent_replies", checker)
        self.assertLess(processor.find("release_session"), processor.find("_notify_session_released"))
        self.assertNotIn(LIST_RISKS, processor)
        self.assertFalse(self.runtime.session_busy(CHAT))


if __name__ == "__main__":
    unittest.main()
