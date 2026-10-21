# -*- coding: utf-8 -*-
"""P3 Topic Store：独立 JSON 存储 MessageRecord / Topic / Link / Processing。

不写入 config.local.json、chat_contexts、CoreMemory。
不上 SQLite / ORM / Redis / Vector DB。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from typing import Any, Optional

from filelock import FileLock

from conversation_store import utc_now_iso
from store_io import atomic_write_json, lock_path_for, read_json

SCHEMA_VERSION = 1
TOPIC_STATUS_ACTIVE = "ACTIVE"
TOPIC_STATUS_WAITING = "WAITING"
TOPIC_STATUS_OPEN = "OPEN"
TOPIC_STATUS_RESOLVED = "RESOLVED"
TOPIC_STATUS_ARCHIVED = "ARCHIVED"
CANDIDATE_STATUSES = (TOPIC_STATUS_ACTIVE, TOPIC_STATUS_WAITING, TOPIC_STATUS_OPEN)

RELATION_CREATED_BY = "CREATED_BY"
RELATION_RELATED = "RELATED"
RELATION_UPDATED_BY = "UPDATED_BY"
ALLOWED_RELATIONS = (RELATION_CREATED_BY, RELATION_RELATED, RELATION_UPDATED_BY)

DIRECTION_INBOUND = "INBOUND"
DIRECTION_OUTBOUND = "OUTBOUND"

DECISION_NEW_TOPIC = "NEW_TOPIC"
DECISION_EXISTING_TOPIC = "EXISTING_TOPIC"
DECISION_TOPIC_UPDATE = "TOPIC_UPDATE"
DECISION_UNRELATED = "UNRELATED"
DECISION_SKIPPED = "SKIPPED"
DECISION_FAILED = "FAILED"
SUCCESS_DECISIONS = {
    DECISION_NEW_TOPIC,
    DECISION_EXISTING_TOPIC,
    DECISION_TOPIC_UPDATE,
    DECISION_UNRELATED,
    DECISION_SKIPPED,
}

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
ALLOWED_CONFIDENCE = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)

DEFAULT_PROCESSING_VERSION = 1


class TopicStoreError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


def _sha1_12(seed: str) -> str:
    return hashlib.sha1((seed or "").encode("utf-8")).hexdigest()[:12]


def make_message_id(
    conversation_id: str,
    platform_message_id: str = "",
    event_fingerprint: str = "",
) -> str:
    key = str(platform_message_id or "").strip() or str(event_fingerprint or "").strip()
    digest = _sha1_12("%s|%s" % (conversation_id or "", key))
    return "msg_%s" % digest


def event_fingerprint(
    sender_wxid: str = "",
    message_type: str = "",
    create_time: Any = "",
    normalized_content: str = "",
) -> str:
    return "%s|%s|%s|%s" % (
        sender_wxid or "",
        message_type or "",
        create_time if create_time is not None else "",
        normalized_content or "",
    )


def make_topic_id(conversation_id: str, created_msg_id: str, created_at: str = "") -> str:
    seed = "%s|%s|%s" % (conversation_id or "", created_msg_id or "", created_at or utc_now_iso())
    return "topic_%s" % _sha1_12(seed)


def make_link_id(topic_id: str, message_id: str, relation: str) -> str:
    return "link_%s" % _sha1_12("%s|%s|%s" % (topic_id or "", message_id or "", relation or ""))


def processing_key(message_id: str, version: int = DEFAULT_PROCESSING_VERSION) -> str:
    return "%s|%s" % (message_id, int(version))


def content_preview(text: str, limit: int = 80) -> str:
    value = str(text or "")
    return value[:limit]


def _safe_conversation_id(conversation_id: str) -> str:
    cid = str(conversation_id or "").strip()
    if not cid or not re.match(r"^conv_[A-Za-z0-9_]+$", cid):
        raise TopicStoreError("INVALID_CONVERSATION_ID", "conversation_id 必须是 conv_*", cid)
    return cid


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


class TopicStore:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.store_dir = os.path.join(self.root_dir, "data", "topic_store")
        self.conversations_dir = os.path.join(self.store_dir, "conversations")
        self.audit_path = os.path.join(self.store_dir, "topic_engine_audit.jsonl")

    def conversation_dir(self, conversation_id: str) -> str:
        return os.path.join(self.conversations_dir, _safe_conversation_id(conversation_id))

    def _paths(self, conversation_id: str) -> dict:
        base = self.conversation_dir(conversation_id)
        return {
            "dir": base,
            "messages": os.path.join(base, "messages.jsonl"),
            "topics": os.path.join(base, "topics.json"),
            "links": os.path.join(base, "links.json"),
            "processed": os.path.join(base, "processed.json"),
        }

    def delete_conversation_topic_data(self, conversation_id: str) -> bool:
        cid = _safe_conversation_id(conversation_id)
        path = os.path.join(self.conversations_dir, cid)
        if not os.path.isdir(path):
            return False
        shutil.rmtree(path)
        return True

    # --- MessageRecord ---

    def upsert_message(self, record: dict) -> dict:
        item = self._normalize_message(record)
        cid = item["conversation_id"]
        path = self._paths(cid)["messages"]
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        lock = FileLock(lock_path_for(path))
        with lock:
            existing = _read_jsonl(path)
            for prev in existing:
                if prev.get("id") == item["id"]:
                    return prev
                platform_id = str(item.get("platform_message_id") or "").strip()
                if platform_id and str(prev.get("platform_message_id") or "").strip() == platform_id:
                    return prev
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def get_message(self, conversation_id: str, message_id: str) -> Optional[dict]:
        for item in self.list_messages(conversation_id):
            if item.get("id") == message_id:
                return item
        return None

    def list_messages(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["messages"]
        lock = FileLock(lock_path_for(path))
        with lock:
            return _read_jsonl(path)

    def recent_messages(self, conversation_id: str, limit: int = 12, exclude_id: str = "") -> list:
        items = [m for m in self.list_messages(conversation_id) if m.get("id") != exclude_id]
        items.sort(key=lambda m: str(m.get("created_at") or ""))
        if limit <= 0:
            return items
        return items[-limit:]

    def _normalize_message(self, record: dict) -> dict:
        data = record if isinstance(record, dict) else {}
        cid = _safe_conversation_id(data.get("conversation_id") or "")
        platform_id = str(data.get("platform_message_id") or "").strip()
        fingerprint = str(data.get("event_fingerprint") or "").strip()
        if not fingerprint:
            fingerprint = event_fingerprint(
                str(data.get("sender_wxid") or ""),
                str(data.get("message_type") or data.get("raw_type") or "text"),
                data.get("created_at") or data.get("create_time") or "",
                str(data.get("content") or "").strip(),
            )
        msg_id = str(data.get("id") or "").strip()
        if not msg_id:
            if not platform_id and not fingerprint:
                raise TopicStoreError("MESSAGE_ID_REQUIRED", "缺少 platform_message_id 与 event_fingerprint")
            msg_id = make_message_id(cid, platform_id, fingerprint)
        raw_reference = data.get("raw_reference") if isinstance(data.get("raw_reference"), dict) else {}
        return {
            "id": msg_id,
            "conversation_id": cid,
            "platform_message_id": platform_id,
            "sender_id": data.get("sender_id") if data.get("sender_id") is not None else "",
            "sender_wxid": str(data.get("sender_wxid") or "").strip(),
            "sender_name": str(data.get("sender_name") or "").strip(),
            "content": str(data.get("content") or ""),
            "message_type": str(data.get("message_type") or data.get("raw_type") or "text").strip() or "text",
            "created_at": str(data.get("created_at") or utc_now_iso()),
            "direction": str(data.get("direction") or DIRECTION_INBOUND).strip().upper() or DIRECTION_INBOUND,
            "reply_to_message_id": str(data.get("reply_to_message_id") or "").strip(),
            "raw_reference": {
                "chat_name": str(raw_reference.get("chat_name") or data.get("chat_name") or ""),
                "chat_wxid": str(raw_reference.get("chat_wxid") or data.get("chat_wxid") or ""),
                "local_id": raw_reference.get("local_id", data.get("local_id")),
                "create_time": raw_reference.get("create_time", data.get("create_time")),
                "quote_excerpt": str(raw_reference.get("quote_excerpt") or ""),
            },
            "ingested_at": str(data.get("ingested_at") or utc_now_iso()),
            "schema_version": int(data.get("schema_version") or SCHEMA_VERSION),
        }

    # --- Topic ---

    def list_topics(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["topics"]
        data = read_json(path, default={"topics": []})
        if isinstance(data, list):
            return data
        return list(data.get("topics") or [])

    def get_topic(self, conversation_id: str, topic_id: str) -> Optional[dict]:
        for topic in self.list_topics(conversation_id):
            if topic.get("id") == topic_id:
                return topic
        return None

    def create_topic(
        self,
        conversation_id: str,
        *,
        title: str,
        summary: str = "",
        created_msg_id: str = "",
        confidence: str = CONFIDENCE_MEDIUM,
        created_at: str = "",
        last_message_at: str = "",
    ) -> dict:
        cid = _safe_conversation_id(conversation_id)
        now = created_at or utc_now_iso()
        existing = self.list_topics(cid)
        used = {item.get("id") for item in existing}
        topic_id = make_topic_id(cid, created_msg_id, now)
        if topic_id in used:
            suffix = 2
            while "%s_%s" % (topic_id, suffix) in used:
                suffix += 1
            topic_id = "%s_%s" % (topic_id, suffix)
        topic = {
            "id": topic_id,
            "conversation_id": cid,
            "title": str(title or "").strip()[:40],
            "summary": str(summary or title or "").strip()[:500],
            "status": TOPIC_STATUS_ACTIVE,
            "confidence": confidence if confidence in ALLOWED_CONFIDENCE else CONFIDENCE_LOW,
            "created_at": now,
            "updated_at": now,
            "last_message_at": last_message_at or now,
            "message_count": 0,
            "schema_version": SCHEMA_VERSION,
        }
        existing.append(topic)
        self._save_topics(cid, existing)
        return topic

    def update_topic(self, conversation_id: str, topic_id: str, **fields) -> Optional[dict]:
        cid = _safe_conversation_id(conversation_id)
        topics = self.list_topics(cid)
        updated = None
        now = utc_now_iso()
        for topic in topics:
            if topic.get("id") != topic_id:
                continue
            if "title" in fields and fields["title"] is not None:
                # v1 默认不改 title；仅当调用方显式传入时才写。Engine 不会传。
                topic["title"] = str(fields["title"] or "").strip()[:40]
            if "summary" in fields and fields["summary"] is not None:
                topic["summary"] = str(fields["summary"] or "").strip()[:500]
            if "status" in fields and fields["status"]:
                topic["status"] = str(fields["status"])
            if "confidence" in fields and fields["confidence"] in ALLOWED_CONFIDENCE:
                topic["confidence"] = fields["confidence"]
            if "last_message_at" in fields and fields["last_message_at"]:
                topic["last_message_at"] = str(fields["last_message_at"])
            if "message_count" in fields and fields["message_count"] is not None:
                topic["message_count"] = int(fields["message_count"])
            topic["updated_at"] = now
            updated = topic
            break
        if updated is None:
            return None
        self._save_topics(cid, topics)
        return updated

    def refresh_topic_message_count(self, conversation_id: str, topic_id: str, last_message_at: str = "") -> Optional[dict]:
        count = len({
            link.get("message_id")
            for link in self.list_links(conversation_id)
            if link.get("topic_id") == topic_id and link.get("message_id")
        })
        return self.update_topic(
            conversation_id,
            topic_id,
            message_count=count,
            last_message_at=last_message_at or None,
        )

    def _save_topics(self, conversation_id: str, topics: list) -> None:
        path = self._paths(conversation_id)["topics"]
        atomic_write_json(path, {"topics": topics})

    # --- TopicMessageLink ---

    def list_links(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["links"]
        data = read_json(path, default={"links": []})
        if isinstance(data, list):
            return data
        return list(data.get("links") or [])

    def add_link(
        self,
        conversation_id: str,
        topic_id: str,
        message_id: str,
        relation: str,
        confidence: str = CONFIDENCE_MEDIUM,
        created_at: str = "",
    ) -> dict:
        cid = _safe_conversation_id(conversation_id)
        rel = str(relation or "").strip().upper()
        if rel not in ALLOWED_RELATIONS:
            raise TopicStoreError("INVALID_RELATION", "非法 relation", rel)
        links = self.list_links(cid)
        for prev in links:
            if (
                prev.get("topic_id") == topic_id
                and prev.get("message_id") == message_id
                and prev.get("relation") == rel
            ):
                return prev
        now = created_at or utc_now_iso()
        item = {
            "id": make_link_id(topic_id, message_id, rel),
            "topic_id": topic_id,
            "message_id": message_id,
            "relation": rel,
            "confidence": confidence if confidence in ALLOWED_CONFIDENCE else CONFIDENCE_LOW,
            "created_at": now,
        }
        links.append(item)
        self._save_links(cid, links)
        self.refresh_topic_message_count(cid, topic_id, last_message_at=now)
        return item

    def links_for_message(self, conversation_id: str, message_id: str) -> list:
        return [item for item in self.list_links(conversation_id) if item.get("message_id") == message_id]

    def links_for_topic(self, conversation_id: str, topic_id: str) -> list:
        return [item for item in self.list_links(conversation_id) if item.get("topic_id") == topic_id]

    def _save_links(self, conversation_id: str, links: list) -> None:
        path = self._paths(conversation_id)["links"]
        atomic_write_json(path, {"links": links})

    # --- TopicProcessingRecord ---

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
        record = self.get_processing(conversation_id, message_id, version)
        if not record:
            return False
        decision = str(record.get("decision") or "")
        return decision in SUCCESS_DECISIONS

    def write_processing(self, record: dict) -> dict:
        data = record if isinstance(record, dict) else {}
        cid = _safe_conversation_id(data.get("conversation_id") or "")
        message_id = str(data.get("message_id") or "").strip()
        version = int(data.get("topic_processing_version") or DEFAULT_PROCESSING_VERSION)
        if not message_id:
            raise TopicStoreError("MESSAGE_ID_REQUIRED", "processing 缺少 message_id")
        item = {
            "message_id": message_id,
            "conversation_id": cid,
            "topic_processing_version": version,
            "extractor_prompt_name": str(data.get("extractor_prompt_name") or ""),
            "extractor_prompt_hash": str(data.get("extractor_prompt_hash") or ""),
            "decision": str(data.get("decision") or ""),
            "topic_id": data.get("topic_id") or None,
            "processed_at": str(data.get("processed_at") or utc_now_iso()),
            "error": str(data.get("error") or ""),
        }
        records = self._load_processed(cid)
        key = processing_key(message_id, version)
        prev = records.get(key)
        if prev and str(prev.get("decision") or "") in SUCCESS_DECISIONS:
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


def project_inbound_to_message_record(inbound: Any, conversation_id: str) -> dict:
    """从 P0 InboundMessage 投影。不修改 InboundMessage 字段含义。"""
    cid = _safe_conversation_id(conversation_id)
    platform_id = str(getattr(inbound, "platform_message_id", "") or "").strip()
    sender_wxid = str(getattr(inbound, "sender_wxid", "") or "").strip()
    message_type = str(getattr(inbound, "raw_type", "") or "text").strip() or "text"
    content = getattr(inbound, "content", "") or ""
    if not isinstance(content, str):
        content = str(content)
    created_at = getattr(inbound, "create_time", None)
    if created_at is None or created_at == "":
        created_iso = utc_now_iso()
    else:
        created_iso = str(created_at)
    fingerprint = ""
    if not platform_id:
        fingerprint = event_fingerprint(sender_wxid, message_type, created_iso, content.strip())
    extra = getattr(inbound, "extra", None)
    reply_to = ""
    if isinstance(extra, dict):
        reply_to = str(extra.get("reply_to_message_id") or "").strip()
    return {
        "id": make_message_id(cid, platform_id, fingerprint),
        "conversation_id": cid,
        "platform_message_id": platform_id,
        "sender_id": getattr(inbound, "sender_id", ""),
        "sender_wxid": sender_wxid,
        "sender_name": str(getattr(inbound, "sender_name", "") or ""),
        "content": content,
        "message_type": message_type,
        "created_at": created_iso,
        "direction": str(getattr(inbound, "direction", "") or DIRECTION_INBOUND).upper() or DIRECTION_INBOUND,
        "reply_to_message_id": reply_to,
        "raw_reference": {
            "chat_name": str(getattr(inbound, "chat_name", "") or ""),
            "chat_wxid": str(getattr(inbound, "chat_wxid", "") or ""),
            "local_id": getattr(inbound, "local_id", None),
            "create_time": getattr(inbound, "create_time", None),
            "quote_excerpt": "",
        },
        "ingested_at": utc_now_iso(),
        "schema_version": SCHEMA_VERSION,
    }
