# -*- coding: utf-8 -*-
"""P5 Decision Store：独立 JSON 存储 Decision / DecisionMessageLink / DecisionProcessingRecord。

不写入 config.local.json、topics.json、tasks.json、chat_contexts、CoreMemory、recurring_reminders。
不上 SQLite / ORM / Redis / Vector DB / action_store。
不修改 Topic Store / Task Store 文件格式。
v1 不提供原地覆盖 decision_text，不自动写 SUPERSEDED / CANCELLED。
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
DECISION_STATUS_RECORDED = "RECORDED"
DECISION_STATUS_SUPERSEDED = "SUPERSEDED"
DECISION_STATUS_CANCELLED = "CANCELLED"
ALLOWED_WRITE_STATUSES = (DECISION_STATUS_RECORDED,)

RELATION_CREATED_BY = "CREATED_BY"
RELATION_RELATED = "RELATED"
ALLOWED_RELATIONS = (RELATION_CREATED_BY, RELATION_RELATED)
FORBIDDEN_RELATIONS = ("UPDATED_BY", "CONFIRMED_BY", "SUPERSEDED_BY")

DECISION_NEW_DECISION = "NEW_DECISION"
DECISION_UNRELATED = "UNRELATED"
DECISION_SKIPPED = "SKIPPED"
DECISION_FAILED = "FAILED"
SUCCESS_DECISIONS = {
    DECISION_NEW_DECISION,
    DECISION_UNRELATED,
    DECISION_SKIPPED,
}

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
ALLOWED_CONFIDENCE = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)

DEFAULT_PROCESSING_VERSION = 1
FORBIDDEN_DECISION_KEYS = {
    "task_id",
    "owner",
    "assignee",
    "assignee_text",
    "due",
    "due_text",
    "due_at",
    "severity",
    "risk_id",
    "risk_ids",
    "decided_by",
    "decided_by_id",
    "cancelled_reason",
    "embedding",
}


class DecisionStoreError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


def _sha1_12(seed: str) -> str:
    return hashlib.sha1((seed or "").encode("utf-8")).hexdigest()[:12]


def make_decision_id(
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
    return "dec_%s" % _sha1_12(seed)


def make_dlink_id(decision_id: str, message_id: str, relation: str) -> str:
    return "dlink_%s" % _sha1_12("%s|%s|%s" % (decision_id or "", message_id or "", relation or ""))


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
        raise DecisionStoreError("INVALID_CONVERSATION_ID", "conversation_id 必须是 conv_*", cid)
    return cid


def _safe_topic_id(topic_id: str) -> str:
    tid = str(topic_id or "").strip()
    if not tid or not re.match(r"^topic_[A-Za-z0-9_]+$", tid):
        raise DecisionStoreError("INVALID_TOPIC_ID", "topic_id 必须是 topic_*", tid)
    return tid


def _safe_decision_id(decision_id: str) -> str:
    value = str(decision_id or "").strip()
    if not value or not re.match(r"^dec_[A-Za-z0-9_]+$", value):
        raise DecisionStoreError("INVALID_DECISION_ID", "decision_id 必须是 dec_*", value)
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


class DecisionStore:
    def __init__(self, root_dir: str, topic_store: Optional[TopicStore] = None):
        self.root_dir = os.path.abspath(root_dir)
        self.store_dir = os.path.join(self.root_dir, "data", "decision_store")
        self.conversations_dir = os.path.join(self.store_dir, "conversations")
        self.audit_path = os.path.join(self.store_dir, "decision_engine_audit.jsonl")
        self.topic_store = topic_store

    def conversation_dir(self, conversation_id: str) -> str:
        return os.path.join(self.conversations_dir, _safe_conversation_id(conversation_id))

    def _paths(self, conversation_id: str) -> dict:
        base = self.conversation_dir(conversation_id)
        return {
            "dir": base,
            "decisions": os.path.join(base, "decisions.json"),
            "links": os.path.join(base, "links.json"),
            "processed": os.path.join(base, "processed.json"),
        }

    def delete_conversation_decision_data(self, conversation_id: str) -> bool:
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
            raise DecisionStoreError("TOPIC_STORE_REQUIRED", "创建 Decision 前必须能校验 Topic")
        try:
            topic = self.topic_store.get_topic(cid, tid)
        except TopicStoreError as exc:
            raise DecisionStoreError(exc.code, exc.message, exc.detail)
        if not topic:
            raise DecisionStoreError("TOPIC_NOT_FOUND", "Topic 不存在，禁止写 Decision", tid)
        if str(topic.get("conversation_id") or "") != cid:
            raise DecisionStoreError("TOPIC_CONVERSATION_MISMATCH", "Topic 不属于当前 Conversation", tid)
        return topic

    def require_created_by_message(self, conversation_id: str, message_id: str) -> dict:
        cid = _safe_conversation_id(conversation_id)
        mid = str(message_id or "").strip()
        if not mid:
            raise DecisionStoreError("EVIDENCE_REQUIRED", "没有 Evidence 的 Decision 不允许写入")
        if self.topic_store is None:
            raise DecisionStoreError("TOPIC_STORE_REQUIRED", "CREATED_BY 必须能校验 MessageRecord")
        message = self.topic_store.get_message(cid, mid)
        if message is None:
            raise DecisionStoreError("MESSAGE_NOT_FOUND", "CREATED_BY.message_id 必须已存在于 Topic Store", mid)
        return message

    # --- Decision ---

    def list_decisions(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["decisions"]
        data = read_json(path, default={"decisions": []})
        if isinstance(data, list):
            return data
        return list(data.get("decisions") or [])

    def get_decision(self, conversation_id: str, decision_id: str) -> Optional[dict]:
        for item in self.list_decisions(conversation_id):
            if item.get("id") == decision_id:
                return item
        return None

    def list_recorded_decisions(
        self,
        conversation_id: str,
        topic_id: str,
        *,
        limit: int = 10,
        current_effective: bool = True,
    ) -> list:
        items = [
            item
            for item in self.list_decisions(conversation_id)
            if item.get("topic_id") == topic_id and item.get("status") == DECISION_STATUS_RECORDED
        ]
        if current_effective:
            superseded_ids = {
                str(item.get("supersedes_decision_id") or "")
                for item in self.list_decisions(conversation_id)
                if item.get("supersedes_decision_id")
            }
            effective = [item for item in items if item.get("id") not in superseded_ids]
            if effective:
                items = effective
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        if limit <= 0:
            return items
        return items[:limit]

    def create_decision(self, record: dict, *, ordinal: int = 0, related_message_ids=None) -> dict:
        """Internal/legacy 直连创建。生产 Engine 走 commit_apply。同 id 仍 suffix。"""
        item = self._normalize_new_decision(record, ordinal=ordinal)
        cid = item["conversation_id"]
        self.require_topic(cid, item["topic_id"])
        created_msg_id = str(item.get("created_msg_id") or "").strip()
        self.require_created_by_message(cid, created_msg_id)
        self._require_supersedes(cid, item.get("supersedes_decision_id"))
        decisions = self.list_decisions(cid)
        used = {decision.get("id") for decision in decisions}
        decision_id = item["id"]
        if decision_id in used:
            suffix = 2
            while "%s_%s" % (decision_id, suffix) in used:
                suffix += 1
            decision_id = "%s_%s" % (decision_id, suffix)
            item["id"] = decision_id
        decisions.append(item)
        links = self.list_links(cid)
        created_link = {
            "id": make_dlink_id(decision_id, created_msg_id, RELATION_CREATED_BY),
            "decision_id": decision_id,
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
                "id": make_dlink_id(decision_id, related_id, RELATION_RELATED),
                "decision_id": decision_id,
                "message_id": related_id,
                "relation": RELATION_RELATED,
                "confidence": item.get("confidence") or CONFIDENCE_LOW,
                "created_at": item.get("created_at") or utc_now_iso(),
            }
            if not _link_exists(links, related_link):
                links.append(related_link)
        self._assert_exactly_one_created_by(item["id"], links)
        self._commit(cid, decisions, links)
        return item

    def _require_supersedes(self, conversation_id: str, supersedes_decision_id) -> None:
        value = str(supersedes_decision_id or "").strip()
        if not value or value.lower() == "none":
            return
        _safe_decision_id(value)
        if self.get_decision(conversation_id, value) is None:
            raise DecisionStoreError(
                "INVALID_SUPERSEDES_DECISION_ID",
                "supersedes_decision_id 必须指向已有 Decision",
                value,
            )

    def _normalize_new_decision(self, record: dict, ordinal: int = 0) -> dict:
        data = record if isinstance(record, dict) else {}
        for key in FORBIDDEN_DECISION_KEYS:
            data = {k: v for k, v in data.items() if k != key}
        cid = _safe_conversation_id(data.get("conversation_id") or "")
        topic_id = _safe_topic_id(data.get("topic_id") or "")
        created_msg_id = str(data.get("created_msg_id") or "").strip()
        created_at = str(data.get("created_at") or utc_now_iso())
        status = str(data.get("status") or DECISION_STATUS_RECORDED).strip().upper() or DECISION_STATUS_RECORDED
        if status not in ALLOWED_WRITE_STATUSES:
            raise DecisionStoreError("INVALID_STATUS", "v1 只允许写入 RECORDED", status)
        confidence = str(data.get("confidence") or CONFIDENCE_LOW).strip().upper()
        if confidence not in ALLOWED_CONFIDENCE:
            confidence = CONFIDENCE_LOW
        explicit_id = str(data.get("id") or "").strip()
        if explicit_id:
            decision_id = _safe_decision_id(explicit_id)
        else:
            decision_id = make_decision_id(cid, topic_id, created_msg_id, ordinal, created_at)
        supersedes = data.get("supersedes_decision_id")
        if supersedes == "" or supersedes is False or supersedes is None:
            supersedes = None
        elif str(supersedes).strip().lower() == "none":
            supersedes = None
        else:
            supersedes = _safe_decision_id(str(supersedes).strip())
        title = str(data.get("title") or "").strip()[:40]
        decision_text = str(data.get("decision_text") or "").strip()[:500]
        summary = str(data.get("summary") or "").strip()[:500] or decision_text
        return {
            "id": decision_id,
            "conversation_id": cid,
            "topic_id": topic_id,
            "title": title,
            "decision_text": decision_text,
            "summary": summary,
            "status": DECISION_STATUS_RECORDED,
            "confidence": confidence,
            "created_msg_id": created_msg_id,
            "supersedes_decision_id": supersedes,
            "created_at": created_at,
            "updated_at": str(data.get("updated_at") or created_at),
            "schema_version": int(data.get("schema_version") or SCHEMA_VERSION),
        }

    def _save_decisions(self, conversation_id: str, decisions: list) -> None:
        path = self._paths(conversation_id)["decisions"]
        atomic_write_json(path, {"decisions": decisions})

    # --- DecisionMessageLink ---

    def list_links(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["links"]
        data = read_json(path, default={"links": []})
        if isinstance(data, list):
            return data
        return list(data.get("links") or [])

    def add_link(
        self,
        conversation_id: str,
        decision_id: str,
        message_id: str,
        relation: str,
        confidence: str = CONFIDENCE_MEDIUM,
        created_at: str = "",
    ) -> dict:
        cid = _safe_conversation_id(conversation_id)
        rel = str(relation or "").strip().upper()
        if rel in FORBIDDEN_RELATIONS:
            raise DecisionStoreError("INVALID_RELATION", "v1 禁止该 relation", rel)
        if rel not in ALLOWED_RELATIONS:
            raise DecisionStoreError("INVALID_RELATION", "非法 relation", rel)
        links = self.list_links(cid)
        for prev in links:
            if (
                prev.get("decision_id") == decision_id
                and prev.get("message_id") == message_id
                and prev.get("relation") == rel
            ):
                return prev
        now = created_at or utc_now_iso()
        item = {
            "id": make_dlink_id(decision_id, message_id, rel),
            "decision_id": decision_id,
            "message_id": message_id,
            "relation": rel,
            "confidence": confidence if confidence in ALLOWED_CONFIDENCE else CONFIDENCE_LOW,
            "created_at": now,
        }
        links.append(item)
        self._save_links(cid, links)
        return item

    def links_for_decision(self, conversation_id: str, decision_id: str) -> list:
        return [item for item in self.list_links(conversation_id) if item.get("decision_id") == decision_id]

    def _save_links(self, conversation_id: str, links: list) -> None:
        path = self._paths(conversation_id)["links"]
        atomic_write_json(path, {"links": links})

    def _commit(self, conversation_id: str, decisions: list, links: list) -> None:
        cid = _safe_conversation_id(conversation_id)
        old_decisions = self.list_decisions(cid)
        old_links = self.list_links(cid)
        try:
            self._save_decisions(cid, decisions)
            self._save_links(cid, links)
        except Exception:
            try:
                self._save_decisions(cid, old_decisions)
                self._save_links(cid, old_links)
            except Exception:
                pass
            raise

    def commit_apply(
        self,
        conversation_id: str,
        *,
        new_decisions: Optional[list] = None,
        new_links: Optional[list] = None,
    ) -> dict:
        """先在内存合并并校验 CREATED_BY，再写 decisions.json / links.json。失败则回滚，避免半套 Decision。

        同一确定性 id 且同一 created_msg_id/topic 视为幂等 skip（retry 不 suffix）。
        仅当同 id 对应不同消息时才走碰撞后缀 _2。
        suffix 后 links / applied_ids / CREATED_BY 校验一律使用最终 id。
        """
        cid = _safe_conversation_id(conversation_id)
        decisions = list(self.list_decisions(cid))
        links = list(self.list_links(cid))
        used_ids = {item.get("id") for item in decisions}
        applied_ids = []
        id_map = {}
        for raw in new_decisions or []:
            item = dict(raw)
            if "task_id" in item:
                item.pop("task_id", None)
            original_id = item.get("id")
            decision_id = original_id
            existing = _lookup_by_id(decisions, decision_id)
            if _same_logical_entity(existing, item):
                applied_ids.append(existing["id"])
                if original_id:
                    id_map[original_id] = existing["id"]
                continue
            if decision_id in used_ids:
                suffix = 2
                while "%s_%s" % (decision_id, suffix) in used_ids:
                    suffix += 1
                decision_id = "%s_%s" % (decision_id, suffix)
                item["id"] = decision_id
            used_ids.add(item["id"])
            decisions.append(item)
            applied_ids.append(item["id"])
            if original_id:
                id_map[original_id] = item["id"]
        for raw_link in new_links or []:
            link = _remap_link(raw_link, id_map, "decision_id", make_dlink_id)
            if _link_exists(links, link):
                continue
            rel = str(link.get("relation") or "").strip().upper()
            if rel in FORBIDDEN_RELATIONS:
                raise DecisionStoreError("INVALID_RELATION", "v1 禁止该 relation", rel)
            if rel not in ALLOWED_RELATIONS:
                raise DecisionStoreError("INVALID_RELATION", "非法 relation", rel)
            links.append(link)
        for decision_id in applied_ids:
            self._assert_exactly_one_created_by(decision_id, links)
            created = [item for item in links if item.get("decision_id") == decision_id and item.get("relation") == RELATION_CREATED_BY]
            self.require_created_by_message(cid, created[0].get("message_id"))
        self._commit(cid, decisions, links)
        return {"decision_ids": applied_ids}

    def _assert_exactly_one_created_by(self, decision_id: str, links: list) -> None:
        created = [
            item
            for item in links
            if item.get("decision_id") == decision_id and item.get("relation") == RELATION_CREATED_BY
        ]
        if len(created) != 1:
            raise DecisionStoreError(
                "CREATED_BY_REQUIRED",
                "每个 Decision 必须恰好有 1 个 CREATED_BY",
                decision_id,
            )

    # --- DecisionProcessingRecord ---

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
        version = int(data.get("decision_processing_version") or DEFAULT_PROCESSING_VERSION)
        if not message_id:
            raise DecisionStoreError("MESSAGE_ID_REQUIRED", "processing 缺少 message_id")
        decision_ids = data.get("decision_ids") or []
        if not isinstance(decision_ids, list):
            decision_ids = []
        item = {
            "message_id": message_id,
            "conversation_id": cid,
            "topic_id": data.get("topic_id") or None,
            "decision_processing_version": version,
            "extractor_prompt_name": str(data.get("extractor_prompt_name") or ""),
            "extractor_prompt_hash": str(data.get("extractor_prompt_hash") or ""),
            "decision_summary": str(data.get("decision_summary") or data.get("decision") or ""),
            "decision_ids": [str(value) for value in decision_ids if value],
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
        prev.get("decision_id") == candidate.get("decision_id")
        and prev.get("message_id") == candidate.get("message_id")
        and prev.get("relation") == candidate.get("relation")
        for prev in links
    )
