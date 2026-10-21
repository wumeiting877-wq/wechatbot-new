# -*- coding: utf-8 -*-
"""P6-G5 Topic Failure Recovery：显式、独立、一次性的 Topic FAILED retry。

只重跑 Topic。成功后复用 TopicSidepath 既有 fan-out。
不得重开 SUCCESS replay fan-out，不得代替 P6-G2 downstream retry。
第一版：同步内部 capability。无 Queue / Scheduler / 自动重试 / WebUI。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from conversation_store import utc_now_iso
from topic_sidepath import TopicSidepath
from topic_store import (
    DECISION_FAILED,
    DEFAULT_PROCESSING_VERSION,
    SUCCESS_DECISIONS,
    TopicStore,
)

RETRYABLE_STATUSES = frozenset({DECISION_FAILED})

EVENT_REQUESTED = "TOPIC_RETRY_REQUESTED"
EVENT_SUCCESS = "TOPIC_RETRY_SUCCESS"
EVENT_FAILED = "TOPIC_RETRY_FAILED"
EVENT_REJECTED = "TOPIC_RETRY_REJECTED"

ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_NOT_RETRYABLE = "NOT_RETRYABLE"
ERROR_ENGINE_DISABLED = "ENGINE_DISABLED"
ERROR_STOPPED = "STOPPED"
ERROR_MISSING_MESSAGE = "MISSING_MESSAGE"

RESULT_SUCCESS = "SUCCESS"
RESULT_FAILED = "FAILED"
RESULT_REJECTED = "REJECTED"


def processing_status(record: Optional[dict]) -> str:
    data = record if isinstance(record, dict) else {}
    return str(data.get("decision") or "").strip()


def is_retryable_status(status: str) -> bool:
    return str(status or "").strip() in RETRYABLE_STATUSES


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
class TopicRetryResult:
    ok: bool = False
    rejected: bool = False
    executed: bool = False
    conversation_id: str = ""
    message_id: str = ""
    version: int = DEFAULT_PROCESSING_VERSION
    previous_status: str = ""
    result: str = ""
    error_code: str = ""
    error: str = ""
    topic_id: str = ""
    decision: str = ""
    replayed: bool = False
    engine_result: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "rejected": self.rejected,
            "executed": self.executed,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "version": self.version,
            "previous_status": self.previous_status,
            "result": self.result,
            "error_code": self.error_code,
            "error": self.error,
            "topic_id": self.topic_id,
            "decision": self.decision,
            "replayed": self.replayed,
            "engine_result": dict(self.engine_result or {}),
        }


class TopicRetryService:
    """显式 one-shot Topic retry。调用方注入 TopicSidepath；不创建 worker / queue。"""

    def __init__(
        self,
        *,
        topic_sidepath: TopicSidepath,
        runtime: Any = None,
        conversation: Optional[dict] = None,
    ):
        self.topic_sidepath = topic_sidepath
        self.runtime = runtime
        self.conversation = dict(conversation or {})
        self.audit_events = []

    @property
    def store(self) -> TopicStore:
        return self.topic_sidepath.store

    def retry_topic(
        self,
        conversation_id: str,
        message_id: str,
        *,
        version: int = 0,
        runtime: Any = None,
    ) -> TopicRetryResult:
        cid = str(conversation_id or "").strip()
        mid = str(message_id or "").strip()
        ver = int(version or 0) or DEFAULT_PROCESSING_VERSION
        outcome = TopicRetryResult(
            conversation_id=cid,
            message_id=mid,
            version=ver,
        )
        sidepath = self.topic_sidepath
        if sidepath is None:
            return self._reject(outcome, ERROR_ENGINE_DISABLED, "Topic Sidepath 未注入")
        engine = getattr(sidepath, "engine", None)
        if not sidepath.enabled() or (engine is not None and not getattr(engine, "enabled", False)):
            return self._reject(outcome, ERROR_ENGINE_DISABLED, "Topic Engine 未启用，禁止旁路 retry")

        processing = None
        try:
            processing = self.store.get_processing(cid, mid, ver)
        except Exception as exc:
            return self._reject(outcome, ERROR_NOT_FOUND, str(exc)[:200])
        if not processing:
            return self._reject(outcome, ERROR_NOT_FOUND, "不存在 Topic processing，禁止自动创建")

        outcome.previous_status = processing_status(processing)
        outcome.topic_id = str(processing.get("topic_id") or "")

        active_runtime = runtime if runtime is not None else self.runtime
        if not _runtime_accepting(active_runtime):
            state = str(getattr(active_runtime, "state", "") or ERROR_STOPPED)
            return self._reject(outcome, ERROR_STOPPED, "Runtime %s，禁止显式 retry" % state)

        if not is_retryable_status(outcome.previous_status):
            return self._reject(
                outcome,
                ERROR_NOT_RETRYABLE,
                "只有 FAILED Topic processing 允许 retry，当前=%s"
                % (outcome.previous_status or "<empty>"),
            )

        message = self.store.get_message(cid, mid)
        if message is None:
            return self._reject(outcome, ERROR_MISSING_MESSAGE, "MessageRecord 不存在")

        conversation = self._conversation(cid)
        self._audit(EVENT_REQUESTED, outcome, extra={"previous_status": outcome.previous_status})
        engine_result = sidepath.process_record_and_fanout(
            message,
            conversation,
            runtime=active_runtime,
        )
        outcome.executed = True
        payload = engine_result.as_dict() if hasattr(engine_result, "as_dict") else dict(engine_result or {})
        outcome.engine_result = payload
        outcome.decision = str(getattr(engine_result, "decision", "") or payload.get("decision") or "")
        outcome.topic_id = str(getattr(engine_result, "topic_id", "") or payload.get("topic_id") or "")
        outcome.replayed = bool(getattr(engine_result, "replayed", False) or payload.get("replayed"))
        failed = (
            outcome.decision == DECISION_FAILED
            or bool(getattr(engine_result, "error_code", "") or payload.get("error_code"))
        )
        if failed:
            outcome.result = RESULT_FAILED
            outcome.error_code = str(
                getattr(engine_result, "error_code", "") or payload.get("error_code") or RESULT_FAILED
            )
            outcome.error = str(getattr(engine_result, "error", "") or payload.get("error") or "")
            self._audit(EVENT_FAILED, outcome)
            return outcome
        outcome.ok = True
        outcome.result = RESULT_SUCCESS
        self._audit(EVENT_SUCCESS, outcome)
        return outcome

    def _conversation(self, conversation_id: str) -> dict:
        conversation = dict(self.conversation)
        for item in list(getattr(self.topic_sidepath, "conversations", None) or []):
            if str((item or {}).get("id") or "") == conversation_id:
                conversation = dict(item)
                break
        conversation["id"] = conversation_id
        return conversation

    def _reject(self, outcome: TopicRetryResult, error_code: str, error: str) -> TopicRetryResult:
        outcome.ok = False
        outcome.rejected = True
        outcome.executed = False
        outcome.result = RESULT_REJECTED
        outcome.error_code = error_code
        outcome.error = error
        self._audit(EVENT_REJECTED, outcome)
        return outcome

    def _audit(self, event: str, outcome: TopicRetryResult, extra: Optional[dict] = None) -> None:
        item = {
            "event": event,
            "ts": utc_now_iso(),
            "conversation_id": outcome.conversation_id,
            "message_id": outcome.message_id,
            "version": outcome.version,
            "previous_status": outcome.previous_status,
            "result": outcome.result,
            "topic_id": outcome.topic_id,
            "decision": outcome.decision,
            "error_code": outcome.error_code,
        }
        if extra:
            item.update(extra)
        self.audit_events.append(item)
        try:
            self.store.write_audit(item)
        except Exception:
            pass


def retry_topic(
    conversation_id: str,
    message_id: str,
    *,
    version: int = 0,
    runtime: Any = None,
    service: TopicRetryService,
) -> TopicRetryResult:
    """同步内部入口。第一版必须显式传入 TopicRetryService，不隐式建 queue。"""
    return service.retry_topic(
        conversation_id,
        message_id,
        version=version,
        runtime=runtime,
    )


# SUCCESS_DECISIONS 在 eligibility 文档中对照；import 保持审计可见。
assert DECISION_FAILED not in SUCCESS_DECISIONS
