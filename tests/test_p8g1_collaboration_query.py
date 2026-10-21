# -*- coding: utf-8 -*-
"""P8-G1 只读查询、规则路由、旁路切断。不调用真实模型。"""

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
from decision_store import DecisionStore
from message.bind import bind_host
from message.identity import InboundMessage
from message.listener import message_listener
from query_formatter import (
    COMMAND_REPLY,
    OUT_OF_SCOPE_REPLY,
    format_query_result,
)
from query_router import (
    KIND_COMMAND,
    KIND_NOT_QUERY,
    KIND_OUT_OF_SCOPE,
    KIND_QUERY,
    LIST_DECISIONS,
    LIST_RISKS,
    LIST_TASKS,
    LIST_TOPICS,
    OPEN_RISKS,
    TOPIC_SUMMARY,
    classify_agent_message,
)
from query_service import (
    OUTCOME_AMBIGUOUS,
    OUTCOME_CONVERSATION_NOT_RESOLVED,
    OUTCOME_EMPTY,
    OUTCOME_NOT_FOUND,
    OUTCOME_OK,
    QueryRequest,
    QueryService,
)
from risk_engine import RISK_ENGINE_ENABLED
from risk_store import RiskStore
from task_engine import TASK_ENGINE_ENABLED
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import TopicSidepath, is_topic_engine_enabled, reset_sidepath
from topic_store import TopicStore

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
BOT_WXID = "wxid_bot_p8"


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
    def __init__(self, runtime, root_dir, is_group=True):
        self.runtime = runtime
        self.logger = logging.getLogger("test_p8g1")
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
        self._is_group = is_group

    def is_user_group_chat(self, _who):
        return self._is_group

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
        return "llm"


def _dump(root, store_name, cid, filename, key, rows):
    path = os.path.join(root, "data", store_name, "conversations", cid, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({key: rows}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def _snapshot(root):
    found = {}
    data = os.path.join(root, "data")
    if not os.path.isdir(data):
        return found
    for dirpath, _dirnames, filenames in os.walk(data):
        for name in filenames:
            if name in ("topics.json", "tasks.json", "decisions.json", "risks.json", "processed.json", "links.json"):
                path = os.path.join(dirpath, name)
                with open(path, "rb") as handle:
                    found[path] = handle.read()
    return found


def _topic(cid, topic_id, title, summary="", count=1, created="2026-09-01T00:00:00Z"):
    return {
        "id": topic_id,
        "conversation_id": cid,
        "title": title,
        "summary": summary,
        "status": "ACTIVE",
        "message_count": count,
        "last_message_at": created,
        "created_at": created,
        "confidence": "HIGH",
        "schema_version": 1,
    }


def _task(cid, task_id, topic_id, title, assignee="", due="", created="2026-09-01T00:00:00Z"):
    return {
        "id": task_id,
        "conversation_id": cid,
        "topic_id": topic_id,
        "title": title,
        "description": "",
        "status": "OPEN",
        "assignee_text": assignee,
        "due_text": due,
        "due_at": "",
        "created_msg_id": "m1",
        "confidence": "MEDIUM",
        "severity": "HIGH",
        "owner": "不应出现",
        "created_at": created,
        "updated_at": created,
        "schema_version": 1,
    }


def _decision(cid, decision_id, topic_id, text, created, supersedes=None):
    return {
        "id": decision_id,
        "conversation_id": cid,
        "topic_id": topic_id,
        "title": text,
        "decision_text": text,
        "summary": text,
        "status": "RECORDED",
        "created_msg_id": "m1",
        "supersedes_decision_id": supersedes,
        "created_at": created,
        "updated_at": created,
    }


def _risk(cid, risk_id, topic_id, title, status="OPEN", created="2026-09-01T00:00:00Z"):
    return {
        "id": risk_id,
        "conversation_id": cid,
        "topic_id": topic_id,
        "task_id": "",
        "title": title,
        "description": "",
        "condition_text": "测试环境频繁重启",
        "impact_text": "周五验收可能推迟",
        "status": status,
        "created_msg_id": "m1",
        "severity": "HIGH",
        "owner": "不应出现",
        "due": "周五",
        "created_at": created,
        "updated_at": created,
    }


class _Counting:
    def __init__(self, inner, label, log):
        self.inner = inner
        self.label = label
        self.log = log

    def list_topics(self, conversation_id):
        self.log.append((self.label, "list_topics", conversation_id))
        return self.inner.list_topics(conversation_id)

    def list_tasks(self, conversation_id):
        self.log.append((self.label, "list_tasks", conversation_id))
        return self.inner.list_tasks(conversation_id)

    def list_decisions(self, conversation_id):
        self.log.append((self.label, "list_decisions", conversation_id))
        return self.inner.list_decisions(conversation_id)

    def list_risks(self, conversation_id):
        self.log.append((self.label, "list_risks", conversation_id))
        return self.inner.list_risks(conversation_id)

    def list_messages(self, conversation_id):
        self.log.append((self.label, "list_messages", conversation_id))
        return self.inner.list_messages(conversation_id)

    def get_processing(self, *args, **kwargs):
        self.log.append((self.label, "get_processing", args))
        raise AssertionError("query must not read processing")


def _service(root):
    log = []
    topic = _Counting(TopicStore(root), "topic", log)
    task = _Counting(TaskStore(root), "task", log)
    decision = _Counting(DecisionStore(root), "decision", log)
    risk = _Counting(RiskStore(root), "risk", log)
    return QueryService(topic, task, decision, risk), log


def _request(query_type, cid="conv_a", topic_id="", topic_title=""):
    return QueryRequest(
        conversation_id=cid,
        message_id="m-q",
        sender_id="88",
        query_type=query_type,
        topic_id=topic_id,
        topic_title=topic_title,
    )


class RouterRuleTests(unittest.TestCase):
    def test_required_query_phrases(self):
        cases = {
            "现在有哪些任务": LIST_TASKS,
            "有哪些任务": LIST_TASKS,
            "当前任务有哪些": LIST_TASKS,
            "查看任务": LIST_TASKS,
            "目前有哪些风险": OPEN_RISKS,
            "现在有什么风险": OPEN_RISKS,
            "有什么风险": OPEN_RISKS,
            "查看风险": OPEN_RISKS,
            "有哪些决定": LIST_DECISIONS,
            "确定了什么": LIST_DECISIONS,
            "刚才确定了什么": LIST_DECISIONS,
            "现在有哪些主题": LIST_TOPICS,
            "有哪些主题": LIST_TOPICS,
            "查看主题": LIST_TOPICS,
        }
        for text, query_type in cases.items():
            decision = classify_agent_message(text)
            self.assertEqual(decision.kind, KIND_QUERY, text)
            self.assertEqual(decision.query_type, query_type, text)

    def test_topic_summary_phrases(self):
        quoted = classify_agent_message("主题「接口联调」现在什么情况")
        self.assertEqual(quoted.query_type, TOPIC_SUMMARY)
        self.assertEqual(quoted.topic_title, "接口联调")
        named = classify_agent_message("接口联调这个主题现在什么情况")
        self.assertEqual(named.topic_title, "接口联调")
        bare = classify_agent_message("主题 接口联调 什么情况")
        self.assertEqual(bare.query_type, TOPIC_SUMMARY)
        self.assertEqual(bare.topic_title, "接口联调")
        this = classify_agent_message("这个主题现在什么情况")
        self.assertEqual(this.query_type, TOPIC_SUMMARY)
        self.assertEqual(this.topic_title, "")

    def test_identity_is_not_list_tasks(self):
        for text in ("我有什么任务", "我有什么任务？", "张三负责什么", "张三有哪些任务", "我的任务"):
            decision = classify_agent_message(text)
            self.assertNotEqual(decision.query_type, LIST_TASKS, text)
            self.assertEqual(decision.kind, KIND_NOT_QUERY, text)

    def test_commands_and_scope_and_chat(self):
        self.assertEqual(classify_agent_message("帮我创建一个任务").kind, KIND_COMMAND)
        self.assertEqual(classify_agent_message("把风险关掉").kind, KIND_COMMAND)
        self.assertEqual(classify_agent_message("把任务改成完成").kind, KIND_COMMAND)
        self.assertEqual(classify_agent_message("关闭这个风险").kind, KIND_COMMAND)
        self.assertEqual(classify_agent_message("修改这个决定").kind, KIND_COMMAND)
        self.assertEqual(classify_agent_message("给张三分配任务").kind, KIND_COMMAND)
        self.assertEqual(classify_agent_message("看看另一个群有什么任务").kind, KIND_OUT_OF_SCOPE)
        self.assertEqual(classify_agent_message("帮我查项目B的风险").kind, KIND_OUT_OF_SCOPE)
        self.assertEqual(classify_agent_message("你好").kind, KIND_NOT_QUERY)
        self.assertEqual(classify_agent_message("/总结").kind, KIND_NOT_QUERY)
        self.assertEqual(classify_agent_message("/重启").kind, KIND_NOT_QUERY)
        self.assertEqual(classify_agent_message("/list").kind, KIND_NOT_QUERY)
        self.assertEqual(classify_agent_message("今天必须完成接口联调").kind, KIND_NOT_QUERY)
        self.assertEqual(classify_agent_message("另一个群今天必须完成接口联调").kind, KIND_NOT_QUERY)

    def test_unmatched_classifier_is_not_query_without_model(self):
        source = inspect.getsource(classify_agent_message)
        self.assertNotIn("deepseek", source.lower())
        self.assertNotIn("openai", source.lower())
        self.assertEqual(classify_agent_message("随便聊聊进度吧").kind, KIND_NOT_QUERY)


class QueryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        _dump(self.root, "topic_store", "conv_a", "topics.json", "topics", [
            _topic("conv_a", "top_1", "接口联调", "正在对齐回调字段", 4),
            _topic("conv_a", "top_2", "验收准备", "准备材料", 2),
        ])
        _dump(self.root, "topic_store", "conv_b", "topics.json", "topics", [
            _topic("conv_b", "top_b", "项目B主题", "", 1),
        ])
        _dump(self.root, "task_store", "conv_a", "tasks.json", "tasks", [
            _task("conv_a", "task_1", "top_1", "完成接口联调", "李明", "周五前", "2026-09-02T00:00:00Z"),
            _task("conv_a", "task_2", "top_2", "补充验收材料", "", "", "2026-09-03T00:00:00Z"),
            _task("conv_b", "task_foreign", "top_b", "不应返回", "王五", "", "2026-09-04T00:00:00Z"),
        ])
        _dump(self.root, "task_store", "conv_b", "tasks.json", "tasks", [
            _task("conv_b", "task_b", "top_b", "B的任务", "赵六"),
        ])
        _dump(self.root, "decision_store", "conv_a", "decisions.json", "decisions", [
            _decision("conv_a", "dec_old", "top_1", "旧决定", "2026-09-01T00:00:00Z"),
            _decision("conv_a", "dec_mid", "top_1", "验收材料由王磊补充", "2026-09-02T00:00:00Z"),
            _decision("conv_a", "dec_new", "top_1", "周五前完成接口联调", "2026-09-03T00:00:00Z", "dec_old"),
        ])
        _dump(self.root, "risk_store", "conv_a", "risks.json", "risks", [
            _risk("conv_a", "risk_open", "top_1", "联调环境不稳定", "OPEN"),
            _risk("conv_a", "risk_closed", "top_1", "已关闭风险", "CLOSED"),
            _risk("conv_b", "risk_foreign", "top_b", "B混入A", "OPEN"),
        ])
        _dump(self.root, "risk_store", "conv_b", "risks.json", "risks", [
            _risk("conv_b", "risk_b", "top_b", "B群风险", "OPEN"),
        ])
        for name in ("processed.json", "links.json"):
            for store, folder in (
                ("topic", "topic_store"),
                ("task", "task_store"),
                ("decision", "decision_store"),
                ("risk", "risk_store"),
            ):
                _dump(self.root, folder, "conv_a", name, "items", [{"id": store}])
        self.service, self.log = _service(self.root)
        self.before = _snapshot(self.root)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_query_01_list_topics(self):
        result = self.service.execute(_request(LIST_TOPICS))
        self.assertEqual(result.outcome, OUTCOME_OK)
        self.assertEqual([item["id"] for item in result.items], ["top_1", "top_2"])
        self.assertEqual(result.items[0]["status"], "ACTIVE")
        self.assertNotIn("confidence", result.items[0])

    def test_query_02_list_tasks(self):
        result = self.service.execute(_request(LIST_TASKS))
        self.assertEqual([item["id"] for item in result.items], ["task_1", "task_2"])
        self.assertTrue(all(item["status"] == "OPEN" for item in result.items))
        self.assertNotIn("due_at", result.items[0])

    def test_query_03_decisions_supersede_and_order(self):
        result = self.service.execute(_request(LIST_DECISIONS))
        self.assertEqual([item["id"] for item in result.items], ["dec_new", "dec_mid"])
        self.assertTrue(all(item["status"] == "RECORDED" for item in result.items))
        self.assertNotIn("SUPERSEDED", [item["status"] for item in result.items])

    def test_query_04_list_risks(self):
        result = self.service.execute(_request(LIST_RISKS))
        self.assertEqual([item["id"] for item in result.items], ["risk_open", "risk_closed"])

    def test_query_05_open_risks(self):
        result = self.service.execute(_request(OPEN_RISKS))
        self.assertEqual([item["id"] for item in result.items], ["risk_open"])
        self.assertEqual(result.items[0]["status"], "OPEN")

    def test_query_06_summary_single_topic_only(self):
        _dump(self.root, "topic_store", "conv_only", "topics.json", "topics", [
            _topic("conv_only", "top_only", "接口联调", "正在对齐回调字段", 4),
        ])
        _dump(self.root, "task_store", "conv_only", "tasks.json", "tasks", [
            _task("conv_only", "task_only", "top_only", "完成接口联调", "李明", "周五前"),
        ])
        _dump(self.root, "decision_store", "conv_only", "decisions.json", "decisions", [
            _decision("conv_only", "dec_only", "top_only", "周五前完成接口联调", "2026-09-03T00:00:00Z"),
        ])
        _dump(self.root, "risk_store", "conv_only", "risks.json", "risks", [
            _risk("conv_only", "risk_only", "top_only", "联调环境不稳定"),
        ])
        result = self.service.execute(_request(TOPIC_SUMMARY, cid="conv_only"))
        self.assertEqual(result.outcome, OUTCOME_OK)
        item = result.items[0]
        self.assertEqual(item["topic"]["title"], "接口联调")
        self.assertEqual(item["tasks"][0]["id"], "task_only")
        self.assertEqual(item["decisions"][0]["status"], "RECORDED")
        self.assertEqual(item["risks"][0]["status"], "OPEN")
        self.assertEqual(result.sources, ["topic_store", "task_store", "decision_store", "risk_store"])

    def test_query_07_exact_title(self):
        result = self.service.execute(_request(TOPIC_SUMMARY, topic_title="验收准备"))
        self.assertEqual(result.outcome, OUTCOME_OK)
        self.assertEqual(result.items[0]["topic"]["id"], "top_2")
        self.assertEqual(result.items[0]["tasks"][0]["id"], "task_2")

    def test_query_08_ambiguous(self):
        result = self.service.execute(_request(TOPIC_SUMMARY))
        self.assertEqual(result.outcome, OUTCOME_AMBIGUOUS)
        self.assertEqual([item["title"] for item in result.items], ["接口联调", "验收准备"])
        self.assertNotIn("tasks", result.items[0])

    def test_query_09_empty_wording(self):
        result = self.service.execute(_request(LIST_TASKS, cid="conv_empty"))
        self.assertEqual(result.outcome, OUTCOME_EMPTY)
        self.assertEqual(format_query_result(result), "当前未查询到已记录的任务。")
        for query_type, line in (
            (LIST_RISKS, "当前未查询到已记录的风险。"),
            (OPEN_RISKS, "当前未查询到已记录的风险。"),
            (LIST_DECISIONS, "当前未查询到已记录的决定。"),
            (LIST_TOPICS, "当前未查询到已记录的主题。"),
        ):
            empty = self.service.execute(_request(query_type, cid="conv_empty"))
            self.assertEqual(format_query_result(empty), line)
            self.assertNotIn("没有任务", line)
            self.assertNotIn("没有任何风险", line)

    def test_query_10_dto_has_no_invented_fields(self):
        task = self.service.execute(_request(LIST_TASKS)).items[0]
        risk = self.service.execute(_request(LIST_RISKS)).items[0]
        for forbidden in ("severity", "owner", "due", "due_at", "confidence", "schema_version"):
            self.assertNotIn(forbidden, task)
            self.assertNotIn(forbidden, risk)
        self.assertIn("assignee_text", task)
        self.assertIn("condition_text", risk)
        self.assertIn("impact_text", risk)

    def test_scope_01_only_current_conversation(self):
        result = self.service.execute(_request(LIST_TASKS, cid="conv_a"))
        self.assertEqual([item["id"] for item in result.items], ["task_1", "task_2"])
        self.assertNotIn("task_b", [item["id"] for item in result.items])
        self.assertTrue(all(item["conversation_id"] == "conv_a" for item in result.items))
        self.assertNotIn(("task", "list_tasks", "conv_b"), self.log)

    def test_scope_02_risk_ids_stay_in_conversation(self):
        result = self.service.execute(_request(OPEN_RISKS, cid="conv_a"))
        ids = [item["id"] for item in result.items]
        self.assertIn("risk_open", ids)
        self.assertNotIn("risk_b", ids)
        self.assertNotIn("risk_foreign", ids)

    def test_scope_03_missing_topic_id_is_not_found(self):
        result = self.service.execute(_request(TOPIC_SUMMARY, topic_id="top_missing"))
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        self.assertEqual(result.items, [])
        self.assertNotIn(("task", "list_tasks", "conv_a"), self.log)

    def test_scope_05_unresolved_makes_no_list_call(self):
        before = len(self.log)
        result = self.service.execute(_request(LIST_TASKS, cid=""))
        self.assertEqual(result.outcome, OUTCOME_CONVERSATION_NOT_RESOLVED)
        self.assertEqual(self.log[before:], [])

    def test_summary_filters_superseded_decision(self):
        result = self.service.execute(_request(TOPIC_SUMMARY, topic_id="top_1"))
        ids = [item["id"] for item in result.items[0]["decisions"]]
        self.assertEqual(ids, ["dec_new", "dec_mid"])
        self.assertNotIn("dec_old", ids)

    def test_store_bytes_unchanged_and_no_processing_read(self):
        from store_io import atomic_write_json
        with patch("store_io.atomic_write_json", side_effect=AssertionError("query wrote json")):
            self.assertIs(atomic_write_json.__module__, "store_io")
            self.service.execute(_request(TOPIC_SUMMARY, topic_id="top_1"))
        self.assertEqual(_snapshot(self.root), self.before)
        self.assertFalse(any(item[1] == "get_processing" for item in self.log))
        self.assertFalse(any(item[1] == "list_messages" for item in self.log))

    def test_formatter_examples(self):
        tasks = self.service.execute(_request(LIST_TASKS))
        text = format_query_result(tasks)
        self.assertIn("当前记录到 2 个任务：", text)
        self.assertIn("负责人：李明", text)
        self.assertIn("负责人：未记录", text)
        self.assertIn("状态：OPEN", text)
        self.assertIn("时间说明：周五前", text)
        self.assertNotIn("进行中", text)
        self.assertNotIn("待处理", text)
        decisions = format_query_result(self.service.execute(_request(LIST_DECISIONS)))
        self.assertIn("当前记录到 2 条决定（按记录时间从新到旧）", decisions)
        self.assertNotIn("刚才", decisions)
        self.assertIn("状态：RECORDED", decisions)
        risks = format_query_result(self.service.execute(_request(OPEN_RISKS)))
        self.assertIn("当前记录到 1 条未关闭的风险：", risks)
        self.assertIn("条件：测试环境频繁重启", risks)
        self.assertIn("影响：周五验收可能推迟", risks)
        ambiguous = format_query_result(self.service.execute(_request(TOPIC_SUMMARY)))
        self.assertIn("当前会话有多个主题，请用主题名称再问一次：", ambiguous)
        self.assertIn("1. 接口联调", ambiguous)
        self.assertIn("2. 验收准备", ambiguous)


class ListenerRouteTests(unittest.TestCase):
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
        _dump(self.root, "task_store", "conv_a", "tasks.json", "tasks", [
            _task("conv_a", "task_1", "top_1", "完成接口联调", "李明", "周五前"),
        ])
        _dump(self.root, "risk_store", "conv_a", "risks.json", "risks", [
            _risk("conv_a", "risk_open", "top_1", "联调环境不稳定"),
        ])
        _dump(self.root, "decision_store", "conv_a", "decisions.json", "decisions", [
            _decision("conv_a", "dec_1", "top_1", "周五前完成接口联调", "2026-09-03T00:00:00Z"),
        ])
        _dump(self.root, "topic_store", "conv_a", "topics.json", "topics", [
            _topic("conv_a", "top_1", "接口联调", "正在对齐回调字段", 4),
        ])

    def tearDown(self):
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
        bind_host(types.SimpleNamespace())
        from message import bind as bind_mod
        bind_mod._host = None
        self.tmpdir.cleanup()
        clear_stop_request()
        clear_emergency_stop()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)
        self.assertFalse(is_topic_engine_enabled())

    def _listen(self, content, who="项目群A", wxid="room_a@chatroom", **msg_kwargs):
        msg = FakeMsg(content, platform_message_id=msg_kwargs.pop("platform_message_id", content), **msg_kwargs)
        message_listener(msg, FakeChat(who, wxid))

    def test_router_01_tasks_skip_sidepath_and_chat(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 现在有哪些任务", platform_message_id="r01")
        enqueued.assert_not_called()
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.memory_logs, [])
        self.assertEqual(self.host.deepseek_calls, [])
        self.assertEqual(self.host.chat_contexts, {})
        self.assertEqual(self.host.user_queues, {})

    def test_router_02_open_risks(self):
        self._listen("@智群Agent 有什么风险", platform_message_id="r02")
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("联调环境不稳定", self.host.sent[0])
        self.assertIn("未关闭的风险", self.host.sent[0])
        self.assertEqual(self.host.handled, [])

    def test_router_03_decisions(self):
        self._listen("@智群Agent 有哪些决定", platform_message_id="r03")
        self.assertIn("周五前完成接口联调", self.host.sent[0])
        self.assertNotIn("刚才", self.host.sent[0])

    def test_router_04_topics(self):
        self._listen("@智群Agent 有哪些主题", platform_message_id="r04")
        self.assertIn("接口联调", self.host.sent[0])
        self.assertIn("ACTIVE", self.host.sent[0])

    def test_router_05_topic_summary(self):
        self._listen("@智群Agent 主题 接口联调 什么情况", platform_message_id="r05")
        self.assertIn("主题：接口联调", self.host.sent[0])
        self.assertIn("完成接口联调", self.host.sent[0])
        self.assertEqual(self.host.handled, [])

    def test_router_06_hello_keeps_chat(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 你好", platform_message_id="r06")
        enqueued.assert_called_once()
        self.assertEqual(len(self.host.handled), 1)
        self.assertEqual(self.host.sent, [])

    def test_router_07_plain_group_message_skips_router(self):
        with patch("collaboration_query.classify_agent_message") as classify:
            with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
                self._listen("今天必须完成接口联调", platform_message_id="r07")
        classify.assert_not_called()
        enqueued.assert_called_once()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])

    def test_router_08_slash_not_captured(self):
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent /list", platform_message_id="r08")
        enqueued.assert_called_once()
        self.assertEqual(len(self.host.handled), 1)
        self.assertEqual(self.host.sent, [])
        self.assertNotIn(COMMAND_REPLY, "".join(self.host.sent))

    def test_scope_04_other_group_does_not_read_store(self):
        with patch("topic_store.TopicStore.list_topics", side_effect=AssertionError("topic list")):
            with patch("task_store.TaskStore.list_tasks", side_effect=AssertionError("task list")):
                with patch("risk_store.RiskStore.list_risks", side_effect=AssertionError("risk list")):
                    with patch("decision_store.DecisionStore.list_decisions", side_effect=AssertionError("decision list")):
                        self._listen("@智群Agent 看看另一个群有什么任务", platform_message_id="s04")
        self.assertEqual(self.host.sent, [OUT_OF_SCOPE_REPLY])
        self.assertEqual(self.host.handled, [])

    def test_scope_05_unresolved_conversation_lists_nothing(self):
        self.host.conversations = []
        with patch("topic_store.TopicStore.list_topics", side_effect=AssertionError("topic list")):
            with patch("task_store.TaskStore.list_tasks", side_effect=AssertionError("task list")):
                self._listen("@智群Agent 现在有哪些任务", platform_message_id="s05")
        self.assertEqual(len(self.host.sent), 1)
        self.assertIn("尚未绑定", self.host.sent[0])
        self.assertEqual(self.host.handled, [])

    def test_commands_do_not_enter_chat_or_write(self):
        before = _snapshot(self.root)
        from store_io import atomic_write_json
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            with patch("store_io.atomic_write_json", side_effect=AssertionError("command wrote")):
                self.assertIs(atomic_write_json.__module__, "store_io")
                self._listen("@智群Agent 帮我创建一个任务", platform_message_id="c01")
                self._listen("@智群Agent 把风险关掉", platform_message_id="c02")
                self._listen("@智群Agent 把任务改成完成", platform_message_id="c03")
        self.assertEqual(enqueued.call_count, 0)
        self.assertEqual(self.host.handled, [])
        self.assertEqual(self.host.sent, [COMMAND_REPLY, COMMAND_REPLY, COMMAND_REPLY])
        self.assertEqual(_snapshot(self.root), before)

    def test_query_store_bytes_and_context_unchanged(self):
        before = _snapshot(self.root)
        self._listen("@智群Agent 现在有哪些任务", platform_message_id="bytes")
        self.assertEqual(_snapshot(self.root), before)
        self.assertEqual(self.host.memory_logs, [])
        self.assertEqual(self.host.user_queues, {})
        self.assertEqual(self.host.chat_contexts, {})

    def test_stop_blocks_query_router(self):
        self.runtime.set_state("STOPPED", "test")
        with patch("collaboration_query.classify_agent_message") as classify:
            with patch("collaboration_query.build_query_service", side_effect=AssertionError("service")):
                self._listen("@智群Agent 现在有哪些任务", platform_message_id="stop")
        classify.assert_not_called()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])

    def test_send_path_is_send_reply_not_wechat_api(self):
        source = inspect.getsource(handle_collaboration_route)
        source += inspect.getsource(__import__("collaboration_query"))
        self.assertIn("send_reply", source)
        self.assertNotIn("SendMsg", source)
        self._listen("@智群Agent 查看任务", platform_message_id="send")
        self.assertEqual(len(self.host.sent), 1)

    def test_allow_reply_blocks_without_falling_through(self):
        self.runtime.note_replied("项目群A")
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 现在有哪些任务", platform_message_id="rate")
        enqueued.assert_not_called()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])

    def test_session_lock_blocks_parallel_send(self):
        self.assertTrue(self.runtime.try_acquire_session("项目群A"))
        with patch("message.listener.try_enqueue_topic_sidepath") as enqueued:
            self._listen("@智群Agent 现在有哪些任务", platform_message_id="lock")
        enqueued.assert_not_called()
        self.assertEqual(self.host.sent, [])
        self.assertEqual(self.host.handled, [])
        self.runtime.release_session("项目群A")

    def test_listener_inserts_router_before_sidepath(self):
        source = inspect.getsource(message_listener)
        admit = source.split("STEP_ADMIT", 1)[1]
        before_reply = admit.split('verdict.get("action") != REPLY', 1)[0]
        self.assertLess(before_reply.find("evaluate_inbound"), before_reply.find("handle_collaboration_route"))
        self.assertLess(before_reply.find("handle_collaboration_route"), before_reply.find("try_enqueue_topic_sidepath"))
        self.assertIn("try_enqueue_topic_sidepath", before_reply)


class SidepathSuppressionTests(unittest.TestCase):
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
        self.sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV_A), dict(CONV_B)],
            extractor=HeuristicTopicExtractor(),
            enabled=True,
            maxsize=4,
        )
        reset_sidepath(self.sidepath)

    def tearDown(self):
        try:
            self.sidepath.shutdown()
            self.sidepath.wait_idle(0.4)
        except Exception:
            pass
        reset_sidepath(TopicSidepath(enabled=False, root_dir=self.root, maxsize=1))
        bind_host(types.SimpleNamespace())
        from message import bind as bind_mod
        bind_mod._host = None
        self.tmpdir.cleanup()
        clear_stop_request()
        clear_emergency_stop()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(is_topic_engine_enabled())

    def _listen(self, content, pid):
        message_listener(FakeMsg(content, platform_message_id=pid), FakeChat())

    def test_query_and_command_do_not_enqueue_topic(self):
        self._listen("@智群Agent 现在有哪些任务", "sq")
        self._listen("@智群Agent 帮我创建一个任务", "sc")
        self.assertEqual(self.sidepath.enqueued_count, 0)
        self.assertEqual(self.host.handled, [])
        self.assertGreaterEqual(len(self.host.sent), 1)

    def test_not_query_still_enqueues_topic(self):
        self._listen("@智群Agent 你好", "sn")
        self.assertEqual(self.sidepath.enqueued_count, 1)
        self.assertEqual(len(self.host.handled), 1)
        self.assertEqual(self.host.sent, [])
        self.assertTrue(self.sidepath.wait_idle(2))


class SourceConstraintTests(unittest.TestCase):
    def test_router_and_service_do_not_call_engines(self):
        import collaboration_query
        import query_formatter
        import query_router
        import query_service
        for module in (query_router, query_service, query_formatter, collaboration_query):
            text = inspect.getsource(module)
            self.assertNotIn("Engine(", text)
            self.assertNotIn("Extractor", text)
            self.assertNotIn("write_processing", text)
            self.assertNotIn("commit_apply", text)
            self.assertNotIn("retry_topic", text)
            self.assertNotIn("retry_downstream", text)
            self.assertNotIn("get_processing", text)
            self.assertNotIn("get_deepseek", text)
            self.assertNotIn("SendMsg", text)


if __name__ == "__main__":
    unittest.main()
