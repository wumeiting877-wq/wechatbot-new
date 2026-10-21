# -*- coding: utf-8 -*-
"""P9-G2：只读解析当前会话里的唯一 Task。"""

from __future__ import annotations

import builtins
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
from identity_store import IdentityStore
from message.bind import bind_host
from message.listener import message_listener
from query_formatter import COMMAND_REPLY
from query_intent_classifier import CALLS, reset_completer, use_completer
from query_router import KIND_COMMAND, KIND_NOT_QUERY, classify_agent_message
from risk_engine import RISK_ENGINE_ENABLED
from task_engine import TASK_ENGINE_ENABLED
from task_identity_link import SOURCE_MANUAL, TaskIdentityLinkStore
from task_lifecycle import TaskLifecycleService
from task_store import (
    TASK_STATUS_DONE,
    TASK_STATUS_OPEN,
    TRANSITION_TRANSITIONED,
    TaskStore,
)
from task_target_resolver import (
    AMBIGUOUS,
    CORRUPT,
    INVALID_SELECTOR,
    NOT_FOUND,
    REASON_CONVERSATION_MISMATCH,
    REASON_DUPLICATE_TASK_ID,
    REASON_DUPLICATE_TITLE,
    REASON_NOT_FOUND,
    REASON_TASKS_STRUCTURE_INVALID,
    REASON_TASKS_UNREADABLE,
    RESOLVED,
    SELECTOR_CURRENT_TASK,
    SELECTOR_EXACT_TITLE,
    SELECTOR_FUZZY_TITLE,
    SELECTOR_INDEX_FROM_CHAT,
    SELECTOR_LAST_TASK,
    SELECTOR_RECENT_TASK,
    SELECTOR_SEMANTIC_TITLE,
    SELECTOR_TASK_ID,
    UNSUPPORTED_REFERENCE,
    TaskTargetResolver,
    TaskTargetSelector,
)
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import TopicSidepath, is_topic_engine_enabled, reset_sidepath

CID_A = "conv_A"
CID_B = "conv_B"
TOPIC = "topic_target01"
CHAT = "项目群A"
BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p9g2"
CONV_A = {
    "id": CID_A,
    "platform": "WECHAT",
    "platform_conversation_id": "room_a@chatroom",
    "conversation_type": "GROUP",
    "display_name": CHAT,
    "enabled": True,
}
CANDIDATE_KEYS = ("task_id", "title", "status", "assignee_text")


def _task(cid, task_id, status=TASK_STATUS_OPEN, title="接口联调", assignee="李明"):
    return {
        "id": task_id,
        "conversation_id": cid,
        "topic_id": TOPIC,
        "title": title,
        "description": "保持描述",
        "status": status,
        "assignee_text": assignee,
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


def _write_bytes(path, blob):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(blob)


class TargetResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        self.store = TaskStore(self.root)
        self.resolver = TaskTargetResolver(self.store)

    def tearDown(self):
        self.tmpdir.cleanup()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def test_target_01_resolve_task_id(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001")])
        result = self.resolver.resolve_task_by_id(CID_A, "task_001")
        self.assertEqual(result.status, RESOLVED)
        self.assertEqual(result.selector_type, SELECTOR_TASK_ID)
        self.assertEqual(result.conversation_id, CID_A)
        self.assertEqual(result.task_id, "task_001")
        self.assertEqual(result.task["title"], "接口联调")
        self.assertEqual(result.task["status"], TASK_STATUS_OPEN)
        self.assertIsNone(result.candidates)

    def test_target_02_missing_task_id(self):
        path = _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001")])
        blob = _read_bytes(path)
        result = self.resolver.resolve_task_by_id(CID_A, "task_xxx")
        self.assertEqual(result.status, NOT_FOUND)
        self.assertEqual(result.reason, REASON_NOT_FOUND)
        self.assertIsNone(result.task_id)
        self.assertIsNone(result.task)
        self.assertEqual(_read_bytes(path), blob)

    def test_target_03_other_conversation_not_returned(self):
        path_b = _dump_tasks(self.root, CID_B, [_task(CID_B, "task_001", title="接口联调")])
        blob_b = _read_bytes(path_b)
        opened = []
        real_open = builtins.open

        def _guard(file, *args, **kwargs):
            opened.append(os.path.abspath(str(file)) if not hasattr(file, "read") else str(file))
            return real_open(file, *args, **kwargs)

        def _listdir(path):
            raise AssertionError("scanned %s" % path)

        with patch("task_target_resolver.os.listdir", _listdir):
            with patch("builtins.open", _guard):
                result = self.resolver.resolve_task_by_id(CID_A, "task_001")
        self.assertEqual(result.status, NOT_FOUND)
        self.assertIsNone(result.task)
        self.assertIsNone(result.task_id)
        self.assertFalse(any(CID_B in item for item in opened))
        self.assertFalse(os.path.isfile(_tasks_path(self.root, CID_A)))
        self.assertEqual(_read_bytes(path_b), blob_b)

    def test_target_04_exact_title(self):
        path = _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        blob = _read_bytes(path)
        result = self.resolver.resolve_task_by_exact_title(CID_A, "  接口联调  ")
        self.assertEqual(result.status, RESOLVED)
        self.assertEqual(result.selector_type, SELECTOR_EXACT_TITLE)
        self.assertEqual(result.task_id, "task_001")
        self.assertEqual(result.task["conversation_id"], CID_A)
        result.task["title"] = "被改写的副本"
        self.assertEqual(_read_bytes(path), blob)
        stored = json.loads(_read_bytes(path).decode("utf-8"))
        self.assertEqual(stored["tasks"][0]["title"], "接口联调")

    def test_target_05_contains_not_matched(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="新华接口联调")])
        result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(result.status, NOT_FOUND)
        self.assertIsNone(result.task_id)
        self.assertIsNone(result.candidates)

    def test_target_06_duplicate_title_ambiguous(self):
        _dump_tasks(
            self.root,
            CID_A,
            [
                _task(CID_A, "task_001", title="接口联调", assignee="李明"),
                _task(CID_A, "task_002", title="接口联调", assignee="王伟"),
            ],
        )
        result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(result.status, AMBIGUOUS)
        self.assertEqual(result.reason, REASON_DUPLICATE_TITLE)
        self.assertIsNone(result.task_id)
        self.assertIsNone(result.task)
        self.assertEqual(
            result.candidates,
            [
                {
                    "task_id": "task_001",
                    "title": "接口联调",
                    "status": TASK_STATUS_OPEN,
                    "assignee_text": "李明",
                },
                {
                    "task_id": "task_002",
                    "title": "接口联调",
                    "status": TASK_STATUS_OPEN,
                    "assignee_text": "王伟",
                },
            ],
        )
        for item in result.candidates:
            self.assertEqual(tuple(item.keys()), CANDIDATE_KEYS)

    def test_target_07_status_does_not_disambiguate(self):
        _dump_tasks(
            self.root,
            CID_A,
            [
                _task(CID_A, "task_001", status=TASK_STATUS_OPEN, title="接口联调"),
                _task(CID_A, "task_002", status=TASK_STATUS_DONE, title="接口联调", assignee="王伟"),
            ],
        )
        result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(result.status, AMBIGUOUS)
        self.assertIsNone(result.task_id)
        self.assertEqual([item["task_id"] for item in result.candidates], ["task_001", "task_002"])
        self.assertEqual(
            [item["status"] for item in result.candidates],
            [TASK_STATUS_OPEN, TASK_STATUS_DONE],
        )

    def test_target_08_current_task_unsupported(self):
        path = _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001")])
        blob = _read_bytes(path)
        opened = []
        real_open = builtins.open

        def _guard(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with patch("builtins.open", _guard):
            result = self.resolver.resolve_task_target(
                CID_A,
                TaskTargetSelector(SELECTOR_CURRENT_TASK),
            )
        self.assertEqual(result.status, UNSUPPORTED_REFERENCE)
        self.assertEqual(result.selector_type, SELECTOR_CURRENT_TASK)
        self.assertIsNone(result.task_id)
        self.assertIsNone(result.task)
        self.assertIsNone(result.candidates)
        self.assertFalse(any(item.endswith("tasks.json") for item in opened))
        self.assertEqual(_read_bytes(path), blob)

    def test_target_09_near_title_not_matched(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        result = self.resolver.resolve_task_by_exact_title(CID_A, "接口对接")
        self.assertEqual(result.status, NOT_FOUND)
        longer = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调工作")
        self.assertEqual(longer.status, NOT_FOUND)

    def test_target_10_files_unchanged(self):
        task_path = _dump_tasks(
            self.root,
            CID_A,
            [
                _task(CID_A, "task_001", title="接口联调"),
                _task(CID_A, "task_002", title="补充材料"),
            ],
        )
        link_path = os.path.join(os.path.dirname(task_path), "links.json")
        processed_path = os.path.join(os.path.dirname(task_path), "processed.json")
        _write_bytes(
            link_path,
            '{"links":[{"id":"tlink_keep","task_id":"task_001","relation":"CREATED_BY"}]}\n'.encode("utf-8"),
        )
        _write_bytes(
            processed_path,
            '{"records":{"m1|1":{"decision_summary":"UNRELATED"}}}\n'.encode("utf-8"),
        )
        people = IdentityStore(self.root)
        people.create_person("person_001", "李明")
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        links.link_task_to_person(CID_A, "task_001", "person_001", source=SOURCE_MANUAL)
        identity_path = links.links_path()
        before = {
            task_path: _read_bytes(task_path),
            link_path: _read_bytes(link_path),
            processed_path: _read_bytes(processed_path),
            identity_path: _read_bytes(identity_path),
        }
        names_before = set(os.listdir(os.path.dirname(task_path)))
        opened = []
        real_open = builtins.open

        def _guard(file, *args, **kwargs):
            if isinstance(file, str):
                opened.append(os.path.abspath(file))
            return real_open(file, *args, **kwargs)

        with patch("builtins.open", _guard):
            by_id = self.resolver.resolve_task_by_id(CID_A, "task_001")
            by_title = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
            missing = self.resolver.resolve_task_by_id(CID_A, "task_xxx")
            current = self.resolver.resolve_task_target(CID_A, TaskTargetSelector(SELECTOR_CURRENT_TASK))
        self.assertEqual(by_id.status, RESOLVED)
        self.assertEqual(by_title.status, RESOLVED)
        self.assertEqual(by_title.task_id, "task_001")
        self.assertEqual(missing.status, NOT_FOUND)
        self.assertEqual(current.status, UNSUPPORTED_REFERENCE)
        for path, blob in before.items():
            self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(set(os.listdir(os.path.dirname(task_path))), names_before)
        self.assertFalse(os.path.isfile(task_path + ".tmp"))
        watched = [
            item
            for item in opened
            if "task_store" in item or "identity" in item or item.endswith("task_person_links.json")
        ]
        self.assertTrue(watched)
        for item in watched:
            self.assertTrue(item.endswith(os.path.join(CID_A, "tasks.json")))
            self.assertFalse(item.endswith("links.json"))
            self.assertFalse(item.endswith("processed.json"))
            self.assertFalse(item.endswith("task_person_links.json"))

    def test_target_11_corrupt_file(self):
        path = _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001")])
        broken = b"{not-json"
        _write_bytes(path, broken)
        result = self.resolver.resolve_task_by_id(CID_A, "task_001")
        self.assertEqual(result.status, CORRUPT)
        self.assertEqual(result.reason, REASON_TASKS_UNREADABLE)
        self.assertIsNone(result.task)
        self.assertEqual(_read_bytes(path), broken)
        shaped = b'{"tasks": {}}\n'
        _write_bytes(path, shaped)
        shaped_result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(shaped_result.status, CORRUPT)
        self.assertEqual(shaped_result.reason, REASON_TASKS_STRUCTURE_INVALID)
        self.assertEqual(_read_bytes(path), shaped)
        self.assertFalse(os.path.isfile(path + ".tmp"))

    def test_target_12_lifecycle_not_called(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        with patch("task_lifecycle.TaskLifecycleService.complete_task") as complete:
            with patch("task_store.TaskStore.transition_task_status") as transition:
                with patch("task_store.TaskStore.update_task") as update:
                    with patch("store_io.atomic_write_json") as writer:
                        by_id = self.resolver.resolve_task_by_id(CID_A, "task_001")
                        by_title = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
                        missing = self.resolver.resolve_task_by_id(CID_A, "task_missing")
                        current = self.resolver.resolve_task_target(
                            CID_A,
                            TaskTargetSelector(SELECTOR_CURRENT_TASK),
                        )
        self.assertEqual(by_id.status, RESOLVED)
        self.assertEqual(by_title.status, RESOLVED)
        self.assertEqual(missing.status, NOT_FOUND)
        self.assertEqual(current.status, UNSUPPORTED_REFERENCE)
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(transition.call_count, 0)
        self.assertEqual(update.call_count, 0)
        self.assertEqual(writer.call_count, 0)

    def test_target_done_task_still_resolved(self):
        _dump_tasks(
            self.root,
            CID_A,
            [_task(CID_A, "task_001", status=TASK_STATUS_DONE, title="接口联调")],
        )
        result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(result.status, RESOLVED)
        self.assertEqual(result.task_id, "task_001")
        self.assertEqual(result.task["status"], TASK_STATUS_DONE)

    def test_target_missing_file_not_created(self):
        cid = "conv_missing01"
        path = _tasks_path(self.root, cid)
        result = self.resolver.resolve_task_by_exact_title(cid, "接口联调")
        self.assertEqual(result.status, NOT_FOUND)
        self.assertEqual(result.reason, REASON_NOT_FOUND)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.isdir(os.path.dirname(path)))
        empty_path = _dump_tasks(self.root, "conv_empty0002", [])
        empty = self.resolver.resolve_task_by_id("conv_empty0002", "task_001")
        self.assertEqual(empty.status, NOT_FOUND)
        self.assertEqual(empty.reason, REASON_NOT_FOUND)
        self.assertTrue(os.path.isfile(empty_path))

    def test_target_strip_only(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        for title in ("“接口联调”", "「接口联调」", '"接口联调"'):
            result = self.resolver.resolve_task_by_exact_title(CID_A, title)
            self.assertEqual(result.status, NOT_FOUND, title)
        path = _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调 ")])
        padded = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(padded.status, NOT_FOUND)
        self.assertEqual(json.loads(_read_bytes(path).decode("utf-8"))["tasks"][0]["title"], "接口联调 ")
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="API联调")])
        folded = self.resolver.resolve_task_by_exact_title(CID_A, "api联调")
        self.assertEqual(folded.status, NOT_FOUND)
        exact_case = self.resolver.resolve_task_by_exact_title(CID_A, "API联调")
        self.assertEqual(exact_case.status, RESOLVED)

    def test_target_same_title_other_conversation_excluded(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调"), _task(CID_A, "task_002", title="接口联调", assignee="王伟")])
        path_b = _dump_tasks(self.root, CID_B, [_task(CID_B, "task_003", title="接口联调", assignee="赵六")])
        blob_b = _read_bytes(path_b)
        opened = []
        real_open = builtins.open

        def _guard(file, *args, **kwargs):
            if isinstance(file, str):
                opened.append(os.path.abspath(file))
            return real_open(file, *args, **kwargs)

        with patch("builtins.open", _guard):
            result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(result.status, AMBIGUOUS)
        self.assertEqual([item["task_id"] for item in result.candidates], ["task_001", "task_002"])
        self.assertNotIn("task_003", [item["task_id"] for item in result.candidates])
        for item in opened:
            self.assertNotIn(CID_B, item)
        self.assertEqual(_read_bytes(path_b), blob_b)
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        unique = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(unique.status, RESOLVED)
        self.assertEqual(unique.task_id, "task_001")
        self.assertEqual(unique.task["conversation_id"], CID_A)

    def test_target_identity_link_does_not_disambiguate(self):
        _dump_tasks(
            self.root,
            CID_A,
            [
                _task(CID_A, "task_001", title="接口联调", assignee="李明"),
                _task(CID_A, "task_002", title="接口联调", assignee="王伟"),
            ],
        )
        people = IdentityStore(self.root)
        people.create_person("person_001", "李明")
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        links.link_task_to_person(CID_A, "task_001", "person_001", source=SOURCE_MANUAL)
        blob = _read_bytes(links.links_path())
        result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(result.status, AMBIGUOUS)
        self.assertEqual([item["task_id"] for item in result.candidates], ["task_001", "task_002"])
        self.assertEqual(_read_bytes(links.links_path()), blob)

    def test_target_foreign_row_in_file_not_returned(self):
        _dump_tasks(self.root, CID_A, [_task(CID_B, "task_001", title="接口联调")])
        by_id = self.resolver.resolve_task_by_id(CID_A, "task_001")
        self.assertEqual(by_id.status, NOT_FOUND)
        self.assertEqual(by_id.reason, REASON_CONVERSATION_MISMATCH)
        self.assertIsNone(by_id.task)
        by_title = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(by_title.status, NOT_FOUND)
        self.assertEqual(by_title.reason, REASON_CONVERSATION_MISMATCH)
        self.assertIsNone(by_title.task)

    def test_target_duplicate_id_not_first(self):
        _dump_tasks(
            self.root,
            CID_A,
            [
                _task(CID_A, "task_001", title="接口联调"),
                _task(CID_A, "task_001", title="补充材料", assignee="王伟"),
            ],
        )
        result = self.resolver.resolve_task_by_id(CID_A, "task_001")
        self.assertEqual(result.status, AMBIGUOUS)
        self.assertEqual(result.reason, REASON_DUPLICATE_TASK_ID)
        self.assertIsNone(result.task_id)
        self.assertEqual(len(result.candidates), 2)

    def test_target_invalid_selector(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001")])
        cases = (
            self.resolver.resolve_task_target(CID_A, None),
            self.resolver.resolve_task_target(CID_A, TaskTargetSelector("这个任务")),
            self.resolver.resolve_task_by_id(CID_A, ""),
            self.resolver.resolve_task_by_id(CID_A, "001"),
            self.resolver.resolve_task_by_exact_title(CID_A, "   "),
            self.resolver.resolve_task_by_id("room", "task_001"),
        )
        for result in cases:
            self.assertEqual(result.status, INVALID_SELECTOR)
            self.assertIsNone(result.task)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "data", "task_store", "conversations", "room")))

    def test_target_unsupported_references(self):
        _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        for selector_type in (
            SELECTOR_LAST_TASK,
            SELECTOR_RECENT_TASK,
            SELECTOR_FUZZY_TITLE,
            SELECTOR_SEMANTIC_TITLE,
            SELECTOR_INDEX_FROM_CHAT,
        ):
            result = self.resolver.resolve_task_target(CID_A, TaskTargetSelector(selector_type, title="接口联调"))
            self.assertEqual(result.status, UNSUPPORTED_REFERENCE, selector_type)
            self.assertIsNone(result.task_id)

    def test_target_resolved_id_can_complete_later(self):
        path = _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        blob = _read_bytes(path)
        with patch("task_lifecycle.TaskLifecycleService.complete_task") as complete:
            result = self.resolver.resolve_task_by_exact_title(CID_A, "接口联调")
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(result.status, RESOLVED)
        self.assertEqual(_read_bytes(path), blob)
        done = TaskLifecycleService(self.store).complete_task(CID_A, result.task_id)
        self.assertEqual(done.status, TRANSITION_TRANSITIONED)
        self.assertEqual(self.store.get_task(CID_A, "task_001")["status"], TASK_STATUS_DONE)

    def test_target_source_and_route_frozen(self):
        with open(os.path.join(ROOT, "task_target_resolver.py"), "r", encoding="utf-8") as handle:
            source = handle.read()
        for token in (
            "LLM",
            "Extractor",
            "send_reply",
            "TaskLifecycleService",
            "transition_task_status",
            "update_task",
            "atomic_write",
            "IdentityResolver",
            "difflib",
            "pinyin",
        ):
            self.assertNotIn(token, source)
        self.assertNotIn("fuzzy", source)
        self.assertIn("FUZZY_TITLE", source)
        for name in (
            "query_router.py",
            "query_formatter.py",
            "collaboration_query.py",
            "task_lifecycle.py",
            "task_engine.py",
            "task_sidepath.py",
            "query_service.py",
        ):
            with open(os.path.join(ROOT, name), "r", encoding="utf-8") as handle:
                body = handle.read()
            self.assertNotIn("task_target_resolver", body)
            self.assertNotIn("resolve_task_target", body)


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
        self.logger = logging.getLogger("test_p9g2")
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
        raise AssertionError("target gate must not call chat")


class TargetRouteTests(unittest.TestCase):
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

    def _assert_route_untouched(self, sentence, pid, kind, sent):
        path = _dump_tasks(self.root, CID_A, [_task(CID_A, "task_001", title="接口联调")])
        blob = _read_bytes(path)
        self.assertEqual(classify_agent_message(sentence).kind, kind)
        with patch("task_target_resolver.TaskTargetResolver.resolve_task_target") as resolve:
            with patch("task_target_resolver.TaskTargetResolver.resolve_task_by_id") as by_id:
                with patch("task_target_resolver.TaskTargetResolver.resolve_task_by_exact_title") as by_title:
                    with patch("task_lifecycle.TaskLifecycleService.complete_task") as complete:
                        with patch("task_store.TaskStore.transition_task_status") as transition:
                            self._listen("@智群Agent " + sentence, pid)
        self.assertEqual(resolve.call_count, 0)
        self.assertEqual(by_id.call_count, 0)
        self.assertEqual(by_title.call_count, 0)
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(transition.call_count, 0)
        self.assertEqual(self.host.sent, sent)
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(_read_bytes(path), blob)
        self.assertEqual(TaskStore(self.root).get_task(CID_A, "task_001")["status"], TASK_STATUS_OPEN)

    def test_target_13_command_still_rejected(self):
        self._assert_route_untouched("帮我把任务改成完成", "p13", KIND_COMMAND, [COMMAND_REPLY])

    def test_target_14_completion_statement(self):
        self._assert_route_untouched("接口联调今天已经完成了", "p14", KIND_NOT_QUERY, [])


if __name__ == "__main__":
    unittest.main()
