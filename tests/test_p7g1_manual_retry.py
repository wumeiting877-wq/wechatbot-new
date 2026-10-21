# -*- coding: utf-8 -*-
"""P7-G1 人工单条重试。ACTION-01 ～ ACTION-18。"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from functools import wraps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED
from decision_extractor_client import HeuristicDecisionExtractor
from decision_sidepath import DecisionSidepath
from decision_store import DecisionStore
from downstream_retry import ERROR_NOT_FOUND as DOWNSTREAM_NOT_FOUND
from downstream_retry import is_retryable_status as downstream_is_retryable
from flask import Flask, jsonify
from operations_action_audit import EVENT_REQUESTED, EVENT_RESULT, read_action_audit
from operations_action_routes import register_operations_action_routes
from operations_action_service import (
    MSG_UNKNOWN,
    OperationsActionService,
)
from operations_read_model import (
    STATE_FAILED_RETRYABLE,
    STATE_NOT_FOUND_UNKNOWN,
    STATE_SUCCESS,
    OperationsReadModel,
)
from operations_routes import register_operations_routes
from risk_engine import RISK_ENGINE_ENABLED
from risk_extractor_client import HeuristicRiskExtractor
from risk_sidepath import RiskSidepath
from risk_store import RiskStore
from task_engine import TASK_ENGINE_ENABLED
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import TaskSidepath
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_extractor_client import HeuristicTopicExtractor
from topic_retry import ERROR_NOT_FOUND as TOPIC_NOT_FOUND
from topic_retry import TopicRetryService, is_retryable_status as topic_is_retryable
from topic_sidepath import TopicSidepath
from topic_store import TopicStore

CONV = "conv_p7g1act"
CREATED = "2026-09-23T08:00:00Z"
_ENV = {
    "topic": "TOPIC_ENGINE_ENABLED",
    "task": "TASK_ENGINE_ENABLED",
    "decision": "DECISION_ENGINE_ENABLED",
    "risk": "RISK_ENGINE_ENABLED",
}


class _Outcome:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def as_dict(self):
        return {
            "ok": bool(self.__dict__.get("ok")),
            "executed": bool(self.__dict__.get("executed")),
            "result": self.__dict__.get("result") or "",
            "error_code": self.__dict__.get("error_code") or "",
            "error": self.__dict__.get("error") or "",
            "decision": self.__dict__.get("decision") or "",
        }


class FakeTopicRetry:
    def __init__(self, store, *, decision="NEW_TOPIC", sleep=0):
        self.store = store
        self.decision = decision
        self.sleep = sleep
        self.calls = 0
        self.inflight = 0
        self.max_inflight = 0
        self._lock = threading.Lock()

    def retry_topic(self, conversation_id, message_id, *, version=0, runtime=None):
        with self._lock:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            self.calls += 1
            if self.sleep:
                time.sleep(self.sleep)
            self.store.write_processing({
                "conversation_id": conversation_id,
                "message_id": message_id,
                "decision": self.decision,
                "topic_id": "topic_after",
                "processed_at": "2026-09-23T10:00:00Z",
            })
            return _Outcome(ok=True, executed=True, result="SUCCESS", decision=self.decision)
        finally:
            with self._lock:
                self.inflight -= 1


class FakeDownstreamRetry:
    def __init__(self, stores, *, decision="NEW_TASK", sleep=0):
        self.stores = stores
        self.decision = decision
        self.sleep = sleep
        self.calls = []
        self.inflight = 0
        self.max_inflight = 0
        self._lock = threading.Lock()

    def retry_downstream(
        self,
        engine,
        conversation_id,
        message_id,
        topic_id="",
        *,
        version=0,
        runtime=None,
    ):
        with self._lock:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            self.calls.append(engine)
            if self.sleep:
                time.sleep(self.sleep)
            self.stores[engine].write_processing({
                "conversation_id": conversation_id,
                "message_id": message_id,
                "decision_summary": self.decision,
                "topic_id": topic_id or "topic_down",
                "processed_at": "2026-09-23T10:00:00Z",
            })
            return _Outcome(ok=True, executed=True, result="SUCCESS", decision=self.decision)
        finally:
            with self._lock:
                self.inflight -= 1


class AcceptingRuntime:
    state = "RUNNING"

    def is_accepting_work(self):
        return True

    def register_stop_hook(self, _hook):
        return None

    def register_emergency_hook(self, _hook):
        return None


class ManualRetryActionTests(unittest.TestCase):
    def setUp(self):
        self._saved_flags = {}
        clear_stop_request()
        clear_emergency_stop()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.topic_store = TopicStore(self.root)
        self.task_store = TaskStore(self.root, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.root, topic_store=self.topic_store)
        self.risk_store = RiskStore(self.root, topic_store=self.topic_store, task_store=self.task_store)
        self.model = OperationsReadModel(self.root, runtime_status={
            "state": "RUNNING",
            "emergency": False,
            "pid": 7,
        })
        self.topic_fake = FakeTopicRetry(self.topic_store)
        self.down_fake = FakeDownstreamRetry({
            "task": self.task_store,
            "decision": self.decision_store,
            "risk": self.risk_store,
        })
        self.service = OperationsActionService(
            self.root,
            read_model=self.model,
            topic_service=self.topic_fake,
            downstream_service=self.down_fake,
            runtime=AcceptingRuntime(),
        )

    def tearDown(self):
        for path, content in list(self._saved_flags.items()):
            if content is None:
                if os.path.isfile(path):
                    os.remove(path)
            else:
                with open(path, "wb") as handle:
                    handle.write(content)
        for key in _ENV.values():
            os.environ.pop(key, None)
        self._tmp.cleanup()
        clear_stop_request()
        clear_emergency_stop()

    def _enable(self, *names):
        control = os.path.join(ROOT, "runtime_control")
        os.makedirs(control, exist_ok=True)
        for name in names:
            path = os.path.join(control, _ENV[name])
            if path not in self._saved_flags:
                if os.path.isfile(path):
                    with open(path, "rb") as handle:
                        self._saved_flags[path] = handle.read()
                else:
                    self._saved_flags[path] = None
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("true")

    def _message(self, platform_id, content="人工重试消息"):
        return self.topic_store.upsert_message({
            "conversation_id": CONV,
            "platform_message_id": platform_id,
            "content": content,
            "created_at": CREATED,
            "ingested_at": CREATED,
            "sender_name": "测试",
            "direction": "INBOUND",
            "message_type": "text",
        })

    def _fail(self, store, message, *, decision="FAILED", summary=False):
        payload = {
            "conversation_id": CONV,
            "message_id": message["id"],
            "error": "RuntimeError: boom",
            "processed_at": CREATED,
            "topic_id": "topic_seed",
        }
        if summary:
            payload["decision_summary"] = decision
        else:
            payload["decision"] = decision
        return store.write_processing(payload)

    def _retry(self, engine, message, version=1):
        return self.service.manual_retry(engine, CONV, message["id"], version)

    def test_action_01_topic_failed_retries_once(self):
        self._enable("topic")
        message = self._message("a01")
        self._fail(self.topic_store, message)
        result = self._retry("topic", message)
        self.assertEqual(result.http_status, 200)
        self.assertTrue(result.executed)
        self.assertEqual(self.topic_fake.calls, 1)
        self.assertEqual(self.down_fake.calls, [])
        self.assertEqual(result.before_state["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(result.after_state["state"], STATE_SUCCESS)
        self.assertEqual(result.after_state["decision"], "NEW_TOPIC")
        events = [item["event"] for item in read_action_audit(self.root)]
        self.assertIn(EVENT_REQUESTED, events)
        self.assertIn(EVENT_RESULT, events)
        for item in read_action_audit(self.root):
            self.assertNotIn("actor", item)

    def test_action_02_task_retries_only_task(self):
        self._enable("task")
        message = self._message("a02")
        self._fail(self.task_store, message, summary=True)
        result = self._retry("task", message)
        self.assertTrue(result.executed)
        self.assertEqual(self.down_fake.calls, ["task"])
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(result.after_state["state"], STATE_SUCCESS)
        self.assertEqual(result.after_state["decision"], "NEW_TASK")

    def test_action_03_decision_retries_only_decision(self):
        self._enable("decision")
        self.down_fake.decision = "NEW_DECISION"
        message = self._message("a03")
        self._fail(self.decision_store, message, summary=True)
        result = self._retry("decision", message)
        self.assertTrue(result.executed)
        self.assertEqual(self.down_fake.calls, ["decision"])
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(result.after_state["decision"], "NEW_DECISION")

    def test_action_04_risk_retries_only_risk(self):
        self._enable("risk")
        self.down_fake.decision = "NEW_RISK"
        message = self._message("a04")
        self._fail(self.risk_store, message, summary=True)
        result = self._retry("risk", message)
        self.assertTrue(result.executed)
        self.assertEqual(self.down_fake.calls, ["risk"])
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(result.after_state["decision"], "NEW_RISK")

    def test_action_05_success_is_not_retryable(self):
        self._enable("topic")
        message = self._message("a05")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "topic_id": "topic_ok",
            "processed_at": CREATED,
        })
        result = self._retry("topic", message)
        self.assertEqual(result.http_status, 409)
        self.assertFalse(result.executed)
        self.assertEqual(result.error_code, "NOT_RETRYABLE")
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(result.after_state["state"], STATE_SUCCESS)

    def test_action_06_unrelated_is_not_retryable(self):
        self._enable("topic")
        message = self._message("a06")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "UNRELATED",
            "processed_at": CREATED,
        })
        result = self._retry("topic", message)
        self.assertEqual(result.http_status, 409)
        self.assertFalse(result.executed)
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(result.after_state["state"], STATE_SUCCESS)

    def test_action_07_skipped_is_not_retryable(self):
        self._enable("task")
        message = self._message("a07")
        self.task_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "SKIPPED",
            "topic_id": "topic_seed",
            "processed_at": CREATED,
        })
        result = self._retry("task", message)
        self.assertEqual(result.http_status, 409)
        self.assertFalse(result.executed)
        self.assertEqual(self.down_fake.calls, [])
        self.assertEqual(result.after_state["state"], STATE_SUCCESS)

    def test_action_08_unknown_never_retries(self):
        self._enable("topic", "task", "decision", "risk")
        message = self._message("a08")
        result = self._retry("topic", message)
        self.assertEqual(result.http_status, 409)
        self.assertFalse(result.executed)
        self.assertEqual(result.error_code, "NOT_FOUND_UNKNOWN")
        self.assertEqual(result.error, MSG_UNKNOWN)
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(self.down_fake.calls, [])
        for engine in ("task", "decision", "risk"):
            again = self._retry(engine, message)
            self.assertFalse(again.executed)
            self.assertEqual(again.error_code, "NOT_FOUND_UNKNOWN")
        self.assertEqual(self.down_fake.calls, [])

    def test_action_09_stale_success_is_rejected(self):
        self._enable("topic")
        message = self._message("a09")
        self._fail(self.topic_store, message)
        self.assertEqual(
            self.model.engine_view("topic", CONV, message["id"])["state"],
            STATE_FAILED_RETRYABLE,
        )
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "topic_id": "topic_now",
            "processed_at": CREATED,
        })
        result = self._retry("topic", message)
        self.assertEqual(result.http_status, 409)
        self.assertEqual(result.error_code, "NOT_RETRYABLE")
        self.assertFalse(result.executed)
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(result.after_state["state"], STATE_SUCCESS)

    def test_action_09_version_mismatch_is_rejected(self):
        self._enable("topic")
        message = self._message("a09b")
        self._fail(self.topic_store, message)
        result = self._retry("topic", message, version=2)
        self.assertEqual(result.http_status, 409)
        self.assertFalse(result.executed)
        self.assertEqual(self.topic_fake.calls, 0)

    def test_action_10_runtime_stopped(self):
        self._enable("topic")
        self.model = OperationsReadModel(self.root, runtime_status={"state": "STOPPED", "emergency": False})
        self.service.read_model = self.model
        message = self._message("a10")
        self._fail(self.topic_store, message)
        result = self._retry("topic", message)
        self.assertEqual(result.http_status, 423)
        self.assertEqual(result.error_code, "STOPPED")
        self.assertFalse(result.executed)
        self.assertEqual(self.topic_fake.calls, 0)

    def test_action_11_engine_disabled(self):
        message = self._message("a11")
        self._fail(self.topic_store, message)
        result = self._retry("topic", message)
        self.assertEqual(result.http_status, 409)
        self.assertEqual(result.error_code, "ENGINE_DISABLED")
        self.assertFalse(result.executed)
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertFalse(TOPIC_ENGINE_ENABLED)

    def test_action_12_topic_success_follows_downstream_flags(self):
        clear_stop_request()
        clear_emergency_stop()
        runtime = AcceptingRuntime()
        task_path = TaskSidepath(
            root_dir=self.root,
            extractor=HeuristicTaskExtractor(),
            maxsize=8,
            prompt_root=ROOT,
        )
        decision_path = DecisionSidepath(
            root_dir=self.root,
            extractor=HeuristicDecisionExtractor(),
            maxsize=8,
            prompt_root=ROOT,
        )
        risk_path = RiskSidepath(
            root_dir=self.root,
            extractor=HeuristicRiskExtractor(),
            maxsize=8,
            prompt_root=ROOT,
        )
        sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[{"id": CONV, "display_name": "测试群", "enabled": True}],
            extractor=HeuristicTopicExtractor(),
            maxsize=8,
            prompt_root=ROOT,
            task_sidepath=task_path,
            decision_sidepath=decision_path,
            risk_sidepath=risk_path,
        )
        topic_service = TopicRetryService(
            topic_sidepath=sidepath,
            runtime=runtime,
            conversation={"id": CONV, "display_name": "测试群", "enabled": True},
        )
        action = OperationsActionService(
            self.root,
            read_model=self.model,
            topic_service=topic_service,
            runtime=runtime,
        )
        try:
            self._enable("topic")
            blocked = self._message("a12-off", "ERP 同步今天还是有问题。")
            self._fail(self.topic_store, blocked)
            quiet = action.manual_retry("topic", CONV, blocked["id"], 1)
            self.assertTrue(quiet.executed, quiet.error)
            self.assertEqual(quiet.after_state["state"], STATE_SUCCESS)
            self.assertEqual(task_path.enqueued_count, 0)
            self.assertEqual(decision_path.enqueued_count, 0)
            self.assertEqual(risk_path.enqueued_count, 0)
            self._enable("task", "decision", "risk")
            opened = self._message("a12-on", "ERP 同步今天还是有问题。")
            self._fail(self.topic_store, opened)
            loud = action.manual_retry("topic", CONV, opened["id"], 1)
            self.assertTrue(loud.executed, loud.error)
            self.assertIn(loud.after_state["decision"], ("NEW_TOPIC", "EXISTING_TOPIC", "TOPIC_UPDATE"))
            self.assertEqual(task_path.enqueued_count, 1)
            self.assertEqual(decision_path.enqueued_count, 1)
            self.assertEqual(risk_path.enqueued_count, 1)
        finally:
            sidepath.shutdown()
            task_path.shutdown()
            decision_path.shutdown()
            risk_path.shutdown()

    def test_action_13_task_retry_does_not_touch_other_chains(self):
        self._enable("task")
        message = self._message("a13")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision": "NEW_TOPIC",
            "topic_id": "topic_seed",
            "processed_at": CREATED,
        })
        self._fail(self.task_store, message, summary=True)
        self.decision_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "NEW_DECISION",
            "topic_id": "topic_seed",
            "processed_at": CREATED,
        })
        self.risk_store.write_processing({
            "conversation_id": CONV,
            "message_id": message["id"],
            "decision_summary": "NEW_RISK",
            "topic_id": "topic_seed",
            "processed_at": CREATED,
        })
        before = (
            self.topic_store.get_processing(CONV, message["id"]),
            self.decision_store.get_processing(CONV, message["id"]),
            self.risk_store.get_processing(CONV, message["id"]),
        )
        result = self._retry("task", message)
        self.assertTrue(result.executed)
        self.assertEqual(self.down_fake.calls, ["task"])
        after = (
            self.topic_store.get_processing(CONV, message["id"]),
            self.decision_store.get_processing(CONV, message["id"]),
            self.risk_store.get_processing(CONV, message["id"]),
        )
        self.assertEqual(before, after)

    def test_action_14_same_identity_cannot_run_twice_at_once(self):
        self._enable("topic")
        self.topic_fake.sleep = 0.05
        message = self._message("a14")
        self._fail(self.topic_store, message)
        barrier = threading.Barrier(2)
        results = [None, None]

        def worker(index):
            barrier.wait()
            results[index] = self._retry("topic", message)

        threads = [threading.Thread(target=worker, args=(index,)) for index in (0, 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertTrue(all(item is not None for item in results))
        executed = [item for item in results if item.executed]
        rejected = [item for item in results if not item.executed]
        self.assertEqual(len(executed), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].error_code, "NOT_RETRYABLE")
        self.assertEqual(self.topic_fake.calls, 1)
        self.assertEqual(self.topic_fake.max_inflight, 1)

    def test_action_15_and_16_retry_button_only_on_failed(self):
        app = Flask(__name__, template_folder=os.path.join(ROOT, "templates"))
        app.secret_key = "p7g1-page"

        def login_required(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapped

        @app.route("/")
        def index():
            return "home"

        register_operations_routes(app, login_required, self.root)
        failed = self._message("a15", "任务失败可重试")
        self.topic_store.write_processing({
            "conversation_id": CONV,
            "message_id": failed["id"],
            "decision": "UNRELATED",
            "processed_at": CREATED,
        })
        self._fail(self.task_store, failed, summary=True)
        self.decision_store.write_processing({
            "conversation_id": CONV,
            "message_id": failed["id"],
            "decision_summary": "SKIPPED",
            "topic_id": "topic_seed",
            "processed_at": CREATED,
        })
        unknown = self._message("a16", "状态未知")
        client = app.test_client()
        page = client.get("/operations")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("retry_topic", html)
        self.assertNotIn("retry_downstream", html)
        self.assertNotIn("重试全部", html)
        self.assertIn("正在重试…", html)
        self.assertIn("可能按现有规则再次触发", html)
        self.assertIn("不会重新执行 Topic", html)
        self.assertIn("data-busy", html)
        failed_row = _row_html(html, failed["id"])
        unknown_row = _row_html(html, unknown["id"])
        self.assertIn("retry-btn", _cell(failed_row, "task"))
        self.assertNotIn("retry-btn", _cell(failed_row, "topic"))
        self.assertNotIn("retry-btn", _cell(failed_row, "decision"))
        self.assertNotIn("retry-btn", _cell(failed_row, "risk"))
        self.assertIn("处理状态未知，需人工检查", unknown_row)
        self.assertNotIn("retry-btn", unknown_row)
        self.assertIn("已处理", failed_row)
        self.assertIn("处理失败，可重试", failed_row)

    def test_action_17_post_uses_existing_login_boundary(self):
        app = Flask(__name__)
        app.secret_key = "p7g1-auth"
        state = {"deny": False, "allow_write": False}

        def login_required(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                if state["deny"]:
                    return jsonify({"error": "login"}), 401
                return func(*args, **kwargs)
            return wrapped

        self._enable("topic")
        message = self._message("a17")
        self._fail(self.topic_store, message)
        register_operations_action_routes(
            app,
            login_required,
            self.root,
            write_allowed=lambda: state["allow_write"],
            action_service=self.service,
        )
        client = app.test_client()
        url = "/api/operations/messages/%s/retry" % message["id"]
        body = {"conversation_id": CONV, "engine": "topic", "version": 1}
        state["deny"] = True
        denied = client.post(url, json=body)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(self.topic_fake.calls, 0)
        state["deny"] = False
        closed = client.post(url, json=body)
        self.assertEqual(closed.status_code, 403)
        self.assertFalse(closed.get_json()["executed"])
        self.assertEqual(closed.get_json()["error_code"], "AUTH_REQUIRED")
        self.assertEqual(self.topic_fake.calls, 0)
        state["allow_write"] = True
        opened = client.post(url, json=body)
        self.assertEqual(opened.status_code, 200)
        payload = opened.get_json()
        self.assertTrue(payload["executed"])
        self.assertEqual(payload["before_state"]["state"], STATE_FAILED_RETRYABLE)
        self.assertEqual(payload["after_state"]["state"], STATE_SUCCESS)
        self.assertIn("retry_result", payload)
        self.assertEqual(self.topic_fake.calls, 1)
        form = client.post(url, data="engine=topic")
        self.assertEqual(form.status_code, 415)
        with open(os.path.join(ROOT, "operations_action_routes.py"), encoding="utf-8") as handle:
            route_text = handle.read()
        self.assertIn("login_required", route_text)
        self.assertIn("ENABLE_LOGIN_PASSWORD", route_text)
        with open(os.path.join(ROOT, "operations_routes.py"), encoding="utf-8") as handle:
            readonly = handle.read()
        self.assertNotIn('methods=["POST"]', readonly)
        self.assertNotIn("methods=['POST']", readonly)

    def test_action_18_missing_processing_contract_unchanged(self):
        self._enable("topic", "task")
        message = self._message("a18")
        result = self._retry("risk", message)
        self.assertFalse(result.executed)
        self.assertEqual(result.error_code, "NOT_FOUND_UNKNOWN")
        self.assertEqual(result.after_state["state"], STATE_NOT_FOUND_UNKNOWN)
        self.assertEqual(self.topic_fake.calls, 0)
        self.assertEqual(self.down_fake.calls, [])
        self.assertEqual(TOPIC_NOT_FOUND, "NOT_FOUND")
        self.assertEqual(DOWNSTREAM_NOT_FOUND, "NOT_FOUND")
        self.assertFalse(topic_is_retryable(""))
        self.assertFalse(downstream_is_retryable(""))
        with open(os.path.join(ROOT, "operations_read_model.py"), encoding="utf-8") as handle:
            read_model = handle.read()
        self.assertNotIn("operations_action_audit", read_model)
        self.assertNotIn("retry_topic(", read_model)
        self.assertNotIn("retry_downstream(", read_model)

    def test_action_source_constraint(self):
        with open(os.path.join(ROOT, "operations_action_service.py"), encoding="utf-8") as handle:
            text = handle.read()
        for token in (
            "TopicEngine(",
            "TaskEngine(",
            "DecisionEngine(",
            "RiskEngine(",
            "write_processing",
            "commit_apply",
            "create_topic",
            "create_task",
            "create_decision",
            "create_risk",
            "send_reply",
        ):
            self.assertNotIn(token, text)
        self.assertIn("retry_topic(", text)
        self.assertIn("retry_downstream(", text)
        with open(os.path.join(ROOT, "operations_action_wiring.py"), encoding="utf-8") as handle:
            wiring = handle.read()
        self.assertNotIn("enabled=True", wiring)
        self.assertNotIn("send_reply", wiring)

    def test_flags_remain_disabled(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)


def _row_html(html: str, message_id: str) -> str:
    marker = 'data-message-id="%s"' % message_id
    start = html.find(marker)
    end = html.find("</tr>", start)
    return html[start:end]


def _cell(row_html: str, engine: str) -> str:
    marker = 'data-engine="%s"' % engine
    start = row_html.find(marker)
    end = row_html.find("</td>", start)
    return row_html[start:end]


if __name__ == "__main__":
    unittest.main()
