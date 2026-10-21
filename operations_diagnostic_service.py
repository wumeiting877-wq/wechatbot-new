# -*- coding: utf-8 -*-
"""P7-G2 消息调查详情。只读聚合已有记录，不推断 processing decision。

状态仍来自 Operations Read Model 的三态。证据缺失显示为无记录 / 未提供。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from operations_action_audit import read_action_audit
from operations_read_model import (
    ENGINES,
    ENGINE_DECISION,
    ENGINE_RISK,
    ENGINE_TASK,
    ENGINE_TOPIC,
    STATE_NOT_FOUND_UNKNOWN,
    OperationsReadModel,
)

AUDIT_LIMIT = 20
MANUAL_ACTION_LIMIT = 20

AUDIT_NOTICE = "Audit 为诊断记录，不是 Processing 真值。"
MANUAL_NOTICE = "人工重试审计只说明有没有人点过重试以及结果，不能用来补 processing。"

FLAG_PROCESSING_MISSING = "PROCESSING_MISSING"
FLAG_PROCESSING_PRESENT = "PROCESSING_PRESENT"
FLAG_ENTITY_PRESENT = "ENTITY_PRESENT"
FLAG_CREATED_BY_PRESENT = "CREATED_BY_PRESENT"
FLAG_UPDATED_BY_PRESENT = "UPDATED_BY_PRESENT"
FLAG_RELATED_PRESENT = "RELATED_PRESENT"
FLAG_AUDIT_FAILED_PRESENT = "AUDIT_FAILED_PRESENT"
FLAG_MANUAL_RETRY_ATTEMPTED = "MANUAL_RETRY_ATTEMPTED"
FLAG_CREATION_EVIDENCE_PRESENT = "CREATION_EVIDENCE_PRESENT"

RELATION_CREATED_BY = "CREATED_BY"
RELATION_UPDATED_BY = "UPDATED_BY"
RELATION_RELATED = "RELATED"
RELATION_ORDER = (RELATION_CREATED_BY, RELATION_UPDATED_BY, RELATION_RELATED)

SUMMARY_PRESENT = "Processing record present; stored decision is %s."
SUMMARY_PRESENT_EMPTY = "Processing record present."
SUMMARY_MISSING_EVIDENCE = "Processing record missing; business entity evidence exists."
SUMMARY_MISSING_NONE = "Processing record missing; no related business entity evidence found."

_AUDIT_DECISION_KEY = {
    ENGINE_TOPIC: "topic_decision",
    ENGINE_TASK: "task_decision",
    ENGINE_DECISION: "decision_decision",
    ENGINE_RISK: "risk_decision",
}

_VERSION_FIELD = {
    ENGINE_TOPIC: "topic_processing_version",
    ENGINE_TASK: "task_processing_version",
    ENGINE_DECISION: "decision_processing_version",
    ENGINE_RISK: "risk_processing_version",
}

_DECISION_FIELD = {
    ENGINE_TOPIC: "decision",
    ENGINE_TASK: "decision_summary",
    ENGINE_DECISION: "decision_summary",
    ENGINE_RISK: "decision_summary",
}

_PROCESSING_ID_FIELD = {
    ENGINE_TASK: "task_ids",
    ENGINE_DECISION: "decision_ids",
    ENGINE_RISK: "risk_ids",
}

_LINK_ID_FIELD = {
    ENGINE_TOPIC: "topic_id",
    ENGINE_TASK: "task_id",
    ENGINE_DECISION: "decision_id",
    ENGINE_RISK: "risk_id",
}

_ENTITY_FIELDS = {
    ENGINE_TOPIC: (
        ("id", "topic_id"),
        ("title", "title"),
        ("summary", "summary"),
        ("status", "status"),
        ("confidence", "confidence"),
        ("conversation_id", "conversation_id"),
        ("created_at", "created_at"),
        ("updated_at", "updated_at"),
        ("last_message_at", "last_message_at"),
        ("message_count", "message_count"),
    ),
    ENGINE_TASK: (
        ("id", "task_id"),
        ("title", "title"),
        ("assignee_text", "assignee_text"),
        ("status", "status"),
        ("created_msg_id", "created_msg_id"),
        ("description", "description"),
        ("due_text", "due_text"),
        ("topic_id", "topic_id"),
        ("confidence", "confidence"),
        ("conversation_id", "conversation_id"),
        ("created_at", "created_at"),
        ("updated_at", "updated_at"),
    ),
    ENGINE_DECISION: (
        ("id", "decision_id"),
        ("title", "title"),
        ("decision_text", "decision_text"),
        ("summary", "summary"),
        ("status", "status"),
        ("created_msg_id", "created_msg_id"),
        ("topic_id", "topic_id"),
        ("confidence", "confidence"),
        ("supersedes_decision_id", "supersedes_decision_id"),
        ("conversation_id", "conversation_id"),
        ("created_at", "created_at"),
        ("updated_at", "updated_at"),
    ),
    ENGINE_RISK: (
        ("id", "risk_id"),
        ("title", "title"),
        ("description", "description"),
        ("condition_text", "condition_text"),
        ("impact_text", "impact_text"),
        ("status", "status"),
        ("created_msg_id", "created_msg_id"),
        ("topic_id", "topic_id"),
        ("task_id", "task_id"),
        ("confidence", "confidence"),
        ("conversation_id", "conversation_id"),
        ("created_at", "created_at"),
        ("updated_at", "updated_at"),
    ),
}

_TIME_SOURCE = {
    "created_at": "entity.created_at",
    "updated_at": "entity.updated_at",
    "last_message_at": "entity.last_message_at",
}


def _show(value: Any) -> Any:
    if value is None:
        return "未提供"
    if isinstance(value, str):
        return value if value.strip() else "未提供"
    if isinstance(value, list):
        items = [str(item) for item in value if item]
        return ", ".join(items) if items else "未提供"
    return value


def _split_decisions(value: str) -> list:
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _audit_failed(engine: str, event: dict) -> bool:
    decision = str(event.get(_AUDIT_DECISION_KEY.get(engine, "")) or "").strip()
    if engine == ENGINE_TOPIC:
        return decision == "FAILED"
    parts = _split_decisions(decision)
    return bool(parts) and all(item == "FAILED" for item in parts)


def _processing_entity_ids(engine: str, record: Optional[dict]) -> list:
    if not record:
        return []
    if engine == ENGINE_TOPIC:
        topic_id = record.get("topic_id")
        return [str(topic_id)] if topic_id else []
    raw = record.get(_PROCESSING_ID_FIELD.get(engine, "")) or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def _list_entities(store: Any, engine: str, conversation_id: str) -> list:
    if engine == ENGINE_TOPIC:
        return list(store.list_topics(conversation_id) or [])
    if engine == ENGINE_TASK:
        return list(store.list_tasks(conversation_id) or [])
    if engine == ENGINE_DECISION:
        return list(store.list_decisions(conversation_id) or [])
    if engine == ENGINE_RISK:
        return list(store.list_risks(conversation_id) or [])
    return []


class OperationsDiagnosticService:
    """详情证据。构造时不启动任务，查询时不写 Store。"""

    def __init__(self, root_dir: str, runtime_status: Optional[dict] = None):
        self.root_dir = os.path.abspath(root_dir)
        self.read_model = OperationsReadModel(self.root_dir, runtime_status=runtime_status)

    def get_message_diagnostics(self, message_id: str, conversation_id: str = "") -> Optional[dict]:
        message = self._find_message(message_id, conversation_id)
        if message is None:
            return None
        operations = self.read_model.message_view(message)
        manual_actions = self._manual_actions(
            str(message.get("conversation_id") or ""),
            str(message.get("id") or ""),
        )
        engines = {}
        for engine in ENGINES:
            engines[engine] = self._engine_view(
                engine,
                message,
                operations[engine],
                manual_actions,
            )
        return {
            "message": self._message_block(message),
            "operations_state": {
                "topic": operations[ENGINE_TOPIC],
                "task": operations[ENGINE_TASK],
                "decision": operations[ENGINE_DECISION],
                "risk": operations[ENGINE_RISK],
                "attention_required": operations["attention_required"],
            },
            "runtime": {
                "runtime": self.read_model.runtime_view(),
                "engines": self.read_model.engine_flags(),
            },
            "topic": engines[ENGINE_TOPIC],
            "task": engines[ENGINE_TASK],
            "decision": engines[ENGINE_DECISION],
            "risk": engines[ENGINE_RISK],
            "diagnostics": {
                "audit_notice": AUDIT_NOTICE,
                "manual_action_notice": MANUAL_NOTICE,
                "manual_actions": manual_actions,
                "summaries": {
                    engine: engines[engine]["diagnosis_summary"] for engine in ENGINES
                },
            },
        }

    def _find_message(self, message_id: str, conversation_id: str) -> Optional[dict]:
        wanted = str(message_id or "").strip()
        cid_filter = str(conversation_id or "").strip()
        if not wanted:
            return None
        store = self.read_model.topic_store
        if cid_filter:
            try:
                return store.get_message(cid_filter, wanted)
            except Exception:
                return None
        for message in self.read_model._iter_messages():
            if str(message.get("id") or "") == wanted:
                return message
        return None

    def _message_block(self, message: dict) -> dict:
        item = message if isinstance(message, dict) else {}
        created_at = str(item.get("created_at") or "").strip()
        ingested_at = str(item.get("ingested_at") or "").strip()
        content = item.get("content")
        sender = str(item.get("sender_name") or "").strip()
        return {
            "id": str(item.get("id") or ""),
            "conversation_id": str(item.get("conversation_id") or ""),
            "sender_name": sender or "未提供",
            "content": content if isinstance(content, str) and content.strip() else "未提供",
            "direction": str(item.get("direction") or ""),
            "message_type": str(item.get("message_type") or ""),
            "timestamps": [
                {
                    "field": "created_at",
                    "value": created_at or "未提供",
                    "source": "message.created_at",
                },
                {
                    "field": "ingested_at",
                    "value": ingested_at or "未提供",
                    "source": "message.ingested_at",
                },
            ],
        }

    def _engine_view(self, engine: str, message: dict, operations_view: dict, manual_actions: list) -> dict:
        conversation_id = str(message.get("conversation_id") or "")
        message_id = str(message.get("id") or "")
        store = self.read_model._stores.get(engine)
        record = None
        if store is not None and conversation_id and message_id:
            try:
                record = store.get_processing(conversation_id, message_id)
            except Exception:
                record = None
        processing_found = record is not None
        entities, links = self._related(engine, store, conversation_id, message_id, record)
        evidence = self._evidence(engine, links)
        audits = self._audits(engine, store, conversation_id, message_id)
        audit_failed = any(_audit_failed(engine, item["event"]) for item in audits["all_matches"])
        manual_for_engine = [
            item for item in manual_actions if str(item.get("engine") or "") == engine
        ]
        flags = self._flags(
            processing_found=processing_found,
            entities=entities,
            evidence=evidence,
            message_id=message_id,
            link_id_field=_LINK_ID_FIELD[engine],
            links=links,
            audit_failed=audit_failed,
            manual_attempted=bool(manual_for_engine),
        )
        summary = self._summary(processing_found, operations_view.get("decision") or "", entities, evidence)
        lines = self._lines(
            processing_found=processing_found,
            state=operations_view.get("state") or "",
            entities=entities,
            evidence=evidence,
            audit_count=audits["matched_count"],
            audit_failed=audit_failed,
            flags=flags,
        )
        return {
            "engine": engine,
            "state": operations_view.get("state") or "",
            "state_label": operations_view.get("state_label") or "",
            "decision": operations_view.get("decision") or "",
            "retryable": bool(operations_view.get("retryable")),
            "retry_type": operations_view.get("retry_type") or "",
            "requires_manual_investigation": bool(operations_view.get("requires_manual_investigation")),
            "notice": list(operations_view.get("notice") or []),
            "processing_found": processing_found,
            "processing": self._processing_block(engine, record),
            "entity_count": len(entities),
            "entity_ids": [str(item.get("id") or "") for item in entities if item.get("id")],
            "entities": [self._entity_block(engine, item) for item in entities],
            "evidence_count": evidence["total"],
            "evidence": evidence["public"],
            "audit_events": audits["events"],
            "audit_matched_count": audits["matched_count"],
            "audit_limit": AUDIT_LIMIT,
            "diagnostic_flags": flags,
            "diagnosis_summary": summary,
            "investigation_lines": lines,
            "audit_notice": AUDIT_NOTICE,
        }

    def _related(self, engine: str, store: Any, conversation_id: str, message_id: str, record: Optional[dict]):
        if store is None or not conversation_id:
            return [], []
        id_field = _LINK_ID_FIELD[engine]
        try:
            links = list(store.list_links(conversation_id) or [])
        except Exception:
            links = []
        message_links = [
            item for item in links
            if isinstance(item, dict) and str(item.get("message_id") or "") == message_id
        ]
        linked_ids = {
            str(item.get(id_field) or "")
            for item in message_links
            if item.get(id_field)
        }
        named_ids = set(_processing_entity_ids(engine, record))
        try:
            rows = _list_entities(store, engine, conversation_id)
        except Exception:
            rows = []
        chosen = []
        seen = set()
        for entity in rows:
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("id") or "")
            if not entity_id or entity_id in seen:
                continue
            created_hit = bool(message_id) and str(entity.get("created_msg_id") or "") == message_id
            if created_hit or entity_id in linked_ids or entity_id in named_ids:
                chosen.append(entity)
                seen.add(entity_id)
        return chosen, message_links

    def _evidence(self, engine: str, links: list) -> dict:
        id_field = _LINK_ID_FIELD[engine]
        buckets = {relation: [] for relation in RELATION_ORDER}
        other = []
        for link in links:
            relation = str(link.get("relation") or "").strip().upper()
            created_at = str(link.get("created_at") or "").strip()
            row = {
                "id": link.get("id") or "",
                "relation": relation or "未提供",
                "message_id": str(link.get("message_id") or ""),
                "entity_id": str(link.get(id_field) or ""),
                "confidence": _show(link.get("confidence")),
                "timestamps": [
                    {
                        "field": "created_at",
                        "value": created_at or "未提供",
                        "source": "evidence.created_at",
                    }
                ],
            }
            if relation in buckets:
                buckets[relation].append(row)
            else:
                other.append(row)
        counts = {relation: len(buckets[relation]) for relation in RELATION_ORDER}
        total = sum(counts.values()) + len(other)
        return {
            "total": total,
            "public": {
                "counts": counts,
                "CREATED_BY": buckets[RELATION_CREATED_BY],
                "UPDATED_BY": buckets[RELATION_UPDATED_BY],
                "RELATED": buckets[RELATION_RELATED],
                "other": other,
            },
        }

    def _audits(self, engine: str, store: Any, conversation_id: str, message_id: str) -> dict:
        if store is None:
            return {"events": [], "matched_count": 0, "all_matches": []}
        try:
            rows = store.read_audit(limit=0) or []
        except Exception:
            rows = []
        matched = []
        for event in rows:
            if not isinstance(event, dict):
                continue
            if str(event.get("message_id") or "") != message_id:
                continue
            if conversation_id and str(event.get("conversation_id") or "") != conversation_id:
                continue
            matched.append(event)
        shown = matched[-AUDIT_LIMIT:]
        decision_key = _AUDIT_DECISION_KEY.get(engine, "")
        events = []
        for event in shown:
            stamp = str(event.get("ts") or "").strip()
            events.append({
                "decision": str(event.get(decision_key) or ""),
                "error": str(event.get("error") or ""),
                "event": event,
                "timestamps": [
                    {
                        "field": "ts",
                        "value": stamp or "未提供",
                        "source": "audit.ts",
                    }
                ],
            })
        return {
            "events": events,
            "matched_count": len(matched),
            "all_matches": [{"event": item} for item in matched],
        }

    def _manual_actions(self, conversation_id: str, message_id: str) -> list:
        try:
            rows = read_action_audit(self.root_dir) or []
        except Exception:
            rows = []
        matched = []
        for event in rows:
            if not isinstance(event, dict):
                continue
            if str(event.get("message_id") or "") != message_id:
                continue
            if conversation_id and str(event.get("conversation_id") or "") != conversation_id:
                continue
            matched.append(event)
        shown = []
        for event in matched[-MANUAL_ACTION_LIMIT:]:
            stamp = str(event.get("ts") or "").strip()
            shown.append({
                "event": str(event.get("event") or ""),
                "engine": str(event.get("engine") or ""),
                "error": str(event.get("error") or ""),
                "error_code": str(event.get("error_code") or ""),
                "executed": bool(event.get("executed")),
                "before_state": str(event.get("before_state") or ""),
                "after_state": str(event.get("after_state") or ""),
                "retry_result": str(event.get("retry_result") or ""),
                "timestamps": [
                    {
                        "field": "ts",
                        "value": stamp or "未提供",
                        "source": "operations_action_audit.ts",
                    }
                ],
            })
        return shown

    def _flags(
        self,
        *,
        processing_found: bool,
        entities: list,
        evidence: dict,
        message_id: str,
        link_id_field: str,
        links: list,
        audit_failed: bool,
        manual_attempted: bool,
    ) -> list:
        counts = evidence["public"]["counts"]
        flags = [FLAG_PROCESSING_PRESENT if processing_found else FLAG_PROCESSING_MISSING]
        if entities:
            flags.append(FLAG_ENTITY_PRESENT)
        if counts[RELATION_CREATED_BY]:
            flags.append(FLAG_CREATED_BY_PRESENT)
        if counts[RELATION_UPDATED_BY]:
            flags.append(FLAG_UPDATED_BY_PRESENT)
        if counts[RELATION_RELATED]:
            flags.append(FLAG_RELATED_PRESENT)
        if self._creation_evidence(entities, links, message_id, link_id_field):
            flags.append(FLAG_CREATION_EVIDENCE_PRESENT)
        if audit_failed:
            flags.append(FLAG_AUDIT_FAILED_PRESENT)
        if manual_attempted:
            flags.append(FLAG_MANUAL_RETRY_ATTEMPTED)
        return flags

    def _creation_evidence(self, entities: list, links: list, message_id: str, link_id_field: str) -> bool:
        if not message_id:
            return False
        created_ids = {
            str(link.get(link_id_field) or "")
            for link in links
            if str(link.get("relation") or "").strip().upper() == RELATION_CREATED_BY and link.get(link_id_field)
        }
        for entity in entities:
            if str(entity.get("created_msg_id") or "") != message_id:
                continue
            if str(entity.get("id") or "") in created_ids:
                return True
        return False

    def _summary(self, processing_found: bool, decision: str, entities: list, evidence: dict) -> str:
        if processing_found:
            stored = str(decision or "").strip()
            if stored:
                return SUMMARY_PRESENT % stored
            return SUMMARY_PRESENT_EMPTY
        if entities or evidence["total"]:
            return SUMMARY_MISSING_EVIDENCE
        return SUMMARY_MISSING_NONE

    def _lines(
        self,
        *,
        processing_found: bool,
        state: str,
        entities: list,
        evidence: dict,
        audit_count: int,
        audit_failed: bool,
        flags: list,
    ) -> list:
        lines = []
        if not processing_found:
            lines.extend([
                "处理状态未知",
                "Processing Record：未找到",
                "禁止自动重试",
                "需要人工调查",
                "需人工调查",
            ])
            if entities or evidence["total"]:
                lines.append("系统存在业务写入痕迹，但无法从现有数据确定原 Processing Decision。")
                lines.append("禁止自动重试。")
            elif audit_count == 0:
                lines.append("未发现业务处理记录")
            else:
                lines.append("未发现相关业务实体或证据。")
        elif state == STATE_NOT_FOUND_UNKNOWN:
            lines.extend([
                "处理状态未知",
                "禁止自动重试",
                "需要人工调查",
                "需人工调查",
            ])
        if FLAG_CREATION_EVIDENCE_PRESENT in flags:
            lines.append("存在创建证据")
        if FLAG_RELATED_PRESENT in flags:
            lines.append("消息与该业务实体有关")
        if audit_failed:
            lines.append("Engine Audit：FAILED")
        lines.append(AUDIT_NOTICE)
        return lines

    def _processing_block(self, engine: str, record: Optional[dict]) -> dict:
        if not record:
            return {
                "found": False,
                "label": "未找到",
                "record": None,
                "fields": [],
                "timestamps": [],
            }
        version_key = _VERSION_FIELD[engine]
        decision_key = _DECISION_FIELD[engine]
        fields = [
            {"name": "message_id", "value": _show(record.get("message_id"))},
            {"name": "conversation_id", "value": _show(record.get("conversation_id"))},
            {"name": version_key, "value": _show(record.get(version_key))},
            {"name": decision_key, "value": _show(record.get(decision_key))},
            {"name": "topic_id", "value": _show(record.get("topic_id"))},
        ]
        id_key = _PROCESSING_ID_FIELD.get(engine)
        if id_key:
            fields.append({"name": id_key, "value": _show(record.get(id_key) or [])})
        fields.append({"name": "error", "value": _show(record.get("error"))})
        for extra in ("extractor_prompt_name", "extractor_prompt_hash"):
            if extra in record:
                fields.append({"name": extra, "value": _show(record.get(extra))})
        processed_at = str(record.get("processed_at") or "").strip()
        return {
            "found": True,
            "label": "已找到",
            "record": dict(record),
            "fields": fields,
            "timestamps": [
                {
                    "field": "processed_at",
                    "value": processed_at or "未提供",
                    "source": "processing.processed_at",
                }
            ],
        }

    def _entity_block(self, engine: str, entity: dict) -> dict:
        fields = []
        timestamps = []
        for source_key, label in _ENTITY_FIELDS.get(engine, ()):
            fields.append({
                "name": label,
                "source_field": source_key,
                "value": _show(entity.get(source_key)),
            })
            if source_key in _TIME_SOURCE:
                raw = str(entity.get(source_key) or "").strip()
                timestamps.append({
                    "field": source_key,
                    "value": raw or "未提供",
                    "source": _TIME_SOURCE[source_key],
                })
        return {
            "id": str(entity.get("id") or ""),
            "fields": fields,
            "timestamps": timestamps,
            "record": dict(entity),
        }
