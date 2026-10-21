# -*- coding: utf-8 -*-
"""P9-G1：Task 生命周期只开放 OPEN → DONE。"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED
from identity_store import IdentityStore
from message.bind import bind_host
from message.listener import message_listener
from query_formatter import COMMAND_REPLY, format_query_result
from query_intent_classifier import CALLS, reset_completer, use_completer
from query_router import KIND_COMMAND, KIND_NOT_QUERY, LIST_TASKS, classify_agent_message
from query_service import MY_TASKS, TASKS_BY_ASSIGNEE, QueryRequest
from collaboration_query import build_query_service
from risk_engine import RISK_ENGINE_ENABLED
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED
from task_extractor_client import HeuristicTaskExtractor
from task_identity_link import SOURCE_MANUAL, TaskIdentityLinkStore
from task_lifecycle import TaskLifecycleService
from task_store import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
    TRANSITION_ALREADY_IN_STATE,
    TRANSITION_CORRUPT,
    TRANSITION_INVALID_TRANSITION,
    TRANSITION_STALE_STATE,
    TRANSITION_TASK_NOT_FOUND,
    TRANSITION_TRANSITIONED,
    TRANSITION_WRITE_FAILED,
    TaskStore,
    TaskStoreError,
)
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import TopicSidepath, is_topic_engine_enabled, reset_sidepath
from topic_store import RELATION_CREATED_BY as TOPIC_CREATED_BY
from topic_store import TopicStore

CID = "conv_lifecycle01"
TOPIC = "topic_lifecycle1"
CHAT = "项目群A"
BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p9g1"
CONV_A = {
    "id": "conv_a",
    "platform": "WECHAT",
    "platform_conversation_id": "room_a@chatroom",
    "conversation_type": "GROUP",
    "display_name": CHAT,
    "enabled": True,
}


def _task(cid, task_id, status=TASK_STATUS_OPEN, title="接口联调"):
    return {
        "id": task_id,
        "conversation_id": cid,
        "topic_id": TOPIC,
        "title": title,
        "description": "保持描述",
        "status": status,
        "assignee_text": "李明",
        "due_text": "",
        "due_at": "",
        "created_msg_id": "msg_seed_000001",
        "confidence": "LOW",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "schema_version": 1,
    }


def _tasks_path(root, cid):
    return os.path.join(root, "data", "task_store", "conversations", cid, "tasks.json")


def _dump_tasks(root, cid, rows):
    path = _tasks_path(root, cid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps({"tasks": rows}, ensure_ascii=False, indent=2) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def _seed_topic(topic_store, cid, topic_id):
    topics = list(topic_store.list_topics(cid))
    if any(item.get("id") == topic_id for item in topics):
        return
    topics.append(
        {
            "id": topic_id,
            "conversation_id": cid,
            "title": "接口联调",
            "summary": "接口联调",
            "status": "ACTIVE",
            "confidence": "HIGH",
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
            "last_message_at": "2026-09-01T00:00:00Z",
            "message_count": 0,
            "schema_version": 1,
        }
    )
    atomic_write_json(os.path.join(topic_store.conversation_dir(cid), "topics.json"), {"topics": topics})


class LifecycleStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        self.store = TaskStore(self.root)
        self.service = TaskLifecycleService(self.store)

    def tearDown(self):
        self.tmpdir.cleanup()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def _open(self, task_id="task_a", title="接口联调"):
        path = _dump_tasks(self.root, CID, [_task(CID, task_id, title=title)])
        return path

    def test_lifecycle_01_open_to_done(self):
        path = self._open()
        processed = os.path.join(os.path.dirname(path), "processed.json")
        links = os.path.join(os.path.dirname(path), "links.json")
        processed_bytes = b'{"records":{"m1|1":{"decision_summary":"UNKNOWN"}}}\n'
        links_bytes = b'{"links":[{"id":"tlink_keep","task_id":"task_a","relation":"CREATED_BY"}]}\n'
        with open(processed, "wb") as handle:
            handle.write(processed_bytes)
        with open(links, "wb") as handle:
            handle.write(links_bytes)
        with self.assertLogs("task_lifecycle", level="INFO") as captured:
            result = self.service.complete_task(CID, "task_a")
        self.assertEqual(result.status, TRANSITION_TRANSITIONED)
        self.assertEqual(result.from_status, TASK_STATUS_OPEN)
        self.assertEqual(result.to_status, TASK_STATUS_DONE)
        stored = self.store.get_task(CID, "task_a")
        self.assertEqual(stored["status"], TASK_STATUS_DONE)
        self.assertEqual(stored["description"], "保持描述")
        self.assertEqual(stored["assignee_text"], "李明")
        self.assertTrue(any("Task lifecycle transitioned" in line for line in captured.output))
        self.assertEqual(_read_bytes(processed), processed_bytes)
        self.assertEqual(_read_bytes(links), links_bytes)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "data", "risk_store")))
        self.assertFalse(os.path.isdir(os.path.join(self.root, "data", "decision_store")))
        self.assertFalse(os.path.isdir(os.path.join(self.root, "data", "identity")))
        updated = self.store.update_task(CID, "task_a", description="只改描述")
        self.assertEqual(updated["status"], TASK_STATUS_DONE)
        self.assertEqual(updated["description"], "只改描述")

    def test_lifecycle_02_updated_at(self):
        self._open()
        before = self.store.get_task(CID, "task_a")
        result = self.service.complete_task(CID, "task_a")
        after = self.store.get_task(CID, "task_a")
        self.assertEqual(result.status, TRANSITION_TRANSITIONED)
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertEqual(after["created_at"], "2026-09-01T00:00:00Z")
        self.assertNotEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(after["updated_at"], result.task["updated_at"])

    def test_lifecycle_03_done_is_idempotent(self):
        self._open()
        first = self.service.complete_task(CID, "task_a")
        self.assertEqual(first.status, TRANSITION_TRANSITIONED)
        path = _tasks_path(self.root, CID)
        blob = _read_bytes(path)
        updated_at = self.store.get_task(CID, "task_a")["updated_at"]
        with self.assertNoLogs("task_lifecycle", level="INFO"):
            second = self.service.complete_task(CID, "task_a")
        self.assertEqual(second.status, TRANSITION_ALREADY_IN_STATE)
        self.assertEqual(second.from_status, TASK_STATUS_DONE)
        self.assertEqual(second.to_status, TASK_STATUS_DONE)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["updated_at"], updated_at)
        direct = self.store.transition_task_status(CID, "task_a", TASK_STATUS_DONE, TASK_STATUS_DONE)
        self.assertEqual(direct.status, TRANSITION_ALREADY_IN_STATE)
        self.assertEqual(_read_bytes(path), blob)

    def test_lifecycle_04_done_to_open_rejected(self):
        self._open()
        self.service.complete_task(CID, "task_a")
        path = _tasks_path(self.root, CID)
        blob = _read_bytes(path)
        result = self.store.transition_task_status(CID, "task_a", TASK_STATUS_DONE, TASK_STATUS_OPEN)
        self.assertEqual(result.status, TRANSITION_INVALID_TRANSITION)
        self.assertEqual(result.from_status, TASK_STATUS_DONE)
        self.assertEqual(result.to_status, TASK_STATUS_OPEN)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)

    def test_lifecycle_05_open_to_in_progress_rejected(self):
        path = self._open()
        blob = _read_bytes(path)
        result = self.store.transition_task_status(CID, "task_a", TASK_STATUS_OPEN, TASK_STATUS_IN_PROGRESS)
        self.assertEqual(result.status, TRANSITION_INVALID_TRANSITION)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        _dump_tasks(self.root, CID, [_task(CID, "task_a", status=TASK_STATUS_IN_PROGRESS)])
        blob = _read_bytes(path)
        forward = self.store.transition_task_status(CID, "task_a", TASK_STATUS_IN_PROGRESS, TASK_STATUS_DONE)
        self.assertEqual(forward.status, TRANSITION_INVALID_TRANSITION)
        self.assertEqual(_read_bytes(path), blob)
        stale = self.service.complete_task(CID, "task_a")
        self.assertEqual(stale.status, TRANSITION_STALE_STATE)
        self.assertEqual(_read_bytes(path), blob)

    def test_lifecycle_06_open_to_cancelled_rejected(self):
        path = self._open()
        blob = _read_bytes(path)
        result = self.store.transition_task_status(CID, "task_a", TASK_STATUS_OPEN, TASK_STATUS_CANCELLED)
        self.assertEqual(result.status, TRANSITION_INVALID_TRANSITION)
        self.assertEqual(_read_bytes(path), blob)
        cases = (
            (TASK_STATUS_DONE, TASK_STATUS_IN_PROGRESS),
            (TASK_STATUS_DONE, TASK_STATUS_CANCELLED),
            (TASK_STATUS_IN_PROGRESS, TASK_STATUS_CANCELLED),
            (TASK_STATUS_CANCELLED, TASK_STATUS_OPEN),
            (TASK_STATUS_CANCELLED, TASK_STATUS_DONE),
        )
        for current, target in cases:
            _dump_tasks(self.root, CID, [_task(CID, "task_a", status=current)])
            blob = _read_bytes(path)
            rejected = self.store.transition_task_status(CID, "task_a", current, target)
            self.assertEqual(rejected.status, TRANSITION_INVALID_TRANSITION, "%s -> %s" % (current, target))
            self.assertEqual(_read_bytes(path), blob)
            self.assertEqual(self.store.get_task(CID, "task_a")["status"], current)

    def test_lifecycle_07_create_rejects_non_open(self):
        topic_store = TopicStore(self.root)
        store = TaskStore(self.root, topic_store=topic_store)
        _seed_topic(topic_store, CID, TOPIC)
        message = topic_store.upsert_message(
            {
                "id": "msg_seed_000001",
                "conversation_id": CID,
                "platform_message_id": "msg_seed_000001",
                "sender_name": "李明",
                "content": "接口联调",
                "created_at": "2026-09-01T00:00:00Z",
            }
        )
        topic_store.add_link(CID, TOPIC, message["id"], TOPIC_CREATED_BY)
        created = store.create_task(
            {
                "conversation_id": CID,
                "topic_id": TOPIC,
                "title": "接口联调",
                "assignee_text": "李明",
                "created_msg_id": message["id"],
                "created_at": "2026-09-01T00:00:00Z",
            }
        )
        self.assertEqual(created["status"], TASK_STATUS_OPEN)
        path = _tasks_path(self.root, CID)
        blob = _read_bytes(path)
        for status in (TASK_STATUS_DONE, TASK_STATUS_IN_PROGRESS, TASK_STATUS_CANCELLED):
            with self.assertRaises(TaskStoreError) as caught:
                store.create_task(
                    {
                        "conversation_id": CID,
                        "topic_id": TOPIC,
                        "title": "接口联调",
                        "assignee_text": "李明",
                        "created_msg_id": message["id"],
                        "status": status,
                    }
                )
            self.assertEqual(caught.exception.code, "INVALID_STATUS")
            self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(len(store.list_tasks(CID)), 1)
        self.assertEqual(store.get_task(CID, created["id"])["status"], TASK_STATUS_OPEN)

    def test_lifecycle_08_update_task_rejects_status(self):
        path = self._open()
        blob = _read_bytes(path)
        with self.assertRaises(TaskStoreError) as caught:
            self.store.update_task(CID, "task_a", status=TASK_STATUS_DONE)
        self.assertEqual(caught.exception.code, "INVALID_STATUS")
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_lifecycle_09_missing_task(self):
        path = self._open()
        blob = _read_bytes(path)
        result = self.service.complete_task(CID, "task_missing")
        self.assertEqual(result.status, TRANSITION_TASK_NOT_FOUND)
        self.assertEqual(_read_bytes(path), blob)
        self.assertIsNone(result.task)
        absent = self.service.complete_task("conv_nobody0001", "task_missing")
        self.assertEqual(absent.status, TRANSITION_TASK_NOT_FOUND)
        self.assertFalse(os.path.isfile(_tasks_path(self.root, "conv_nobody0001")))

    def test_lifecycle_10_corrupt_file_kept(self):
        path = self._open()
        broken = b"{not-json"
        with open(path, "wb") as handle:
            handle.write(broken)
        result = self.service.complete_task(CID, "task_a")
        self.assertEqual(result.status, TRANSITION_CORRUPT)
        self.assertEqual(_read_bytes(path), broken)
        self.assertFalse(os.path.isfile(path + ".tmp"))
        shaped = b'{"tasks": {}}\n'
        with open(path, "wb") as handle:
            handle.write(shaped)
        shaped_result = self.service.complete_task(CID, "task_a")
        self.assertEqual(shaped_result.status, TRANSITION_CORRUPT)
        self.assertEqual(_read_bytes(path), shaped)

    def test_lifecycle_11_identity_link_unchanged(self):
        self._open()
        people = IdentityStore(self.root)
        people.create_person("person_001", "李明")
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        links.link_task_to_person(CID, "task_a", "person_001", source=SOURCE_MANUAL)
        blob = _read_bytes(links.links_path())
        result = self.service.complete_task(CID, "task_a")
        self.assertEqual(result.status, TRANSITION_TRANSITIONED)
        self.assertEqual(_read_bytes(links.links_path()), blob)
        found = links.find_link(CID, "task_a")
        self.assertEqual(found["person_id"], "person_001")
        self.assertEqual(len(links.list_links()), 1)
        stored = self.store.get_task(CID, "task_a")
        self.assertEqual(stored["status"], TASK_STATUS_DONE)
        self.assertNotIn("person_id", stored)

    def test_lifecycle_15_second_complete_does_not_rewrite(self):
        path = self._open()
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def _run():
            try:
                barrier.wait(timeout=5)
                results.append(self.service.complete_task(CID, "task_a"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        statuses = sorted(item.status for item in results)
        self.assertEqual(statuses, [TRANSITION_ALREADY_IN_STATE, TRANSITION_TRANSITIONED])
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        blob = _read_bytes(path)
        again = self.service.complete_task(CID, "task_a")
        self.assertEqual(again.status, TRANSITION_ALREADY_IN_STATE)
        self.assertEqual(_read_bytes(path), blob)
        _dump_tasks(self.root, CID, [_task(CID, "task_a", status=TASK_STATUS_CANCELLED)])
        blob = _read_bytes(path)
        stale = self.service.complete_task(CID, "task_a")
        self.assertEqual(stale.status, TRANSITION_STALE_STATE)
        self.assertEqual(stale.from_status, TASK_STATUS_CANCELLED)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_CANCELLED)

    def test_lifecycle_write_failed_keeps_file(self):
        path = self._open()
        blob = _read_bytes(path)

        def _fail_replace(*_args, **_kwargs):
            raise OSError("disk full")

        with patch("task_store.os.replace", _fail_replace):
            result = self.service.complete_task(CID, "task_a")
        self.assertEqual(result.status, TRANSITION_WRITE_FAILED)
        self.assertIsNone(result.task)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertFalse(os.path.isfile(path + ".tmp"))

    def test_lifecycle_service_source(self):
        with open(os.path.join(ROOT, "task_lifecycle.py"), "r", encoding="utf-8") as handle:
            source = handle.read()
        for token in (
            "LLM",
            "Extractor",
            "send_reply",
            "QueryService",
            "IdentityResolver",
            "fuzzy",
            "wx",
            "commit_apply",
            "operations_action_audit",
            "write_processing",
        ):
            self.assertNotIn(token, source)
        for name in ("task_engine.py", "collaboration_query.py", "query_service.py", "task_sidepath.py"):
            with open(os.path.join(ROOT, name), "r", encoding="utf-8") as handle:
                body = handle.read()
            self.assertNotIn("task_lifecycle", body)
            self.assertNotIn("complete_task", body)


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
        self.logger = logging.getLogger("test_p9g1")
        self.user_names = [CHAT]
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
        raise AssertionError("lifecycle gate must not call chat")


class LifecycleRouteTests(unittest.TestCase):
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
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
        self._completer = use_completer(lambda _messages: (_ for _ in ()).throw(AssertionError("classifier")))
        self._completer.__enter__()

    def tearDown(self):
        self._completer.__exit__(None, None, None)
        reset_completer()
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
        try:
            self.runtime.send_queue.stop()
        except Exception:
            pass
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

    def _listen(self, content, pid):
        message_listener(FakeMsg(content, platform_message_id=pid), FakeChat())

    def test_lifecycle_12_my_tasks_shows_done(self):
        people = IdentityStore(self.root)
        people.create_person("person_001", "李明")
        people.bind_wechat("wxid_liming", "person_001")
        _dump_tasks(
            self.root,
            "conv_a",
            [
                _task("conv_a", "task_a", title="接口联调"),
                _task("conv_a", "task_b", title="补充材料"),
            ],
        )
        store = TaskStore(self.root)
        links = TaskIdentityLinkStore(self.root, task_store=store, identity_store=people)
        links.link_task_to_person("conv_a", "task_a", "person_001", source=SOURCE_MANUAL)
        links.link_task_to_person("conv_a", "task_b", "person_001", source=SOURCE_MANUAL)
        done = TaskLifecycleService(store).complete_task("conv_a", "task_a")
        self.assertEqual(done.status, TRANSITION_TRANSITIONED)
        self._listen("@智群Agent 我有什么任务", "p12")
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(len(self.host.sent), 1)
        reply = self.host.sent[0]
        self.assertIn("接口联调", reply)
        self.assertIn("补充材料", reply)
        self.assertIn("状态：DONE", reply)
        self.assertIn("状态：OPEN", reply)
        self.assertNotIn("状态：已完成", reply)
        self.assertNotIn("task_a", reply)
        service = build_query_service(self.root)
        listed = service.execute(
            QueryRequest("conv_a", "p12", "88", LIST_TASKS)
        )
        text = format_query_result(listed)
        self.assertIn("接口联调", text)
        self.assertIn("补充材料", text)
        self.assertIn("状态：DONE", text)
        self.assertIn("状态：OPEN", text)
        by_person = service.execute(
            QueryRequest("conv_a", "p12", "88", TASKS_BY_ASSIGNEE, person_id="person_001")
        )
        self.assertEqual(by_person.query_type, TASKS_BY_ASSIGNEE)
        self.assertEqual(
            sorted(item["status"] for item in by_person.items),
            [TASK_STATUS_DONE, TASK_STATUS_OPEN],
        )
        mine = service.execute(
            QueryRequest("conv_a", "p12", "88", MY_TASKS, person_id="person_001")
        )
        self.assertEqual(len(mine.items), 2)

    def test_lifecycle_13_command_still_rejected(self):
        path = _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a")])
        blob = _read_bytes(path)
        self.assertEqual(classify_agent_message("帮我把任务改成完成").kind, KIND_COMMAND)
        with patch("task_lifecycle.TaskLifecycleService.complete_task") as complete:
            with patch("task_store.TaskStore.transition_task_status") as transition:
                self._listen("@智群Agent 帮我把任务改成完成", "p13")
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(transition.call_count, 0)
        self.assertEqual(self.host.sent, [COMMAND_REPLY])
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(TaskStore(self.root).get_task("conv_a", "task_a")["status"], TASK_STATUS_OPEN)

    def test_lifecycle_14_completion_statement_does_not_complete(self):
        path = _dump_tasks(self.root, "conv_a", [_task("conv_a", "task_a", title="接口联调")])
        blob = _read_bytes(path)
        sentence = "接口联调今天已经完成了"
        self.assertEqual(classify_agent_message(sentence).kind, KIND_NOT_QUERY)
        with patch("task_lifecycle.TaskLifecycleService.complete_task") as complete:
            with patch("task_store.TaskStore.transition_task_status") as transition:
                self._listen("@智群Agent " + sentence, "p14")
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(transition.call_count, 0)
        self.assertEqual(self.host.sent, [])
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(TaskStore(self.root).get_task("conv_a", "task_a")["status"], TASK_STATUS_OPEN)
        extracted = HeuristicTaskExtractor().extract(
            {
                "current_message": {"id": "m1", "content": sentence, "sender_name": "李明"},
                "existing_tasks": [_task("conv_a", "task_a", title="接口联调")],
            },
            "",
        )
        self.assertEqual(extracted["decisions"][0]["decision"], "UNRELATED")
        prompt_path = os.path.join(ROOT, "prompts", "extractors", "TASK_EXTRACTOR.md")
        with open(prompt_path, "r", encoding="utf-8") as handle:
            prompt = handle.read()
        self.assertIn("即使消息说已完成、已修好、关掉吧，也输出 UNRELATED。本版本不结束 Task。", prompt)
        with open(os.path.join(ROOT, "task_engine.py"), "r", encoding="utf-8") as handle:
            engine = handle.read()
        self.assertNotIn("task_lifecycle", engine)
        self.assertNotIn("complete_task", engine)


if __name__ == "__main__":
    unittest.main()
