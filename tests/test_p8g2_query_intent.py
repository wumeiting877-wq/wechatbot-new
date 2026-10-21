# -*- coding: utf-8 -*-
"""P8-G2 Hybrid Query Intent。生产路由测试全部使用 Fake Completer，不连接真实模型。"""

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

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from collaboration_query import handle_collaboration_route
from decision_engine import DECISION_ENGINE_ENABLED
from llm_client import call_narrow_completion
from message.bind import bind_host
from message.listener import message_listener
from query_formatter import (
    ASSIGNEE_TASK_QUERY_REPLY,
    CLASSIFIER_FAILURE_REPLY,
    COMMAND_REPLY,
    OUT_OF_SCOPE_REPLY,
    SELF_TASK_QUERY_REPLY,
)
from query_intent_classifier import (
    CALLS,
    CLASSIFIER_TIMEOUT_SEC,
    SYSTEM_PROMPT,
    classify,
    parse_query_type,
    reset_completer,
    use_completer,
)
from query_router import (
    KIND_NOT_QUERY,
    LIST_DECISIONS,
    LIST_TASKS,
    LIST_TOPICS,
    OPEN_RISKS,
    ROUTE_CLASSIFIER_FAILURE,
    ROUTE_NOT_QUERY,
    ROUTE_OUT_OF_SCOPE,
    ROUTE_QUERY,
    ROUTE_UNSUPPORTED_IDENTITY,
    TOPIC_SUMMARY,
    classify_agent_message,
    looks_like_query_candidate,
    route_hybrid,
)
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
CONV_B = {
    "id": "conv_b",
    "platform": "WECHAT",
    "platform_conversation_id": "room_b@chatroom",
    "conversation_type": "GROUP",
    "display_name": "项目群B",
    "enabled": True,
}
BOT_NAME = "智群Agent"
BOT_WXID = "wxid_bot_p8g2"

STUB = {
    "帮我盘一下现在手上的待办": LIST_TASKS,
    "我们主要有哪些潜在问题需要注意": OPEN_RISKS,
    "我们现在主要卡在哪些风险点": OPEN_RISKS,
    "之前到底定下来了哪些事情": LIST_DECISIONS,
    "之前讨论最终定下来的事情有哪些": LIST_DECISIONS,
    "这个群现在主要在推进哪些事情": LIST_TOPICS,
    "现在这个群主要在推进哪几个事情": LIST_TOPICS,
    "帮我看看当前主题整体怎么样": TOPIC_SUMMARY,
    "帮我看一下当前主题的整体情况": TOPIC_SUMMARY,
    "任务怎么样了": "NOT_QUERY",
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
    def __init__(self, who="项目群A", wxid="room_a@chatroom"):
        self.who = who
        self._wxid = wxid


class FakeHost:
    def __init__(self, runtime, root_dir):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p8g2")
        self.user_names = ["项目群A", "项目群B", "李明"]
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


def _stub_completer(messages):
    user = messages[-1]["content"]
    if user not in STUB:
        raise AssertionError("unexpected classifier text: %s" % user)
    payload = {"query_type": STUB[user]}
    if user == "帮我盘一下现在手上的待办":
        payload["answer"] = "任务A"
    return json.dumps(payload, ensure_ascii=False)


def _dump(root, store_name, cid, filename, key, rows):
    path = os.path.join(root, "data", store_name, "conversations", cid, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({key: rows}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def _write_bytes(root, relative, payload):
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


def _snapshot(root):
    found = {}
    data = os.path.join(root, "data")
    for dirpath, _dirnames, filenames in os.walk(data):
        for name in filenames:
            if name in ("topics.json", "tasks.json", "decisions.json", "risks.json", "processed.json", "links.json"):
                path = os.path.join(dirpath, name)
                with open(path, "rb") as handle:
                    found[path] = handle.read()
    return found


def _topic(cid, topic_id, title):
    return {
        "id": topic_id,
        "conversation_id": cid,
        "title": title,
        "summary": "正在对齐回调字段",
        "status": "ACTIVE",
        "message_count": 2,
        "last_message_at": "2026-09-01T00:00:00Z",
        "created_at": "2026-09-01T00:00:00Z",
        "confidence": "HIGH",
        "schema_version": 1,
    }


def _task(cid, task_id, topic_id, title):
    return {
        "id": task_id,
        "conversation_id": cid,
        "topic_id": topic_id,
        "title": title,
        "description": "",
        "status": "OPEN",
        "assignee_text": "李明",
        "due_text": "",
        "created_msg_id": "m1",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


class _RouteCase(unittest.TestCase):
    def setUp(self):
        CALLS.calls = 0
        reset_completer()

    def tearDown(self):
        reset_completer()
        CALLS.calls = 0
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)


class CandidateGateTests(_RouteCase):
    def test_statements_and_greetings_are_not_candidates(self):
        for text in (
            "今天必须完成接口联调",
            "测试环境目前有风险",
            "测试环境现在有风险",
            "我们决定周五上线",
            "这个主题今天继续讨论",
            "李明负责补材料",
            "你好",
            "在吗",
            "谢谢",
            "好的",
            "收到",
            "风险呢",
            "决定呢",
        ):
            self.assertFalse(looks_like_query_candidate(text), text)

    def test_natural_queries_are_candidates(self):
        for text in STUB:
            self.assertTrue(looks_like_query_candidate(text), text)
        self.assertTrue(looks_like_query_candidate("任务怎么样了"))


class HybridRouteTests(_RouteCase):
    def test_intent_01_to_03_rules_skip_classifier(self):
        def boom(_messages):
            raise AssertionError("classifier")

        with use_completer(boom):
            tasks = route_hybrid("现在有哪些任务")
            risks = route_hybrid("目前有哪些风险")
            decisions = route_hybrid("有哪些决定")
            recent = route_hybrid("刚才确定了什么")
        self.assertEqual(tasks.query_type, LIST_TASKS)
        self.assertEqual(risks.query_type, OPEN_RISKS)
        self.assertEqual(decisions.query_type, LIST_DECISIONS)
        self.assertEqual(recent.query_type, LIST_DECISIONS)
        for result in (tasks, risks, decisions, recent):
            self.assertEqual(result.route, ROUTE_QUERY)
            self.assertFalse(result.classifier_used)
        self.assertEqual(CALLS.calls, 0)

    def test_intent_04_to_08_classifier_fallback(self):
        expected = {
            "帮我盘一下现在手上的待办": LIST_TASKS,
            "我们主要有哪些潜在问题需要注意": OPEN_RISKS,
            "之前到底定下来了哪些事情": LIST_DECISIONS,
            "这个群现在主要在推进哪些事情": LIST_TOPICS,
            "帮我看看当前主题整体怎么样": TOPIC_SUMMARY,
        }
        with use_completer(_stub_completer):
            for text, query_type in expected.items():
                CALLS.calls = 0
                result = route_hybrid(text)
                self.assertEqual(result.route, ROUTE_QUERY, text)
                self.assertEqual(result.query_type, query_type, text)
                self.assertTrue(result.classifier_used, text)
                self.assertEqual(result.classifier_status, "OK", text)
                self.assertEqual(result.topic_title, "", text)
                self.assertEqual(CALLS.calls, 1, text)

    def test_intent_09_to_11_discussion_stays_not_query(self):
        def boom(_messages):
            raise AssertionError("classifier")

        with use_completer(boom):
            for text in (
                "今天必须完成接口联调",
                "测试环境目前有风险",
                "我们决定周五上线",
                "你好",
                "在吗",
                "谢谢",
                "好的",
                "收到",
            ):
                result = route_hybrid(text)
                self.assertEqual(result.route, ROUTE_NOT_QUERY, text)
                self.assertFalse(result.classifier_used, text)
        self.assertEqual(CALLS.calls, 0)

    def test_intent_12_to_15_safety_before_classifier(self):
        def boom(_messages):
            raise AssertionError("classifier")

        with use_completer(boom):
            scope = route_hybrid("帮我看看另一个群有哪些任务")
            mine = route_hybrid("我有什么任务")
            mine_short = route_hybrid("我的任务")
            person = route_hybrid("张三负责什么")
            person_tasks = route_hybrid("张三有哪些任务")
            command = route_hybrid("帮我创建一个任务")
            delete = route_hybrid("删除这个任务")
            statement = route_hybrid("李明负责补材料")
        self.assertEqual(scope.route, ROUTE_OUT_OF_SCOPE)
        self.assertEqual(mine.route, ROUTE_UNSUPPORTED_IDENTITY)
        self.assertEqual(mine.identity_scope, "self")
        self.assertEqual(mine_short.identity_scope, "self")
        self.assertEqual(person.route, ROUTE_UNSUPPORTED_IDENTITY)
        self.assertEqual(person.identity_scope, "assignee")
        self.assertEqual(person_tasks.identity_scope, "assignee")
        self.assertEqual(command.route, "COMMAND")
        self.assertEqual(delete.route, "COMMAND")
        self.assertEqual(statement.route, ROUTE_NOT_QUERY)
        for result in (scope, mine, mine_short, person, person_tasks, command, delete, statement):
            self.assertFalse(result.classifier_used)
        self.assertEqual(CALLS.calls, 0)
        self.assertEqual(classify_agent_message("我有什么任务").kind, KIND_NOT_QUERY)

    def test_ambiguous_sample_can_reach_classifier_and_fall_through(self):
        with use_completer(_stub_completer):
            result = route_hybrid("任务怎么样了")
        self.assertTrue(looks_like_query_candidate("任务怎么样了"))
        self.assertEqual(result.route, ROUTE_NOT_QUERY)
        self.assertTrue(result.classifier_used)
        self.assertEqual(result.classifier_status, "OK")
        self.assertFalse(looks_like_query_candidate("风险呢"))
        self.assertEqual(route_hybrid("风险呢").classifier_used, False)

    def test_slash_never_calls_classifier(self):
        def boom(_messages):
            raise AssertionError("classifier")

        with use_completer(boom):
            result = route_hybrid("/看看任务")
        self.assertEqual(result.route, ROUTE_NOT_QUERY)
        self.assertFalse(result.classifier_used)


class ParseFailureTests(_RouteCase):
    def _route(self, raw):
        def completer(_messages):
            return raw

        with use_completer(completer):
            return route_hybrid("帮我盘一下现在手上的待办")

    def test_classify_01_to_05(self):
        cases = [
            (lambda _messages: (_ for _ in ()).throw(TimeoutError("deadline")), "TIMEOUT"),
            (lambda _messages: (_ for _ in ()).throw(ConnectionError("connection reset")), "CONNECTION_ERROR"),
            (lambda _messages: "不是 JSON", "CLASSIFIER_INVALID"),
            (lambda _messages: '{"query_type":"MY_TASKS"}', "CLASSIFIER_INVALID"),
            (lambda _messages: "", "CLASSIFIER_INVALID"),
            (lambda _messages: '```json\n{"query_type":"LIST_TASKS"}\n```', "CLASSIFIER_INVALID"),
            (lambda _messages: "现在有这些任务：任务A", "CLASSIFIER_INVALID"),
        ]
        for completer, status in cases:
            CALLS.calls = 0
            with use_completer(completer):
                result = route_hybrid("帮我盘一下现在手上的待办")
            self.assertEqual(result.route, ROUTE_CLASSIFIER_FAILURE, status)
            self.assertEqual(result.classifier_status, status)
            self.assertTrue(result.classifier_used)
            self.assertEqual(result.query_type, "")
            self.assertEqual(CALLS.calls, 1)

    def test_parse_keeps_enum_and_rejects_illegal_output(self):
        self.assertEqual(
            parse_query_type('{"answer":"任务A","query_type":"LIST_TASKS"}'),
            LIST_TASKS,
        )
        for raw in (
            '{"query_type":"MY_TASKS"}',
            "",
            "不是 JSON",
            '```json\n{"query_type":"LIST_TASKS"}\n```',
            "现在有这些任务：任务A",
        ):
            with self.assertRaises(Exception):
                parse_query_type(raw)


class ListenerIntentTests(unittest.TestCase):
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
        _dump(self.root, "topic_store", "conv_a", "topics.json", "topics", [
            _topic("conv_a", "top_1", "接口联调"),
        ])
        _dump(self.root, "topic_store", "conv_b", "topics.json", "topics", [
            _topic("conv_b", "top_b", "项目B主题"),
        ])
        _dump(self.root, "task_store", "conv_a", "tasks.json", "tasks", [
            _task("conv_a", "task_1", "top_1", "完成接口联调"),
        ])
        _dump(self.root, "task_store", "conv_b", "tasks.json", "tasks", [
            _task("conv_b", "task_b", "top_b", "B的任务"),
        ])
        _write_bytes(self.root, os.path.join("data", "task_store", "conversations", "conv_a", "processed.json"), b'{"items":[]}\n')
        _write_bytes(self.root, os.path.join("data", "task_store", "conversations", "conv_a", "links.json"), b'{"links":[]}\n')
        self.before = _snapshot(self.root)
        self._completer = use_completer(_stub_completer)
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

    def _listen(self, content, pid):
        message_listener(FakeMsg(content, platform_message_id=pid), FakeChat())

    def test_classifier_list_tasks_reply_comes_from_store(self):
        before_calls = CALLS.calls
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            with patch("llm_client.get_deepseek_response", side_effect=AssertionError("chat")):
                self._listen("@智群Agent 帮我盘一下现在手上的待办", "i04")
        enqueued.assert_not_called()
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.deepseek_calls, [])
        self.assertEqual(self.host.chat_contexts, {})
        self.assertEqual(self.host.user_queues, {})
        self.assertEqual(self.host.memory_logs, [])
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertNotIn("任务A", self.host.sent[0])
        self.assertNotIn("B的任务", self.host.sent[0])
        self.assertEqual(_snapshot(self.root), self.before)
        self.assertGreater(CALLS.calls, before_calls)

    def test_classifier_failure_does_not_enter_sidepath_or_chat_or_service(self):
        def timeout(_messages):
            raise TimeoutError("deadline")

        with use_completer(timeout):
            with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
                with patch("collaboration_query.build_query_service", side_effect=AssertionError("service")):
                    self._listen("@智群Agent 帮我盘一下现在手上的待办", "c01")
        enqueued.assert_not_called()
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.sent, [CLASSIFIER_FAILURE_REPLY])
        self.assertEqual(_snapshot(self.root), self.before)
        self.assertNotIn("任务A", CLASSIFIER_FAILURE_REPLY)

    def test_remaining_failure_modes_stay_handled(self):
        samples = [
            ConnectionError("connection refused"),
            None,
        ]

        def connection(_messages):
            raise samples[0]

        def invalid(_messages):
            return "你好，任务A"

        for index, completer in enumerate((connection, invalid)):
            self.host.sent.clear()
            self.host.handled.clear()
            with use_completer(completer):
                with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
                    self._listen("@智群Agent 我们主要有哪些潜在问题需要注意", "bad-%s" % index)
            enqueued.assert_not_called()
            self.assertEqual(self.host.handled, [])
            self.assertEqual(self.host.sent, [CLASSIFIER_FAILURE_REPLY])
            self.assertNotIn("任务A", self.host.sent[0])

    def test_identity_and_command_replies_skip_classifier(self):
        before = CALLS.calls
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 我有什么任务", "id1")
            self._listen("@智群Agent 张三负责什么", "id2")
            self._listen("@智群Agent 帮我创建一个任务", "cmd")
        self.assertEqual(CALLS.calls, before)
        enqueued.assert_not_called()
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.sent[0], SELF_TASK_QUERY_REPLY)
        self.assertEqual(self.host.sent[1], ASSIGNEE_TASK_QUERY_REPLY)
        self.assertEqual(self.host.sent[2], COMMAND_REPLY)
        self.assertEqual(_snapshot(self.root), self.before)

    def test_out_of_scope_still_fixed_and_classifier_idle(self):
        before = CALLS.calls
        with patch("task_store.TaskStore.list_tasks", side_effect=AssertionError("tasks")):
            self._listen("@智群Agent 帮我看看另一个群有哪些任务", "scope")
        self.assertEqual(CALLS.calls, before)
        self.assertEqual(self.host.sent, [OUT_OF_SCOPE_REPLY])
        self.assertEqual(self.host.handled, [])

    def test_discussion_still_enters_sidepath(self):
        before = CALLS.calls
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 今天必须完成接口联调", "talk")
            self._listen("@智群Agent 李明负责补材料", "owner")
            self._listen("@智群Agent 你好", "hi")
        self.assertEqual(CALLS.calls, before)
        self.assertEqual(enqueued.call_count, 3)
        self.assertEqual(len(self.host.handled), 3)
        self.assertEqual(self.host.sent, [])

    def test_classifier_not_query_still_enters_sidepath(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 任务怎么样了", "amb")
        enqueued.assert_called_once()
        self.assertEqual(len(self.host.handled), 1)
        self.assertEqual(self.host.sent, [])
        self.assertGreater(CALLS.calls, 0)

    def test_topic_summary_does_not_use_classifier_title(self):
        def poisoned(_messages):
            return '{"query_type":"TOPIC_SUMMARY","topic_title":"伪造主题","answer":"任务A"}'

        with use_completer(poisoned):
            self._listen("@智群Agent 帮我看看当前主题整体怎么样", "sum")
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("主题：接口联调", self.host.sent[0])
        self.assertNotIn("伪造主题", self.host.sent[0])
        self.assertNotIn("任务A", self.host.sent[0])
        self.assertEqual(_snapshot(self.root), self.before)

    def test_topic_summary_ambiguous_when_two_topics(self):
        _dump(self.root, "topic_store", "conv_a", "topics.json", "topics", [
            _topic("conv_a", "top_1", "接口联调"),
            _topic("conv_a", "top_2", "验收准备"),
        ])
        self._listen("@智群Agent 帮我看看当前主题整体怎么样", "ambig")
        self.assertIn("当前会话有多个主题", self.host.sent[0])
        self.assertIn("接口联调", self.host.sent[0])
        self.assertIn("验收准备", self.host.sent[0])
        self.assertNotIn("伪造", self.host.sent[0])

    def test_stop_does_not_call_router_or_classifier(self):
        self.runtime.set_state("STOPPED", "test")
        with patch("collaboration_query.route_hybrid", side_effect=AssertionError("router")) as routed:
            with patch("collaboration_query.build_query_service", side_effect=AssertionError("service")):
                self._listen("@智群Agent 帮我盘一下现在手上的待办", "stop")
        routed.assert_not_called()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])

    def test_busy_session_consumes_classifier_query_without_chat(self):
        self.assertTrue(self.runtime.try_acquire_session("项目群A"))
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 帮我盘一下现在手上的待办", "busy")
        enqueued.assert_not_called()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])
        self.runtime.release_session("项目群A")

    def test_send_path_stays_on_send_reply(self):
        import collaboration_query
        source = inspect.getsource(collaboration_query)
        self.assertIn("send_reply", source)
        self.assertNotIn("SendMsg", source)
        self.assertIn("_send", inspect.getsource(handle_collaboration_route))


class CallPathTests(_RouteCase):
    def test_live_complete_uses_narrow_client_without_history(self):
        reset_completer()
        with patch("llm_client.call_narrow_completion", return_value='{"query_type":"OPEN_RISKS"}') as call:
            outcome = classify("我们主要有哪些潜在问题需要注意")
        self.assertEqual(outcome.query_type, OPEN_RISKS)
        messages = call.call_args.args[0]
        self.assertEqual([item["role"] for item in messages], ["system", "user"])
        self.assertEqual(messages[0]["content"], SYSTEM_PROMPT)
        self.assertEqual(messages[1]["content"], "我们主要有哪些潜在问题需要注意")
        self.assertEqual(len(messages), 2)
        self.assertEqual(call.call_args.kwargs["timeout"], CLASSIFIER_TIMEOUT_SEC)
        self.assertEqual(call.call_args.kwargs["temperature"], 0)
        self.assertLessEqual(call.call_args.kwargs["max_tokens"], 128)

    def test_narrow_completion_bounds_timeout_without_chat_state(self):
        source = inspect.getsource(call_narrow_completion)
        for banned in (
            "get_deepseek_response",
            "clear_chat_context",
            "clear_memory",
            "chat_contexts",
            "get_user_prompt",
            "load_chat_contexts",
        ):
            self.assertNotIn(banned, source)
        fn = call_narrow_completion
        ns = fn.__globals__
        old_client = ns.get("client")
        old_model = ns.get("MODEL")
        captured = {}

        class Client:
            def with_options(self, **kwargs):
                captured["options"] = kwargs
                return self

            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        captured["create"] = kwargs
                        import time
                        time.sleep(1.2)

        ns["client"] = Client()
        ns["MODEL"] = "unit-model"
        try:
            with self.assertRaises(TimeoutError):
                fn(
                    [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                    timeout=0.2,
                    max_tokens=32,
                    temperature=0,
                )
        finally:
            if old_client is None:
                ns.pop("client", None)
            else:
                ns["client"] = old_client
            if old_model is None:
                ns.pop("MODEL", None)
            else:
                ns["MODEL"] = old_model
        self.assertEqual(captured["options"]["timeout"], 0.2)
        self.assertEqual(captured["options"]["max_retries"], 0)
        self.assertEqual(captured["create"]["max_tokens"], 32)
        self.assertEqual(captured["create"]["temperature"], 0)
        self.assertEqual(len(captured["create"]["messages"]), 2)

    def test_classifier_and_router_source_constraints(self):
        import query_intent_classifier
        import query_router

        classifier_source = inspect.getsource(query_intent_classifier)
        router_source = inspect.getsource(query_router)
        for banned in (
            "TopicStore",
            "TaskStore",
            "DecisionStore",
            "RiskStore",
            "write_processing",
            "commit_apply",
            "Engine(",
            "Extractor",
            "send_reply",
            "get_deepseek_response",
        ):
            self.assertNotIn(banned, classifier_source)
        for banned in ("TopicStore", "TaskStore", "DecisionStore", "RiskStore", "get_deepseek_response", "send_reply"):
            self.assertNotIn(banned, router_source)
        self.assertNotIn("get_deepseek_response", inspect.getsource(handle_collaboration_route))
        self.assertNotIn("chat_contexts", classifier_source)


if __name__ == "__main__":
    unittest.main()
