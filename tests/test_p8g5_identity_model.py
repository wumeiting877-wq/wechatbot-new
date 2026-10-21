# -*- coding: utf-8 -*-
"""P8-G5：显式人员目录、wxid 绑定、精确别名。查询行为保持冻结。"""

from __future__ import annotations

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

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED
from filelock import FileLock
from identity_resolver import AMBIGUOUS, NOT_FOUND, RESOLVED, resolve_exact_alias, resolve_wxid
from identity_store import STATUS_ACTIVE, STATUS_DISABLED, IdentityStore, IdentityStoreError
from message.bind import bind_host
from message.listener import message_listener
from query_formatter import SELF_TASK_QUERY_REPLY
from query_intent_classifier import CALLS, reset_completer, use_completer
from risk_engine import RISK_ENGINE_ENABLED
from store_io import lock_path_for
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
BOT_WXID = "wxid_bot_p8g5"
FORBIDDEN_SOURCE_TOKENS = (
    "LLM",
    "Extractor",
    "contains",
    "difflib",
    "pinyin",
    "semantic",
    "get_deepseek",
    "call_narrow_completion",
    "write_processing",
    "send_reply",
    "edit distance",
    "edit_distance",
    "Engine",
    "retry",
)


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
        self.logger = logging.getLogger("test_p8g5")
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
        raise AssertionError("identity model must not call chat")


class IdentityModelTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = IdentityStore(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def test_identity_model_01_create_person(self):
        person = self.store.create_person("person_001", "李明")
        self.assertEqual(person["person_id"], "person_001")
        self.assertEqual(person["canonical_name"], "李明")
        self.assertEqual(person["status"], STATUS_ACTIVE)
        self.assertNotEqual(person["person_id"], person["canonical_name"])
        saved = self.store.get_person("person_001")
        self.assertEqual(saved["canonical_name"], "李明")

    def test_identity_model_02_same_canonical_name_is_two_people(self):
        first = self.store.create_person("person_001", "张三")
        second = self.store.create_person("person_002", "张三")
        self.assertEqual(first["canonical_name"], second["canonical_name"])
        self.assertNotEqual(first["person_id"], second["person_id"])
        self.assertEqual(len(self.store.list_people()), 2)
        self.assertEqual(resolve_exact_alias(self.store, "张三").status, NOT_FOUND)

    def test_identity_model_03_duplicate_person_id_rejected(self):
        self.store.create_person("person_001", "李明")
        with self.assertRaises(IdentityStoreError) as caught:
            self.store.create_person("person_001", "李明")
        self.assertEqual(caught.exception.code, "DUPLICATE_PERSON_ID")
        people = self.store.list_people()
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0]["canonical_name"], "李明")

    def test_identity_model_04_bind_wxid(self):
        self.store.create_person("person_001", "李明")
        binding = self.store.bind_wechat("wxid_a", "person_001", display_name="李明", binding_source="MANUAL")
        self.assertEqual(binding["wxid"], "wxid_a")
        self.assertEqual(binding["person_id"], "person_001")
        self.assertEqual(binding["binding_source"], "MANUAL")
        again = self.store.bind_wechat("wxid_a", "person_001")
        self.assertEqual(again["person_id"], "person_001")
        self.assertEqual(len(self.store.list_bindings()), 1)

    def test_identity_model_05_resolve_wxid(self):
        self.store.create_person("person_001", "李明")
        self.store.bind_wechat("wxid_a", "person_001")
        result = resolve_wxid(self.store, " wxid_a ")
        self.assertEqual(result.status, RESOLVED)
        self.assertEqual(result.person_id, "person_001")
        self.assertEqual(result.person["canonical_name"], "李明")

    def test_identity_model_06_wxid_rebind_conflicts(self):
        self.store.create_person("person_001", "李明")
        self.store.create_person("person_002", "李明")
        self.store.bind_wechat("wxid_a", "person_001")
        before = _read(self.store.bindings_path())
        with self.assertRaises(IdentityStoreError) as caught:
            self.store.bind_wechat("wxid_a", "person_002")
        self.assertEqual(caught.exception.code, "CONFLICT")
        self.assertEqual(_read(self.store.bindings_path()), before)
        self.assertEqual(resolve_wxid(self.store, "wxid_a").person_id, "person_001")

    def test_identity_model_07_unknown_wxid(self):
        result = resolve_wxid(self.store, "wxid_missing")
        self.assertEqual(result.status, NOT_FOUND)
        self.assertEqual(result.person_id, "")
        self.assertIsNone(result.person)
        self.assertFalse(os.path.isfile(self.store.people_path()))
        self.assertEqual(self.store.list_people(), [])

    def test_identity_model_08_explicit_alias(self):
        self.store.create_person("person_001", "李明")
        alias = self.store.add_alias("李明", "person_001")
        self.assertEqual(alias["exact_text"], "李明")
        self.assertEqual(alias["person_id"], "person_001")
        self.store.add_alias("  李明  ", "person_001")
        self.assertEqual(len(self.store.list_aliases()), 1)

    def test_identity_model_09_resolve_exact_alias(self):
        self.store.create_person("person_001", "李明")
        self.assertEqual(resolve_exact_alias(self.store, "李明").status, NOT_FOUND)
        self.store.add_alias("李明", "person_001")
        result = resolve_exact_alias(self.store, " 李明 ")
        self.assertEqual(result.status, RESOLVED)
        self.assertEqual(result.person_id, "person_001")
        self.assertEqual(result.person["canonical_name"], "李明")

    def test_identity_model_10_decorated_text_is_not_found(self):
        self.store.create_person("person_001", "李明")
        self.store.add_alias("李明", "person_001")
        result = resolve_exact_alias(self.store, "李明负责")
        self.assertEqual(result.status, NOT_FOUND)
        self.assertEqual(self.store.list_aliases()[0]["exact_text"], "李明")

    def test_identity_model_11_alias_rebind_conflicts(self):
        self.store.create_person("person_001", "李明")
        self.store.create_person("person_002", "李明")
        self.store.add_alias("李明", "person_001")
        before = _read(self.store.aliases_path())
        with self.assertRaises(IdentityStoreError) as caught:
            self.store.add_alias("李明", "person_002")
        self.assertEqual(caught.exception.code, "CONFLICT")
        self.assertEqual(_read(self.store.aliases_path()), before)
        self.assertEqual(resolve_exact_alias(self.store, "李明").person_id, "person_001")

    def test_identity_model_12_no_fuzzy_alias(self):
        self.store.create_person("person_001", "李明")
        self.store.add_alias("李明", "person_001")
        for text in ("@李明", "研发部李明", "由李明", "李明负责"):
            result = resolve_exact_alias(self.store, text)
            self.assertEqual(result.status, NOT_FOUND, text)
            self.assertEqual(result.person_id, "")
        self.assertEqual(len(self.store.list_people()), 1)
        self.assertEqual(len(self.store.list_aliases()), 1)

    def test_identity_model_ambiguous_alias_is_not_picked(self):
        self.store.create_person("person_001", "张三")
        self.store.create_person("person_002", "张三")
        _write_json(self.store.aliases_path(), {
            "schema_version": 1,
            "aliases": [
                {"exact_text": "张三", "person_id": "person_001", "created_at": "2026-09-23T00:00:00Z"},
                {"exact_text": "张三", "person_id": "person_002", "created_at": "2026-09-23T00:00:00Z"},
            ],
        })
        before = _read(self.store.aliases_path())
        result = resolve_exact_alias(self.store, "张三")
        self.assertEqual(result.status, AMBIGUOUS)
        self.assertEqual(result.person_id, "")
        self.assertIsNone(result.person)
        with self.assertRaises(IdentityStoreError) as caught:
            self.store.add_alias("老张", "person_001")
        self.assertEqual(caught.exception.code, "INTEGRITY")
        self.assertEqual(_read(self.store.aliases_path()), before)

    def test_identity_model_reload(self):
        self.store.create_person("person_001", "李明")
        self.store.bind_wechat("wxid_a", "person_001", binding_source="MANUAL")
        self.store.add_alias("老李", "person_001")
        again = IdentityStore(self.tmpdir.name)
        self.assertEqual(again.get_person("person_001")["canonical_name"], "李明")
        self.assertEqual(resolve_wxid(again, "wxid_a").person_id, "person_001")
        self.assertEqual(resolve_exact_alias(again, "老李").person_id, "person_001")

    def test_identity_model_atomic_write_failure_keeps_file(self):
        self.store.create_person("person_001", "李明")
        before = _read(self.store.people_path())
        with patch("identity_store.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.store.create_person("person_002", "张三")
        self.assertEqual(_read(self.store.people_path()), before)
        self.assertFalse(os.path.exists(self.store.people_path() + ".tmp"))
        self.assertIsNone(self.store.get_person("person_002"))

    def test_identity_model_filelock_blocks_second_writer(self):
        path = self.store.people_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = FileLock(lock_path_for(path))
        lock.acquire()
        started = threading.Event()
        finished = threading.Event()
        errors = []

        def worker():
            started.set()
            try:
                self.store.create_person("person_001", "李明")
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(started.wait(2))
        time.sleep(0.3)
        self.assertFalse(finished.is_set())
        lock.release()
        thread.join(5)
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [])
        self.assertEqual(self.store.get_person("person_001")["canonical_name"], "李明")

    def test_identity_model_corrupt_file_is_not_reset(self):
        path = self.store.people_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = b"{not-json"
        with open(path, "wb") as handle:
            handle.write(payload)
        with self.assertRaises(IdentityStoreError) as listed:
            self.store.list_people()
        self.assertEqual(listed.exception.code, "CORRUPT")
        with self.assertRaises(IdentityStoreError) as created:
            self.store.create_person("person_001", "李明")
        self.assertEqual(created.exception.code, "CORRUPT")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), payload)

    def test_identity_model_disable_keeps_the_row(self):
        self.store.create_person("person_001", "李明")
        self.store.bind_wechat("wxid_a", "person_001")
        disabled = self.store.set_person_status("person_001", STATUS_DISABLED)
        self.assertEqual(disabled["status"], STATUS_DISABLED)
        self.assertEqual(len(self.store.list_people()), 1)
        result = resolve_wxid(self.store, "wxid_a")
        self.assertEqual(result.status, RESOLVED)
        self.assertEqual(result.person["status"], STATUS_DISABLED)
        with self.assertRaises(IdentityStoreError) as caught:
            self.store.create_person("person_001", "李明")
        self.assertEqual(caught.exception.code, "DUPLICATE_PERSON_ID")

    def test_identity_model_source_has_no_guessing_tools(self):
        for name in ("identity_store.py", "identity_resolver.py"):
            with open(os.path.join(ROOT, name), "r", encoding="utf-8") as handle:
                source = handle.read()
            for token in FORBIDDEN_SOURCE_TOKENS:
                self.assertNotIn(token, source, "%s has %s" % (name, token))


class IdentityQueryFreezeTests(unittest.TestCase):
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

    def test_identity_model_13_my_tasks_stays_fixed(self):
        service_calls = {"n": 0}

        def reject_service(*_args, **_kwargs):
            service_calls["n"] += 1
            raise AssertionError("query service")

        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            with patch("collaboration_query.build_query_service", side_effect=reject_service):
                message_listener(
                    FakeMsg(
                        "@智群Agent 我有什么任务",
                        platform_message_id="id13",
                        sender="李明",
                        sender_wxid="wxid_liming",
                    ),
                    FakeChat(),
                )
        enqueued.assert_not_called()
        self.assertEqual(service_calls["n"], 0)
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.sent, [SELF_TASK_QUERY_REPLY])
        self.assertIn("无法确定你的人员身份", self.host.sent[0])
        self.assertNotIn("完成接口联调", self.host.sent[0])
        self.assertFalse(os.path.isdir(os.path.join(self.root, "data", "identity")))


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)
        handle.write("\n")


if __name__ == "__main__":
    unittest.main()
