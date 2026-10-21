# -*- coding: utf-8 -*-
"""P7-G2 调查详情：DIAG-01 ～ DIAG-15。只读证据，不推断 processing decision。"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from functools import wraps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decision_engine import DECISION_ENGINE_ENABLED
from decision_sidepath import is_decision_engine_enabled
from decision_store import DecisionStore
from flask import Flask
from operations_action_audit import append_action_audit
from operations_diagnostic_service import (
    AUDIT_LIMIT,
    FLAG_AUDIT_FAILED_PRESENT,
    FLAG_CREATED_BY_PRESENT,
    FLAG_CREATION_EVIDENCE_PRESENT,
    FLAG_ENTITY_PRESENT,
    FLAG_MANUAL_RETRY_ATTEMPTED,
    FLAG_PROCESSING_MISSING,
    FLAG_RELATED_PRESENT,
    SUMMARY_MISSING_EVIDENCE,
    SUMMARY_MISSING_NONE,
    OperationsDiagnosticService,
)
from operations_read_model import (
    STATE_FAILED_RETRYABLE,
    STATE_NOT_FOUND_UNKNOWN,
    STATE_SUCCESS,
)
from operations_routes import register_operations_routes
from risk_engine import RISK_ENGINE_ENABLED
from risk_sidepath import is_risk_engine_enabled
from task_engine import TASK_ENGINE_ENABLED
from task_sidepath import is_task_engine_enabled
from task_store import RELATION_CREATED_BY as TASK_CREATED_BY
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import is_topic_engine_enabled
from topic_store import RELATION_CREATED_BY, RELATION_RELATED, RELATION_UPDATED_BY, TopicStore

CONV = "conv_p7g2diag"
OTHER = "conv_p7g2other"
CREATED = "2026-09-23T08:00:00Z"
AUDIT_TS = "2026-09-23T08:05:00Z"

_INFERENCE = (
    "确认从未执行",
    "尚未处理",
    "系统已经处理成功",
    "系统肯定没有执行",
    "建议自动重跑",
    "RECOVER_AS_NEW_TASK",
    "SHOULD_BE_SUCCESS",
    "PARTIAL_SUCCESS",
    "LIKELY_SUCCESS",
    "PROBABLY_NOT_RUN",
)


class DiagnosticViewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.topic_store = TopicStore(self.root)
        self.task_store = TaskStore(self.root, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.root, topic_store=self.topic_store)
        self.service = OperationsDiagnosticService(self.root, runtime_status={
            "state": "RUNNING",
            "emergency": False,
            "wechat": "disconnected",
            "pid": 4242,
        })
        self.model = self.service.read_model

    def tearDown(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)
        self.assertFalse(is_topic_engine_enabled())
        self.assertFalse(is_task_engine_enabled())
        self.assertFalse(is_decision_engine_enabled())
        self.assertFalse(is_risk_engine_enabled())
        self._tmp.cleanup()

    def _message(self, platform_id, content, conversation_id=CONV, created_at=CREATED):
        return self.topic_store.upsert_message({
            "conversation_id": conversation_id,
            "platform_message_id": platform_id,
            "content": content,
            "created_at": created_at,
            "ingested_at": created_at,
            "sender_name": "测试",
            "direction": "INBOUND",
            "message_type": "text",
        })

    def _topic(self, message, title="排期主题"):
        return self.topic_store.create_topic(
            message["conversation_id"],
            title=title,
            summary="摘要",
            created_msg_id=message["id"],
            created_at=CREATED,
        )

    def _assert_same_classification(self, message):
        ops = self.model.get_message(message["id"], message["conversation_id"])
        view = self.service.get_message_diagnostics(message["id"], message["conversation_id"])
        for engine in ("topic", "task", "decision", "risk"):
            self.assertEqual(view[engine]["state"], ops[engine]["state"])
            self.assertEqual(view[engine]["decision"], ops[engine]["decision"])
            self.assertEqual(view[engine]["retryable"], ops[engine]["retryable"])
            self.assertEqual(view[engine]["retry_type"], ops[engine]["retry_type"])
            self.assertEqual(view[engine]["processing_found"], ops[engine]["processing_present"])
            self.assertEqual(view["operations_state"][engine]["state"], ops[engine]["state"])
        return view

    def _assert_no_inference(self, payload, extra=()):
        blob = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        for phrase in _INFERENCE + tuple(extra):
            self.assertNotIn(phrase, blob)

    def test_diag01_success_shows_processing_entity_and_evidence(self):
        content = "完整正文" * 30
        message = self._message("d01", content)
        topic = self._topic(message, title="上线窗口")
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_CREATED_BY, created_at=CREATED)
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_UPDATED_BY, created_at=CREATED)
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "topic_id": topic["id"],
            "processed_at": CREATED,
        })
        view = self._assert_same_classification(message)
        block = view["topic"]
        self.assertEqual(block["state"], STATE_SUCCESS)
        self.assertTrue(block["processing_found"])
        self.assertEqual(block["processing"]["record"]["decision"], "NEW_TOPIC")
        self.assertEqual(block["processing"]["timestamps"][0]["source"], "processing.processed_at")
        self.assertEqual(block["entity_count"], 1)
        self.assertEqual(block["entities"][0]["record"]["title"], "上线窗口")
        self.assertEqual(block["entities"][0]["record"]["status"], "ACTIVE")
        self.assertEqual(block["evidence"]["counts"]["CREATED_BY"], 1)
        self.assertEqual(block["evidence"]["counts"]["UPDATED_BY"], 1)
        self.assertEqual(block["evidence"]["counts"]["RELATED"], 0)
        self.assertEqual(view["message"]["content"], content)
        self.assertEqual(view["message"]["timestamps"][0]["source"], "message.created_at")
        self.assertNotEqual(view["message"]["timestamps"][0]["source"], view["message"]["timestamps"][1]["source"])

    def test_diag02_failed_shows_stored_error_without_parsed_code(self):
        message = self._message("d02", "任务失败原文")
        self.task_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "FAILED",
            "error": "RuntimeError: boom",
            "processed_at": CREATED,
        })
        view = self._assert_same_classification(message)
        block = view["task"]
        self.assertEqual(block["state"], STATE_FAILED_RETRYABLE)
        self.assertTrue(block["retryable"])
        self.assertEqual(block["processing"]["record"]["error"], "RuntimeError: boom")
        self.assertNotIn("error_code", block["processing"]["record"])
        names = [field["name"] for field in block["processing"]["fields"]]
        self.assertIn("error", names)
        self.assertNotIn("error_code", names)
        self.assertEqual(block["decision"], "FAILED")

    def test_diag03_unknown_with_entity_stays_unknown(self):
        message = self._message("d03", "有任务实体")
        topic = self._topic(message)
        self.task_store.create_task({
            "id": "task_diag03",
            "conversation_id": CONV,
            "topic_id": topic["id"],
            "title": "核对权限",
            "created_msg_id": message["id"],
            "assignee_text": "李娜",
            "created_at": CREATED,
        })
        self.assertIsNone(self.task_store.get_processing(CONV, message["id"]))
        view = self._assert_same_classification(message)
        block = view["task"]
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertNotEqual(block["state"], STATE_SUCCESS)
        self.assertFalse(block["retryable"])
        self.assertGreaterEqual(block["entity_count"], 1)
        self.assertEqual(block["diagnosis_summary"], SUMMARY_MISSING_EVIDENCE)
        self.assertIn(FLAG_PROCESSING_MISSING, block["diagnostic_flags"])
        self.assertIn(FLAG_ENTITY_PRESENT, block["diagnostic_flags"])
        self._assert_no_inference(block)

    def test_diag04_unknown_with_created_by_stays_unknown(self):
        message = self._message("d04", "只有创建链接")
        topic = self._topic(message)
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_CREATED_BY, created_at=CREATED)
        view = self._assert_same_classification(message)
        block = view["topic"]
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertEqual(block["decision"], "")
        self.assertEqual(block["evidence"]["counts"]["CREATED_BY"], 1)
        self.assertIn(FLAG_CREATED_BY_PRESENT, block["diagnostic_flags"])
        self.assertNotIn("NEW_TOPIC", block["diagnostic_flags"])
        self._assert_no_inference(block, ("NEW_TOPIC",))

    def test_diag05_unknown_with_failed_audit_stays_unknown(self):
        message = self._message("d05", "只有失败审计")
        self.topic_store.write_audit({
            "ts": AUDIT_TS,
            "conversation_id": CONV,
            "message_id": message["id"],
            "topic_decision": "FAILED",
            "error": "RuntimeError: audit",
        })
        view = self._assert_same_classification(message)
        block = view["topic"]
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertNotEqual(block["state"], STATE_FAILED_RETRYABLE)
        self.assertFalse(block["retryable"])
        self.assertIn(FLAG_AUDIT_FAILED_PRESENT, block["diagnostic_flags"])
        self.assertEqual(block["audit_events"][0]["decision"], "FAILED")
        self.assertEqual(block["audit_events"][0]["error"], "RuntimeError: audit")
        self.assertEqual(block["audit_events"][0]["timestamps"][0]["source"], "audit.ts")
        self.assertEqual(block["audit_events"][0]["timestamps"][0]["value"], AUDIT_TS)
        self.assertIn("Audit 为诊断记录，不是 Processing 真值。", block["investigation_lines"])
        self._assert_no_inference(block)

    def test_diag06_unknown_without_traces_does_not_claim_never_ran(self):
        message = self._message("d06", "什么都没有")
        self.assertIsNone(self.topic_store.get_processing(CONV, message["id"]))
        view = self._assert_same_classification(message)
        block = view["task"]
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertEqual(block["entity_count"], 0)
        self.assertEqual(block["evidence_count"], 0)
        self.assertEqual(block["audit_events"], [])
        self.assertEqual(block["diagnosis_summary"], SUMMARY_MISSING_NONE)
        self.assertIn("未发现业务处理记录", block["investigation_lines"])
        self.assertIn("Processing Record：未找到", block["investigation_lines"])
        self._assert_no_inference(view)
        self.assertIsNone(self.topic_store.get_processing(CONV, message["id"]))
        self.assertIsNone(self.task_store.get_processing(CONV, message["id"]))

    def test_diag07_related_is_not_existing_topic(self):
        message = self._message("d07", "只是相关")
        topic = self._topic(message, title="别的主题")
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_RELATED, created_at=CREATED)
        view = self._assert_same_classification(message)
        block = view["topic"]
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertEqual(block["decision"], "")
        self.assertIn(FLAG_RELATED_PRESENT, block["diagnostic_flags"])
        self.assertEqual(block["evidence"]["counts"]["RELATED"], 1)
        self.assertEqual(block["evidence"]["counts"]["CREATED_BY"], 0)
        self.assertIn("消息与该业务实体有关", block["investigation_lines"])
        self._assert_no_inference(block, ("EXISTING_TOPIC", "NEW_TOPIC"))

    def test_diag08_created_msg_and_created_by_are_facts_only(self):
        message = self._message("d08", "创建了任务")
        topic = self._topic(message)
        task = self.task_store.create_task({
            "id": "task_diag08",
            "conversation_id": CONV,
            "topic_id": topic["id"],
            "title": "补文档",
            "created_msg_id": message["id"],
            "assignee_text": "周凯",
            "created_at": CREATED,
        })
        links = [
            item for item in self.task_store.list_links(CONV)
            if item.get("message_id") == message["id"] and item.get("relation") == TASK_CREATED_BY
        ]
        self.assertTrue(links)
        self.assertEqual(task["created_msg_id"], message["id"])
        view = self._assert_same_classification(message)
        block = view["task"]
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertIn(FLAG_CREATION_EVIDENCE_PRESENT, block["diagnostic_flags"])
        self.assertIn(FLAG_CREATED_BY_PRESENT, block["diagnostic_flags"])
        self.assertIn("存在创建证据", block["investigation_lines"])
        shown = {field["name"]: field["value"] for field in block["entities"][0]["fields"]}
        self.assertEqual(shown["task_id"], task["id"])
        self.assertEqual(shown["assignee_text"], "周凯")
        self.assertEqual(shown["created_msg_id"], message["id"])
        self._assert_no_inference(block, ("NEW_TASK", "TASK_UPDATE"))

    def test_diag09_manual_retry_audit_does_not_change_processing_state(self):
        message = self._message("d09", "有人点过重试")
        append_action_audit(self.root, {
            "event": "MANUAL_RETRY_REQUESTED",
            "engine": "risk",
            "conversation_id": CONV,
            "message_id": message["id"],
            "executed": False,
            "error": "",
        })
        append_action_audit(self.root, {
            "event": "MANUAL_RETRY_RESULT",
            "engine": "risk",
            "conversation_id": CONV,
            "message_id": message["id"],
            "executed": True,
            "after_state": "SUCCESS",
            "error": "",
        })
        view = self._assert_same_classification(message)
        block = view["risk"]
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertFalse(block["processing_found"])
        self.assertIn(FLAG_MANUAL_RETRY_ATTEMPTED, block["diagnostic_flags"])
        events = [item["event"] for item in view["diagnostics"]["manual_actions"]]
        self.assertEqual(events, ["MANUAL_RETRY_REQUESTED", "MANUAL_RETRY_RESULT"])
        self.assertEqual(view["diagnostics"]["manual_actions"][0]["timestamps"][0]["source"], "operations_action_audit.ts")
        self.assertIsNone(self.service.read_model.risk_store.get_processing(CONV, message["id"]))
        self.assertNotIn(FLAG_MANUAL_RETRY_ATTEMPTED, view["topic"]["diagnostic_flags"])

    def test_diag10_four_engines_are_independent(self):
        message = self._message("d10", "四路分开")
        topic = self._topic(message, title="独立主题")
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_CREATED_BY, created_at=CREATED)
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "topic_id": topic["id"],
            "processed_at": CREATED,
        })
        self.task_store.create_task({
            "id": "task_diag10",
            "conversation_id": CONV,
            "topic_id": topic["id"],
            "title": "独立任务",
            "created_msg_id": message["id"],
            "assignee_text": "李娜",
            "created_at": CREATED,
        })
        self.decision_store.create_decision({
            "id": "dec_diag10",
            "conversation_id": CONV,
            "topic_id": topic["id"],
            "title": "独立决策",
            "decision_text": "先观察",
            "created_msg_id": message["id"],
            "created_at": CREATED,
        })
        self.decision_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "FAILED",
            "error": "RuntimeError: decision",
            "processed_at": CREATED,
        })
        view = self._assert_same_classification(message)
        self.assertEqual(view["topic"]["state"], STATE_SUCCESS)
        self.assertEqual(view["task"]["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertGreaterEqual(view["task"]["entity_count"], 1)
        self.assertEqual(view["decision"]["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(view["decision"]["processing"]["record"]["error"], "RuntimeError: decision")
        self.assertEqual(view["risk"]["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertEqual(view["risk"]["entity_count"], 0)
        self.assertEqual(view["risk"]["diagnosis_summary"], SUMMARY_MISSING_NONE)
        self.assertNotIn("dec_diag10", view["task"]["entity_ids"])
        self.assertNotIn("task_diag10", view["decision"]["entity_ids"])

    def test_diag11_evidence_stays_on_current_message(self):
        message = self._message("d11", "当前消息")
        other_message = self._message("d11b", "同会话另一条")
        foreign = self._message("d11c", "另一个会话", conversation_id=OTHER)
        topic = self._topic(message, title="当前主题")
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_RELATED, created_at=CREATED)
        self.topic_store.add_link(CONV, topic["id"], other_message["id"], RELATION_CREATED_BY, created_at=CREATED)
        foreign_topic = self.topic_store.create_topic(
            OTHER,
            title="外部主题",
            created_msg_id=foreign["id"],
            created_at=CREATED,
        )
        self.topic_store.add_link(OTHER, foreign_topic["id"], foreign["id"], RELATION_CREATED_BY, created_at=CREATED)
        view = self.service.get_message_diagnostics(message["id"], CONV)
        block = view["topic"]
        self.assertEqual(block["evidence"]["counts"]["RELATED"], 1)
        self.assertEqual(block["evidence"]["counts"]["CREATED_BY"], 0)
        linked_messages = [item["message_id"] for item in block["evidence"]["RELATED"]]
        self.assertEqual(linked_messages, [message["id"]])
        blob = json.dumps(block, ensure_ascii=False)
        self.assertNotIn(foreign["id"], blob)
        self.assertNotIn(foreign_topic["id"], blob)
        self.assertNotIn(other_message["id"], blob)

    def test_diag12_diagnostics_api_is_get_only(self):
        message = self._message("d12", "接口")
        app = self._app()
        client = app.test_client()
        url = "/api/operations/messages/%s/diagnostics?conversation_id=%s" % (message["id"], CONV)
        got = client.get(url)
        self.assertEqual(got.status_code, 200)
        body = got.get_json()
        self.assertEqual(body["message"]["id"], message["id"])
        self.assertEqual(body["topic"]["state"], STATE_NOT_FOUND_UNKNOWN)
        missing = client.get("/api/operations/messages/msg_missing/diagnostics")
        self.assertEqual(missing.status_code, 404)
        posted = client.post(url)
        self.assertEqual(posted.status_code, 405)
        home = client.get("/operations?attention=0")
        html = home.get_data(as_text=True)
        self.assertIn("查看详情", html)
        self.assertIn("/operations/messages/%s" % message["id"], html)
        with open(os.path.join(ROOT, "operations_routes.py"), encoding="utf-8") as handle:
            route_text = handle.read()
        self.assertIn('"/api/operations/messages/<message_id>/diagnostics", methods=["GET"]', route_text)
        self.assertNotIn('methods=["POST"]', route_text)
        self.assertNotIn("methods=['POST']", route_text)
        self.assertIn("@login_required", route_text)

    def test_diag13_unknown_page_has_no_retry_repair_or_reprocess(self):
        message = self._message("d13", "未知页")
        app = self._app()
        client = app.test_client()
        page = client.get("/operations/messages/%s?conversation_id=%s" % (message["id"], CONV))
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("需人工调查", html)
        self.assertIn("需要人工调查", html)
        self.assertIn("Processing Record：未找到", html)
        self.assertIn("处理状态未知", html)
        self.assertIn("未发现业务处理记录", html)
        self.assertIn("禁止自动重试", html)
        self.assertNotIn("确认从未执行", html)
        self.assertNotIn("尚未处理", html)
        self.assertNotIn("<button", html)
        self.assertNotIn("/retry", html)
        self.assertNotIn("Repair", html)
        self.assertNotIn("Reprocess", html)
        self.assertNotIn("repair", html.lower())
        self.assertNotIn("reprocess", html.lower())

    def test_diag14_read_model_three_state_suite_still_passes(self):
        self._run_module("test_p7g0_operations_read_model")
        message = self._message("d14", "三态仍在")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "UNRELATED",
            "processed_at": CREATED,
        })
        view = self._assert_same_classification(message)
        self.assertEqual(view["topic"]["state"], STATE_SUCCESS)
        self.assertEqual(set(view["diagnostics"]["summaries"]), {"topic", "task", "decision", "risk"})
        blob = json.dumps(view["task"]["diagnostic_flags"], ensure_ascii=False)
        for phrase in ("PARTIAL_SUCCESS", "LIKELY_SUCCESS", "PROBABLY_NOT_RUN"):
            self.assertNotIn(phrase, blob)

    def test_diag15_p6g6_type_c_suite_still_passes(self):
        self._run_module("test_p6g6_missing_processing")
        message = self._message("d15", "缺失仍不可推断")
        topic = self._topic(message)
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_CREATED_BY, created_at=CREATED)
        self.topic_store.write_audit({
            "conversation_id": CONV,
            "message_id": message["id"],
            "topic_decision": "NEW_TOPIC",
            "topic_id": topic["id"],
        })
        view = self._assert_same_classification(message)
        self.assertEqual(view["topic"]["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertFalse(view["topic"]["retryable"])
        self.assertIsNone(self.topic_store.get_processing(CONV, message["id"]))

    def test_diag_source_has_no_write_or_execution_paths(self):
        path = os.path.join(ROOT, "operations_diagnostic_service.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for token in (
            "write_processing",
            "commit_apply",
            "create_topic",
            "create_task",
            "create_decision",
            "create_risk",
            "retry_topic(",
            "retry_downstream(",
            "Engine(",
            "Extractor",
            "send_reply",
        ):
            self.assertNotIn(token, text)
        self.assertIn("AUDIT_LIMIT = 20", text)
        self.assertEqual(AUDIT_LIMIT, 20)

    def test_diag_audit_returns_latest_twenty(self):
        message = self._message("dlim", "审计上限")
        for index in range(25):
            self.topic_store.write_audit({
                "ts": "2026-09-23T08:%02d:00Z" % index,
                "conversation_id": CONV,
                "message_id": message["id"],
                "topic_decision": "FAILED" if index == 0 else "SKIPPED",
                "error": "n-%s" % index,
            })
        block = self.service.get_message_diagnostics(message["id"], CONV)["topic"]
        self.assertEqual(len(block["audit_events"]), 20)
        self.assertEqual(block["audit_matched_count"], 25)
        self.assertEqual(block["audit_events"][0]["error"], "n-5")
        self.assertEqual(block["audit_events"][-1]["error"], "n-24")
        self.assertIn(FLAG_AUDIT_FAILED_PRESENT, block["diagnostic_flags"])
        self.assertEqual(block["state"], STATE_NOT_FOUND_UNKNOWN)

    def _app(self):
        app = Flask(__name__, template_folder=os.path.join(ROOT, "templates"))
        app.secret_key = "p7g2-test"

        def login_required(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapped

        @app.route("/")
        def index():
            return "home"

        register_operations_routes(app, login_required, self.root)
        return app

    def _run_module(self, name):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        if tests_dir not in sys.path:
            sys.path.insert(0, tests_dir)
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        problems = []
        for test, err in list(result.failures) + list(result.errors):
            problems.append("%s\n%s" % (test, err[-800:]))
        self.assertTrue(result.wasSuccessful(), "\n".join(problems[:4]))


if __name__ == "__main__":
    unittest.main()
