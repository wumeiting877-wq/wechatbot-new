# -*- coding: utf-8 -*-
"""P9-G3：结构化 COMPLETE_TASK。准备不写任务，确认才走生命周期。"""

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
from business_action import (
    ACTION_COMPLETE_TASK,
    ACTION_NOT_APPLICABLE,
    ACTION_NOT_FOUND,
    ACTION_TARGET_AMBIGUOUS,
    ACTION_TARGET_NOT_FOUND,
    ACTION_TYPE_NOT_ALLOWED,
    ACTOR_MISMATCH,
    ACTOR_REQUIRED,
    ALREADY_EXECUTED,
    CORRUPT,
    EXECUTED,
    FAILED,
    MESSAGE_ID_REQUIRED,
    NO_ACTION_NEEDED,
    PREPARED,
    RECORD_PERSIST_FAILED,
    SUCCEEDED_NOOP,
    UNSUPPORTED_REFERENCE,
    ActionRequest,
    BusinessActionService,
    make_action_id,
)
from business_action_audit import EVENT_EXECUTED, EVENT_FAILED, EVENT_NOOP, EVENT_PREPARED, EVENT_REJECTED, read_business_action_audit
from business_action_store import actions_path
from collaboration_query import build_query_service
from decision_engine import DECISION_ENGINE_ENABLED
from identity_store import IdentityStore
from message.listener import message_listener
from operations_action_audit import audit_path as operations_audit_path
from query_formatter import COMMAND_REPLY, format_query_result
from query_intent_classifier import CALLS, reset_completer, use_completer
from query_router import KIND_COMMAND, KIND_NOT_QUERY, LIST_TASKS, classify_agent_message
from query_service import MY_TASKS, TASKS_BY_ASSIGNEE, QueryRequest
from risk_engine import RISK_ENGINE_ENABLED
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
    TRANSITION_STALE_STATE,
    TRANSITION_TASK_NOT_FOUND,
    TRANSITION_TRANSITIONED,
    TRANSITION_WRITE_FAILED,
    TaskStore,
)
from task_target_resolver import (
    SELECTOR_CURRENT_TASK,
    SELECTOR_EXACT_TITLE,
    SELECTOR_LAST_TASK,
    SELECTOR_TASK_ID,
    TaskTargetResolver,
    TaskTargetSelector,
)
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import TopicSidepath, is_topic_engine_enabled, reset_sidepath

CID = "conv_action01"
CHAT = "项目群A"
BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p9g3"
ACTOR = "wxid_a"
CONV_A = {
    "id": CID,
    "platform": "WECHAT",
    "platform_conversation_id": "room_a@chatroom",
    "conversation_type": "GROUP",
    "display_name": CHAT,
    "enabled": True,
}
AUDIT_KEYS = (
    "ts",
    "event",
    "action_id",
    "action_type",
    "conversation_id",
    "message_id",
    "actor_ref",
    "target_type",
    "target_id",
    "before_status",
    "after_status",
    "result",
    "reason",
)
FROZEN_SOURCES = (
    "query_router.py",
    "collaboration_query.py",
    "message/listener.py",
    "query_intent_classifier.py",
    "agent_reply_delivery.py",
    "query_service.py",
    "query_formatter.py",
    "task_lifecycle.py",
    "task_store.py",
    "task_target_resolver.py",
    "task_identity_link.py",
    "task_engine.py",
)
ACTION_SOURCES = (
    "business_action.py",
    "business_action_store.py",
    "business_action_audit.py",
)
BANNED_MARKERS = (
    "send_reply",
    "SendMsg",
    "query_intent_classifier",
    "Extractor",
    "openai",
    "deepseek",
    "update_task",
    "transition_task_status",
    "difflib",
)


def _task(task_id, status=TASK_STATUS_OPEN, title="接口联调"):
    return {
        "id": task_id,
        "conversation_id": CID,
        "topic_id": "topic_action1",
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


def _tasks_path(root):
    return os.path.join(root, "data", "task_store", "conversations", CID, "tasks.json")


def _dump_tasks(root, rows):
    path = _tasks_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps({"tasks": rows}, ensure_ascii=False, indent=2) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class BusinessActionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        self.store = TaskStore(self.root)
        self.service = BusinessActionService(
            self.root,
            task_store=self.store,
            resolver=TaskTargetResolver(self.store),
            lifecycle=TaskLifecycleService(self.store),
        )

    def tearDown(self):
        self.tmpdir.cleanup()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def _dump(self, rows):
        path = _dump_tasks(self.root, rows)
        people = IdentityStore(self.root)
        if people.get_person("person_001") is None:
            people.create_person("person_001", "李明")
        if not any(item.get("wxid") == ACTOR for item in people.list_bindings()):
            people.bind_wechat(ACTOR, "person_001", display_name="李明")
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        for task in rows:
            task_id = str(task.get("id") or "")
            if task_id and links.find_link(CID, task_id) is None:
                links.link_task_to_person(CID, task_id, "person_001", source=SOURCE_MANUAL)
        return path

    def _request(self, selector, message_id="msg_01", actor=ACTOR, action_type=ACTION_COMPLETE_TASK):
        return ActionRequest(action_type, CID, message_id, actor, selector)

    def _title(self, title="接口联调"):
        return TaskTargetSelector(SELECTOR_EXACT_TITLE, title=title)

    def _by_id(self, task_id="task_a"):
        return TaskTargetSelector(SELECTOR_TASK_ID, task_id=task_id)

    def _prepare(self, selector=None, message_id="msg_01", actor=ACTOR):
        if selector is None:
            selector = self._title()
        return self.service.prepare_action(self._request(selector, message_id=message_id, actor=actor))

    def _assert_no_lifecycle(self, call):
        path = _tasks_path(self.root)
        before = _read_bytes(path)
        with patch.object(self.service.lifecycle, "complete_task", wraps=self.service.lifecycle.complete_task) as complete:
            with patch.object(self.store, "transition_task_status", wraps=self.store.transition_task_status) as transition:
                result = call()
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(transition.call_count, 0)
        self.assertEqual(_read_bytes(path), before)
        return result

    def test_action_01_prepare_open_task(self):
        path = self._dump([_task("task_a")])
        result = self._assert_no_lifecycle(lambda: self._prepare())
        self.assertEqual(result.status, PREPARED)
        self.assertTrue(result.requires_confirmation)
        self.assertEqual(result.state, PREPARED)
        self.assertEqual(result.target_task_id, "task_a")
        self.assertEqual(result.current_status, TASK_STATUS_OPEN)
        self.assertEqual(result.target_status, TASK_STATUS_DONE)
        self.assertEqual(result.preview.action_type, ACTION_COMPLETE_TASK)
        self.assertEqual(result.preview.actor_ref, ACTOR)
        self.assertEqual(result.preview.message_id, "msg_01")
        self.assertEqual(
            result.preview.text(),
            "操作：完成任务\n任务：接口联调\n当前状态：OPEN\n目标状态：DONE",
        )
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(_read_bytes(path), _read_bytes(path))
        stored = self.service.action_store.list_actions()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["state"], PREPARED)
        self.assertIn("FileLock", _read_text(os.path.join(ROOT, "business_action_store.py")))
        self.assertIn("lock_path_for", _read_text(os.path.join(ROOT, "business_action_store.py")))

    def test_action_02_ambiguous(self):
        self._dump([_task("task_a", title="接口联调"), _task("task_b", title="接口联调")])
        result = self._assert_no_lifecycle(lambda: self._prepare())
        self.assertEqual(result.status, ACTION_TARGET_AMBIGUOUS)
        self.assertEqual(result.action_id, "")
        self.assertIsNone(result.preview)
        self.assertFalse(result.requires_confirmation)
        self.assertEqual(result.target_task_id, "")
        self.assertFalse(os.path.isfile(actions_path(self.root)))
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self.store.get_task(CID, "task_b")["status"], TASK_STATUS_OPEN)

    def test_action_03_not_found(self):
        self._dump([_task("task_a", title="接口联调")])
        result = self._assert_no_lifecycle(lambda: self._prepare(self._title("不存在的任务")))
        self.assertEqual(result.status, ACTION_TARGET_NOT_FOUND)
        self.assertEqual(result.action_id, "")
        self.assertFalse(os.path.isfile(actions_path(self.root)))

    def test_action_04_unsupported_reference(self):
        self._dump([_task("task_a")])
        with patch.object(self.service.resolver, "resolve_task_target", wraps=self.service.resolver.resolve_task_target) as resolve:
            result = self._assert_no_lifecycle(
                lambda: self._prepare(TaskTargetSelector(SELECTOR_CURRENT_TASK))
            )
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(result.status, UNSUPPORTED_REFERENCE)
        self.assertEqual(result.action_id, "")
        self.assertFalse(os.path.isfile(actions_path(self.root)))
        last = self._assert_no_lifecycle(lambda: self._prepare(TaskTargetSelector(SELECTOR_LAST_TASK)))
        self.assertEqual(last.status, UNSUPPORTED_REFERENCE)

    def test_action_05_already_done(self):
        self._dump([_task("task_a", status=TASK_STATUS_DONE)])
        result = self._assert_no_lifecycle(lambda: self._prepare())
        self.assertEqual(result.status, NO_ACTION_NEEDED)
        self.assertFalse(result.requires_confirmation)
        self.assertIsNone(result.preview)
        self.assertEqual(result.action_id, "")
        self.assertEqual(result.target_task_id, "task_a")
        self.assertFalse(os.path.isfile(actions_path(self.root)))
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)

    def test_action_06_confirm(self):
        self._dump([_task("task_a")])
        prepared = self._prepare()
        self.assertEqual(prepared.status, PREPARED)
        calls = []
        original = self.service.lifecycle.complete_task

        def wrapped(conversation_id, task_id):
            lock = self.service.action_store._held_lock
            self.assertIsNotNone(lock)
            self.assertTrue(lock.is_locked)
            calls.append((conversation_id, task_id))
            return original(conversation_id, task_id)

        self.service.lifecycle.complete_task = wrapped
        with patch.object(self.service.resolver, "resolve_task_target", wraps=self.service.resolver.resolve_task_target) as resolve:
            result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(resolve.call_count, 0)
        self.assertEqual(calls, [(CID, "task_a")])
        self.assertEqual(result.status, EXECUTED)
        self.assertEqual(result.state, EXECUTED)
        self.assertEqual(result.lifecycle_status, TRANSITION_TRANSITIONED)
        self.assertFalse(result.requires_confirmation)
        stored = self.store.get_task(CID, "task_a")
        self.assertEqual(stored["status"], TASK_STATUS_DONE)
        self.assertEqual(stored["description"], "保持描述")
        self.assertEqual(stored["assignee_text"], "李明")
        record = self.service.action_store.get_action(prepared.action_id)
        self.assertEqual(record["state"], EXECUTED)
        self.assertEqual(record["actor_ref"], ACTOR)
        self.assertEqual(len(self.service.action_store.list_actions()), 1)

    def test_action_07_prepare_without_confirm(self):
        path = self._dump([_task("task_a")])
        before = _read_bytes(path)
        prepared = self._prepare()
        self.assertEqual(prepared.status, PREPARED)
        self.assertEqual(_read_bytes(path), before)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], PREPARED)

    def test_action_08_actor_mismatch(self):
        path = self._dump([_task("task_a")])
        prepared = self._prepare(actor="wxid_a")
        result = self._assert_no_lifecycle(lambda: self.service.confirm_action(prepared.action_id, "wxid_b"))
        self.assertEqual(result.status, ACTOR_MISMATCH)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(_read_bytes(path), _read_bytes(path))
        record = self.service.action_store.get_action(prepared.action_id)
        self.assertEqual(record["state"], PREPARED)
        self.assertEqual(record["actor_ref"], "wxid_a")
        done = self.service.confirm_action(prepared.action_id, "wxid_a")
        self.assertEqual(done.status, EXECUTED)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)

    def test_action_09_prepare_idempotent(self):
        self._dump([_task("task_a")])
        first = self._prepare()
        blob = _read_bytes(actions_path(self.root))
        second = self._assert_no_lifecycle(lambda: self._prepare())
        third = self._assert_no_lifecycle(lambda: self._prepare(self._by_id("task_a")))
        self.assertEqual(first.action_id, second.action_id)
        self.assertEqual(second.action_id, third.action_id)
        self.assertEqual(first.action_id, make_action_id(CID, "msg_01", ACTION_COMPLETE_TASK, "task_a"))
        self.assertTrue(first.action_id.startswith("act_"))
        self.assertNotIn("接口联调", first.action_id)
        self.assertEqual(len(self.service.action_store.list_actions()), 1)
        self.assertEqual(_read_bytes(actions_path(self.root)), blob)
        self.assertEqual(second.created_at, first.created_at)
        self.assertEqual(second.status, PREPARED)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_action_10_confirm_idempotent(self):
        self._dump([_task("task_a")])
        prepared = self._prepare()
        calls = []
        original = self.service.lifecycle.complete_task

        def wrapped(conversation_id, task_id):
            calls.append(task_id)
            return original(conversation_id, task_id)

        self.service.lifecycle.complete_task = wrapped
        first = self.service.confirm_action(prepared.action_id, ACTOR)
        blob = _read_bytes(_tasks_path(self.root))
        second = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(first.status, EXECUTED)
        self.assertEqual(second.status, ALREADY_EXECUTED)
        self.assertEqual(second.state, EXECUTED)
        self.assertEqual(calls, ["task_a"])
        self.assertEqual(_read_bytes(_tasks_path(self.root)), blob)
        executed = [row for row in read_business_action_audit(self.root) if row["event"] == EVENT_EXECUTED]
        self.assertEqual(len(executed), 1)

    def test_action_11_concurrent_confirm(self):
        self._dump([_task("task_a")])
        prepared = self._prepare()
        calls = []
        original = self.service.lifecycle.complete_task

        def wrapped(conversation_id, task_id):
            calls.append(task_id)
            time.sleep(0.05)
            return original(conversation_id, task_id)

        self.service.lifecycle.complete_task = wrapped
        gate = threading.Barrier(2)
        results = []
        errors = []

        def run():
            try:
                gate.wait(timeout=5)
                results.append(self.service.confirm_action(prepared.action_id, ACTOR))
            except Exception as exc:
                errors.append(exc)

        first = threading.Thread(target=run)
        second = threading.Thread(target=run)
        first.start()
        second.start()
        first.join(5)
        second.join(5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(calls, ["task_a"])
        self.assertEqual(sorted(item.status for item in results), [ALREADY_EXECUTED, EXECUTED])
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], EXECUTED)
        self.assertEqual(len(self.service.action_store.list_actions()), 1)

    def test_action_12_external_complete_is_noop(self):
        self._dump([_task("task_a")])
        prepared = self._prepare()
        external = TaskLifecycleService(self.store).complete_task(CID, "task_a")
        self.assertEqual(external.status, TRANSITION_TRANSITIONED)
        blob = _read_bytes(_tasks_path(self.root))
        seen = []
        original = self.service.lifecycle.complete_task

        def wrapped(conversation_id, task_id):
            result = original(conversation_id, task_id)
            seen.append(result.status)
            return result

        self.service.lifecycle.complete_task = wrapped
        result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(seen, [TRANSITION_ALREADY_IN_STATE])
        self.assertEqual(result.status, SUCCEEDED_NOOP)
        self.assertEqual(result.lifecycle_status, TRANSITION_ALREADY_IN_STATE)
        self.assertEqual(result.reason, TRANSITION_ALREADY_IN_STATE)
        self.assertEqual(_read_bytes(_tasks_path(self.root)), blob)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], SUCCEEDED_NOOP)

    def test_action_13_stale_state(self):
        self._dump([_task("task_a")])
        prepared = self._prepare()
        self._dump([_task("task_a", status=TASK_STATUS_IN_PROGRESS)])
        blob = _read_bytes(_tasks_path(self.root))
        result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(result.status, FAILED)
        self.assertEqual(result.reason, TRANSITION_STALE_STATE)
        self.assertEqual(result.lifecycle_status, TRANSITION_STALE_STATE)
        self.assertEqual(_read_bytes(_tasks_path(self.root)), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_IN_PROGRESS)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], FAILED)
        again = self._assert_no_lifecycle(lambda: self.service.confirm_action(prepared.action_id, ACTOR))
        self.assertEqual(again.status, FAILED)
        self.assertEqual(again.reason, TRANSITION_STALE_STATE)

    def test_action_14_write_failed(self):
        path = self._dump([_task("task_a")])
        prepared = self._prepare()
        blob = _read_bytes(path)

        def boom(_path, _data):
            raise OSError("disk")

        with patch("task_store._replace_json_unlocked", side_effect=boom):
            result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(result.status, FAILED)
        self.assertEqual(result.reason, TRANSITION_WRITE_FAILED)
        self.assertNotEqual(result.status, EXECUTED)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], FAILED)
        again = self._assert_no_lifecycle(lambda: self.service.confirm_action(prepared.action_id, ACTOR))
        self.assertEqual(again.status, FAILED)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_action_15_store_corrupt(self):
        path = self._dump([_task("task_a")])
        task_blob = _read_bytes(path)
        store_path = actions_path(self.root)
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        with patch.object(self.service.resolver, "resolve_task_target") as resolve:
            with patch.object(self.service.lifecycle, "complete_task") as complete:
                for payload in (b"{", b"{}"):
                    with open(store_path, "wb") as handle:
                        handle.write(payload)
                    prepared = self.service.prepare_action(self._request(self._title()))
                    confirmed = self.service.confirm_action("act_missing", ACTOR)
                    self.assertEqual(prepared.status, CORRUPT)
                    self.assertEqual(confirmed.status, CORRUPT)
                    self.assertEqual(_read_bytes(store_path), payload)
        self.assertEqual(resolve.call_count, 0)
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(_read_bytes(path), task_blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_action_16_identity_link_unchanged(self):
        self._dump([_task("task_a")])
        people = IdentityStore(self.root)
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        blob = _read_bytes(links.links_path())
        prepared = self._prepare()
        result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(result.status, EXECUTED)
        self.assertEqual(_read_bytes(links.links_path()), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)

    def test_action_17_processing_unchanged(self):
        self._dump([_task("task_a")])
        processed = os.path.join(os.path.dirname(_tasks_path(self.root)), "processed.json")
        blob = b'{"records":{"m1|1":{"decision_summary":"UNKNOWN"}}}\n'
        with open(processed, "wb") as handle:
            handle.write(blob)
        prepared = self._prepare()
        with patch.object(self.store, "_save_processed") as save_processed:
            with patch.object(self.store, "write_audit") as task_audit:
                result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(result.status, EXECUTED)
        self.assertEqual(save_processed.call_count, 0)
        self.assertEqual(task_audit.call_count, 0)
        self.assertEqual(_read_bytes(processed), blob)
        self.assertFalse(os.path.isfile(operations_audit_path(self.root)))

    def test_action_18_query_shows_done(self):
        self._dump([_task("task_a", title="接口联调"), _task("task_b", title="补充材料")])
        people = IdentityStore(self.root)
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        prepared = self._prepare(self._by_id("task_a"), message_id="msg_query")
        done = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(done.status, EXECUTED)
        audit_file = os.path.join(self.root, "data", "business_actions", "business_action_audit.jsonl")
        os.remove(audit_file)
        service = build_query_service(self.root)
        mine = service.execute(QueryRequest(CID, "m18", "88", MY_TASKS, person_id="person_001"))
        self.assertEqual(len(mine.items), 2)
        self.assertEqual(
            sorted(item["status"] for item in mine.items),
            [TASK_STATUS_DONE, TASK_STATUS_OPEN],
        )
        text = format_query_result(mine)
        self.assertIn("接口联调", text)
        self.assertIn("补充材料", text)
        self.assertIn("状态：DONE", text)
        self.assertIn("状态：OPEN", text)
        listed = service.execute(QueryRequest(CID, "m18", "88", LIST_TASKS))
        self.assertIn("状态：DONE", format_query_result(listed))
        by_person = service.execute(
            QueryRequest(CID, "m18", "88", TASKS_BY_ASSIGNEE, person_id="person_001")
        )
        self.assertEqual(
            sorted(item["status"] for item in by_person.items),
            [TASK_STATUS_DONE, TASK_STATUS_OPEN],
        )

    def test_action_actor_and_message_required(self):
        self._dump([_task("task_a")])
        with patch.object(self.service.resolver, "resolve_task_target") as resolve:
            missing_actor = self._assert_no_lifecycle(lambda: self._prepare(actor="  "))
            missing_message = self._assert_no_lifecycle(
                lambda: self.service.prepare_action(ActionRequest(ACTION_COMPLETE_TASK, CID, "  ", ACTOR, self._title()))
            )
        self.assertEqual(missing_actor.status, ACTOR_REQUIRED)
        self.assertEqual(missing_message.status, MESSAGE_ID_REQUIRED)
        self.assertEqual(resolve.call_count, 0)
        self.assertFalse(os.path.isfile(actions_path(self.root)))
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_action_type_not_allowed(self):
        self._dump([_task("task_a")])
        blocked = (
            "CREATE_TASK",
            "UPDATE_TASK",
            "START_TASK",
            "CANCEL_TASK",
            "REASSIGN_TASK",
            "CREATE_RISK",
            "CLOSE_RISK",
            "RECORD_DECISION",
            "SUPERSEDE_DECISION",
            "RESOLVE_TOPIC",
            "DELETE",
        )
        with patch.object(self.service.lifecycle, "complete_task") as complete:
            with patch.object(self.service.resolver, "resolve_task_target") as resolve:
                for action_type in blocked:
                    result = self.service.prepare_action(self._request(self._title(), action_type=action_type))
                    self.assertEqual(result.status, ACTION_TYPE_NOT_ALLOWED)
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(resolve.call_count, 0)
        self.assertFalse(os.path.isfile(actions_path(self.root)))
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_action_not_applicable_status(self):
        for status in (TASK_STATUS_IN_PROGRESS, TASK_STATUS_CANCELLED):
            self._dump([_task("task_a", status=status)])
            result = self._assert_no_lifecycle(lambda: self._prepare())
            self.assertEqual(result.status, ACTION_NOT_APPLICABLE)
            self.assertEqual(result.action_id, "")
            self.assertFalse(os.path.isfile(actions_path(self.root)))
            self.assertEqual(self.store.get_task(CID, "task_a")["status"], status)

    def test_action_confirm_uses_saved_task_id(self):
        self._dump([_task("task_a", title="接口联调")])
        prepared = self._prepare()
        self._dump(
            [
                _task("task_a", title="接口联调"),
                _task("task_b", title="接口联调"),
            ]
        )
        with patch.object(self.service.resolver, "resolve_task_target") as resolve:
            result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(resolve.call_count, 0)
        self.assertEqual(result.status, EXECUTED)
        self.assertEqual(result.target_task_id, "task_a")
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertEqual(self.store.get_task(CID, "task_b")["status"], TASK_STATUS_OPEN)

    def test_action_record_persist_failure_recovers(self):
        path = self._dump([_task("task_a")])
        prepared = self._prepare()
        real_replace = __import__("business_action_store")._replace_json_unlocked

        def flaky(store_path, data):
            actions = data.get("actions") or {}
            if any(item.get("state") != PREPARED for item in actions.values()):
                raise OSError("disk")
            return real_replace(store_path, data)

        with patch("business_action_store._replace_json_unlocked", side_effect=flaky):
            first = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(first.status, RECORD_PERSIST_FAILED)
        self.assertEqual(first.lifecycle_status, TRANSITION_TRANSITIONED)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], PREPARED)
        blob = _read_bytes(path)
        seen = []
        original = self.service.lifecycle.complete_task

        def wrapped(conversation_id, task_id):
            result = original(conversation_id, task_id)
            seen.append(result.status)
            return result

        self.service.lifecycle.complete_task = wrapped
        second = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(seen, [TRANSITION_ALREADY_IN_STATE])
        self.assertEqual(second.status, SUCCEEDED_NOOP)
        self.assertNotEqual(second.status, FAILED)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], SUCCEEDED_NOOP)

    def test_action_audit_failure_does_not_roll_back(self):
        self._dump([_task("task_a")])
        with patch("business_action.append_business_action_audit", side_effect=OSError("audit")):
            prepared = self.service.prepare_action(self._request(self._title()))
            confirmed = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(prepared.status, PREPARED)
        self.assertEqual(confirmed.status, EXECUTED)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], EXECUTED)

    def test_action_missing_task_on_confirm(self):
        self._dump([_task("task_a")])
        prepared = self._prepare()
        self._dump([])
        result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(result.status, FAILED)
        self.assertEqual(result.reason, TRANSITION_TASK_NOT_FOUND)
        self.assertEqual(result.lifecycle_status, TRANSITION_TASK_NOT_FOUND)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], FAILED)

    def test_action_noop_confirm_is_idempotent(self):
        self._dump([_task("task_a")])
        prepared = self._prepare()
        TaskLifecycleService(self.store).complete_task(CID, "task_a")
        calls = []
        original = self.service.lifecycle.complete_task

        def wrapped(conversation_id, task_id):
            calls.append(task_id)
            return original(conversation_id, task_id)

        self.service.lifecycle.complete_task = wrapped
        first = self.service.confirm_action(prepared.action_id, ACTOR)
        blob = _read_bytes(_tasks_path(self.root))
        second = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(first.status, SUCCEEDED_NOOP)
        self.assertEqual(second.status, ALREADY_EXECUTED)
        self.assertEqual(second.state, SUCCEEDED_NOOP)
        self.assertEqual(calls, ["task_a"])
        self.assertEqual(_read_bytes(_tasks_path(self.root)), blob)
        noop = [row for row in read_business_action_audit(self.root) if row["event"] == EVENT_NOOP]
        self.assertEqual(len(noop), 1)

    def test_action_existing_survives_later_ambiguity(self):
        self._dump([_task("task_a", title="接口联调")])
        prepared = self._prepare()
        self._dump([_task("task_a", title="接口联调"), _task("task_b", title="接口联调")])
        again = self._prepare()
        self.assertEqual(again.status, ACTION_TARGET_AMBIGUOUS)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], PREPARED)
        result = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(result.status, EXECUTED)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertEqual(self.store.get_task(CID, "task_b")["status"], TASK_STATUS_OPEN)

    def test_action_unknown_confirm(self):
        result = self._assert_no_lifecycle_without_tasks(lambda: self.service.confirm_action("act_missing", ACTOR))
        self.assertEqual(result.status, ACTION_NOT_FOUND)

    def test_action_audit_events(self):
        self._dump([_task("task_a", title="接口联调"), _task("task_b", title="补充材料")])
        prepared = self._prepare(self._by_id("task_a"), message_id="msg_audit")
        confirmed = self.service.confirm_action(prepared.action_id, ACTOR)
        self.assertEqual(confirmed.status, EXECUTED)
        missing = self._prepare(self._title("没有的任务"), message_id="msg_missing")
        self.assertEqual(missing.status, ACTION_TARGET_NOT_FOUND)
        self._dump([_task("task_c", title="接口联调"), _task("task_d", title="接口联调")])
        dup = self._prepare(self._title("接口联调"), message_id="msg_dup")
        self.assertEqual(dup.status, ACTION_TARGET_AMBIGUOUS)
        self._dump([_task("task_b", title="补充材料")])
        mismatch_prepared = self._prepare(self._by_id("task_b"), message_id="msg_mismatch", actor="wxid_a")
        mismatch = self.service.confirm_action(mismatch_prepared.action_id, "wxid_b")
        self.assertEqual(mismatch.status, ACTOR_MISMATCH)
        stale_prepared = self._prepare(self._by_id("task_b"), message_id="msg_stale", actor="wxid_a")
        self._dump([_task("task_b", status=TASK_STATUS_CANCELLED, title="补充材料")])
        failed = self.service.confirm_action(stale_prepared.action_id, "wxid_a")
        self.assertEqual(failed.status, FAILED)
        rows = read_business_action_audit(self.root)
        for row in rows:
            for key in AUDIT_KEYS:
                self.assertIn(key, row)
            self.assertTrue(row["ts"])
            self.assertEqual(row["target_type"], "TASK")
            self.assertTrue(row["action_type"])
            self.assertTrue(row["result"])
        prepared_rows = [row for row in rows if row["event"] == EVENT_PREPARED and row["message_id"] == "msg_audit"]
        self.assertEqual(len(prepared_rows), 1)
        self.assertEqual(prepared_rows[0]["actor_ref"], ACTOR)
        self.assertEqual(prepared_rows[0]["target_id"], "task_a")
        self.assertEqual(prepared_rows[0]["action_id"], prepared.action_id)
        executed = [row for row in rows if row["event"] == EVENT_EXECUTED]
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0]["actor_ref"], ACTOR)
        self.assertEqual(executed[0]["target_id"], "task_a")
        self.assertEqual(executed[0]["before_status"], TASK_STATUS_OPEN)
        self.assertEqual(executed[0]["after_status"], TASK_STATUS_DONE)
        self.assertEqual(executed[0]["result"], EXECUTED)
        confirm_requested = [row for row in rows if row["event"] == "ACTION_CONFIRM_REQUESTED" and row["target_id"] == "task_a"]
        self.assertTrue(confirm_requested)
        rejected = [row for row in rows if row["event"] == EVENT_REJECTED and row["result"] == ACTION_TARGET_AMBIGUOUS]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["actor_ref"], ACTOR)
        self.assertEqual(rejected[0]["target_id"], "")
        self.assertEqual(rejected[0]["action_id"], "")
        mismatch_rows = [row for row in rows if row["event"] == EVENT_REJECTED and row["result"] == ACTOR_MISMATCH]
        self.assertEqual(len(mismatch_rows), 1)
        self.assertEqual(mismatch_rows[0]["actor_ref"], "wxid_b")
        self.assertEqual(mismatch_rows[0]["target_id"], "task_b")
        self.assertTrue(mismatch_rows[0]["ts"])
        failed_rows = [row for row in rows if row["event"] == EVENT_FAILED and row["reason"] == TRANSITION_STALE_STATE]
        self.assertEqual(len(failed_rows), 1)
        self.assertEqual(failed_rows[0]["actor_ref"], "wxid_a")
        self.assertEqual(failed_rows[0]["target_id"], "task_b")
        self.assertEqual(failed_rows[0]["before_status"], TASK_STATUS_CANCELLED)
        self.assertEqual(failed_rows[0]["after_status"], TASK_STATUS_CANCELLED)
        self.assertEqual(failed_rows[0]["result"], FAILED)

    def test_action_source_boundary(self):
        for name in FROZEN_SOURCES:
            text = _read_text(os.path.join(ROOT, name.replace("/", os.sep)))
            self.assertNotIn("business_action", text)
        for name in ACTION_SOURCES:
            text = _read_text(os.path.join(ROOT, name))
            for marker in BANNED_MARKERS:
                self.assertNotIn(marker, text)
            self.assertNotIn("operations_action_audit", text)
        service = _read_text(os.path.join(ROOT, "business_action.py"))
        self.assertIn("complete_task", service)
        self.assertIn("TaskTargetResolver", service)
        self.assertIn("TaskLifecycleService", service)
        store = _read_text(os.path.join(ROOT, "business_action_store.py"))
        self.assertNotIn("complete_task", store)
        self.assertIn("FileLock", store)
        audit = _read_text(os.path.join(ROOT, "business_action_audit.py"))
        self.assertNotIn("complete_task", audit)
        self.assertNotIn("task_store", audit)

    def _assert_no_lifecycle_without_tasks(self, call):
        with patch.object(self.service.lifecycle, "complete_task", wraps=self.service.lifecycle.complete_task) as complete:
            result = call()
        self.assertEqual(complete.call_count, 0)
        return result


class FakeMsg:
    def __init__(self, content, **kwargs):
        self.type = "text"
        self.mtype = "text"
        self.content = content
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
        self.logger = logging.getLogger("test_p9g3")
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
        raise AssertionError("business action gate must not call chat")


class BusinessActionRouteTests(unittest.TestCase):
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
        from message.bind import bind_host

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
        from message.bind import bind_host
        from message import bind as bind_mod

        bind_host(types.SimpleNamespace())
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

    def _assert_route_untouched(self, sentence, pid, kind, sent):
        path = _dump_tasks(self.root, [_task("task_a")])
        blob = _read_bytes(path)
        self.assertEqual(classify_agent_message(sentence).kind, kind)
        with patch("business_action.BusinessActionService.prepare_action") as prepare:
            with patch("business_action.BusinessActionService.confirm_action") as confirm:
                with patch("task_target_resolver.TaskTargetResolver.resolve_task_target") as resolve:
                    with patch("task_target_resolver.TaskTargetResolver.resolve_task_by_id") as by_id:
                        with patch("task_target_resolver.TaskTargetResolver.resolve_task_by_exact_title") as by_title:
                            with patch("task_lifecycle.TaskLifecycleService.complete_task") as complete:
                                with patch("task_store.TaskStore.transition_task_status") as transition:
                                    self._listen("@智群Agent " + sentence, pid)
        self.assertEqual(prepare.call_count, 0)
        self.assertEqual(confirm.call_count, 0)
        self.assertEqual(resolve.call_count, 0)
        self.assertEqual(by_id.call_count, 0)
        self.assertEqual(by_title.call_count, 0)
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(transition.call_count, 0)
        self.assertEqual(self.host.sent, sent)
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(TaskStore(self.root).get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_action_19_command_still_rejected(self):
        self._assert_route_untouched("帮我把任务改成完成", "p19", KIND_COMMAND, [COMMAND_REPLY])

    def test_action_20_completion_statement(self):
        sentence = "接口联调今天已经完成了"
        self._assert_route_untouched(sentence, "p20", KIND_NOT_QUERY, [])
        extracted = HeuristicTaskExtractor().extract(
            {
                "current_message": {"id": "m1", "content": sentence, "sender_name": "李明"},
                "existing_tasks": [_task("task_a", title="接口联调")],
            },
            "",
        )
        self.assertEqual(extracted["decisions"][0]["decision"], "UNRELATED")


if __name__ == "__main__":
    unittest.main()
