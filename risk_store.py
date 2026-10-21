# -*- coding: utf-8 -*-
"""P5 Risk Store：独立 JSON 存储 Risk / RiskMessageLink / RiskProcessingRecord。

不写入 config.local.json、topics.json、tasks.json、decisions.json、chat_contexts、CoreMemory、recurring_reminders。
不上 SQLite / ORM / Redis / Vector DB / action_store。
不修改 Topic Store / Task Store / Decision Store 文件格式。
v1 只写 OPEN，不写 MITIGATED / RESOLVED / CLOSED，不写 severity。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from typing import Optional

from filelock import FileLock

from conversation_store import utc_now_iso
from store_io import atomic_write_json, lock_path_for, read_json
from topic_store import TopicStore, TopicStoreError

SCHEMA_VERSION = 1
RISK_STATUS_OPEN = "OPEN"
RISK_STATUS_MITIGATED = "MITIGATED"
RISK_STATUS_RESOLVED = "RESOLVED"
RISK_STATUS_CLOSED = "CLOSED"
ALLOWED_WRITE_STATUSES = (RISK_STATUS_OPEN,)
FORBIDDEN_STATUSES = (RISK_STATUS_MITIGATED, RISK_STATUS_RESOLVED, RISK_STATUS_CLOSED)

RELATION_CREATED_BY = "CREATED_BY"
RELATION_RELATED = "RELATED"
RELATION_UPDATED_BY = "UPDATED_BY"
ALLOWED_RELATIONS = (RELATION_CREATED_BY, RELATION_RELATED, RELATION_UPDATED_BY)
FORBIDDEN_RELATIONS = ("MITIGATION_EVIDENCE", "RESOLUTION_EVIDENCE")

DECISION_NEW_RISK = "NEW_RISK"
DECISION_RISK_UPDATE = "RISK_UPDATE"
DECISION_UNRELATED = "UNRELATED"
DECISION_SKIPPED = "SKIPPED"
DECISION_FAILED = "FAILED"
SUCCESS_DECISIONS = {
    DECISION_NEW_RISK,
    DECISION_RISK_UPDATE,
    DECISION_UNRELATED,
    DECISION_SKIPPED,
}

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
ALLOWED_CONFIDENCE = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)

DEFAULT_PROCESSING_VERSION = 1
FORBIDDEN_RISK_KEYS = {
    "severity",
    "severity_text",
    "owner",
    "owner_id",
    "owner_text",
    "due",
    "due_at",
    "due_text",
    "decision_id",
    "decision_ids",
    "decided_by",
    "mitigation_text",
    "embedding",
}


class RiskStoreError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


def _sha1_12(seed: str) -> str:
    return hashlib.sha1((seed or "").encode("utf-8")).hexdigest()[:12]


def make_risk_id(
    conversation_id: str,
    topic_id: str,
    created_msg_id: str,
    ordinal: int = 0,
    created_at: str = "",
) -> str:
    seed = "%s|%s|%s|%s|%s" % (
        conversation_id or "",
        topic_id or "",
        created_msg_id or "",
        int(ordinal),
        created_at or "",
    )
    return "risk_%s" % _sha1_12(seed)


def make_rlink_id(risk_id: str, message_id: str, relation: str) -> str:
    return "rlink_%s" % _sha1_12("%s|%s|%s" % (risk_id or "", message_id or "", relation or ""))


def processing_key(message_id: str, version: int = DEFAULT_PROCESSING_VERSION) -> str:
    return "%s|%s" % (message_id, int(version))


def _lookup_by_id(items: list, entity_id) -> Optional[dict]:
    for item in items:
        if item.get("id") == entity_id:
            return item
    return None


def _same_logical_entity(existing: Optional[dict], incoming: dict) -> bool:
    if existing is None:
        return False
    return (
        str(existing.get("conversation_id") or "") == str(incoming.get("conversation_id") or "")
        and str(existing.get("topic_id") or "") == str(incoming.get("topic_id") or "")
        and str(existing.get("created_msg_id") or "") == str(incoming.get("created_msg_id") or "")
    )


def _remap_link(raw_link: dict, id_map: dict, entity_key: str, make_id) -> dict:
    link = dict(raw_link or {})
    original = link.get(entity_key)
    final = id_map.get(original, original)
    if original and final and final != original:
        link[entity_key] = final
        link["id"] = make_id(final, str(link.get("message_id") or ""), str(link.get("relation") or ""))
    return link


def content_preview(text: str, limit: int = 80) -> str:
    return str(text or "")[:limit]


def _safe_conversation_id(conversation_id: str) -> str:
    cid = str(conversation_id or "").strip()
    if not cid or not re.match(r"^conv_[A-Za-z0-9_]+$", cid):
        raise RiskStoreError("INVALID_CONVERSATION_ID", "conversation_id 必须是 conv_*", cid)
    return cid


def _safe_topic_id(topic_id: str) -> str:
    tid = str(topic_id or "").strip()
    if not tid or not re.match(r"^topic_[A-Za-z0-9_]+$", tid):
        raise RiskStoreError("INVALID_TOPIC_ID", "topic_id 必须是 topic_*", tid)
    return tid


def _safe_risk_id(risk_id: str) -> str:
    value = str(risk_id or "").strip()
    if not value or not re.match(r"^risk_[A-Za-z0-9_]+$", value):
        raise RiskStoreError("INVALID_RISK_ID", "risk_id 必须是 risk_*", value)
    return value


def _normalize_task_id(task_id) -> str:
    value = str(task_id or "").strip()
    if not value or value.lower() in ("none", "null"):
        return ""
    if not re.match(r"^task_[A-Za-z0-9_]+$", value):
        return ""
    return value


def _read_jsonl(path: str) -> list:
    if not os.path.isfile(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _append_jsonl(path: str, obj: dict) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    lock = FileLock(lock_path_for(path))
    with lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _is_success_processing(record: Optional[dict]) -> bool:
    if not record:
        return False
    summary = str(record.get("decision_summary") or record.get("decision") or "")
    if not summary:
        return False
    parts = [item.strip() for item in summary.replace(";", ",").split(",") if item.strip()]
    return bool(parts) and all(item in SUCCESS_DECISIONS for item in parts)


class RiskStore:
    def __init__(self, root_dir: str, topic_store: Optional[TopicStore] = None, task_store=None):
        self.root_dir = os.path.abspath(root_dir)
        self.store_dir = os.path.join(self.root_dir, "data", "risk_store")
        self.conversations_dir = os.path.join(self.store_dir, "conversations")
        self.audit_path = os.path.join(self.store_dir, "risk_engine_audit.jsonl")
        self.topic_store = topic_store
        self.task_store = task_store

    def conversation_dir(self, conversation_id: str) -> str:
        return os.path.join(self.conversations_dir, _safe_conversation_id(conversation_id))

    def _paths(self, conversation_id: str) -> dict:
        base = self.conversation_dir(conversation_id)
        return {
            "dir": base,
            "risks": os.path.join(base, "risks.json"),
            "links": os.path.join(base, "links.json"),
            "processed": os.path.join(base, "processed.json"),
        }

    def delete_conversation_risk_data(self, conversation_id: str) -> bool:
        cid = _safe_conversation_id(conversation_id)
        path = os.path.join(self.conversations_dir, cid)
        if not os.path.isdir(path):
            return False
        shutil.rmtree(path)
        return True

    def require_topic(self, conversation_id: str, topic_id: str) -> dict:
        cid = _safe_conversation_id(conversation_id)
        tid = _safe_topic_id(topic_id)
        if self.topic_store is None:
            raise RiskStoreError("TOPIC_STORE_REQUIRED", "创建 Risk 前必须能校验 Topic")
        try:
            topic = self.topic_store.get_topic(cid, tid)
        except TopicStoreError as exc:
            raise RiskStoreError(exc.code, exc.message, exc.detail)
        if not topic:
            raise RiskStoreError("TOPIC_NOT_FOUND", "Topic 不存在，禁止写 Risk", tid)
        if str(topic.get("conversation_id") or "") != cid:
            raise RiskStoreError("TOPIC_CONVERSATION_MISMATCH", "Topic 不属于当前 Conversation", tid)
        return topic

    def require_created_by_message(self, conversation_id: str, message_id: str) -> dict:
        cid = _safe_conversation_id(conversation_id)
        mid = str(message_id or "").strip()
        if not mid:
            raise RiskStoreError("EVIDENCE_REQUIRED", "没有 Evidence 的 Risk 不允许写入")
        if self.topic_store is None:
            raise RiskStoreError("TOPIC_STORE_REQUIRED", "CREATED_BY 必须能校验 MessageRecord")
        message = self.topic_store.get_message(cid, mid)
        if message is None:
            raise RiskStoreError("MESSAGE_NOT_FOUND", "CREATED_BY.message_id 必须已存在于 Topic Store", mid)
        return message

    def _accepted_task_id(self, conversation_id: str, topic_id: str, task_id) -> str:
        value = _normalize_task_id(task_id)
        if not value:
            return ""
        if self.task_store is None:
            return value
        try:
            task = self.task_store.get_task(conversation_id, value)
        except Exception:
            return ""
        if not task:
            return ""
        if str(task.get("conversation_id") or "") != conversation_id:
            return ""
        if str(task.get("topic_id") or "") != topic_id:
            return ""
        if str(task.get("status") or "") != "OPEN":
            return ""
        return value

    # --- Risk ---

    def list_risks(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["risks"]
        data = read_json(path, default={"risks": []})
        if isinstance(data, list):
            return data
        return list(data.get("risks") or [])

    def get_risk(self, conversation_id: str, risk_id: str) -> Optional[dict]:
        for item in self.list_risks(conversation_id):
            if item.get("id") == risk_id:
                return item
        return None

    def list_open_risks(self, conversation_id: str, topic_id: str, *, limit: int = 10) -> list:
        items = [
            item
            for item in self.list_risks(conversation_id)
            if item.get("topic_id") == topic_id and item.get("status") == RISK_STATUS_OPEN
        ]
        items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        if limit <= 0:
            return items
        return items[:limit]

    def create_risk(self, record: dict, *, ordinal: int = 0, related_message_ids=None) -> dict:
        """Internal/legacy 直连创建。生产 Engine 走 commit_apply。同 id 仍 suffix。"""
        item = self._normalize_new_risk(record, ordinal=ordinal)
        cid = item["conversation_id"]
        self.require_topic(cid, item["topic_id"])
        created_msg_id = str(item.get("created_msg_id") or "").strip()
        self.require_created_by_message(cid, created_msg_id)
        risks = self.list_risks(cid)
        used = {risk.get("id") for risk in risks}
        risk_id = item["id"]
        if risk_id in used:
            suffix = 2
            while "%s_%s" % (risk_id, suffix) in used:
                suffix += 1
            risk_id = "%s_%s" % (risk_id, suffix)
            item["id"] = risk_id
        risks.append(item)
        links = self.list_links(cid)
        created_link = {
            "id": make_rlink_id(risk_id, created_msg_id, RELATION_CREATED_BY),
            "risk_id": risk_id,
            "message_id": created_msg_id,
            "relation": RELATION_CREATED_BY,
            "confidence": item.get("confidence") or CONFIDENCE_LOW,
            "created_at": item.get("created_at") or utc_now_iso(),
        }
        if not _link_exists(links, created_link):
            links.append(created_link)
        for related_id in related_message_ids or []:
            related_id = str(related_id or "").strip()
            if not related_id or related_id == created_msg_id:
                continue
            if self.topic_store is not None and self.topic_store.get_message(cid, related_id) is None:
                continue
            related_link = {
                "id": make_rlink_id(risk_id, related_id, RELATION_RELATED),
                "risk_id": risk_id,
                "message_id": related_id,
                "relation": RELATION_RELATED,
                "confidence": item.get("confidence") or CONFIDENCE_LOW,
                "created_at": item.get("created_at") or utc_now_iso(),
            }
            if not _link_exists(links, related_link):
                links.append(related_link)
        self._assert_at_least_one_created_by(item["id"], links)
        self._commit(cid, risks, links)
        return item

    def update_risk(self, conversation_id: str, risk_id: str, **fields) -> Optional[dict]:
        cid = _safe_conversation_id(conversation_id)
        rid = _safe_risk_id(risk_id)
        if "status" in fields and fields["status"]:
            raise RiskStoreError("INVALID_STATUS", "RISK_UPDATE 不得改 status", str(fields["status"]))
        if "conversation_id" in fields or "topic_id" in fields:
            raise RiskStoreError("IMMUTABLE_FK", "不得改 conversation_id / topic_id")
        for key in FORBIDDEN_RISK_KEYS:
            if key in fields and fields.get(key) not in (None, ""):
                raise RiskStoreError("FORBIDDEN_FIELD", "v1 禁止写入该字段", key)
        risks = self.list_risks(cid)
        updated = None
        now = utc_now_iso()
        for risk in risks:
            if risk.get("id") != rid:
                continue
            for key in ("title", "description", "condition_text", "impact_text", "confidence"):
                if key not in fields:
                    continue
                value = fields[key]
                if value is None:
                    continue
                text = str(value).strip() if key != "confidence" else str(value or "").strip().upper()
                if key == "title" and text:
                    risk["title"] = text[:40]
                elif key == "description":
                    risk["description"] = text[:500]
                elif key == "condition_text" and text:
                    risk["condition_text"] = text[:500]
                elif key == "impact_text" and text:
                    risk["impact_text"] = text[:500]
                elif key == "confidence" and text in ALLOWED_CONFIDENCE:
                    risk["confidence"] = text
            if "task_id" in fields:
                incoming = _normalize_task_id(fields.get("task_id"))
                current = str(risk.get("task_id") or "")
                if not current and incoming:
                    accepted = self._accepted_task_id(cid, risk.get("topic_id") or "", incoming)
                    if accepted:
                        risk["task_id"] = accepted
            risk["updated_at"] = now
            updated = risk
            break
        if updated is None:
            return None
        self._save_risks(cid, risks)
        return updated

    def _normalize_new_risk(self, record: dict, ordinal: int = 0) -> dict:
        data = record if isinstance(record, dict) else {}
        for key in FORBIDDEN_RISK_KEYS:
            data = {k: v for k, v in data.items() if k != key}
        cid = _safe_conversation_id(data.get("conversation_id") or "")
        topic_id = _safe_topic_id(data.get("topic_id") or "")
        created_msg_id = str(data.get("created_msg_id") or "").strip()
        created_at = str(data.get("created_at") or utc_now_iso())
        status = str(data.get("status") or RISK_STATUS_OPEN).strip().upper() or RISK_STATUS_OPEN
        if status in FORBIDDEN_STATUSES or status not in ALLOWED_WRITE_STATUSES:
            raise RiskStoreError("INVALID_STATUS", "v1 只允许写入 OPEN", status)
        confidence = str(data.get("confidence") or CONFIDENCE_LOW).strip().upper()
        if confidence not in ALLOWED_CONFIDENCE:
            confidence = CONFIDENCE_LOW
        title = str(data.get("title") or "").strip()[:40]
        condition_text = str(data.get("condition_text") or "").strip()[:500]
        impact_text = str(data.get("impact_text") or "").strip()[:500]
        if not condition_text or not impact_text:
            raise RiskStoreError("INVALID_RISK_DECISION", "NEW_RISK 必须同时有 condition_text 与 impact_text")
        if not title:
            raise RiskStoreError("INVALID_RISK_DECISION", "NEW_RISK 需要 title")
        explicit_id = str(data.get("id") or "").strip()
        if explicit_id:
            risk_id = _safe_risk_id(explicit_id)
        else:
            risk_id = make_risk_id(cid, topic_id, created_msg_id, ordinal, created_at)
        task_id = self._accepted_task_id(cid, topic_id, data.get("task_id"))
        return {
            "id": risk_id,
            "conversation_id": cid,
            "topic_id": topic_id,
            "task_id": task_id,
            "title": title,
            "description": str(data.get("description") or "").strip()[:500],
            "condition_text": condition_text,
            "impact_text": impact_text,
            "status": RISK_STATUS_OPEN,
            "confidence": confidence,
            "created_msg_id": created_msg_id,
            "created_at": created_at,
            "updated_at": str(data.get("updated_at") or created_at),
            "schema_version": int(data.get("schema_version") or SCHEMA_VERSION),
        }

    def _save_risks(self, conversation_id: str, risks: list) -> None:
        path = self._paths(conversation_id)["risks"]
        atomic_write_json(path, {"risks": risks})

    # --- RiskMessageLink ---

    def list_links(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["links"]
        data = read_json(path, default={"links": []})
        if isinstance(data, list):
            return data
        return list(data.get("links") or [])

    def add_link(
        self,
        conversation_id: str,
        risk_id: str,
        message_id: str,
        relation: str,
        confidence: str = CONFIDENCE_MEDIUM,
        created_at: str = "",
    ) -> dict:
        cid = _safe_conversation_id(conversation_id)
        rel = str(relation or "").strip().upper()
        if rel in FORBIDDEN_RELATIONS:
            raise RiskStoreError("INVALID_RELATION", "v1 禁止该 relation", rel)
        if rel not in ALLOWED_RELATIONS:
            raise RiskStoreError("INVALID_RELATION", "非法 relation", rel)
        links = self.list_links(cid)
        for prev in links:
            if (
                prev.get("risk_id") == risk_id
                and prev.get("message_id") == message_id
                and prev.get("relation") == rel
            ):
                return prev
        now = created_at or utc_now_iso()
        item = {
            "id": make_rlink_id(risk_id, message_id, rel),
            "risk_id": risk_id,
            "message_id": message_id,
            "relation": rel,
            "confidence": confidence if confidence in ALLOWED_CONFIDENCE else CONFIDENCE_LOW,
            "created_at": now,
        }
        links.append(item)
        self._save_links(cid, links)
        return item

    def links_for_risk(self, conversation_id: str, risk_id: str) -> list:
        return [item for item in self.list_links(conversation_id) if item.get("risk_id") == risk_id]

    def _save_links(self, conversation_id: str, links: list) -> None:
        path = self._paths(conversation_id)["links"]
        atomic_write_json(path, {"links": links})

    def _commit(self, conversation_id: str, risks: list, links: list) -> None:
        cid = _safe_conversation_id(conversation_id)
        old_risks = self.list_risks(cid)
        old_links = self.list_links(cid)
        try:
            self._save_risks(cid, risks)
            self._save_links(cid, links)
        except Exception:
            try:
                self._save_risks(cid, old_risks)
                self._save_links(cid, old_links)
            except Exception:
                pass
            raise

    def commit_apply(
        self,
        conversation_id: str,
        *,
        new_risks: Optional[list] = None,
        updates: Optional[list] = None,
        new_links: Optional[list] = None,
    ) -> dict:
        """先在内存合并并校验 CREATED_BY，再写 risks.json / links.json。失败则回滚，避免半套 Risk。

        同一确定性 id 且同一 created_msg_id/topic 视为幂等 skip（retry 不 suffix）。
        仅当同 id 对应不同消息时才走碰撞后缀 _2。
        suffix 后 links / applied_ids / CREATED_BY 校验一律使用最终 id。
        """
        cid = _safe_conversation_id(conversation_id)
        risks = list(self.list_risks(cid))
        links = list(self.list_links(cid))
        used_ids = {item.get("id") for item in risks}
        applied_ids = []
        created_final_ids = []
        id_map = {}
        for raw in new_risks or []:
            item = dict(raw)
            for key in FORBIDDEN_RISK_KEYS:
                item.pop(key, None)
            item["status"] = RISK_STATUS_OPEN
            if not str(item.get("condition_text") or "").strip() or not str(item.get("impact_text") or "").strip():
                raise RiskStoreError("INVALID_RISK_DECISION", "NEW_RISK 必须同时有 condition_text 与 impact_text")
            original_id = item.get("id")
            risk_id = original_id
            existing = _lookup_by_id(risks, risk_id)
            if _same_logical_entity(existing, item):
                applied_ids.append(existing["id"])
                created_final_ids.append(existing["id"])
                if original_id:
                    id_map[original_id] = existing["id"]
                continue
            if risk_id in used_ids:
                suffix = 2
                while "%s_%s" % (risk_id, suffix) in used_ids:
                    suffix += 1
                risk_id = "%s_%s" % (risk_id, suffix)
                item["id"] = risk_id
            used_ids.add(item["id"])
            risks.append(item)
            applied_ids.append(item["id"])
            created_final_ids.append(item["id"])
            if original_id:
                id_map[original_id] = item["id"]
        for change in updates or []:
            target_id = change.get("id")
            for risk in risks:
                if risk.get("id") != target_id:
                    continue
                if "status" in (change.get("fields") or {}):
                    raise RiskStoreError("INVALID_STATUS", "RISK_UPDATE 不得改 status")
                for key, value in (change.get("fields") or {}).items():
                    if key in FORBIDDEN_RISK_KEYS or key in ("status", "conversation_id", "topic_id"):
                        continue
                    risk[key] = value
                risk["updated_at"] = change.get("updated_at") or utc_now_iso()
                risk["status"] = RISK_STATUS_OPEN
                applied_ids.append(risk["id"])
                break
        for raw_link in new_links or []:
            link = _remap_link(raw_link, id_map, "risk_id", make_rlink_id)
            if _link_exists(links, link):
                continue
            rel = str(link.get("relation") or "").strip().upper()
            if rel in FORBIDDEN_RELATIONS:
                raise RiskStoreError("INVALID_RELATION", "v1 禁止该 relation", rel)
            if rel not in ALLOWED_RELATIONS:
                raise RiskStoreError("INVALID_RELATION", "非法 relation", rel)
            links.append(link)
        for risk_id in created_final_ids:
            if not risk_id:
                continue
            self._assert_at_least_one_created_by(risk_id, links)
            created = [
                item
                for item in links
                if item.get("risk_id") == risk_id and item.get("relation") == RELATION_CREATED_BY
            ]
            self.require_created_by_message(cid, created[0].get("message_id"))
        self._commit(cid, risks, links)
        return {"risk_ids": applied_ids}

    def _assert_at_least_one_created_by(self, risk_id: str, links: list) -> None:
        created = [
            item
            for item in links
            if item.get("risk_id") == risk_id and item.get("relation") == RELATION_CREATED_BY
        ]
        if len(created) < 1:
            raise RiskStoreError(
                "CREATED_BY_REQUIRED",
                "每个 Risk 必须至少有 1 个 CREATED_BY",
                risk_id,
            )

    # --- RiskProcessingRecord ---

    def get_processing(
        self,
        conversation_id: str,
        message_id: str,
        version: int = DEFAULT_PROCESSING_VERSION,
    ) -> Optional[dict]:
        records = self._load_processed(conversation_id)
        return records.get(processing_key(message_id, version))

    def has_successful_processing(
        self,
        conversation_id: str,
        message_id: str,
        version: int = DEFAULT_PROCESSING_VERSION,
    ) -> bool:
        return _is_success_processing(self.get_processing(conversation_id, message_id, version))

    def write_processing(self, record: dict) -> dict:
        data = record if isinstance(record, dict) else {}
        cid = _safe_conversation_id(data.get("conversation_id") or "")
        message_id = str(data.get("message_id") or "").strip()
        version = int(data.get("risk_processing_version") or DEFAULT_PROCESSING_VERSION)
        if not message_id:
            raise RiskStoreError("MESSAGE_ID_REQUIRED", "processing 缺少 message_id")
        risk_ids = data.get("risk_ids") or []
        if not isinstance(risk_ids, list):
            risk_ids = []
        item = {
            "message_id": message_id,
            "conversation_id": cid,
            "topic_id": data.get("topic_id") or None,
            "risk_processing_version": version,
            "extractor_prompt_name": str(data.get("extractor_prompt_name") or ""),
            "extractor_prompt_hash": str(data.get("extractor_prompt_hash") or ""),
            "decision_summary": str(data.get("decision_summary") or data.get("decision") or ""),
            "risk_ids": [str(value) for value in risk_ids if value],
            "processed_at": str(data.get("processed_at") or utc_now_iso()),
            "error": str(data.get("error") or ""),
        }
        records = self._load_processed(cid)
        key = processing_key(message_id, version)
        prev = records.get(key)
        if _is_success_processing(prev):
            return prev
        records[key] = item
        self._save_processed(cid, records)
        return item

    def _load_processed(self, conversation_id: str) -> dict:
        path = self._paths(conversation_id)["processed"]
        data = read_json(path, default={"records": {}})
        if isinstance(data, dict) and isinstance(data.get("records"), dict):
            return dict(data["records"])
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k != "records"}
        return {}

    def _save_processed(self, conversation_id: str, records: dict) -> None:
        path = self._paths(conversation_id)["processed"]
        atomic_write_json(path, {"records": records})

    # --- Audit ---

    def write_audit(self, event: dict) -> dict:
        item = dict(event or {})
        item.setdefault("ts", utc_now_iso())
        if "content" in item:
            item["content"] = content_preview(item.get("content") or "")
        if "content_preview" in item:
            item["content_preview"] = content_preview(item.get("content_preview") or "")
        for secret_key in ("api_key", "API_KEY", "Authorization", "authorization", "DEEPSEEK_API_KEY"):
            item.pop(secret_key, None)
        _append_jsonl(self.audit_path, item)
        return item

    def read_audit(self, limit: int = 200) -> list:
        items = _read_jsonl(self.audit_path)
        if limit <= 0:
            return items
        return items[-limit:]


def _link_exists(links: list, candidate: dict) -> bool:
    return any(
        prev.get("risk_id") == candidate.get("risk_id")
        and prev.get("message_id") == candidate.get("message_id")
        and prev.get("relation") == candidate.get("relation")
        for prev in links
    )
