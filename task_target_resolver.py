# -*- coding: utf-8 -*-
"""在当前会话里把确定性 selector 解析成唯一 Task。

只读该会话的 tasks.json。不改任务，不调用生命周期，不发送消息。
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from task_store import TaskStore, TaskStoreError

SELECTOR_TASK_ID = "TASK_ID"
SELECTOR_EXACT_TITLE = "EXACT_TITLE"
SUPPORTED_SELECTOR_TYPES = (SELECTOR_TASK_ID, SELECTOR_EXACT_TITLE)

SELECTOR_CURRENT_TASK = "CURRENT_TASK"
SELECTOR_LAST_TASK = "LAST_TASK"
SELECTOR_RECENT_TASK = "RECENT_TASK"
SELECTOR_FUZZY_TITLE = "FUZZY_TITLE"
SELECTOR_SEMANTIC_TITLE = "SEMANTIC_TITLE"
SELECTOR_INDEX_FROM_CHAT = "INDEX_FROM_CHAT"
UNSUPPORTED_SELECTOR_TYPES = (
    SELECTOR_CURRENT_TASK,
    SELECTOR_LAST_TASK,
    SELECTOR_RECENT_TASK,
    SELECTOR_FUZZY_TITLE,
    SELECTOR_SEMANTIC_TITLE,
    SELECTOR_INDEX_FROM_CHAT,
)

RESOLVED = "RESOLVED"
NOT_FOUND = "NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS"
UNSUPPORTED_REFERENCE = "UNSUPPORTED_REFERENCE"
INVALID_SELECTOR = "INVALID_SELECTOR"
CORRUPT = "CORRUPT"

REASON_INVALID_SELECTOR = "INVALID_SELECTOR"
REASON_UNSUPPORTED_REFERENCE = "UNSUPPORTED_REFERENCE"
REASON_NOT_FOUND = "NOT_FOUND"
REASON_CONVERSATION_MISMATCH = "CONVERSATION_MISMATCH"
REASON_DUPLICATE_TITLE = "DUPLICATE_TITLE"
REASON_DUPLICATE_TASK_ID = "DUPLICATE_TASK_ID"
REASON_TASKS_UNREADABLE = "TASKS_UNREADABLE"
REASON_TASKS_STRUCTURE_INVALID = "TASKS_STRUCTURE_INVALID"

_TASK_ID_RE = re.compile(r"^task_[A-Za-z0-9_]+$")


class TaskTargetSelector:
    def __init__(self, selector_type: str, task_id: str = "", title: str = ""):
        self.selector_type = selector_type
        self.task_id = task_id
        self.title = title


class TargetResolutionResult:
    def __init__(
        self,
        status: str,
        conversation_id: str,
        selector_type: str,
        task_id: Optional[str] = None,
        task: Optional[dict] = None,
        candidates: Optional[list] = None,
        reason: str = "",
    ):
        self.status = status
        self.conversation_id = conversation_id
        self.selector_type = selector_type
        self.task_id = task_id
        self.task = task
        self.candidates = candidates
        self.reason = reason


class TaskTargetResolver:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store

    def resolve_task_by_id(self, conversation_id: str, task_id: str) -> TargetResolutionResult:
        return self.resolve_task_target(
            conversation_id,
            TaskTargetSelector(SELECTOR_TASK_ID, task_id=task_id),
        )

    def resolve_task_by_exact_title(self, conversation_id: str, title: str) -> TargetResolutionResult:
        return self.resolve_task_target(
            conversation_id,
            TaskTargetSelector(SELECTOR_EXACT_TITLE, title=title),
        )

    def resolve_task_target(self, conversation_id: str, selector) -> TargetResolutionResult:
        raw_cid = "" if conversation_id is None else str(conversation_id).strip()
        if not isinstance(selector, TaskTargetSelector):
            return _result(INVALID_SELECTOR, raw_cid, "", reason=REASON_INVALID_SELECTOR)
        selector_type = str(selector.selector_type or "").strip()
        if selector_type in UNSUPPORTED_SELECTOR_TYPES:
            return _result(
                UNSUPPORTED_REFERENCE,
                raw_cid,
                selector_type,
                reason=REASON_UNSUPPORTED_REFERENCE,
            )
        if selector_type not in SUPPORTED_SELECTOR_TYPES:
            return _result(INVALID_SELECTOR, raw_cid, selector_type, reason=REASON_INVALID_SELECTOR)
        try:
            base = self.task_store.conversation_dir(raw_cid)
        except TaskStoreError:
            return _result(INVALID_SELECTOR, raw_cid, selector_type, reason=REASON_INVALID_SELECTOR)
        cid = os.path.basename(base)
        if selector_type == SELECTOR_TASK_ID:
            task_id = _text(selector.task_id)
            if not _TASK_ID_RE.fullmatch(task_id):
                return _result(INVALID_SELECTOR, cid, selector_type, reason=REASON_INVALID_SELECTOR)
        else:
            title = _text(selector.title)
            if title == "":
                return _result(INVALID_SELECTOR, cid, selector_type, reason=REASON_INVALID_SELECTOR)
        state, rows, reason = _read_task_document(os.path.join(base, "tasks.json"))
        if state == "MISSING":
            return _result(NOT_FOUND, cid, selector_type, reason=REASON_NOT_FOUND)
        if state == "CORRUPT":
            return _result(CORRUPT, cid, selector_type, reason=reason)
        if selector_type == SELECTOR_TASK_ID:
            return _resolve_id(cid, rows, task_id)
        return _resolve_exact_title(cid, rows, title)


def _resolve_id(conversation_id: str, rows: list, task_id: str) -> TargetResolutionResult:
    hits = [item for item in rows if str(item.get("id") or "") == task_id]
    visible = [item for item in hits if _row_in_conversation(item, conversation_id)]
    return _finish(
        conversation_id,
        SELECTOR_TASK_ID,
        visible,
        hidden_foreign=bool(hits) and not visible,
        duplicate_reason=REASON_DUPLICATE_TASK_ID,
    )


def _resolve_exact_title(conversation_id: str, rows: list, title: str) -> TargetResolutionResult:
    hits = [item for item in rows if str(item.get("title") or "") == title]
    visible = [item for item in hits if _row_in_conversation(item, conversation_id)]
    return _finish(
        conversation_id,
        SELECTOR_EXACT_TITLE,
        visible,
        hidden_foreign=bool(hits) and not visible,
        duplicate_reason=REASON_DUPLICATE_TITLE,
    )


def _finish(
    conversation_id: str,
    selector_type: str,
    visible: list,
    hidden_foreign: bool,
    duplicate_reason: str,
) -> TargetResolutionResult:
    if len(visible) == 1:
        task = dict(visible[0])
        return _result(
            RESOLVED,
            conversation_id,
            selector_type,
            task_id=str(task.get("id") or "") or None,
            task=task,
        )
    if len(visible) > 1:
        return _result(
            AMBIGUOUS,
            conversation_id,
            selector_type,
            candidates=[_candidate(item) for item in visible],
            reason=duplicate_reason,
        )
    if hidden_foreign:
        return _result(
            NOT_FOUND,
            conversation_id,
            selector_type,
            reason=REASON_CONVERSATION_MISMATCH,
        )
    return _result(NOT_FOUND, conversation_id, selector_type, reason=REASON_NOT_FOUND)


def _candidate(task: dict) -> dict:
    return {
        "task_id": str(task.get("id") or ""),
        "title": str(task.get("title") or ""),
        "status": str(task.get("status") or ""),
        "assignee_text": str(task.get("assignee_text") or ""),
    }


def _row_in_conversation(task: dict, conversation_id: str) -> bool:
    owner = str(task.get("conversation_id") or "")
    if not owner:
        return True
    return owner == conversation_id


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _result(
    status: str,
    conversation_id: str,
    selector_type: str,
    task_id: Optional[str] = None,
    task: Optional[dict] = None,
    candidates: Optional[list] = None,
    reason: str = "",
) -> TargetResolutionResult:
    return TargetResolutionResult(
        status,
        conversation_id,
        selector_type,
        task_id=task_id,
        task=task,
        candidates=candidates,
        reason=reason,
    )


def _read_task_document(path: str):
    if not os.path.isfile(path):
        return "MISSING", [], ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeError, ValueError):
        return "CORRUPT", [], REASON_TASKS_UNREADABLE
    rows = _task_rows(data)
    if rows is None:
        return "CORRUPT", [], REASON_TASKS_STRUCTURE_INVALID
    return "OK", rows, ""


def _task_rows(data):
    if isinstance(data, list):
        if any(not isinstance(item, dict) for item in data):
            return None
        return data
    if not isinstance(data, dict):
        return None
    rows = data.get("tasks")
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        return None
    return rows
