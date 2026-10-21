# -*- coding: utf-8 -*-
"""P8-G4 TYPE C：姓名相同、同名、自由文本负责人都不能当成身份查询。"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED
from message.bind import bind_host
from message.listener import message_listener
from query_formatter import ASSIGNEE_TASK_QUERY_REPLY, SELF_TASK_QUERY_REPLY
from query_intent_classifier import CALLS, reset_completer, use_completer
from risk_engine import RISK_ENGINE_ENABLED
from task_engine import TASK_ENGINE_ENABLED
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import TopicSidepath, is_topic_engine_enabled, reset_sidepath

CONV_A = {
    "id": "conv_a",
    "platform": "WECHAT",
    "platform_conversation_id": "room_a@chatroom",
    "conversation_type": "GROUP",
    "display_name": "项目群A",
    "enabled": True,
}
BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p8g4"
STORE_FILES = ("topics.json", "tasks.json", "decisions.json", "risks.json", "processed.json", "links.json")


class FakeMsg:
    def __init__(self, content, **kwargs):
        self.content = content
        self.type = "text"
        self.sender = kwargs.get("sender", "李明")
        self.attr = "friend"
        self.sender_id = kwargs.get("sender_id", 88)
        self.sender_wxid = kwargs.get("sender_wxid", "wxid_liming")
        self.local_id = kwargs.get("local_id", 1001)
        self.create_time = 1710000000
        self.sort_seq = 1
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
    def __init__(self, who="项目群A", wxid="room_a@chatroom"):
        self.who = who
        self._wxid = wxid


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p8g4")
        self.user_names = ["项目群A"]
        self.ACCEPT_ALL_GROUP_CHAT_MESSAGES = False
        self.ENABLE_GROUP_AT_REPLY = True
        self.ENABLE_GROUP_KEYWORD_REPLY = False
        self.GROUP_KEYWORD_LIST = []
        self.GROUP_CHAT_RESPONSE_PROBABILITY = 100
        self.GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY = True
        self.ENABLE_EMOJI_RECOGNITION = False
        self.bot_last_sent_msg = {}
        self.user_last_msg = {}
        self.conversations = [dict(CONV_A)]
        self.root_dir = root_dir
        self.can_send_messages = True
        self.sent = []
        self.handled = []

    def is_user_group_chat(self, _who):
        return True

    def send_reply(self, user_id, sender_name, username, original, reply, is_system_message=False, _direct=False):
        self.sent.append(reply)

    def handle_wxauto_message(self, msg, who):
        self.handled.append((who, getattr(msg, "content", "")))

    def handle_emoji_message(self, msg, who):
        self.handled.append((who, "emoji"))

    def log_user_message_to_memory(self, username, content):
        return None

    def get_deepseek_response(self, *args, **kwargs):
        raise AssertionError("identity query must not call chat")


def _dump(root, store_name, cid, filename, key, rows):
    path = os.path.join(root, "data", store_name, "conversations", cid, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({key: rows}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_bytes(root, relative, payload):
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)


def _snapshot(root):
    found = {}
    data = os.path.join(root, "data")
    for dirpath, _dirnames, filenames in os.walk(data):
        for name in filenames:
            if name in STORE_FILES:
                path = os.path.join(dirpath, name)
                with open(path, "rb") as handle:
                    found[path] = handle.read()
    return found


def _task(task_id, title, assignee_text):
    return {
        "id": task_id,
        "conversation_id": "conv_a",
        "topic_id": "top_1",
        "title": title,
        "description": "",
        "status": "OPEN",
        "assignee_text": assignee_text,
        "due_text": "",
        "created_msg_id": "m1",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


class IdentityBlockedTests(unittest.TestCase):
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
            "last_message_at": "2026-09-01T00:00:00Z",
            "created_at": "2026-09-01T00:00:00Z",
            "confidence": "HIGH",
            "schema_version": 1,
        }])
        _dump(self.root, "task_store", "conv_a", "tasks.json", "tasks", [
            _task("task_same", "完成接口联调", "李明"),
            _task("task_zhang_a", "甲的材料", "张三"),
            _task("task_zhang_b", "乙的验收", "张三"),
            _task("task_free_1", "自由文本一", "李明负责"),
            _task("task_free_2", "自由文本二", "由李明"),
            _task("task_free_3", "自由文本三", "研发部李明"),
            _task("task_free_4", "自由文本四", "@李明"),
            _task("task_free_5", "自由文本五", ""),
        ])
        _write_bytes(self.root, os.path.join("data", "task_store", "conversations", "conv_a", "processed.json"), b'{"items":[]}\n')
        _write_bytes(self.root, os.path.join("data", "task_store", "conversations", "conv_a", "links.json"), b'{"links":[]}\n')
        self.before = _snapshot(self.root)
        self._completer = use_completer(lambda _messages: (_ for _ in ()).throw(AssertionError("classifier")))
        self._completer.__enter__()

    def tearDown(self):
        self._completer.__exit__(None, None, None)
        reset_completer()
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
        bind_host(types.SimpleNamespace())
        from message import bind as bind_mod
        bind_mod._host = None
        self.tmpdir.cleanup()
        clear_stop_request()
        clear_emergency_stop()
        CALLS.calls = 0
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(is_topic_engine_enabled())
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def _listen(self, content, pid, **msg_kwargs):
        message_listener(FakeMsg(content, platform_message_id=pid, **msg_kwargs), FakeChat())

    def _assert_fixed(self, reply):
        self.assertEqual(self.host.handled, [])
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(_snapshot(self.root), self.before)
        for title in (
            "完成接口联调",
            "甲的材料",
            "乙的验收",
            "自由文本一",
            "自由文本二",
            "自由文本三",
            "自由文本四",
            "自由文本五",
        ):
            self.assertNotIn(title, reply)

    def test_identity_01_same_name_is_not_my_tasks(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            with patch("collaboration_query.build_query_service", side_effect=AssertionError("store")):
                self._listen(
                    "@智群Agent 我有什么任务",
                    "id01",
                    sender="李明",
                    sender_wxid="wxid_liming",
                    sender_id=88,
                )
        enqueued.assert_not_called()
        self.assertEqual(self.host.sent, [SELF_TASK_QUERY_REPLY])
        self._assert_fixed(self.host.sent[0])

    def test_identity_02_same_display_name_is_not_guessed(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            with patch("collaboration_query.build_query_service", side_effect=AssertionError("store")):
                self._listen(
                    "@智群Agent 我有什么任务",
                    "id02a",
                    sender="张三",
                    sender_wxid="wxid_zhang_a",
                    sender_id=11,
                )
                self._listen(
                    "@智群Agent 我有什么任务",
                    "id02b",
                    sender="张三",
                    sender_wxid="wxid_zhang_b",
                    sender_id=22,
                )
                self._listen("@智群Agent 张三负责什么", "id02c", sender="李明", sender_wxid="wxid_liming")
                self._listen("@智群Agent 张三有哪些任务", "id02d", sender="李明", sender_wxid="wxid_liming")
        enqueued.assert_not_called()
        self.assertEqual(self.host.sent[0], SELF_TASK_QUERY_REPLY)
        self.assertEqual(self.host.sent[1], SELF_TASK_QUERY_REPLY)
        self.assertEqual(self.host.sent[2], ASSIGNEE_TASK_QUERY_REPLY)
        self.assertEqual(self.host.sent[3], ASSIGNEE_TASK_QUERY_REPLY)
        self._assert_fixed("\n".join(self.host.sent))

    def test_identity_03_free_text_assignee_is_not_fuzzy_matched(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            with patch("collaboration_query.build_query_service", side_effect=AssertionError("store")):
                self._listen("@智群Agent 李明有哪些任务", "id03a")
                self._listen("@智群Agent 李明负责什么", "id03b")
        enqueued.assert_not_called()
        self.assertEqual(self.host.sent, [ASSIGNEE_TASK_QUERY_REPLY, ASSIGNEE_TASK_QUERY_REPLY])
        self._assert_fixed("\n".join(self.host.sent))


if __name__ == "__main__":
    unittest.main()
