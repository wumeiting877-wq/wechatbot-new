# -*- coding: utf-8 -*-
"""P4 Task Store：独立 JSON 存储 Task / TaskMessageLink / TaskProcessingRecord。

不写入 config.local.json、topics.json、chat_contexts、CoreMemory、recurring_reminders。
不上 SQLite / ORM / Redis / Vector DB。
不修改 Topic Store 文件格式。
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
from topic_store import TopicStore, TopicStoreError

SCHEMA_VERSION = 1
TASK_STATUS_OPEN = "OPEN"
TASK_STATUS_IN_PROGRESS = "IN_PROGRESS"
TASK_STATUS_DONE = "DONE"
TASK_STATUS_CANCELLED = "CANCELLED"
ALLOWED_WRITE_STATUSES = (TASK_STATUS_OPEN,)
ALLOWED_TASK_TRANSITIONS_V1 = (
    (TASK_STATUS_OPEN, TASK_STATUS_DONE),
)
TRANSITION_TRANSITIONED = "TRANSITIONED"
TRANSITION_ALREADY_IN_STATE = "ALREADY_IN_STATE"
TRANSITION_INVALID_TRANSITION = "INVALID_TRANSITION"
TRANSITION_TASK_NOT_FOUND = "TASK_NOT_FOUND"
TRANSITION_STALE_STATE = "STALE_STATE"
TRANSITION_CORRUPT = "CORRUPT"
TRANSITION_WRITE_FAILED = "WRITE_FAILED"

RELATION_CREATED_BY = "CREATED_BY"
RELATION_RELATED = "RELATED"
RELATION_UPDATED_BY = "UPDATED_BY"
ALLOWED_RELATIONS = (RELATION_CREATED_BY, RELATION_RELATED, RELATION_UPDATED_BY)

DECISION_NEW_TASK = "NEW_TASK"
DECISION_TASK_UPDATE = "TASK_UPDATE"
DECISION_UNRELATED = "UNRELATED"
DECISION_SKIPPED = "SKIPPED"
DECISION_FAILED = "FAILED"
SUCCESS_DECISIONS = {
    DECISION_NEW_TASK,
    DECISION_TASK_UPDATE,
    DECISION_UNRELATED,
    DECISION_SKIPPED,
}

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
ALLOWED_CONFIDENCE = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)

DEFAULT_PROCESSING_VERSION = 1
FORBIDDEN_TASK_KEYS = {
    "assignee_id",
    "assignee_wxid",
    "assignee_type",
    "assignee",
    "progress_percent",
    "risk_ids",
    "decision_ids",
    "reminder_id",
    "priority",
    "source_agent",
    "embedding",
}


class TaskTransitionResult:
    def __init__(
        self,
        status: str,
        conversation_id: str,
        task_id: str,
        from_status: str,
        to_status: str,
        task: Optional[dict],
    ):
        self.status = status
        self.conversation_id = conversation_id
        self.task_id = task_id
        self.from_status = from_status
        self.to_status = to_status
        self.task = task


class TaskStoreError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


def _sha1_12(seed: str) -> str:
    return hashlib.sha1((seed or "").encode("utf-8")).hexdigest()[:12]


def make_task_id(
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
    return "task_%s" % _sha1_12(seed)


def make_tlink_id(task_id: str, message_id: str, relation: str) -> str:
    return "tlink_%s" % _sha1_12("%s|%s|%s" % (task_id or "", message_id or "", relation or ""))


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
        raise TaskStoreError("INVALID_CONVERSATION_ID", "conversation_id 必须是 conv_*", cid)
    return cid


def _safe_topic_id(topic_id: str) -> str:
    tid = str(topic_id or "").strip()
    if not tid or not re.match(r"^topic_[A-Za-z0-9_]+$", tid):
        raise TaskStoreError("INVALID_TOPIC_ID", "topic_id 必须是 topic_*", tid)
    return tid


def _safe_task_id(task_id: str) -> str:
    value = str(task_id or "").strip()
    if not value or not re.match(r"^task_[A-Za-z0-9_]+$", value):
        raise TaskStoreError("INVALID_TASK_ID", "task_id 必须是 task_*", value)
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


class TaskStore:
    def __init__(self, root_dir: str, topic_store: Optional[TopicStore] = None):
        self.root_dir = os.path.abspath(root_dir)
        self.store_dir = os.path.join(self.root_dir, "data", "task_store")
        self.conversations_dir = os.path.join(self.store_dir, "conversations")
        self.audit_path = os.path.join(self.store_dir, "task_engine_audit.jsonl")
        self.topic_store = topic_store

    def conversation_dir(self, conversation_id: str) -> str:
        return os.path.join(self.conversations_dir, _safe_conversation_id(conversation_id))

    def _paths(self, conversation_id: str) -> dict:
        base = self.conversation_dir(conversation_id)
        return {
            "dir": base,
            "tasks": os.path.join(base, "tasks.json"),
            "links": os.path.join(base, "links.json"),
            "processed": os.path.join(base, "processed.json"),
        }

    def delete_conversation_task_data(self, conversation_id: str) -> bool:
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
            raise TaskStoreError("TOPIC_STORE_REQUIRED", "创建 Task 前必须能校验 Topic")
        try:
            topic = self.topic_store.get_topic(cid, tid)
        except TopicStoreError as exc:
            raise TaskStoreError(exc.code, exc.message, exc.detail)
        if not topic:
            raise TaskStoreError("TOPIC_NOT_FOUND", "Topic 不存在，禁止写 Task", tid)
        if str(topic.get("conversation_id") or "") != cid:
            raise TaskStoreError("TOPIC_CONVERSATION_MISMATCH", "Topic 不属于当前 Conversation", tid)
        return topic

    # --- Task ---

    def list_tasks(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["tasks"]
        data = read_json(path, default={"tasks": []})
        if isinstance(data, list):
            return data
        return list(data.get("tasks") or [])

    def get_task(self, conversation_id: str, task_id: str) -> Optional[dict]:
        for item in self.list_tasks(conversation_id):
            if item.get("id") == task_id:
                return item
        return None

    def list_open_tasks(
        self,
        conversation_id: str,
        topic_id: str,
        *,
        limit: int = 10,
        content: str = "",
    ) -> list:
        items = [
            item
            for item in self.list_tasks(conversation_id)
            if item.get("topic_id") == topic_id and item.get("status") == TASK_STATUS_OPEN
        ]

        def sort_key(task: dict):
            assignee = str(task.get("assignee_text") or "")
            hit = 1 if assignee and assignee in (content or "") else 0
            return (hit, str(task.get("updated_at") or ""))

        items.sort(key=sort_key, reverse=True)
        if limit <= 0:
            return items
        return items[:limit]

    def create_task(self, record: dict, *, ordinal: int = 0) -> dict:
        """Internal/legacy 直连创建。生产 Engine 走 commit_apply。同 id 仍 suffix。"""
        item = self._normalize_new_task(record, ordinal=ordinal)
        cid = item["conversation_id"]
        self.require_topic(cid, item["topic_id"])
        created_msg_id = str(item.get("created_msg_id") or "").strip()
        if not created_msg_id:
            raise TaskStoreError("EVIDENCE_REQUIRED", "没有 Evidence 的 Task 不允许写入")
        if self.topic_store is not None and self.topic_store.get_message(cid, created_msg_id) is None:
            raise TaskStoreError("MESSAGE_NOT_FOUND", "created_msg_id 必须已存在于 Topic Store", created_msg_id)
        tasks = self.list_tasks(cid)
        used = {task.get("id") for task in tasks}
        task_id = item["id"]
        if task_id in used:
            suffix = 2
            while "%s_%s" % (task_id, suffix) in used:
                suffix += 1
            task_id = "%s_%s" % (task_id, suffix)
            item["id"] = task_id
        tasks.append(item)
        link = {
            "id": make_tlink_id(task_id, created_msg_id, RELATION_CREATED_BY),
            "task_id": task_id,
            "message_id": created_msg_id,
            "relation": RELATION_CREATED_BY,
            "confidence": item.get("confidence") or CONFIDENCE_LOW,
            "created_at": item.get("created_at") or utc_now_iso(),
        }
        links = self.list_links(cid)
        if not any(
            prev.get("task_id") == task_id
            and prev.get("message_id") == created_msg_id
            and prev.get("relation") == RELATION_CREATED_BY
            for prev in links
        ):
            links.append(link)
        self._commit(cid, tasks, links)
        return item

    def update_task(self, conversation_id: str, task_id: str, **fields) -> Optional[dict]:
        cid = _safe_conversation_id(conversation_id)
        tid = _safe_task_id(task_id)
        tasks = self.list_tasks(cid)
        updated = None
        now = utc_now_iso()
        for task in tasks:
            if task.get("id") != tid:
                continue
            for key in ("title", "description", "assignee_text", "due_text", "confidence"):
                if key not in fields:
                    continue
                value = fields[key]
                if value is None:
                    continue
                text = str(value).strip() if key != "confidence" else str(value or "").strip().upper()
                if key in ("assignee_text", "due_text", "title", "description") and text == "":
                    continue
                if key == "title":
                    task["title"] = text[:40]
                elif key == "description":
                    task["description"] = text[:500]
                elif key == "confidence":
                    if text in ALLOWED_CONFIDENCE:
                        task["confidence"] = text
                else:
                    task[key] = text
            if "status" in fields and fields["status"]:
                raise TaskStoreError("INVALID_STATUS", "TASK_UPDATE 不得改 status", str(fields["status"]))
            if "conversation_id" in fields or "topic_id" in fields:
                raise TaskStoreError("IMMUTABLE_FK", "不得改 conversation_id / topic_id")
            if "due_at" in fields and str(fields.get("due_at") or "").strip():
                raise TaskStoreError("DUE_AT_FORBIDDEN", "G1 禁止写入 due_at")
            task["updated_at"] = now
            updated = task
            break
        if updated is None:
            return None
        self._save_tasks(cid, tasks)
        return updated

    def transition_task_status(
        self,
        conversation_id: str,
        task_id: str,
        expected_status: str,
        target_status: str,
    ) -> TaskTransitionResult:
        """锁内重读后迁移 status。v1 表只有 OPEN → DONE。不改其它字段。"""
        cid = _safe_conversation_id(conversation_id)
        tid = _safe_task_id(task_id)
        expected = str(expected_status or "").strip().upper()
        target = str(target_status or "").strip().upper()
        path = self._paths(cid)["tasks"]
        lock = FileLock(lock_path_for(path))
        with lock:
            try:
                data, tasks = _load_tasks_for_transition(path)
            except TaskStoreError as exc:
                if exc.code == TRANSITION_CORRUPT:
                    return _transition_result(TRANSITION_CORRUPT, cid, tid, "", "", None)
                raise
            task = _lookup_by_id(tasks, tid)
            if task is None:
                return _transition_result(TRANSITION_TASK_NOT_FOUND, cid, tid, "", "", None)
            current = str(task.get("status") or "").strip().upper()
            if current == target:
                return _transition_result(
                    TRANSITION_ALREADY_IN_STATE,
                    cid,
                    tid,
                    current,
                    current,
                    dict(task),
                )
            if current != expected:
                return _transition_result(
                    TRANSITION_STALE_STATE,
                    cid,
                    tid,
                    current,
                    target,
                    dict(task),
                )
            if (current, target) not in ALLOWED_TASK_TRANSITIONS_V1:
                return _transition_result(
                    TRANSITION_INVALID_TRANSITION,
                    cid,
                    tid,
                    current,
                    target,
                    dict(task),
                )
            previous_updated = task.get("updated_at")
            task["status"] = target
            task["updated_at"] = utc_now_iso()
            try:
                _replace_json_unlocked(path, data)
            except (OSError, TypeError, ValueError):
                task["status"] = current
                task["updated_at"] = previous_updated
                return _transition_result(TRANSITION_WRITE_FAILED, cid, tid, current, target, None)
            return _transition_result(
                TRANSITION_TRANSITIONED,
                cid,
                tid,
                current,
                target,
                dict(task),
            )

    def _normalize_new_task(self, record: dict, ordinal: int = 0) -> dict:
        data = record if isinstance(record, dict) else {}
        for key in FORBIDDEN_TASK_KEYS:
            data = {k: v for k, v in data.items() if k != key}
        cid = _safe_conversation_id(data.get("conversation_id") or "")
        topic_id = _safe_topic_id(data.get("topic_id") or "")
        created_msg_id = str(data.get("created_msg_id") or "").strip()
        created_at = str(data.get("created_at") or utc_now_iso())
        status = str(data.get("status") or TASK_STATUS_OPEN).strip().upper() or TASK_STATUS_OPEN
        if status not in ALLOWED_WRITE_STATUSES:
            raise TaskStoreError("INVALID_STATUS", "v1 只允许写入 OPEN", status)
        confidence = str(data.get("confidence") or CONFIDENCE_LOW).strip().upper()
        if confidence not in ALLOWED_CONFIDENCE:
            confidence = CONFIDENCE_LOW
        explicit_id = str(data.get("id") or "").strip()
        if explicit_id:
            task_id = _safe_task_id(explicit_id)
        else:
            task_id = make_task_id(cid, topic_id, created_msg_id, ordinal, created_at)
        due_at = str(data.get("due_at") or "")
        if due_at.strip():
            due_at = ""
        return {
            "id": task_id,
            "conversation_id": cid,
            "topic_id": topic_id,
            "title": str(data.get("title") or "").strip()[:40],
            "description": str(data.get("description") or "").strip()[:500],
            "status": TASK_STATUS_OPEN,
            "assignee_text": str(data.get("assignee_text") or "").strip(),
            "due_text": str(data.get("due_text") or "").strip(),
            "due_at": "",
            "created_msg_id": created_msg_id,
            "confidence": confidence,
            "created_at": created_at,
            "updated_at": str(data.get("updated_at") or created_at),
            "schema_version": int(data.get("schema_version") or SCHEMA_VERSION),
        }

    def _save_tasks(self, conversation_id: str, tasks: list) -> None:
        path = self._paths(conversation_id)["tasks"]
        atomic_write_json(path, {"tasks": tasks})

    # --- TaskMessageLink ---

    def list_links(self, conversation_id: str) -> list:
        path = self._paths(conversation_id)["links"]
        data = read_json(path, default={"links": []})
        if isinstance(data, list):
            return data
        return list(data.get("links") or [])

    def add_link(
        self,
        conversation_id: str,
        task_id: str,
        message_id: str,
        relation: str,
        confidence: str = CONFIDENCE_MEDIUM,
        created_at: str = "",
    ) -> dict:
        cid = _safe_conversation_id(conversation_id)
        rel = str(relation or "").strip().upper()
        if rel not in ALLOWED_RELATIONS:
            raise TaskStoreError("INVALID_RELATION", "非法 relation", rel)
        if rel == "COMPLETION_EVIDENCE":
            raise TaskStoreError("INVALID_RELATION", "v1 禁止 COMPLETION_EVIDENCE", rel)
        links = self.list_links(cid)
        for prev in links:
            if (
                prev.get("task_id") == task_id
                and prev.get("message_id") == message_id
                and prev.get("relation") == rel
            ):
                return prev
        now = created_at or utc_now_iso()
        item = {
            "id": make_tlink_id(task_id, message_id, rel),
            "task_id": task_id,
            "message_id": message_id,
            "relation": rel,
            "confidence": confidence if confidence in ALLOWED_CONFIDENCE else CONFIDENCE_LOW,
            "created_at": now,
        }
        links.append(item)
        self._save_links(cid, links)
        return item

    def links_for_task(self, conversation_id: str, task_id: str) -> list:
        return [item for item in self.list_links(conversation_id) if item.get("task_id") == task_id]

    def _save_links(self, conversation_id: str, links: list) -> None:
        path = self._paths(conversation_id)["links"]
        atomic_write_json(path, {"links": links})

    def _commit(self, conversation_id: str, tasks: list, links: list) -> None:
        cid = _safe_conversation_id(conversation_id)
        old_tasks = self.list_tasks(cid)
        old_links = self.list_links(cid)
        try:
            self._save_tasks(cid, tasks)
            self._save_links(cid, links)
        except Exception:
            try:
                self._save_tasks(cid, old_tasks)
                self._save_links(cid, old_links)
            except Exception:
                pass
            raise

    def commit_apply(
        self,
        conversation_id: str,
        *,
        new_tasks: Optional[list] = None,
        updates: Optional[list] = None,
        new_links: Optional[list] = None,
    ) -> dict:
        """先在内存合并，再写 tasks.json / links.json。失败则回滚，避免半套 Task。

        同一确定性 id 且同一 created_msg_id/topic 视为幂等 skip（retry 不 suffix）。
        仅当同 id 对应不同消息时才走碰撞后缀 _2。
        suffix 后 links / applied_ids 一律使用最终 id。
        """
        cid = _safe_conversation_id(conversation_id)
        tasks = list(self.list_tasks(cid))
        links = list(self.list_links(cid))
        used_ids = {item.get("id") for item in tasks}
        applied_task_ids = []
        id_map = {}
        for raw in new_tasks or []:
            item = dict(raw)
            original_id = item.get("id")
            task_id = original_id
            existing = _lookup_by_id(tasks, task_id)
            if _same_logical_entity(existing, item):
                applied_task_ids.append(existing["id"])
                if original_id:
                    id_map[original_id] = existing["id"]
                continue
            if task_id in used_ids:
                suffix = 2
                while "%s_%s" % (task_id, suffix) in used_ids:
                    suffix += 1
                task_id = "%s_%s" % (task_id, suffix)
                item["id"] = task_id
            used_ids.add(item["id"])
            tasks.append(item)
            applied_task_ids.append(item["id"])
            if original_id:
                id_map[original_id] = item["id"]
        for change in updates or []:
            target_id = change.get("id")
            for task in tasks:
                if task.get("id") != target_id:
                    continue
                for key, value in (change.get("fields") or {}).items():
                    task[key] = value
                task["updated_at"] = change.get("updated_at") or utc_now_iso()
                applied_task_ids.append(task["id"])
                break
        for raw_link in new_links or []:
            link = _remap_link(raw_link, id_map, "task_id", make_tlink_id)
            exists = any(
                prev.get("task_id") == link.get("task_id")
                and prev.get("message_id") == link.get("message_id")
                and prev.get("relation") == link.get("relation")
                for prev in links
            )
            if exists:
                continue
            links.append(link)
        self._commit(cid, tasks, links)
        return {"task_ids": applied_task_ids}

    # --- TaskProcessingRecord ---

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
        version = int(data.get("task_processing_version") or DEFAULT_PROCESSING_VERSION)
        if not message_id:
            raise TaskStoreError("MESSAGE_ID_REQUIRED", "processing 缺少 message_id")
        task_ids = data.get("task_ids") or []
        if not isinstance(task_ids, list):
            task_ids = []
        item = {
            "message_id": message_id,
            "conversation_id": cid,
            "topic_id": data.get("topic_id") or None,
            "task_processing_version": version,
            "extractor_prompt_name": str(data.get("extractor_prompt_name") or ""),
            "extractor_prompt_hash": str(data.get("extractor_prompt_hash") or ""),
            "decision_summary": str(data.get("decision_summary") or data.get("decision") or ""),
            "task_ids": [str(value) for value in task_ids if value],
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


def _transition_result(
    status: str,
    conversation_id: str,
    task_id: str,
    from_status: str,
    to_status: str,
    task: Optional[dict],
) -> TaskTransitionResult:
    return TaskTransitionResult(status, conversation_id, task_id, from_status, to_status, task)


def _load_tasks_for_transition(path: str):
    """迁移专用读取。解析失败或结构不对时拒绝写入，不把文件看成空表。"""
    if not os.path.isfile(path):
        return {"tasks": []}, []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise TaskStoreError(TRANSITION_CORRUPT, "tasks.json 无法读取，已停止写入", str(exc))
    if isinstance(data, list):
        if any(not isinstance(item, dict) for item in data):
            raise TaskStoreError(TRANSITION_CORRUPT, "tasks.json 结构无效，已停止写入", "tasks")
        return {"tasks": data}, data
    if not isinstance(data, dict):
        raise TaskStoreError(TRANSITION_CORRUPT, "tasks.json 结构无效，已停止写入", "tasks")
    rows = data.get("tasks")
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        raise TaskStoreError(TRANSITION_CORRUPT, "tasks.json 结构无效，已停止写入", "tasks")
    return data, rows


def _replace_json_unlocked(path: str, data: Any) -> None:
    """调用方已持有 tasks.json.lock。提交点只有 os.replace。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
