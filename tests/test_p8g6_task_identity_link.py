# -*- coding: utf-8 -*-
"""P8-G6：TaskIdentityLink 与个人任务查询。只返回已经确定链接的任务。"""

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

from agent_reply_delivery import notify_session_released, pending_count, pending_snapshot
from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED
from identity_store import STATUS_DISABLED, IdentityStore
from message.bind import bind_host
from message.listener import message_listener
from query_formatter import (
    ASSIGNEE_TASK_QUERY_REPLY,
    IDENTITY_AMBIGUOUS_REPLY,
    IDENTITY_DISABLED_REPLY,
    MY_TASKS_EMPTY_REPLY,
    SELF_TASK_QUERY_REPLY,
)
from query_intent_classifier import CALLS, reset_completer, use_completer
from risk_engine import RISK_ENGINE_ENABLED
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED, TaskEngine
from task_identity_link import (
    SOURCE_EXACT_EXPLICIT_ALIAS,
    SOURCE_MANUAL,
    SOURCE_TRUSTED_DIRECTORY,
    TaskIdentityLinkError,
    TaskIdentityLinkStore,
    attach_exact_links_for_created_tasks,
)
from task_store import FORBIDDEN_TASK_KEYS, TaskStore
from tests.test_task_engine_offline import ScriptedExtractor
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import TopicSidepath, is_topic_engine_enabled, reset_sidepath
from topic_store import RELATION_CREATED_BY, TopicStore

BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p8g6"
CHAT = "项目群A"
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
    "display_name": "项目群B",
    "enabled": True,
}


def _task(cid, task_id, title, assignee_text):
    return {
        "id": task_id,
        "conversation_id": cid,
        "topic_id": "topic_1",
        "title": title,
        "description": "",
        "status": "OPEN",
        "assignee_text": assignee_text,
        "due_text": "",
        "created_msg_id": "m1",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


def _dump_tasks(root, cid, rows):
    path = os.path.join(root, "data", "task_store", "conversations", cid, "tasks.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"tasks": rows}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _read(path):
    with open(path, "rb") as handle:
        return handle.read()


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
    def __init__(self, who=CHAT, wxid="room_a@chatroom"):
        self.who = who
        self._wxid = wxid


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p8g6")
        self.user_names = [CHAT, "项目群B"]
        self.ACCEPT_ALL_GROUP_CHAT_MESSAGES = False
        self.ENABLE_GROUP_AT_REPLY = True
        self.ENABLE_GROUP_KEYWORD_REPLY = False
        self.GROUP_KEYWORD_LIST = []
        self.GROUP_CHAT_RESPONSE_PROBABILITY = 100
        self.GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY = True
        self.ENABLE_EMOJI_RECOGNITION = False
        self.bot_last_sent_msg = {}
        self.user_last_msg = {}
        self.conversations = [dict(CONV_A), dict(CONV_B)]
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
        raise AssertionError("personal query must not call chat")


class LinkStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.people = IdentityStore(self.root)
        self.tasks = TaskStore(self.root)
        self.links = TaskIdentityLinkStore(self.root, task_store=self.tasks, identity_store=self.people)
        self.people.create_person("person_001", "李明")
        self.people.create_person("person_002", "张三")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        _dump_tasks(self.root, "conv_b", [_task("conv_b", "task_b", "另一会话任务", "李明")])

    def tearDown(self):
        self.tmpdir.cleanup()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def test_link_01_manual_link(self):
        record = self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self.assertEqual(record["person_id"], "person_001")
        self.assertEqual(record["source"], SOURCE_MANUAL)
        self.assertEqual(record["conversation_id"], "conv_a")
        self.assertEqual(len(self.links.list_links()), 1)
        stored = self.tasks.get_task("conv_a", "task_a")
        self.assertNotIn("person_id", stored)
        self.assertNotIn("assignee_id", stored)

    def test_link_02_same_link_is_idempotent(self):
        first = self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        second = self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_TRUSTED_DIRECTORY)
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertEqual(second["source"], SOURCE_MANUAL)
        self.assertEqual(len(self.links.list_links()), 1)

    def test_link_03_second_person_conflicts(self):
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        before = _read(self.links.links_path())
        with self.assertRaises(TaskIdentityLinkError) as caught:
            self.links.link_task_to_person("conv_a", "task_a", "person_002", source=SOURCE_MANUAL)
        self.assertEqual(caught.exception.code, "CONFLICT")
        self.assertEqual(_read(self.links.links_path()), before)
        self.assertEqual(self.links.find_link("conv_a", "task_a")["person_id"], "person_001")

    def test_link_04_missing_person(self):
        with self.assertRaises(TaskIdentityLinkError) as caught:
            self.links.link_task_to_person("conv_a", "task_a", "person_404", source=SOURCE_MANUAL)
        self.assertEqual(caught.exception.code, "PERSON_NOT_FOUND")
        self.assertFalse(os.path.isfile(self.links.links_path()))

    def test_link_05_missing_task(self):
        with self.assertRaises(TaskIdentityLinkError) as caught:
            self.links.link_task_to_person("conv_a", "task_missing", "person_001", source=SOURCE_MANUAL)
        self.assertEqual(caught.exception.code, "TASK_NOT_FOUND")
        self.assertFalse(os.path.isfile(self.links.links_path()))

    def test_link_06_conversation_mismatch(self):
        with self.assertRaises(TaskIdentityLinkError) as caught:
            self.links.link_task_to_person("conv_b", "task_a", "person_001", source=SOURCE_MANUAL)
        self.assertEqual(caught.exception.code, "CONVERSATION_MISMATCH")
        self.assertFalse(os.path.isfile(self.links.links_path()))

    def test_link_07_disabled_person_cannot_link(self):
        self.people.set_person_status("person_001", STATUS_DISABLED)
        with self.assertRaises(TaskIdentityLinkError) as caught:
            self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self.assertEqual(caught.exception.code, "PERSON_DISABLED")
        self.assertFalse(os.path.isfile(self.links.links_path()))
        self.assertEqual(self.people.get_person("person_001")["status"], STATUS_DISABLED)

    def test_link_08_corrupt_file_keeps_bytes(self):
        path = self.links.links_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = b"{not-json\n"
        with open(path, "wb") as handle:
            handle.write(payload)
        with self.assertRaises(TaskIdentityLinkError) as listed:
            self.links.list_links()
        self.assertEqual(listed.exception.code, "CORRUPT")
        with self.assertRaises(TaskIdentityLinkError) as linked:
            self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self.assertEqual(linked.exception.code, "CORRUPT")
        self.assertEqual(_read(path), payload)

    def test_link_09_exact_alias_links(self):
        self.people.add_alias("李明", "person_001")
        record = self.links.link_task_to_person(
            "conv_a",
            "task_a",
            "person_001",
            source=SOURCE_EXACT_EXPLICIT_ALIAS,
        )
        self.assertEqual(record["source"], SOURCE_EXACT_EXPLICIT_ALIAS)
        self.assertEqual(record["person_id"], "person_001")

    def test_link_10_loose_assignee_text_does_not_link(self):
        self.people.add_alias("李明", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "补材料", "李明负责")])
        before = os.path.isfile(self.links.links_path())
        with self.assertRaises(TaskIdentityLinkError) as caught:
            self.links.link_task_to_person(
                "conv_a",
                "task_a",
                "person_001",
                source=SOURCE_EXACT_EXPLICIT_ALIAS,
            )
        self.assertEqual(caught.exception.code, "NOT_FOUND")
        self.assertEqual(os.path.isfile(self.links.links_path()), before)

    def test_preview_does_not_apply(self):
        self.people.add_alias("李明", "person_001")
        _dump_tasks(
            self.root,
            "conv_a",
            [
                _task("conv_a", "task_exact", "可绑定", "李明"),
                _task("conv_a", "task_loose", "不可绑定", "李明负责"),
                _task("conv_a", "task_linked", "已绑定", "李明"),
            ],
        )
        self.links.link_task_to_person("conv_a", "task_linked", "person_001", source=SOURCE_MANUAL)
        before = _read(self.links.links_path())
        with patch.object(TaskIdentityLinkStore, "link_task_to_person", side_effect=AssertionError("apply")):
            preview = TaskIdentityLinkStore(self.root, task_store=self.tasks, identity_store=self.people)
            report = preview.preview_task_identity_links("conv_a")
        self.assertEqual(_read(self.links.links_path()), before)
        counts = report["counts"]
        self.assertEqual(counts["EXACT_RESOLVABLE"], 1)
        self.assertEqual(counts["UNRESOLVED"], 1)
        self.assertEqual(counts["ALREADY_LINKED"], 1)
        self.assertEqual(counts["AMBIGUOUS"], 0)

    def test_no_rebind_or_historical_apply_api(self):
        with open(os.path.join(ROOT, "task_identity_link.py"), "r", encoding="utf-8") as handle:
            source = handle.read()
        for token in ("unlink_task", "reassign_task_person", "difflib", "pinyin", "sender_name", "LLM", "Extractor"):
            self.assertNotIn(token, source)
        self.assertNotIn("fuzzy", source.lower())
        self.assertIn("assignee_id", FORBIDDEN_TASK_KEYS)
        self.assertIn("assignee_wxid", FORBIDDEN_TASK_KEYS)
        self.assertNotIn("person_id", FORBIDDEN_TASK_KEYS)


class BestEffortTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.topic_store = TopicStore(self.root)
        self.task_store = TaskStore(self.root, topic_store=self.topic_store)
        self.people = IdentityStore(self.root)
        self.cid = "conv_link01"
        self.topic_id = "topic_link01"
        path = os.path.join(self.topic_store.conversation_dir(self.cid), "topics.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(
            path,
            {
                "topics": [
                    {
                        "id": self.topic_id,
                        "conversation_id": self.cid,
                        "title": "联调",
                        "summary": "",
                        "status": "ACTIVE",
                        "confidence": "HIGH",
                        "created_at": "2026-09-20T09:00:00+08:00",
                        "updated_at": "2026-09-20T09:00:00+08:00",
                        "last_message_at": "2026-09-20T09:00:00+08:00",
                        "message_count": 0,
                        "schema_version": 1,
                    }
                ]
            },
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _message(self, msg_id, content):
        record = self.topic_store.upsert_message(
            {
                "id": msg_id,
                "conversation_id": self.cid,
                "platform_message_id": msg_id,
                "sender_name": "周敏",
                "content": content,
                "created_at": "2026-09-20T09:08:00+08:00",
                "direction": "INBOUND",
                "message_type": "text",
            }
        )
        self.topic_store.add_link(self.cid, self.topic_id, record["id"], RELATION_CREATED_BY)
        return record

    def test_new_task_exact_alias_links_without_touching_history(self):
        self.people.create_person("person_001", "李明")
        self.people.add_alias("李明", "person_001")
        message = self._message("msg_hist", "历史里李明已经有一项工作。")
        self.task_store.create_task(
            {
                "id": "task_old01",
                "conversation_id": self.cid,
                "topic_id": self.topic_id,
                "title": "历史任务",
                "assignee_text": "李明",
                "created_msg_id": message["id"],
                "created_at": "2026-09-20T09:00:00+08:00",
            }
        )
        current = self._message("msg_new", "李明今天补一下材料。")
        engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_TASK",
                            "task_id": None,
                            "title": "补材料",
                            "assignee_text": "李明",
                            "due_text": "",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            root_dir=ROOT,
            enabled=True,
        )
        topic = self.topic_store.get_topic(self.cid, self.topic_id)
        result = engine.process_record({"id": self.cid}, topic, current)
        self.assertEqual(result.error, "")
        self.assertNotEqual(result.decision, "FAILED")
        self.assertTrue(self.task_store.has_successful_processing(self.cid, current["id"]))
        linker = TaskIdentityLinkStore(self.root, task_store=self.task_store, identity_store=self.people)
        self.assertIsNone(linker.find_link(self.cid, "task_old01"))
        created = [item for item in result.task_ids if item != "task_old01"]
        self.assertEqual(len(created), 1)
        linked = linker.find_link(self.cid, created[0])
        self.assertEqual(linked["person_id"], "person_001")
        self.assertEqual(linked["source"], SOURCE_EXACT_EXPLICIT_ALIAS)

    def test_link_failure_keeps_task_success(self):
        self.people.create_person("person_001", "李明")
        self.people.add_alias("李明", "person_001")
        current = self._message("msg_fail_link", "李明今天补一下材料。")
        engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_TASK",
                            "task_id": None,
                            "title": "补材料",
                            "assignee_text": "李明",
                            "due_text": "",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            root_dir=ROOT,
            enabled=True,
        )
        topic = self.topic_store.get_topic(self.cid, self.topic_id)
        with patch(
            "task_identity_link.TaskIdentityLinkStore.link_task_to_person",
            side_effect=RuntimeError("link down"),
        ):
            result = engine.process_record({"id": self.cid}, topic, current)
        self.assertEqual(result.error, "")
        self.assertNotEqual(result.decision, "FAILED")
        self.assertTrue(self.task_store.has_successful_processing(self.cid, current["id"]))
        self.assertEqual(len(self.task_store.list_tasks(self.cid)), 1)
        linker = TaskIdentityLinkStore(self.root, task_store=self.task_store, identity_store=self.people)
        self.assertEqual(linker.list_links(), [])

    def test_assignee_text_change_keeps_old_link(self):
        self.people.create_person("person_001", "李明")
        self.people.create_person("person_002", "王强")
        message = self._message("msg_keep", "李明先做。")
        self.task_store.create_task(
            {
                "id": "task_keep01",
                "conversation_id": self.cid,
                "topic_id": self.topic_id,
                "title": "先做",
                "assignee_text": "李明",
                "created_msg_id": message["id"],
                "created_at": "2026-09-20T09:00:00+08:00",
            }
        )
        linker = TaskIdentityLinkStore(self.root, task_store=self.task_store, identity_store=self.people)
        linker.link_task_to_person(self.cid, "task_keep01", "person_001", source=SOURCE_MANUAL)
        current = self._message("msg_drift", "王强来接手这项工作。")
        engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "TASK_UPDATE",
                            "task_id": "task_keep01",
                            "title": "",
                            "assignee_text": "王强",
                            "due_text": "",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            root_dir=ROOT,
            enabled=True,
        )
        topic = self.topic_store.get_topic(self.cid, self.topic_id)
        result = engine.process_record({"id": self.cid}, topic, current)
        self.assertEqual(result.error, "")
        self.assertEqual(self.task_store.get_task(self.cid, "task_keep01")["assignee_text"], "王强")
        self.assertEqual(linker.find_link(self.cid, "task_keep01")["person_id"], "person_001")
        self.assertEqual(len(linker.list_links()), 1)

    def test_loose_text_best_effort_writes_nothing(self):
        self.people.create_person("person_001", "李明")
        self.people.add_alias("李明", "person_001")
        _dump_tasks(self.root, self.cid, [_task(self.cid, "task_loose01", "松文本", "李明负责")])
        attach_exact_links_for_created_tasks(self.task_store, self.cid, ["task_loose01"])
        linker = TaskIdentityLinkStore(self.root, task_store=self.task_store, identity_store=self.people)
        self.assertEqual(linker.list_links(), [])


class PersonalQueryTests(unittest.TestCase):
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
        self.people = IdentityStore(self.root)
        self.links = TaskIdentityLinkStore(self.root, task_store=TaskStore(self.root), identity_store=self.people)
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

    def _listen(self, content, pid, who=CHAT, wxid="room_a@chatroom", **msg):
        message_listener(FakeMsg(content, platform_message_id=pid, **msg), FakeChat(who, wxid))

    def _hold(self):
        self.assertTrue(self.runtime.try_acquire_session(CHAT))

    def test_personal_01_only_linked_task(self):
        self.people.create_person("person_001", "李明")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(
            self.root,
            "conv_a",
            [
                _task("conv_a", "task_a", "完成接口联调", "李明"),
                _task("conv_a", "task_b", "补充验收材料", "李明"),
            ],
        )
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 我有什么任务", "p01")
        enqueued.assert_not_called()
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(self.host.handled, [])
        reply = self.host.sent[0]
        self.assertIn("完成接口联调", reply)
        self.assertNotIn("补充验收材料", reply)
        self.assertIn("本会话", reply)
        self.assertIn("已确认负责人绑定", reply)
        self.assertNotIn("你没有任务", reply)

    def test_personal_02_only_this_person(self):
        self.people.create_person("person_001", "李明")
        self.people.create_person("person_002", "张三")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(
            self.root,
            "conv_a",
            [
                _task("conv_a", "task_a", "完成接口联调", "李明"),
                _task("conv_a", "task_b", "张三的验收", "张三"),
            ],
        )
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self.links.link_task_to_person("conv_a", "task_b", "person_002", source=SOURCE_MANUAL)
        self._listen("@智群Agent 我有什么任务", "p02", sender="李明", sender_wxid="wxid_liming")
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertNotIn("张三的验收", self.host.sent[0])

    def test_personal_03_unbound_wxid(self):
        self.people.create_person("person_001", "李明")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        with patch("collaboration_query.build_query_service", side_effect=AssertionError("service")):
            self._listen("@智群Agent 我有什么任务", "p03", sender_wxid="wxid_unknown")
        self.assertEqual(self.host.sent, [SELF_TASK_QUERY_REPLY])
        self.assertNotIn("完成接口联调", self.host.sent[0])

    def test_personal_04_empty_wxid_does_not_use_sender_name(self):
        self.people.create_person("person_001", "李明")
        self.people.add_alias("李明", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self._listen("@智群Agent 我有什么任务", "p04", sender="李明", sender_wxid="")
        self.assertEqual(self.host.sent, [SELF_TASK_QUERY_REPLY])
        self.assertNotIn("完成接口联调", self.host.sent[0])

    def test_personal_05_alias_query_uses_canonical_name(self):
        self.people.create_person("person_001", "张三丰")
        self.people.add_alias("张三", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "甲的材料", "张三")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self._listen("@智群Agent 张三负责什么", "p05")
        reply = self.host.sent[0]
        self.assertIn("张三丰", reply)
        self.assertIn("甲的材料", reply)
        self.assertIn("本会话", reply)
        self.assertIn("已确认负责人绑定", reply)

    def test_personal_06_canonical_name_is_not_an_alias(self):
        self.people.create_person("person_001", "张三")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "甲的材料", "张三")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        with patch("collaboration_query.build_query_service", side_effect=AssertionError("service")):
            self._listen("@智群Agent 张三负责什么", "p06")
        self.assertEqual(self.host.sent, [ASSIGNEE_TASK_QUERY_REPLY])
        self.assertIn("无法确定人员身份", self.host.sent[0])
        self.assertNotIn("甲的材料", self.host.sent[0])

    def test_personal_07_conversation_scope(self):
        self.people.create_person("person_001", "李明")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        _dump_tasks(self.root, "conv_b", [_task("conv_b", "task_b", "B会话任务", "李明")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self.links.link_task_to_person("conv_b", "task_b", "person_001", source=SOURCE_MANUAL)
        self._listen("@智群Agent 我有什么任务", "p07")
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertNotIn("B会话任务", self.host.sent[0])

    def test_personal_08_pending_rereads_links_not_identity(self):
        self.people.create_person("person_001", "李明")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self._hold()
        self._listen("@智群Agent 我有什么任务", "p08")
        self.assertEqual(self.host.sent, [])
        snap = pending_snapshot(self.runtime, CHAT)[0]
        self.assertEqual(snap["query_type"], "MY_TASKS")
        self.assertEqual(snap["person_id"], "person_001")
        _dump_tasks(
            self.root,
            "conv_a",
            [
                _task("conv_a", "task_a", "完成接口联调", "李明"),
                _task("conv_a", "task_c", "新增绑定任务", "李明"),
                _task("conv_a", "task_b", "仍未绑定", "李明"),
            ],
        )
        self.links.link_task_to_person("conv_a", "task_c", "person_001", source=SOURCE_MANUAL)
        self.runtime.release_session(CHAT)
        with patch("collaboration_query.resolve_wxid", side_effect=AssertionError("reresolve")):
            with patch("collaboration_query.resolve_exact_alias", side_effect=AssertionError("reresolve")):
                notify_session_released(self.runtime, CHAT)
        reply = self.host.sent[0]
        self.assertIn("完成接口联调", reply)
        self.assertIn("新增绑定任务", reply)
        self.assertNotIn("仍未绑定", reply)
        self.assertEqual(CALLS.calls, 0)

    def test_personal_09_stop_clears_pending(self):
        self.people.create_person("person_001", "李明")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self._hold()
        self._listen("@智群Agent 我有什么任务", "p09")
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self.runtime.begin_graceful_stop("p8g6-stop")
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(pending_count(self.runtime), 0)
        self.assertEqual(self.host.sent, [])

    def test_personal_emergency_clears_pending(self):
        self.people.create_person("person_001", "李明")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self._hold()
        self._listen("@智群Agent 我有什么任务", "p09e")
        self.runtime.activate_emergency("p8g6-emergency")
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(pending_count(self.runtime), 0)
        self.assertEqual(self.host.sent, [])

    def test_personal_10_statement_stays_not_query(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 李明负责补材料", "p10")
        self.assertEqual(enqueued.call_count, 1)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(len(self.host.handled), 1)

    def test_personal_11_classifier_not_used(self):
        self.people.create_person("person_001", "张三丰")
        self.people.bind_wechat("wxid_liming", "person_001")
        self.people.add_alias("张三", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "甲的材料", "张三")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self._listen("@智群Agent 我有什么任务", "p11a")
        self._listen("@智群Agent 张三负责什么", "p11b")
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(len(self.host.sent), 2)

    def test_ambiguous_wxid_does_not_guess(self):
        self.people.create_person("person_001", "李明")
        self.people.create_person("person_002", "张三")
        path = self.people.bindings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "schema_version": 1,
                    "bindings": [
                        {"wxid": "wxid_liming", "person_id": "person_001", "display_name": "", "binding_source": "MANUAL", "created_at": "t"},
                        {"wxid": "wxid_liming", "person_id": "person_002", "display_name": "", "binding_source": "MANUAL", "created_at": "t"},
                    ],
                },
                handle,
            )
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self._listen("@智群Agent 我有什么任务", "amb")
        self.assertEqual(self.host.sent, [IDENTITY_AMBIGUOUS_REPLY])
        self.assertNotIn("完成接口联调", self.host.sent[0])

    def test_disabled_person_checked_again_before_send(self):
        self.people.create_person("person_001", "李明")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self.links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        self._hold()
        self._listen("@智群Agent 我有什么任务", "dis")
        self.people.set_person_status("person_001", STATUS_DISABLED)
        self.runtime.release_session(CHAT)
        notify_session_released(self.runtime, CHAT)
        self.assertEqual(self.host.sent, [IDENTITY_DISABLED_REPLY])
        self.assertNotIn("完成接口联调", self.host.sent[0])
        self.assertEqual(len(self.links.list_links()), 1)

    def test_empty_linked_tasks_uses_confirmed_wording(self):
        self.people.create_person("person_001", "李明")
        self.people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", "完成接口联调", "李明")])
        self._listen("@智群Agent 我有什么任务", "empty")
        self.assertEqual(self.host.sent, [MY_TASKS_EMPTY_REPLY])
        self.assertNotIn("你没有任务", self.host.sent[0])
        self.assertNotIn("完成接口联调", self.host.sent[0])

    def test_query_service_does_not_match_assignee_text(self):
        with open(os.path.join(ROOT, "query_service.py"), "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("assignee_text ==", source)
        self.assertNotIn("in assignee_text", source)
        self.assertNotIn("in task.assignee_text", source)


if __name__ == "__main__":
    unittest.main()
