# -*- coding: utf-8 -*-
"""P9-G4：显式完成命令、Preview，以及只认「确认完成」。"""

from __future__ import annotations

import inspect
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

from agent_reply_delivery import notify_session_released, pending_count
from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from business_action import ACTION_COMPLETE_TASK, PREPARED, ActionRequest, BusinessActionService
from business_action_audit import EVENT_CONFIRM_REQUESTED, EVENT_EXECUTED, EVENT_PREPARED, read_business_action_audit
from business_action_store import BusinessActionStore, actions_path
from collaboration_query import build_query_service
from decision_engine import DECISION_ENGINE_ENABLED
from identity_store import IdentityStore
from message.listener import message_listener
from query_formatter import COMMAND_REPLY, format_query_result
from query_intent_classifier import CALLS, reset_completer, use_completer
from query_router import LIST_TASKS
from query_service import MY_TASKS, TASKS_BY_ASSIGNEE, QueryRequest
from risk_engine import RISK_ENGINE_ENABLED
from task_command_parser import (
    ACTION_COMPLETE_TASK as PARSED_COMPLETE,
    COMMAND,
    NOT_COMMAND,
    SELECTOR_EXACT_TITLE,
    UNSUPPORTED,
    parse_task_command,
)
from task_engine import TASK_ENGINE_ENABLED
from task_identity_link import SOURCE_MANUAL, TaskIdentityLinkStore
from task_lifecycle import TaskLifecycleService
from task_store import TASK_STATUS_CANCELLED, TASK_STATUS_DONE, TASK_STATUS_OPEN, TaskStore, TaskTransitionResult
from task_target_resolver import SELECTOR_EXACT_TITLE as RESOLVER_EXACT, TaskTargetSelector
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import TopicSidepath, is_topic_engine_enabled, reset_sidepath

CID = "conv_action01"
CID_B = "conv_action02"
CHAT = "项目群A"
CHAT_B = "项目群B"
BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p9g4"
ACTOR = "wxid_a"
ACTOR_B = "wxid_b"
CONV_A = {
    "id": CID,
    "platform": "WECHAT",
    "platform_conversation_id": "room_a@chatroom",
    "conversation_type": "GROUP",
    "display_name": CHAT,
    "enabled": True,
}
CONV_B = {
    "id": CID_B,
    "platform": "WECHAT",
    "platform_conversation_id": "room_b@chatroom",
    "conversation_type": "GROUP",
    "display_name": CHAT_B,
    "enabled": True,
}
Q_OPEN = "\u201c"
Q_CLOSE = "\u201d"


def _task(task_id, status=TASK_STATUS_OPEN, title="接口联调", assignee="李明", conversation_id=CID):
    return {
        "id": task_id,
        "conversation_id": conversation_id,
        "topic_id": "topic_action1",
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


def _tasks_path(root, conversation_id=CID):
    return os.path.join(root, "data", "task_store", "conversations", conversation_id, "tasks.json")


def _dump_tasks(root, rows, conversation_id=CID):
    path = _tasks_path(root, conversation_id)
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


class ParserTests(unittest.TestCase):
    def test_command_01_exact_title(self):
        intent = parse_task_command("把接口联调这个任务标记为完成")
        self.assertEqual(intent.status, COMMAND)
        self.assertEqual(intent.action_type, PARSED_COMPLETE)
        self.assertEqual(intent.selector_type, SELECTOR_EXACT_TITLE)
        self.assertEqual(intent.title, "接口联调")

    def test_command_02_polite_prefixes(self):
        for text in ("请把接口联调这个任务标记为完成", "帮我把接口联调这个任务标记为完成"):
            intent = parse_task_command(text)
            self.assertEqual(intent.status, COMMAND, text)
            self.assertEqual(intent.action_type, PARSED_COMPLETE)
            self.assertEqual(intent.title, "接口联调")

    def test_command_03_colon(self):
        for text in ("完成任务：接口联调", "请完成任务：接口联调"):
            intent = parse_task_command(text)
            self.assertEqual(intent.status, COMMAND, text)
            self.assertEqual(intent.title, "接口联调")

    def test_command_04_outer_quotes(self):
        samples = (
            ("把\u300c接口联调\u300d这个任务标记为完成", "接口联调"),
            ("把%s接口联调%s这个任务标记为完成" % (Q_OPEN, Q_CLOSE), "接口联调"),
            ("完成任务：\u300c接口联调\u300d", "接口联调"),
            ("把\u300c 接口联调 \u300d这个任务标记为完成", "接口联调"),
        )
        for text, title in samples:
            intent = parse_task_command(text)
            self.assertEqual(intent.status, COMMAND, text)
            self.assertEqual(intent.title, title)
            self.assertEqual(intent.selector_type, SELECTOR_EXACT_TITLE)

    def test_command_05_statements_are_not_commands(self):
        for text in ("接口联调今天已经完成了", "接口联调完成了", "王强说接口联调完成了", "接口联调差不多做完了", "接口联调应该完成了"):
            self.assertEqual(parse_task_command(text).status, NOT_COMMAND, text)

    def test_command_06_queries_are_not_commands(self):
        for text in ("接口联调完成了吗？", "现在有哪些任务？"):
            self.assertEqual(parse_task_command(text).status, NOT_COMMAND, text)

    def test_narrow_colloquial_forms_stay_unparsed(self):
        for text in ("帮我完成接口联调", "接口联调给我完成一下", "把接口联调做完", "接口联调结束掉", "请帮我把接口联调这个任务标记为完成"):
            self.assertEqual(parse_task_command(text).status, NOT_COMMAND, text)

    def test_slash_and_generic_confirmation_words(self):
        self.assertEqual(parse_task_command("/总结").status, NOT_COMMAND)
        for text in ("确认", "是", "好的", "可以", "执行", "确定", "嗯", "OK", "确认完成。"):
            self.assertNotEqual(parse_task_command(text).status, COMMAND, text)

    def test_deictic_and_index_are_unsupported(self):
        for text in ("把这个任务标记为完成", "完成这个任务", "把刚才那个任务完成", "完成第一个任务", "完成任务1", "把第2个任务完成"):
            self.assertEqual(parse_task_command(text).status, UNSUPPORTED, text)

    def test_parser_source_has_no_side_effects(self):
        source = _read_text(os.path.join(ROOT, "task_command_parser.py"))
        for token in (
            "LLM",
            "Extractor",
            "TaskStore",
            "BusinessActionService",
            "TaskLifecycleService",
            "send_reply",
            "openai",
            "difflib",
            "pinyin",
            "SendMsg",
        ):
            self.assertNotIn(token, source)


class FakeMsg:
    def __init__(self, content, **kwargs):
        self.type = "text"
        self.mtype = "text"
        self.content = content
        self.sender = kwargs.get("sender", "李明")
        self.attr = "friend"
        self.sender_id = kwargs.get("sender_id", 88)
        self.sender_wxid = kwargs.get("sender_wxid", ACTOR)
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
        self.logger = logging.getLogger("test_p9g4")
        self.user_names = [CHAT, CHAT_B]
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
        raise AssertionError("task command must not call chat")


class ConversationTests(unittest.TestCase):
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
        self.store = TaskStore(self.root)

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

    def _listen(self, content, pid, sender_wxid=ACTOR, sender="李明", who=CHAT, wxid="room_a@chatroom"):
        message_listener(
            FakeMsg(content, platform_message_id=pid, sender_wxid=sender_wxid, sender=sender),
            FakeChat(who, wxid),
        )

    def _at(self, text):
        return "@%s %s" % (BOT_NAME, text)

    def _dump(self, rows, conversation_id=CID):
        path = _dump_tasks(self.root, rows, conversation_id)
        people = IdentityStore(self.root)
        if people.get_person("person_001") is None:
            people.create_person("person_001", "李明")
        if not any(item.get("wxid") == ACTOR for item in people.list_bindings()):
            people.bind_wechat(ACTOR, "person_001", display_name="李明")
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        for task in rows:
            task_id = str(task.get("id") or "")
            if task_id and links.find_link(conversation_id, task_id) is None:
                links.link_task_to_person(conversation_id, task_id, "person_001", source=SOURCE_MANUAL)
        return path

    def _prepare_direct(self, title="接口联调", message_id="msg_direct", actor=ACTOR, conversation_id=CID):
        service = BusinessActionService(self.root)
        return service.prepare_action(
            ActionRequest(
                ACTION_COMPLETE_TASK,
                conversation_id,
                message_id,
                actor,
                TaskTargetSelector(RESOLVER_EXACT, title=title),
            )
        )

    def _actions(self):
        return BusinessActionStore(self.root).list_actions()

    def _count_writes(self, call):
        path = _tasks_path(self.root)
        before = _read_bytes(path) if os.path.isfile(path) else None
        complete_calls = []
        transition_calls = []
        original_complete = TaskLifecycleService.complete_task
        original_transition = TaskStore.transition_task_status

        def complete(service, conversation_id, task_id):
            complete_calls.append((conversation_id, task_id))
            return original_complete(service, conversation_id, task_id)

        def transition(store, *args, **kwargs):
            transition_calls.append(args)
            return original_transition(store, *args, **kwargs)

        with patch.object(TaskLifecycleService, "complete_task", complete):
            with patch.object(TaskStore, "transition_task_status", transition):
                call()
        after = _read_bytes(path) if os.path.isfile(path) else None
        return complete_calls, transition_calls, before, after

    def test_command_07_current_task_guidance(self):
        path = self._dump([_task("task_a")])
        before = _read_bytes(path)
        with patch("task_target_resolver.TaskTargetResolver.resolve_task_target") as resolve:
            with patch("business_action.BusinessActionService.prepare_action") as prepare:
                complete_calls, transition_calls, _before, after = self._count_writes(
                    lambda: self._listen(self._at("把这个任务标记为完成"), "c07")
                )
        self.assertEqual(resolve.call_count, 0)
        self.assertEqual(prepare.call_count, 0)
        self.assertEqual(complete_calls, [])
        self.assertEqual(transition_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self.host.handled, [])
        self.assertIn("请明确任务标题", self.host.sent[0])
        self.assertIn("把接口联调这个任务标记为完成", self.host.sent[0])

    def test_command_08_preview_does_not_write_task(self):
        path = self._dump([_task("task_a")])
        processed = os.path.join(os.path.dirname(path), "processed.json")
        with open(processed, "wb") as handle:
            handle.write(b'{"items":[]}\n')
        processed_before = _read_bytes(processed)
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            complete_calls, transition_calls, before, after = self._count_writes(
                lambda: self._listen(self._at("把接口联调这个任务标记为完成"), "c08", sender="窗口名不能当账号")
            )
        enqueued.assert_not_called()
        self.assertEqual(complete_calls, [])
        self.assertEqual(transition_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(_read_bytes(processed), processed_before)
        rows = self._actions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], PREPARED)
        self.assertEqual(rows[0]["actor_ref"], ACTOR)
        self.assertEqual(rows[0]["target_task_id"], "task_a")
        self.assertNotIn("窗口名不能当账号", rows[0]["actor_ref"])
        reply = self.host.sent[0]
        self.assertIn("将执行以下操作：", reply)
        self.assertIn("操作：完成任务", reply)
        self.assertIn("任务：接口联调", reply)
        self.assertIn("当前状态：OPEN", reply)
        self.assertIn("目标状态：DONE", reply)
        self.assertIn("确认完成", reply)
        self.assertNotIn("task_a", reply)
        prepared = [row for row in read_business_action_audit(self.root) if row["event"] == EVENT_PREPARED]
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["actor_ref"], ACTOR)
        self.assertEqual(CALLS.calls, 0)

    def test_command_09_confirm_same_actor_and_conversation(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c09a")
        self._listen(self._at("确认完成"), "c09b")
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertEqual(self._actions()[0]["state"], "EXECUTED")
        self.assertEqual(self._actions()[0]["actor_ref"], ACTOR)
        self.assertIn("任务已完成。", self.host.sent[-1])
        self.assertIn("任务：接口联调", self.host.sent[-1])
        self.assertIn("状态：DONE", self.host.sent[-1])
        self.assertNotIn("task_a", self.host.sent[-1])
        events = [row["event"] for row in read_business_action_audit(self.root)]
        self.assertIn(EVENT_PREPARED, events)
        self.assertIn(EVENT_CONFIRM_REQUESTED, events)
        self.assertIn(EVENT_EXECUTED, events)
        self.assertEqual(self.host.handled, [])

    def test_command_10_other_actor_cannot_confirm(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c10a")
        complete_calls, transition_calls, before, after = self._count_writes(
            lambda: self._listen(self._at("确认完成"), "c10b", sender_wxid=ACTOR_B, sender="王强")
        )
        self.assertEqual(complete_calls, [])
        self.assertEqual(transition_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self._actions()[0]["state"], PREPARED)
        self.assertEqual(self._actions()[0]["actor_ref"], ACTOR)
        self.assertIn("当前没有待确认的任务完成操作。", self.host.sent[-1])

    def test_command_11_cross_conversation_cannot_confirm(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c11a")
        complete_calls, _transitions, before, after = self._count_writes(
            lambda: self._listen(self._at("确认完成"), "c11b", who=CHAT_B, wxid="room_b@chatroom")
        )
        self.assertEqual(complete_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self._actions()[0]["state"], PREPARED)
        self.assertEqual(self._actions()[0]["conversation_id"], CID)
        self.assertIn("当前没有待确认的任务完成操作。", self.host.sent[-1])

    def test_command_12_confirm_without_pending(self):
        self._dump([_task("task_a")])
        complete_calls, _transitions, before, after = self._count_writes(
            lambda: self._listen(self._at("确认完成"), "c12")
        )
        self.assertEqual(complete_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self._actions(), [])
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.sent, ["当前没有待确认的任务完成操作。"])

    def test_multiple_pending_is_not_guessed(self):
        self._dump([_task("task_a", title="接口联调"), _task("task_b", title="补充材料")])
        self._prepare_direct("接口联调", "msg_multi_a")
        self._prepare_direct("补充材料", "msg_multi_b")
        complete_calls, _transitions, before, after = self._count_writes(
            lambda: self._listen(self._at("确认完成"), "c-multi")
        )
        self.assertEqual(complete_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self.store.get_task(CID, "task_b")["status"], TASK_STATUS_OPEN)
        states = sorted(item["state"] for item in self._actions())
        self.assertEqual(states, [PREPARED, PREPARED])
        self.assertIn("当前存在多个待确认的任务操作", self.host.sent[-1])

    def test_command_13_new_command_while_pending(self):
        self._dump([_task("task_a", title="接口联调"), _task("task_b", title="补充材料")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c13a")
        self.assertEqual(len(self._actions()), 1)
        with patch("business_action.BusinessActionService.prepare_action") as prepare:
            self._listen(self._at("把补充材料这个任务标记为完成"), "c13b")
        self.assertEqual(prepare.call_count, 0)
        self.assertEqual(len(self._actions()), 1)
        self.assertEqual(self._actions()[0]["target_task_id"], "task_a")
        self.assertEqual(self.store.get_task(CID, "task_b")["status"], TASK_STATUS_OPEN)
        self.assertIn("你当前还有一项任务完成操作等待确认。", self.host.sent[-1])

    def test_command_14_expired_confirmation(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c14a")
        path = actions_path(self.root)
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        for item in data["actions"].values():
            item["created_at"] = "2020-01-01T00:00:00Z"
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.write("\n")
        complete_calls, _transitions, before, after = self._count_writes(
            lambda: self._listen(self._at("确认完成"), "c14b")
        )
        self.assertEqual(complete_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self._actions()[0]["state"], PREPARED)
        self.assertIn("该任务操作的确认已超时，请重新发起。", self.host.sent[-1])
        self._dump([_task("task_a"), _task("task_b", title="补充材料")])
        self._listen(self._at("把补充材料这个任务标记为完成"), "c14c")
        titles = sorted(item["target_task_id"] for item in self._actions() if item["state"] == PREPARED)
        self.assertEqual(titles, ["task_a", "task_b"])

    def test_command_15_already_done_has_no_pending(self):
        self._dump([_task("task_a", status=TASK_STATUS_DONE)])
        self._listen(self._at("完成任务：接口联调"), "c15")
        self.assertEqual(self._actions(), [])
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertIn("该任务已经是完成状态，无需再次操作。", self.host.sent[0])
        self.assertIn("状态：DONE", self.host.sent[0])
        self.assertNotIn("将执行以下操作", self.host.sent[0])

    def test_command_16_ambiguous_title(self):
        path = self._dump([
            _task("task_a", status=TASK_STATUS_OPEN, title="接口联调", assignee="李明"),
            _task("task_b", status=TASK_STATUS_DONE, title="接口联调", assignee="王强"),
        ])
        before = _read_bytes(path)
        self._listen(self._at("把接口联调这个任务标记为完成"), "c16")
        self.assertEqual(_read_bytes(path), before)
        self.assertEqual(self._actions(), [])
        reply = self.host.sent[0]
        self.assertIn("当前找到多个同名任务", reply)
        self.assertIn("接口联调｜状态：OPEN｜负责人：李明", reply)
        self.assertIn("接口联调｜状态：DONE｜负责人：王强", reply)
        self.assertIn("当前不会自动选择其中一条。", reply)
        self.assertNotIn("task_a", reply)
        self.assertNotIn("task_b", reply)

    def test_command_17_not_found(self):
        self._dump([_task("task_a", title="补充材料")])
        complete_calls, _transitions, before, after = self._count_writes(
            lambda: self._listen(self._at("把接口联调这个任务标记为完成"), "c17")
        )
        self.assertEqual(complete_calls, [])
        self.assertEqual(after, before)
        self.assertEqual(self._actions(), [])
        self.assertIn("当前会话中未找到标题完全等于%s接口联调%s的任务。" % (Q_OPEN, Q_CLOSE), self.host.sent[0])

    def test_command_18_missing_sender_wxid(self):
        self._dump([_task("task_a")])
        with patch("business_action.BusinessActionService.prepare_action") as prepare:
            with patch("task_target_resolver.TaskTargetResolver.resolve_task_target") as resolve:
                self._listen(self._at("把接口联调这个任务标记为完成"), "c18", sender_wxid="", sender="李明")
        self.assertEqual(prepare.call_count, 0)
        self.assertEqual(resolve.call_count, 0)
        self.assertEqual(self._actions(), [])
        self.assertEqual(self.host.sent, ["当前无法确定你的账号身份，因此不能执行任务修改操作。"])

    def test_command_19_second_confirmation_does_not_repeat_lifecycle(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c19a")
        calls = []
        original = TaskLifecycleService.complete_task

        def wrapped(service, conversation_id, task_id):
            calls.append(task_id)
            return original(service, conversation_id, task_id)

        with patch.object(TaskLifecycleService, "complete_task", wrapped):
            self._listen(self._at("确认完成"), "c19b")
            self._listen(self._at("确认完成"), "c19c")
        self.assertEqual(calls, ["task_a"])
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertIn("当前没有待确认的任务完成操作。", self.host.sent[-1])

    def test_command_20_busy_session_keeps_preview_pending(self):
        path = self._dump([_task("task_a")])
        before = _read_bytes(path)
        self.assertTrue(self.runtime.try_acquire_session(CHAT))
        complete_calls = []
        original = TaskLifecycleService.complete_task

        def wrapped(service, conversation_id, task_id):
            complete_calls.append(task_id)
            return original(service, conversation_id, task_id)

        with patch.object(TaskLifecycleService, "complete_task", wrapped):
            self._listen(self._at("把接口联调这个任务标记为完成"), "c20")
            self.assertEqual(self.host.sent, [])
            self.assertEqual(pending_count(self.runtime, CHAT), 1)
            self.assertEqual(self._actions()[0]["state"], PREPARED)
            self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
            self.runtime.release_session(CHAT)
            notify_session_released(self.runtime, CHAT)
        self.assertEqual(complete_calls, [])
        self.assertEqual(_read_bytes(path), before)
        self.assertIn("将执行以下操作：", self.host.sent[0])
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_command_21_busy_session_keeps_result(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c21a")
        self.assertTrue(self.runtime.try_acquire_session(CHAT))
        self._listen(self._at("确认完成"), "c21b")
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        self.assertEqual(len(self.host.sent), 1)
        self.assertEqual(pending_count(self.runtime, CHAT), 1)
        self.runtime.release_session(CHAT)
        notify_session_released(self.runtime, CHAT)
        self.assertIn("任务已完成。", self.host.sent[-1])
        self.assertEqual(pending_count(self.runtime, CHAT), 0)

    def test_command_22_stop_does_not_confirm(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c22a")
        self.runtime.begin_graceful_stop("command-22")
        with patch("business_action.BusinessActionService.confirm_action") as confirm:
            self._listen(self._at("确认完成"), "c22b")
        self.assertEqual(confirm.call_count, 0)
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("将执行以下操作：", self.host.sent[0])
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self._actions()[0]["state"], PREPARED)

    def test_emergency_stop_drops_confirmation(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c-stop-a")
        self.runtime.activate_emergency("command-emergency")
        with patch("business_action.BusinessActionService.confirm_action") as confirm:
            self._listen(self._at("确认完成"), "c-stop-b")
        self.assertEqual(confirm.call_count, 0)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self._actions()[0]["state"], PREPARED)

    def test_generic_acknowledgements_do_not_confirm(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c-ack-0")
        for index, word in enumerate(("确认", "是", "好的", "可以", "执行", "确定", "嗯", "OK")):
            self._listen(self._at(word), "c-ack-%s" % index)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self._actions()[0]["state"], PREPARED)
        self.assertTrue(all("任务已完成" not in item for item in self.host.sent))

    def test_generic_commands_keep_p8_reply(self):
        self._dump([_task("task_a")])
        for index, text in enumerate(("新建任务", "关闭风险", "修改决定", "删除任务", "帮我把任务改成完成")):
            self.host.sent.clear()
            self._listen(self._at(text), "c-generic-%s" % index)
            self.assertEqual(self.host.sent, [COMMAND_REPLY], text)
        self.assertEqual(self._actions(), [])
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_statements_and_queries_do_not_prepare(self):
        path = self._dump([_task("task_a")])
        before = _read_bytes(path)
        for index, text in enumerate(("接口联调今天已经完成了", "接口联调完成了", "王强说接口联调完成了", "接口联调完成了吗？")):
            self._listen(self._at(text), "c-talk-%s" % index)
        self._listen(self._at("现在有哪些任务？"), "c-talk-query")
        self.assertEqual(_read_bytes(path), before)
        self.assertEqual(self._actions(), [])
        self.assertTrue(self.host.handled)
        self.assertTrue(any("接口联调" in item or "任务" in item for item in self.host.sent))
        self.assertFalse(any("将执行以下操作" in item for item in self.host.sent))

    def test_unresolved_conversation_does_not_prepare(self):
        self._dump([_task("task_a")])
        self.host.conversations = []
        with patch("business_action.BusinessActionService.prepare_action") as prepare:
            self._listen(self._at("把接口联调这个任务标记为完成"), "c-noconv")
        self.assertEqual(prepare.call_count, 0)
        self.assertEqual(self._actions(), [])
        self.assertEqual(self.host.sent, ["当前无法确定会话范围，因此不能执行该操作。"])

    def test_slash_command_is_not_handled_here(self):
        self._dump([_task("task_a")])
        with patch("business_action.BusinessActionService.prepare_action") as prepare:
            self._listen(self._at("/总结"), "c-slash")
        self.assertEqual(prepare.call_count, 0)
        self.assertEqual(self._actions(), [])
        self.assertTrue(self.host.handled)

    def test_identity_link_unchanged_and_queries_show_done(self):
        self._dump([_task("task_a", assignee="李明")])
        people = IdentityStore(self.root)
        people.add_alias("李明", "person_001")
        links = TaskIdentityLinkStore(self.root, task_store=self.store, identity_store=people)
        blob = _read_bytes(links.links_path())
        self._listen(self._at("把接口联调这个任务标记为完成"), "c-link-a")
        self._listen(self._at("确认完成"), "c-link-b")
        self.assertEqual(_read_bytes(links.links_path()), blob)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_DONE)
        service = build_query_service(self.root)
        for query_type in (LIST_TASKS, MY_TASKS, TASKS_BY_ASSIGNEE):
            result = service.execute(QueryRequest(CID, "q-" + query_type, ACTOR, query_type, person_id="person_001"))
            text = format_query_result(result)
            self.assertIn("接口联调", text, query_type)
            self.assertIn("状态：DONE", text, query_type)

    def test_confirm_noop_stale_missing_and_persist(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c-noop-a")
        self.store.transition_task_status(CID, "task_a", TASK_STATUS_OPEN, TASK_STATUS_DONE)
        self._listen(self._at("确认完成"), "c-noop-b")
        self.assertIn("该任务已经是完成状态，无需重复操作。", self.host.sent[-1])
        self.assertNotIn("再次完成成功", self.host.sent[-1])

        self._dump([_task("task_b", title="补充材料")])
        self._listen(self._at("把补充材料这个任务标记为完成"), "c-stale-a")
        self._dump([_task("task_b", status=TASK_STATUS_CANCELLED, title="补充材料")])
        self._listen(self._at("确认完成"), "c-stale-b")
        self.assertIn("任务状态已经发生变化，本次没有执行完成操作。", self.host.sent[-1])

        self._dump([_task("task_c", title="回归用例")])
        self._listen(self._at("把回归用例这个任务标记为完成"), "c-miss-a")
        self._dump([])
        self._listen(self._at("确认完成"), "c-miss-b")
        self.assertIn("目标任务当前已不存在，本次操作未执行。", self.host.sent[-1])

        self._dump([_task("task_d", title="写入失败样例")])
        self._listen(self._at("把写入失败样例这个任务标记为完成"), "c-write-a")

        def failed(self, conversation_id, task_id):
            return TaskTransitionResult("WRITE_FAILED", conversation_id, task_id, TASK_STATUS_OPEN, TASK_STATUS_DONE, None)

        with patch.object(TaskLifecycleService, "complete_task", failed):
            self._listen(self._at("确认完成"), "c-write-b")
        self.assertIn("本次任务完成操作未能安全写入，请稍后重新发起。", self.host.sent[-1])
        self.assertEqual(self.store.get_task(CID, "task_d")["status"], TASK_STATUS_OPEN)

        self._dump([_task("task_e", title="记录收口")])
        self._listen(self._at("把记录收口这个任务标记为完成"), "c-persist-a")

        def broken(path, data):
            raise OSError("disk")

        with patch("business_action_store._replace_json_unlocked", broken):
            self._listen(self._at("确认完成"), "c-persist-b")
        reply = self.host.sent[-1]
        self.assertIn("任务状态可能已经更新，但操作记录暂未成功收口。", reply)
        self.assertNotIn("任务完成失败", reply)

    def test_find_prepared_actions_is_readonly(self):
        self._dump([_task("task_a")])
        prepared = self._prepare_direct()
        path = actions_path(self.root)
        before = _read_bytes(path)
        found = BusinessActionStore(self.root).find_prepared_actions(CID, ACTOR, ACTION_COMPLETE_TASK)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["action_id"], prepared.action_id)
        self.assertEqual(_read_bytes(path), before)
        self.assertEqual(BusinessActionStore(self.root).get_action(prepared.action_id)["state"], PREPARED)
        self.assertEqual(BusinessActionStore(self.root).find_prepared_actions(CID_B, ACTOR, ACTION_COMPLETE_TASK), [])
        self.assertEqual(BusinessActionStore(self.root).find_prepared_actions(CID, ACTOR_B, ACTION_COMPLETE_TASK), [])

    def test_same_platform_message_does_not_create_a_second_action(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把接口联调这个任务标记为完成"), "c-dup")
        self._listen(self._at("把接口联调这个任务标记为完成"), "c-dup")
        self.assertEqual(len(self._actions()), 1)
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)

    def test_listener_orders_task_command_before_generic_route(self):
        source = inspect.getsource(message_listener)
        admit = source.split("STEP_ADMIT", 1)[1]
        before_reply = admit.split('verdict.get("action") != REPLY', 1)[0]
        self.assertLess(before_reply.find("evaluate_inbound"), before_reply.find("handle_task_command_turn"))
        self.assertLess(before_reply.find("handle_task_command_turn"), before_reply.find("handle_collaboration_route"))
        self.assertLess(before_reply.find("handle_collaboration_route"), before_reply.find("try_enqueue_topic_sidepath"))
        listener = _read_text(os.path.join(ROOT, "message", "listener.py"))
        self.assertNotIn("business_action", listener)
        conversation = _read_text(os.path.join(ROOT, "business_action_conversation.py"))
        for token in ("update_task", "transition_task_status", "complete_task", "SendMsg", "TaskEngine", "Extractor"):
            self.assertNotIn(token, conversation)
        self.assertIn("confirm_action", conversation)
        self.assertIn("prepare_action", conversation)
        self.assertIn("offer_agent_reply", conversation)

    def test_quoted_command_reaches_exact_title(self):
        self._dump([_task("task_a")])
        self._listen(self._at("把\u300c接口联调\u300d这个任务标记为完成"), "c-quote")
        self.assertEqual(self._actions()[0]["target_task_id"], "task_a")
        self.assertEqual(self.store.get_task(CID, "task_a")["status"], TASK_STATUS_OPEN)
        self.assertIn("任务：接口联调", self.host.sent[0])


if __name__ == "__main__":
    unittest.main()
