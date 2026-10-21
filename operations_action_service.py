# -*- coding: utf-8 -*-
"""P7-G1 人工单条重试。只编排只读状态与既有 retry capability。

不调用 Extractor，不改 Store，不直接跑 Engine。
资格来自 Operations Read Model，执行入口只有 retry_topic / retry_downstream。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Optional

from downstream_retry import retry_downstream
from operations_action_audit import EVENT_REQUESTED, EVENT_RESULT, append_action_audit
from operations_read_model import (
    ENGINE_DECISION,
    ENGINE_RISK,
    ENGINE_TASK,
    ENGINE_TOPIC,
    RETRY_DOWNSTREAM,
    RETRY_TOPIC,
    STATE_FAILED_RETRYABLE,
    STATE_NOT_FOUND_UNKNOWN,
    OperationsReadModel,
)
from topic_retry import retry_topic

ERROR_NOT_RETRYABLE = "NOT_RETRYABLE"
ERROR_NOT_FOUND_UNKNOWN = "NOT_FOUND_UNKNOWN"
ERROR_STOPPED = "STOPPED"
ERROR_ENGINE_DISABLED = "ENGINE_DISABLED"
ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_BAD_REQUEST = "BAD_REQUEST"

MSG_UNKNOWN = "处理状态未知，禁止自动重试，请人工检查。"
MSG_STALE = "当前状态已变化，无法重试"
MSG_STOPPED = "Runtime 未在接收工作，禁止人工重试"
MSG_DISABLED = "目标 Engine 未启用，禁止人工重试"
MSG_NOT_FOUND = "message not found"

_ENGINES = (ENGINE_TOPIC, ENGINE_TASK, ENGINE_DECISION, ENGINE_RISK)
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()

_HTTP = {
    ERROR_NOT_RETRYABLE: 409,
    ERROR_NOT_FOUND_UNKNOWN: 409,
    ERROR_ENGINE_DISABLED: 409,
    ERROR_STOPPED: 423,
    ERROR_NOT_FOUND: 404,
    ERROR_BAD_REQUEST: 400,
}


def _identity_lock(key: tuple):
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _json_ready(value: Any):
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def _outcome_payload(outcome: Any) -> dict:
    if outcome is None:
        return {}
    if hasattr(outcome, "as_dict"):
        data = outcome.as_dict()
        return dict(data) if isinstance(data, dict) else {}
    if isinstance(outcome, dict):
        return dict(outcome)
    return {}


@dataclass
class ManualRetryResult:
    engine: str = ""
    conversation_id: str = ""
    message_id: str = ""
    before_state: Optional[dict] = None
    retry_result: Optional[dict] = None
    after_state: Optional[dict] = None
    executed: bool = False
    error_code: str = ""
    error: str = ""
    after_message: Optional[dict] = None
    http_status: int = 200

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "before_state": self.before_state,
            "retry_result": _json_ready(self.retry_result),
            "after_state": self.after_state,
            "executed": bool(self.executed),
            "error_code": self.error_code,
            "error": self.error,
            "after_message": self.after_message,
        }


class _ObservedRuntime:
    """把刚刚读到的 Runtime 视图交给既有 retry。不改 Runtime，也不把未接收工作说成可执行。"""

    def __init__(self, view: dict):
        data = view if isinstance(view, dict) else {}
        self.state = str(data.get("runtime_state") or "")
        self._accepting = bool(data.get("is_accepting_work"))

    def is_accepting_work(self) -> bool:
        return self._accepting

    def register_stop_hook(self, _hook) -> None:
        return None

    def register_emergency_hook(self, _hook) -> None:
        return None


class OperationsActionService:
    def __init__(
        self,
        root_dir: str,
        *,
        read_model: Optional[OperationsReadModel] = None,
        topic_service: Any = None,
        downstream_service: Any = None,
        topic_service_factory: Any = None,
        downstream_service_factory: Any = None,
        runtime: Any = None,
    ):
        self.root_dir = root_dir
        self.read_model = read_model if read_model is not None else OperationsReadModel(root_dir)
        self.topic_service = topic_service
        self.downstream_service = downstream_service
        self.topic_service_factory = topic_service_factory
        self.downstream_service_factory = downstream_service_factory
        self.runtime = runtime

    def manual_retry(
        self,
        engine: str,
        conversation_id: str,
        message_id: str,
        version: int,
        *,
        session_present: bool = False,
    ) -> ManualRetryResult:
        name = str(engine or "").strip().lower()
        cid = str(conversation_id or "").strip()
        mid = str(message_id or "").strip()
        try:
            ver = int(version)
        except (TypeError, ValueError):
            ver = 0
        result = ManualRetryResult(engine=name, conversation_id=cid, message_id=mid)
        if name not in _ENGINES or not cid or not mid or ver <= 0:
            result.error_code = ERROR_BAD_REQUEST
            result.error = "engine、conversation_id、message_id、version 不完整"
            result.http_status = 400
            self._audit(EVENT_REQUESTED, result, ver, session_present)
            self._audit(EVENT_RESULT, result, ver, session_present)
            return result
        lock = _identity_lock((name, cid, mid, ver))
        with lock:
            return self._retry_locked(result, name, cid, mid, ver, session_present)

    def _retry_locked(
        self,
        result: ManualRetryResult,
        engine: str,
        conversation_id: str,
        message_id: str,
        version: int,
        session_present: bool,
    ) -> ManualRetryResult:
        row = self.read_model.get_message(message_id, conversation_id)
        if row is None:
            return self._finish(
                result,
                version,
                session_present,
                error_code=ERROR_NOT_FOUND,
                error=MSG_NOT_FOUND,
                http_status=404,
            )
        before = self.read_model.engine_view(engine, conversation_id, message_id)
        result.before_state = before
        state = before.get("state")
        if state != STATE_FAILED_RETRYABLE or not before.get("retryable"):
            if state == STATE_NOT_FOUND_UNKNOWN:
                return self._finish(
                    result,
                    version,
                    session_present,
                    error_code=ERROR_NOT_FOUND_UNKNOWN,
                    error=MSG_UNKNOWN,
                    http_status=409,
                    after=before,
                    after_message=row,
                )
            return self._finish(
                result,
                version,
                session_present,
                error_code=ERROR_NOT_RETRYABLE,
                error=MSG_STALE,
                http_status=409,
                after=before,
                after_message=row,
            )
        expected = RETRY_TOPIC if engine == ENGINE_TOPIC else RETRY_DOWNSTREAM
        if before.get("retry_type") != expected:
            return self._finish(
                result,
                version,
                session_present,
                error_code=ERROR_NOT_RETRYABLE,
                error=MSG_STALE,
                http_status=409,
                after=before,
                after_message=row,
            )
        stored_version = before.get("version")
        if stored_version is None or int(stored_version) != int(version):
            return self._finish(
                result,
                version,
                session_present,
                error_code=ERROR_NOT_RETRYABLE,
                error=MSG_STALE,
                http_status=409,
                after=before,
                after_message=row,
            )
        if not before.get("runtime_accepting_work"):
            return self._finish(
                result,
                version,
                session_present,
                error_code=ERROR_STOPPED,
                error=MSG_STOPPED,
                http_status=423,
                after=before,
                after_message=row,
            )
        if not before.get("engine_enabled"):
            return self._finish(
                result,
                version,
                session_present,
                error_code=ERROR_ENGINE_DISABLED,
                error=MSG_DISABLED,
                http_status=409,
                after=before,
                after_message=row,
            )
        runtime = self._runtime_for_retry()
        try:
            if engine == ENGINE_TOPIC:
                outcome = self._invoke_topic(conversation_id, message_id, version, runtime)
            else:
                outcome = self._invoke_downstream(engine, conversation_id, message_id, version, runtime)
        except Exception as exc:
            after_row = self.read_model.get_message(message_id, conversation_id)
            after = (after_row or {}).get(engine) if after_row else self.read_model.engine_view(
                engine, conversation_id, message_id
            )
            return self._finish(
                result,
                version,
                session_present,
                error_code="FAILED",
                error=str(exc)[:200],
                http_status=500,
                after=after,
                after_message=after_row,
            )
        payload = _outcome_payload(outcome)
        executed = bool(payload.get("executed"))
        after_row = self.read_model.get_message(message_id, conversation_id)
        after = (after_row or {}).get(engine) if after_row else self.read_model.engine_view(
            engine, conversation_id, message_id
        )
        if executed:
            error_code = str(payload.get("error_code") or "")
            error = str(payload.get("error") or "")
            return self._finish(
                result,
                version,
                session_present,
                executed=True,
                error_code=error_code,
                error=error,
                http_status=200,
                retry_result=payload,
                after=after,
                after_message=after_row,
            )
        error_code = str(payload.get("error_code") or ERROR_NOT_RETRYABLE)
        error = str(payload.get("error") or MSG_STALE)
        status = _HTTP.get(error_code, 409)
        if error_code == ERROR_NOT_FOUND:
            status = 409
        return self._finish(
            result,
            version,
            session_present,
            executed=False,
            error_code=error_code,
            error=error,
            http_status=status,
            retry_result=payload,
            after=after,
            after_message=after_row,
        )

    def _runtime_for_retry(self) -> Any:
        if self.runtime is not None:
            return self.runtime
        return _ObservedRuntime(self.read_model.runtime_view())

    def _invoke_topic(self, conversation_id: str, message_id: str, version: int, runtime: Any):
        service = self._topic_service(runtime)
        if service is None:
            raise RuntimeError("Topic retry capability 未装配")
        try:
            return retry_topic(
                conversation_id,
                message_id,
                version=version,
                runtime=runtime,
                service=service,
            )
        finally:
            closer = getattr(service, "close", None)
            if callable(closer):
                closer()

    def _invoke_downstream(self, engine: str, conversation_id: str, message_id: str, version: int, runtime: Any):
        service = self._downstream_service(runtime)
        if service is None:
            raise RuntimeError("Downstream retry capability 未装配")
        try:
            return retry_downstream(
                engine,
                conversation_id,
                message_id,
                "",
                version=version,
                runtime=runtime,
                service=service,
            )
        finally:
            closer = getattr(service, "close", None)
            if callable(closer):
                closer()

    def _topic_service(self, runtime: Any):
        if self.topic_service_factory is not None:
            return self.topic_service_factory(runtime)
        return self.topic_service

    def _downstream_service(self, runtime: Any):
        if self.downstream_service_factory is not None:
            return self.downstream_service_factory(runtime)
        return self.downstream_service

    def _finish(
        self,
        result: ManualRetryResult,
        version: int,
        session_present: bool,
        *,
        executed: bool = False,
        error_code: str = "",
        error: str = "",
        http_status: int = 200,
        retry_result: Optional[dict] = None,
        after: Optional[dict] = None,
        after_message: Optional[dict] = None,
    ) -> ManualRetryResult:
        result.executed = executed
        result.error_code = error_code
        result.error = error
        result.http_status = http_status
        result.retry_result = retry_result
        result.after_state = after if after is not None else result.before_state
        result.after_message = after_message
        self._audit(EVENT_REQUESTED, result, version, session_present)
        self._audit(EVENT_RESULT, result, version, session_present)
        return result

    def _audit(
        self,
        event: str,
        result: ManualRetryResult,
        version: int,
        session_present: bool,
        before_state: Any = None,
    ) -> None:
        before = result.before_state if isinstance(result.before_state, dict) else {}
        after = result.after_state if isinstance(result.after_state, dict) else {}
        if before_state is None:
            before_state = before.get("state") or ""
        retry_name = ""
        if isinstance(result.retry_result, dict):
            retry_name = str(result.retry_result.get("result") or "")
        item = {
            "event": event,
            "engine": result.engine,
            "conversation_id": result.conversation_id,
            "message_id": result.message_id,
            "version": int(version or 0),
            "before_state": before_state if event == EVENT_REQUESTED else (before.get("state") or ""),
            "executed": bool(result.executed),
            "retry_result": retry_name,
            "after_state": after.get("state") or "",
            "error": result.error,
            "error_code": result.error_code,
            "session_present": bool(session_present),
        }
        try:
            append_action_audit(self.root_dir, item)
        except Exception:
            return
