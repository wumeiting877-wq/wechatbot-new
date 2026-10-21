# -*- coding: utf-8 -*-
"""P7-G0 Operations Read Model：只读聚合 Runtime / Store / Engine flags / Audit。

不写 Store，不改 processing，不运行 Engine，不发送消息。
processing 缺失统一为 NOT_FOUND_UNKNOWN，且 retryable 永远为 false。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from bot_runtime import emergency_stop_requested, read_status_file, stop_requested
from decision_sidepath import is_decision_engine_enabled
from decision_store import SUCCESS_DECISIONS as DECISION_SUCCESS
from decision_store import DecisionStore
from risk_sidepath import is_risk_engine_enabled
from risk_store import SUCCESS_DECISIONS as RISK_SUCCESS
from risk_store import RiskStore
from task_sidepath import is_task_engine_enabled
from task_store import SUCCESS_DECISIONS as TASK_SUCCESS
from task_store import TaskStore
from topic_sidepath import is_topic_engine_enabled
from topic_store import SUCCESS_DECISIONS as TOPIC_SUCCESS
from topic_store import TopicStore, content_preview

STATE_SUCCESS = "SUCCESS"
STATE_FAILED_RETRYABLE = "FAILED_RETRYABLE"
STATE_NOT_FOUND_UNKNOWN = "NOT_FOUND_UNKNOWN"

RETRY_NONE = "NONE"
RETRY_TOPIC = "TOPIC_RETRY"
RETRY_DOWNSTREAM = "DOWNSTREAM_RETRY"

ENGINE_TOPIC = "topic"
ENGINE_TASK = "task"
ENGINE_DECISION = "decision"
ENGINE_RISK = "risk"
ENGINES = (ENGINE_TOPIC, ENGINE_TASK, ENGINE_DECISION, ENGINE_RISK)

STATE_LABELS = {
    STATE_SUCCESS: "已处理",
    STATE_FAILED_RETRYABLE: "处理失败，可重试",
    STATE_NOT_FOUND_UNKNOWN: "处理状态未知，需人工检查",
}

_SUCCESS = {
    ENGINE_TOPIC: TOPIC_SUCCESS,
    ENGINE_TASK: TASK_SUCCESS,
    ENGINE_DECISION: DECISION_SUCCESS,
    ENGINE_RISK: RISK_SUCCESS,
}

_AUDIT_DECISION_KEY = {
    ENGINE_TOPIC: "topic_decision",
    ENGINE_TASK: "task_decision",
    ENGINE_DECISION: "decision_decision",
    ENGINE_RISK: "risk_decision",
}

_ENTITY_KEY = {
    ENGINE_TASK: "task_ids",
    ENGINE_DECISION: "decision_ids",
    ENGINE_RISK: "risk_ids",
}

_VERSION_FIELD = {
    ENGINE_TOPIC: "topic_processing_version",
    ENGINE_TASK: "task_processing_version",
    ENGINE_DECISION: "decision_processing_version",
    ENGINE_RISK: "risk_processing_version",
}

_NOTICE_MISSING = (
    "processing record not found",
    "automatic retry disabled",
    "manual investigation required",
)
_NOTICE_UNRECOGNIZED = (
    "processing outcome unrecognized",
    "automatic retry disabled",
    "manual investigation required",
)

_OPERATIONAL_STATES = ("RUNNING", "DEGRADED")
_PREVIEW_LIMIT = 80


def _split_decisions(value: str) -> list:
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _stored_decision(engine: str, record: dict) -> str:
    if engine == ENGINE_TOPIC:
        return str(record.get("decision") or "").strip()
    return str(record.get("decision_summary") or record.get("decision") or "").strip()


def _is_success(engine: str, decision: str) -> bool:
    allowed = _SUCCESS[engine]
    if engine == ENGINE_TOPIC:
        return decision in allowed
    parts = _split_decisions(decision)
    return bool(parts) and all(item in allowed for item in parts)


def _is_failed(engine: str, decision: str) -> bool:
    if engine == ENGINE_TOPIC:
        return decision == "FAILED"
    parts = _split_decisions(decision)
    return bool(parts) and all(item == "FAILED" for item in parts)


def _processing_version(engine: str, record: Optional[dict]):
    if not record:
        return None
    key = _VERSION_FIELD.get(engine)
    if not key:
        return None
    try:
        value = int(record.get(key) or 1)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _entity_ids(engine: str, record: Optional[dict]) -> list:
    if not record:
        return []
    if engine == ENGINE_TOPIC:
        topic_id = record.get("topic_id")
        return [str(topic_id)] if topic_id else []
    raw = record.get(_ENTITY_KEY[engine]) or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def _source_timestamp(record: Optional[dict], message: Optional[dict], state: str) -> dict:
    processed_at = str((record or {}).get("processed_at") or "").strip()
    created_at = str((message or {}).get("created_at") or "").strip()
    ingested_at = str((message or {}).get("ingested_at") or "").strip()
    if state == STATE_NOT_FOUND_UNKNOWN and not processed_at:
        if created_at:
            return {"value": created_at, "source": "message.created_at"}
        if ingested_at:
            return {"value": ingested_at, "source": "message.ingested_at"}
        return {"value": "", "source": ""}
    if processed_at:
        return {"value": processed_at, "source": "processing.processed_at"}
    if created_at:
        return {"value": created_at, "source": "message.created_at"}
    if ingested_at:
        return {"value": ingested_at, "source": "message.ingested_at"}
    return {"value": "", "source": ""}


class OperationsReadModel:
    """聚合已有 Store 与 Runtime 文件。构造函数只保存路径，不启动任务。"""

    def __init__(self, root_dir: str, runtime_status: Optional[dict] = None):
        self.root_dir = os.path.abspath(root_dir)
        self._runtime_status = dict(runtime_status) if isinstance(runtime_status, dict) else None
        self.topic_store = TopicStore(self.root_dir)
        self.task_store = TaskStore(self.root_dir, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.root_dir, topic_store=self.topic_store)
        self.risk_store = RiskStore(self.root_dir, topic_store=self.topic_store, task_store=self.task_store)
        self._stores = {
            ENGINE_TOPIC: self.topic_store,
            ENGINE_TASK: self.task_store,
            ENGINE_DECISION: self.decision_store,
            ENGINE_RISK: self.risk_store,
        }

    def engine_flags(self) -> dict:
        return {
            "topic_enabled": bool(is_topic_engine_enabled()),
            "task_enabled": bool(is_task_engine_enabled()),
            "decision_enabled": bool(is_decision_engine_enabled()),
            "risk_enabled": bool(is_risk_engine_enabled()),
        }

    def runtime_view(self, status: Optional[dict] = None) -> dict:
        if isinstance(status, dict):
            data = dict(status)
        elif self._runtime_status is not None:
            data = dict(self._runtime_status)
        else:
            data = read_status_file()
        runtime_state = data.get("state") if isinstance(data.get("state"), str) else ""
        emergency = bool(data.get("emergency"))
        accepting = runtime_state in _OPERATIONAL_STATES and not emergency
        if accepting and (stop_requested() or emergency_stop_requested()):
            accepting = False
        wechat = data.get("wechat")
        if wechat == "connected":
            wechat_connected = True
        elif wechat == "disconnected":
            wechat_connected = False
        else:
            wechat_connected = None
        listen_count = data.get("listen_count") if "listen_count" in data else None
        if listen_count is not None and not isinstance(listen_count, int):
            listen_count = None
        return {
            "runtime_state": runtime_state,
            "is_accepting_work": accepting,
            "bot_pid": data.get("pid") if "pid" in data else None,
            "wechat_connected": wechat_connected,
            "listen_count": listen_count,
        }

    def engine_view(
        self,
        engine: str,
        conversation_id: str,
        message_id: str,
        message: Optional[dict] = None,
        *,
        flags: Optional[dict] = None,
        runtime: Optional[dict] = None,
        audit_index: Optional[dict] = None,
    ) -> dict:
        engine_name = str(engine or "").strip().lower()
        record = None
        store = self._stores.get(engine_name)
        if store is not None and conversation_id and message_id:
            record = store.get_processing(conversation_id, message_id)
        flags = flags if isinstance(flags, dict) else self.engine_flags()
        runtime = runtime if isinstance(runtime, dict) else self.runtime_view()
        enabled_key = "%s_enabled" % engine_name
        decision = _stored_decision(engine_name, record) if record else ""
        processing_present = record is not None
        if not processing_present:
            state = STATE_NOT_FOUND_UNKNOWN
            notice = list(_NOTICE_MISSING)
            decision = ""
        elif _is_success(engine_name, decision):
            state = STATE_SUCCESS
            notice = []
        elif _is_failed(engine_name, decision):
            state = STATE_FAILED_RETRYABLE
            notice = []
        else:
            state = STATE_NOT_FOUND_UNKNOWN
            notice = list(_NOTICE_UNRECOGNIZED)
        retryable = state == STATE_FAILED_RETRYABLE
        if state == STATE_FAILED_RETRYABLE and engine_name == ENGINE_TOPIC:
            retry_type = RETRY_TOPIC
        elif state == STATE_FAILED_RETRYABLE and engine_name in (ENGINE_TASK, ENGINE_DECISION, ENGINE_RISK):
            retry_type = RETRY_DOWNSTREAM
        else:
            retry_type = RETRY_NONE
        audit = {}
        if isinstance(audit_index, dict):
            audit = audit_index.get((conversation_id, message_id)) or {}
        elif store is not None:
            audit = self._last_audit(engine_name, conversation_id, message_id)
        audit_key = _AUDIT_DECISION_KEY.get(engine_name, "")
        topic_id = None
        error = ""
        error_code = ""
        processed_at = ""
        if record:
            topic_id = record.get("topic_id") or None
            error = str(record.get("error") or "")
            error_code = str(record.get("error_code") or "")
            processed_at = str(record.get("processed_at") or "")
        return {
            "engine": engine_name,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "state": state,
            "state_label": STATE_LABELS.get(state, state),
            "decision": decision,
            "retryable": retryable,
            "retry_type": retry_type,
            "requires_manual_investigation": state == STATE_NOT_FOUND_UNKNOWN,
            "topic_id": topic_id,
            "entity_ids": _entity_ids(engine_name, record),
            "error_code": error_code,
            "error": error,
            "processed_at": processed_at,
            "engine_enabled": bool(flags.get(enabled_key)),
            "runtime_accepting_work": bool(runtime.get("is_accepting_work")),
            "processing_present": processing_present,
            "version": _processing_version(engine_name, record),
            "notice": notice,
            "source_timestamp": _source_timestamp(record, message, state),
            "last_audit_event": str(audit.get(audit_key) or "") if isinstance(audit, dict) else "",
            "last_audit_error": str(audit.get("error") or "") if isinstance(audit, dict) else "",
        }

    def message_view(
        self,
        message: dict,
        *,
        flags: Optional[dict] = None,
        runtime: Optional[dict] = None,
        audits: Optional[dict] = None,
    ) -> dict:
        item = message if isinstance(message, dict) else {}
        conversation_id = str(item.get("conversation_id") or "")
        message_id = str(item.get("id") or "")
        flags = flags if isinstance(flags, dict) else self.engine_flags()
        runtime = runtime if isinstance(runtime, dict) else self.runtime_view()
        audits = audits if isinstance(audits, dict) else self._audit_indexes()
        engines = {}
        for engine in ENGINES:
            engines[engine] = self.engine_view(
                engine,
                conversation_id,
                message_id,
                item,
                flags=flags,
                runtime=runtime,
                audit_index=audits.get(engine) or {},
            )
        attention = any(engines[engine]["requires_manual_investigation"] or engines[engine]["retryable"] for engine in ENGINES)
        return {
            "message": {
                "id": message_id,
                "conversation_id": conversation_id,
                "sender_name": str(item.get("sender_name") or ""),
                "direction": str(item.get("direction") or ""),
                "created_at": str(item.get("created_at") or ""),
                "ingested_at": str(item.get("ingested_at") or ""),
                "content_preview": content_preview(item.get("content") or "", _PREVIEW_LIMIT),
            },
            "topic": engines[ENGINE_TOPIC],
            "task": engines[ENGINE_TASK],
            "decision": engines[ENGINE_DECISION],
            "risk": engines[ENGINE_RISK],
            "attention_required": attention,
        }

    def list_messages(self) -> list:
        flags = self.engine_flags()
        runtime = self.runtime_view()
        audits = self._audit_indexes()
        rows = []
        for message in self._iter_messages():
            rows.append(self.message_view(message, flags=flags, runtime=runtime, audits=audits))
        rows.sort(key=lambda row: str(row["message"].get("created_at") or ""), reverse=True)
        return rows

    def get_message(self, message_id: str, conversation_id: str = "") -> Optional[dict]:
        wanted = str(message_id or "").strip()
        cid_filter = str(conversation_id or "").strip()
        if not wanted:
            return None
        flags = self.engine_flags()
        runtime = self.runtime_view()
        audits = self._audit_indexes()
        for message in self._iter_messages():
            if str(message.get("id") or "") != wanted:
                continue
            if cid_filter and str(message.get("conversation_id") or "") != cid_filter:
                continue
            return self.message_view(message, flags=flags, runtime=runtime, audits=audits)
        return None

    def issues(self, limit: int = 50) -> list:
        rows = []
        for message_row in self.list_messages():
            preview = message_row["message"].get("content_preview") or ""
            for engine in ENGINES:
                view = message_row[engine]
                if view["state"] not in (STATE_FAILED_RETRYABLE, STATE_NOT_FOUND_UNKNOWN):
                    continue
                stamp = view.get("source_timestamp") or {}
                rows.append({
                    "engine": engine,
                    "conversation_id": view["conversation_id"],
                    "message_id": view["message_id"],
                    "state": view["state"],
                    "state_label": view["state_label"],
                    "decision": view["decision"],
                    "retryable": view["retryable"],
                    "retry_type": view["retry_type"],
                    "requires_manual_investigation": view["requires_manual_investigation"],
                    "error_code": view["error_code"],
                    "error": view["error"],
                    "notice": list(view.get("notice") or []),
                    "source_timestamp": stamp,
                    "content_preview": preview,
                    "last_audit_event": view.get("last_audit_event") or "",
                    "last_audit_error": view.get("last_audit_error") or "",
                })
        rows.sort(
            key=lambda item: (
                str((item.get("source_timestamp") or {}).get("value") or ""),
                str(item.get("message_id") or ""),
                str(item.get("engine") or ""),
            ),
            reverse=True,
        )
        if limit is None or int(limit) <= 0:
            return rows
        return rows[: int(limit)]

    def status(self) -> dict:
        return {
            "runtime": self.runtime_view(),
            "engines": self.engine_flags(),
        }

    def _iter_messages(self):
        base = self.topic_store.conversations_dir
        if not os.path.isdir(base):
            return
        for name in sorted(os.listdir(base)):
            if not str(name).startswith("conv_"):
                continue
            path = os.path.join(base, name)
            if not os.path.isdir(path):
                continue
            try:
                messages = self.topic_store.list_messages(name)
            except Exception:
                continue
            for message in messages:
                if isinstance(message, dict) and message.get("id"):
                    yield message

    def _audit_indexes(self) -> dict:
        return {engine: self._audit_index(engine) for engine in ENGINES}

    def _audit_index(self, engine: str) -> dict:
        store = self._stores.get(engine)
        index = {}
        if store is None:
            return index
        try:
            events = store.read_audit(limit=0)
        except Exception:
            return index
        for event in events or []:
            if not isinstance(event, dict):
                continue
            message_id = str(event.get("message_id") or "")
            conversation_id = str(event.get("conversation_id") or "")
            if not message_id:
                continue
            index[(conversation_id, message_id)] = event
        return index

    def _last_audit(self, engine: str, conversation_id: str, message_id: str) -> dict:
        return self._audit_index(engine).get((conversation_id, message_id)) or {}
