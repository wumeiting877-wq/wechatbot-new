# -*- coding: utf-8 -*-
"""P6-G2 Downstream Failure Recovery：显式、独立、一次性的下游 FAILED retry。

只重试 Task / Decision / Risk 中失败的那一路。
不得重跑 Topic，不得 fan-out 另外两路，不得走 Chat / listener。
第一版：同步内部 capability。无 Queue / Scheduler / 自动重试 / WebUI。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from conversation_store import utc_now_iso
from decision_engine import DecisionEngine
from decision_store import DEFAULT_PROCESSING_VERSION as DECISION_PROCESSING_VERSION
from risk_engine import RiskEngine
from risk_store import DEFAULT_PROCESSING_VERSION as RISK_PROCESSING_VERSION
from task_engine import TaskEngine
from task_store import DEFAULT_PROCESSING_VERSION as TASK_PROCESSING_VERSION
from topic_store import TopicStore

ALLOWED_ENGINES = ("task", "decision", "risk")
RETRYABLE_STATUSES = frozenset({"FAILED"})

EVENT_REQUESTED = "DOWNSTREAM_RETRY_REQUESTED"
EVENT_SUCCESS = "DOWNSTREAM_RETRY_SUCCESS"
EVENT_FAILED = "DOWNSTREAM_RETRY_FAILED"
EVENT_REJECTED = "DOWNSTREAM_RETRY_REJECTED"

ERROR_INVALID_ENGINE = "INVALID_ENGINE"
ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_NOT_RETRYABLE = "NOT_RETRYABLE"
ERROR_ENGINE_DISABLED = "ENGINE_DISABLED"
ERROR_STOPPED = "STOPPED"
ERROR_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
ERROR_MISSING_TOPIC = "MISSING_TOPIC"
ERROR_MISSING_MESSAGE = "MISSING_MESSAGE"

RESULT_SUCCESS = "SUCCESS"
RESULT_FAILED = "FAILED"
RESULT_REJECTED = "REJECTED"


def _normalize_engine(engine: str) -> str:
    return str(engine or "").strip().lower()


def processing_status(record: Optional[dict]) -> str:
    data = record if isinstance(record, dict) else {}
    return str(data.get("decision_summary") or data.get("decision") or "").strip()


def is_retryable_status(status: str) -> bool:
    parts = [item.strip() for item in str(status or "").replace(";", ",").split(",") if item.strip()]
    return bool(parts) and all(item in RETRYABLE_STATUSES for item in parts)


def _runtime_accepting(runtime: Any) -> bool:
    if runtime is None:
        return True
    checker = getattr(runtime, "is_accepting_work", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    state = str(getattr(runtime, "state", "") or "").upper()
    if state in ("STOPPING", "STOPPED", "ERROR", "STARTING"):
        return False
    return True


@dataclass
class RetryResult:
    ok: bool = False
    rejected: bool = False
    executed: bool = False
    engine: str = ""
    conversation_id: str = ""
    message_id: str = ""
    topic_id: str = ""
    version: int = 1
    previous_status: str = ""
    result: str = ""
    error_code: str = ""
    error: str = ""
    engine_decision: str = ""
    engine_result: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "rejected": self.rejected,
            "executed": self.executed,
            "engine": self.engine,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "topic_id": self.topic_id,
            "version": self.version,
            "previous_status": self.previous_status,
            "result": self.result,
            "error_code": self.error_code,
            "error": self.error,
            "engine_decision": self.engine_decision,
            "engine_result": dict(self.engine_result or {}),
        }


class DownstreamRetryService:
    """显式 one-shot retry。调用方注入 Engine；不创建 worker / queue。"""

    def __init__(
        self,
        *,
        topic_store: TopicStore,
        task_engine: Optional[TaskEngine] = None,
        decision_engine: Optional[DecisionEngine] = None,
        risk_engine: Optional[RiskEngine] = None,
        runtime: Any = None,
        conversation: Optional[dict] = None,
    ):
        self.topic_store = topic_store
        self.task_engine = task_engine
        self.decision_engine = decision_engine
        self.risk_engine = risk_engine
        self.runtime = runtime
        self.conversation = dict(conversation or {})
        self.audit_events = []

    def retry_downstream(
        self,
        engine: str,
        conversation_id: str,
        message_id: str,
        topic_id: str = "",
        *,
        version: int = 0,
        runtime: Any = None,
    ) -> RetryResult:
        name = _normalize_engine(engine)
        cid = str(conversation_id or "").strip()
        mid = str(message_id or "").strip()
        requested_topic = str(topic_id or "").strip()
        ver = int(version or 0)
        outcome = RetryResult(
            engine=name,
            conversation_id=cid,
            message_id=mid,
            topic_id=requested_topic,
            version=ver or 1,
        )
        if name not in ALLOWED_ENGINES:
            outcome.engine = str(engine or "")
            return self._reject(outcome, ERROR_INVALID_ENGINE, "engine 必须是 task|decision|risk")

        bundle = self._bundle(name)
        engine_obj = bundle["engine"]
        store = bundle["store"]
        default_version = bundle["version"]
        if ver <= 0:
            ver = default_version
            outcome.version = ver

        if engine_obj is None or store is None or not getattr(engine_obj, "enabled", False):
            return self._reject(outcome, ERROR_ENGINE_DISABLED, "目标 Engine 未启用，禁止旁路 retry")

        processing = None
        try:
            processing = store.get_processing(cid, mid, ver)
        except Exception as exc:
            return self._reject(outcome, ERROR_NOT_FOUND, str(exc)[:200])
        if not processing:
            return self._reject(outcome, ERROR_NOT_FOUND, "不存在 processing，禁止自动创建")

        outcome.previous_status = processing_status(processing)
        stored_topic = str(processing.get("topic_id") or "").strip()
        if requested_topic and stored_topic and requested_topic != stored_topic:
            return self._reject(outcome, ERROR_IDENTITY_MISMATCH, "topic_id 与 processing 不一致")
        resolved_topic = requested_topic or stored_topic
        outcome.topic_id = resolved_topic

        active_runtime = runtime if runtime is not None else self.runtime
        if not _runtime_accepting(active_runtime):
            state = str(getattr(active_runtime, "state", "") or ERROR_STOPPED)
            return self._reject(outcome, ERROR_STOPPED, "Runtime %s，禁止显式 retry" % state)

        if not is_retryable_status(outcome.previous_status):
            return self._reject(
                outcome,
                ERROR_NOT_RETRYABLE,
                "只有 FAILED processing 允许 retry，当前=%s" % (outcome.previous_status or "<empty>"),
            )

        if not resolved_topic:
            return self._reject(outcome, ERROR_MISSING_TOPIC, "processing 缺少 topic_id")
        topic = self.topic_store.get_topic(cid, resolved_topic)
        if topic is None:
            return self._reject(outcome, ERROR_MISSING_TOPIC, "TopicRecord 不存在")
        message = self.topic_store.get_message(cid, mid)
        if message is None:
            return self._reject(outcome, ERROR_MISSING_MESSAGE, "MessageRecord 不存在")

        conversation = dict(self.conversation)
        conversation["id"] = cid

        self._audit(
            EVENT_REQUESTED,
            store,
            outcome,
            extra={"previous_status": outcome.previous_status},
        )
        engine_result = engine_obj.process_record(conversation, topic, message)
        outcome.executed = True
        payload = engine_result.as_dict() if hasattr(engine_result, "as_dict") else dict(engine_result or {})
        outcome.engine_result = payload
        outcome.engine_decision = str(getattr(engine_result, "decision", "") or payload.get("decision") or "")
        failed = (
            outcome.engine_decision == RESULT_FAILED
            or bool(getattr(engine_result, "error_code", "") or payload.get("error_code"))
        )
        if failed:
            outcome.result = RESULT_FAILED
            outcome.error_code = str(
                getattr(engine_result, "error_code", "") or payload.get("error_code") or RESULT_FAILED
            )
            outcome.error = str(getattr(engine_result, "error", "") or payload.get("error") or "")
            self._audit(EVENT_FAILED, store, outcome)
            return outcome
        outcome.ok = True
        outcome.result = RESULT_SUCCESS
        self._audit(EVENT_SUCCESS, store, outcome)
        return outcome

    def _bundle(self, engine: str) -> dict:
        if engine == "task":
            obj = self.task_engine
            store = getattr(obj, "store", None) if obj is not None else None
            return {"engine": obj, "store": store, "version": TASK_PROCESSING_VERSION}
        if engine == "decision":
            obj = self.decision_engine
            store = getattr(obj, "store", None) if obj is not None else None
            return {"engine": obj, "store": store, "version": DECISION_PROCESSING_VERSION}
        obj = self.risk_engine
        store = getattr(obj, "store", None) if obj is not None else None
        return {"engine": obj, "store": store, "version": RISK_PROCESSING_VERSION}

    def _reject(self, outcome: RetryResult, error_code: str, error: str) -> RetryResult:
        outcome.ok = False
        outcome.rejected = True
        outcome.executed = False
        outcome.result = RESULT_REJECTED
        outcome.error_code = error_code
        outcome.error = error
        store = None
        if outcome.engine in ALLOWED_ENGINES:
            store = self._bundle(outcome.engine).get("store")
        self._audit(EVENT_REJECTED, store, outcome)
        return outcome

    def _audit(self, event: str, store: Any, outcome: RetryResult, extra: Optional[dict] = None) -> None:
        item = {
            "event": event,
            "ts": utc_now_iso(),
            "engine": outcome.engine,
            "conversation_id": outcome.conversation_id,
            "message_id": outcome.message_id,
            "topic_id": outcome.topic_id,
            "version": outcome.version,
            "previous_status": outcome.previous_status,
            "result": outcome.result,
            "error_code": outcome.error_code,
            "engine_decision": outcome.engine_decision,
        }
        if extra:
            item.update(extra)
        self.audit_events.append(item)
        if store is None:
            return
        try:
            writer = getattr(store, "write_audit", None)
            if callable(writer):
                writer(item)
        except Exception:
            pass


def retry_downstream(
    engine: str,
    conversation_id: str,
    message_id: str,
    topic_id: str = "",
    *,
    version: int = 0,
    runtime: Any = None,
    service: DownstreamRetryService,
) -> RetryResult:
    """同步内部入口。第一版必须显式传入 DownstreamRetryService，不隐式建 queue。"""
    return service.retry_downstream(
        engine,
        conversation_id,
        message_id,
        topic_id,
        version=version,
        runtime=runtime,
    )
