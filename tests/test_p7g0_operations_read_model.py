# -*- coding: utf-8 -*-
"""P7-G0 Operations Read Model：OPS-01 ～ OPS-14。只读分类，不执行 retry。"""

from __future__ import annotations

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
from downstream_retry import ERROR_NOT_FOUND as DOWNSTREAM_NOT_FOUND
from downstream_retry import is_retryable_status as downstream_is_retryable
from flask import Flask
from operations_read_model import (
    RETRY_DOWNSTREAM,
    RETRY_NONE,
    RETRY_TOPIC,
    STATE_FAILED_RETRYABLE,
    STATE_NOT_FOUND_UNKNOWN,
    STATE_SUCCESS,
    OperationsReadModel,
)
from operations_routes import register_operations_routes
from risk_engine import RISK_ENGINE_ENABLED
from risk_sidepath import is_risk_engine_enabled
from risk_store import RiskStore
from task_engine import TASK_ENGINE_ENABLED
from task_sidepath import is_task_engine_enabled
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_retry import ERROR_NOT_FOUND as TOPIC_NOT_FOUND
from topic_retry import is_retryable_status as topic_is_retryable
from topic_retry import processing_status as topic_processing_status
from topic_sidepath import is_topic_engine_enabled
from topic_store import RELATION_CREATED_BY, TopicStore

CONV = "conv_p7g0ops"
CREATED = "2026-09-23T08:00:00Z"
LATER = "2026-09-23T09:00:00Z"


class OperationsReadModelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.topic_store = TopicStore(self.root)
        self.task_store = TaskStore(self.root, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.root, topic_store=self.topic_store)
        self.risk_store = RiskStore(self.root, topic_store=self.topic_store, task_store=self.task_store)
        self.model = OperationsReadModel(self.root, runtime_status={
            "state": "RUNNING",
            "emergency": False,
            "wechat": "disconnected",
            "pid": 4242,
        })

    def tearDown(self):
        self._tmp.cleanup()

    def _message(self, platform_id, content, created_at=CREATED):
        return self.topic_store.upsert_message({
            "conversation_id": CONV,
            "platform_message_id": platform_id,
            "content": content,
            "created_at": created_at,
            "ingested_at": created_at,
            "sender_name": "测试",
            "direction": "INBOUND",
            "message_type": "text",
        })

    def test_ops01_topic_success(self):
        message = self._message("p1", "新主题")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "topic_id": "topic_ops01",
            "processed_at": CREATED,
        })
        view = self.model.get_message(message["id"])["topic"]
        self.assertEqual(view["state"], STATE_SUCCESS)
        self.assertEqual(view["decision"], "NEW_TOPIC")
        self.assertFalse(view["retryable"])
        self.assertEqual(view["retry_type"], RETRY_NONE)
        self.assertFalse(view["requires_manual_investigation"])
        self.assertEqual(view["state_label"], "已处理")
        self.assertEqual(view["entity_ids"], ["topic_ops01"])

    def test_ops02_topic_failed_retry_type(self):
        message = self._message("p2", "主题失败")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "FAILED",
            "error": "RuntimeError: boom",
            "processed_at": CREATED,
        })
        view = self.model.get_message(message["id"])["topic"]
        self.assertEqual(view["state"], STATE_FAILED_RETRYABLE)
        self.assertTrue(view["retryable"])
        self.assertEqual(view["retry_type"], RETRY_TOPIC)
        self.assertEqual(view["error"], "RuntimeError: boom")
        self.assertEqual(view["error_code"], "")
        self.assertEqual(view["state_label"], "处理失败，可重试")

    def test_ops03_task_failed_downstream(self):
        message = self._message("p3", "任务失败")
        self.task_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "FAILED",
            "topic_id": "topic_ops03",
            "error": "RuntimeError: task",
            "processed_at": CREATED,
        })
        view = self.model.get_message(message["id"])["task"]
        self.assertEqual(view["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(view["retry_type"], RETRY_DOWNSTREAM)
        self.assertTrue(view["retryable"])
        self.assertEqual(view["decision"], "FAILED")

    def test_ops04_decision_failed(self):
        message = self._message("p4", "决策失败")
        self.decision_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "FAILED",
            "error": "RuntimeError: decision",
            "processed_at": CREATED,
        })
        view = self.model.get_message(message["id"])["decision"]
        self.assertEqual(view["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(view["retry_type"], RETRY_DOWNSTREAM)
        self.assertTrue(view["retryable"])

    def test_ops05_risk_failed(self):
        message = self._message("p5", "风险失败")
        self.risk_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "FAILED",
            "error": "RuntimeError: risk",
            "processed_at": CREATED,
        })
        view = self.model.get_message(message["id"])["risk"]
        self.assertEqual(view["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(view["retry_type"], RETRY_DOWNSTREAM)
        self.assertTrue(view["retryable"])

    def test_ops06_missing_processing_is_unknown(self):
        message = self._message("p6", "没有 processing")
        topic = self.topic_store.create_topic(
            CONV,
            title="已经存在的主题",
            created_msg_id=message["id"],
            created_at=CREATED,
        )
        self.topic_store.add_link(CONV, topic["id"], message["id"], RELATION_CREATED_BY, created_at=CREATED)
        self.topic_store.write_audit({
            "conversation_id": CONV,
            "message_id": message["id"],
            "topic_decision": "NEW_TOPIC",
            "topic_id": topic["id"],
        })
        view = self.model.get_message(message["id"])["topic"]
        self.assertIsNone(self.topic_store.get_processing(CONV, message["id"]))
        self.assertEqual(view["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertFalse(view["retryable"])
        self.assertEqual(view["retry_type"], RETRY_NONE)
        self.assertTrue(view["requires_manual_investigation"])
        self.assertEqual(view["state_label"], "处理状态未知，需人工检查")
        self.assertIn("processing record not found", view["notice"])
        self.assertIn("automatic retry disabled", view["notice"])
        self.assertIn("manual investigation required", view["notice"])
        self.assertEqual(view["last_audit_event"], "NEW_TOPIC")
        self.assertEqual(view["decision"], "")
        self.assertEqual(view["entity_ids"], [])
        self.assertEqual(view["source_timestamp"]["source"], "message.created_at")
        self.assertEqual(view["source_timestamp"]["value"], CREATED)

    def test_ops07_unrelated_is_success(self):
        message = self._message("p7", "无关")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "UNRELATED",
            "processed_at": CREATED,
        })
        row = self.model.get_message(message["id"])
        view = row["topic"]
        self.assertEqual(view["state"], STATE_SUCCESS)
        self.assertEqual(view["decision"], "UNRELATED")
        self.assertFalse(view["retryable"])
        self.assertFalse(view["requires_manual_investigation"])
        self.assertNotEqual(view["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(view["state_label"], "已处理")

    def test_ops08_skipped_is_success(self):
        message = self._message("p8", "跳过")
        self.task_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "SKIPPED",
            "processed_at": CREATED,
        })
        view = self.model.get_message(message["id"])["task"]
        self.assertEqual(view["state"], STATE_SUCCESS)
        self.assertEqual(view["decision"], "SKIPPED")
        self.assertFalse(view["retryable"])

    def test_ops09_engines_stay_independent(self):
        message = self._message("p9", "四路互不覆盖")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "topic_id": "topic_ops09",
            "processed_at": CREATED,
        })
        self.decision_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "UNRELATED",
            "processed_at": CREATED,
        })
        self.risk_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "FAILED",
            "error": "RuntimeError: risk",
            "processed_at": LATER,
        })
        row = self.model.get_message(message["id"])
        self.assertEqual(row["topic"]["state"], STATE_SUCCESS)
        self.assertEqual(row["topic"]["decision"], "NEW_TOPIC")
        self.assertEqual(row["task"]["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertFalse(row["task"]["retryable"])
        self.assertEqual(row["decision"]["state"], STATE_SUCCESS)
        self.assertEqual(row["decision"]["decision"], "UNRELATED")
        self.assertEqual(row["risk"]["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(row["risk"]["retry_type"], RETRY_DOWNSTREAM)
        self.assertTrue(row["attention_required"])
        self.assertNotEqual(row["topic"]["state"], row["risk"]["state"])

    def test_ops10_attention_only_for_failed_or_unknown(self):
        ok = self._message("p10a", "正常", CREATED)
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": ok["id"],
            "decision": "EXISTING_TOPIC",
            "processed_at": CREATED,
        })
        self.task_store.write_processing({
            "conversation_id": CONV,
            "message_id": ok["id"],
            "decision_summary": "NEW_TASK",
            "processed_at": CREATED,
        })
        self.decision_store.write_processing({
            "conversation_id": CONV,
            "message_id": ok["id"],
            "decision_summary": "NEW_DECISION",
            "processed_at": CREATED,
        })
        self.risk_store.write_processing({
            "conversation_id": CONV,
            "message_id": ok["id"],
            "decision_summary": "NEW_RISK",
            "processed_at": CREATED,
        })
        failed = self._message("p10b", "失败", LATER)
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": failed["id"],
            "decision": "TOPIC_UPDATE",
            "processed_at": LATER,
        })
        self.task_store.write_processing({
            "conversation_id": CONV,
            "message_id": failed["id"],
            "decision_summary": "FAILED",
            "processed_at": LATER,
        })
        self.decision_store.write_processing({
            "conversation_id": CONV,
            "message_id": failed["id"],
            "decision_summary": "SKIPPED",
            "processed_at": LATER,
        })
        self.risk_store.write_processing({
            "conversation_id": CONV,
            "message_id": failed["id"],
            "decision_summary": "RISK_UPDATE",
            "processed_at": LATER,
        })
        unknown = self._message("p10c", "未知", "2026-09-23T07:00:00Z")
        ok_row = self.model.get_message(ok["id"])
        failed_row = self.model.get_message(failed["id"])
        unknown_row = self.model.get_message(unknown["id"])
        self.assertFalse(ok_row["attention_required"])
        self.assertTrue(failed_row["attention_required"])
        self.assertTrue(failed_row["task"]["retryable"])
        self.assertFalse(failed_row["topic"]["retryable"])
        self.assertTrue(unknown_row["attention_required"])
        self.assertTrue(unknown_row["topic"]["requires_manual_investigation"])
        issues = self.model.issues(limit=20)
        stamps = [item["source_timestamp"]["value"] for item in issues]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        unknown_issue = next(item for item in issues if item["message_id"] == unknown["id"] and item["engine"] == "topic")
        self.assertEqual(unknown_issue["source_timestamp"]["source"], "message.created_at")
        failed_issue = next(item for item in issues if item["message_id"] == failed["id"] and item["engine"] == "task")
        self.assertEqual(failed_issue["source_timestamp"]["source"], "processing.processed_at")
        self.assertNotIn(ok["id"], [item["message_id"] for item in issues])

    def test_ops11_disabled_flag_does_not_forge_failed(self):
        message = self._message("p11", "开关关闭仍成功")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "processed_at": CREATED,
        })
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)
        self.assertFalse(is_topic_engine_enabled())
        self.assertFalse(is_task_engine_enabled())
        self.assertFalse(is_decision_engine_enabled())
        self.assertFalse(is_risk_engine_enabled())
        row = self.model.get_message(message["id"])
        self.assertFalse(row["topic"]["engine_enabled"])
        self.assertEqual(row["topic"]["state"], STATE_SUCCESS)
        self.assertNotEqual(row["topic"]["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(row["task"]["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertFalse(row["task"]["engine_enabled"])
        self.assertFalse(row["task"]["retryable"])
        flags = self.model.engine_flags()
        self.assertFalse(flags["topic_enabled"])
        self.assertFalse(flags["task_enabled"])
        self.assertFalse(flags["decision_enabled"])
        self.assertFalse(flags["risk_enabled"])

    def test_ops12_stopped_runtime_still_reads(self):
        message = self._message("p12", "停止后仍只读")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "processed_at": CREATED,
        })
        before = self.topic_store.get_processing(CONV, message["id"])
        stopped = OperationsReadModel(self.root, runtime_status={
            "state": "STOPPED",
            "emergency": False,
            "wechat": "disconnected",
            "pid": 7,
        })
        runtime = stopped.runtime_view()
        row = stopped.get_message(message["id"])
        after = self.topic_store.get_processing(CONV, message["id"])
        self.assertEqual(runtime["runtime_state"], "STOPPED")
        self.assertFalse(runtime["is_accepting_work"])
        self.assertEqual(runtime["bot_pid"], 7)
        self.assertIs(runtime["wechat_connected"], False)
        self.assertIsNone(runtime["listen_count"])
        self.assertEqual(row["topic"]["state"], STATE_SUCCESS)
        self.assertFalse(row["topic"]["runtime_accepting_work"])
        self.assertEqual(before, after)
        self.assertIsNone(self.task_store.get_processing(CONV, message["id"]))

    def test_ops13_source_has_no_write_or_retry_calls(self):
        path = os.path.join(ROOT, "operations_read_model.py")
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("write_processing", text)
        self.assertNotIn("retry_topic(", text)
        self.assertNotIn("retry_downstream(", text)
        self.assertNotIn("send_reply", text)
        routes = os.path.join(ROOT, "operations_routes.py")
        with open(routes, "r", encoding="utf-8") as handle:
            route_text = handle.read()
        self.assertNotIn("methods=['POST']", route_text)
        self.assertNotIn('methods=["POST"]', route_text)
        self.assertNotIn("retry_topic(", route_text)
        self.assertNotIn("retry_downstream(", route_text)

    def test_ops14_not_found_contract_stays_closed(self):
        message = self._message("p14", "缺失契约")
        view = self.model.get_message(message["id"])["risk"]
        self.assertEqual(TOPIC_NOT_FOUND, "NOT_FOUND")
        self.assertEqual(DOWNSTREAM_NOT_FOUND, "NOT_FOUND")
        self.assertFalse(topic_is_retryable(topic_processing_status(None)))
        self.assertFalse(downstream_is_retryable(""))
        self.assertEqual(view["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertFalse(view["retryable"])
        self.assertEqual(view["retry_type"], RETRY_NONE)
        self.assertTrue(view["requires_manual_investigation"])

    def test_readonly_api_and_page(self):
        message = self._message("papi", "接口消息")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "FAILED",
            "error": "RuntimeError: api",
            "processed_at": CREATED,
        })
        app = Flask(__name__, template_folder=os.path.join(ROOT, "templates"))
        app.secret_key = "p7g0-test"

        def login_required(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapped

        @app.route("/")
        def index():
            return "home"

        register_operations_routes(app, login_required, self.root)
        client = app.test_client()
        status = client.get("/api/operations/status")
        self.assertEqual(status.status_code, 200)
        runtime = status.get_json()["runtime"]
        self.assertIn("runtime_state", runtime)
        self.assertIn("is_accepting_work", runtime)
        self.assertIn("bot_pid", runtime)
        self.assertIn("wechat_connected", runtime)
        self.assertIn("listen_count", runtime)
        self.assertEqual(status.get_json()["engines"]["topic_enabled"], is_topic_engine_enabled())
        self.assertFalse(status.get_json()["engines"]["topic_enabled"])
        issues = client.get("/api/operations/issues")
        self.assertEqual(issues.status_code, 200)
        self.assertTrue(any(item["message_id"] == message["id"] for item in issues.get_json()["issues"]))
        detail = client.get("/api/operations/messages/%s" % message["id"])
        body = detail.get_json()
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(body["topic"]["state"], STATE_FAILED_RETRYABLE)
        self.assertIn("processing record not found", body["task"]["notice"])
        missing = client.get("/api/operations/messages/msg_missing")
        self.assertEqual(missing.status_code, 404)
        page = client.get("/operations")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("处理状态未知，需人工检查", html)
        self.assertIn("processing record not found", html)
        self.assertNotIn("retry_topic", html)
        self.assertNotIn("retry_downstream", html)
        posted = client.post("/api/operations/issues")
        self.assertEqual(posted.status_code, 405)


if __name__ == "__main__":
    unittest.main()
