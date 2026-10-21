# -*- coding: utf-8 -*-
"""Business Action 的 append-only 追踪。不是任务状态，也不参与查询。"""

from __future__ import annotations

import json
import os

from filelock import FileLock

from conversation_store import utc_now_iso
from store_io import lock_path_for

EVENT_PREPARED = "ACTION_PREPARED"
EVENT_CONFIRM_REQUESTED = "ACTION_CONFIRM_REQUESTED"
EVENT_EXECUTED = "ACTION_EXECUTED"
EVENT_NOOP = "ACTION_NOOP"
EVENT_FAILED = "ACTION_FAILED"
EVENT_REJECTED = "ACTION_REJECTED"
TARGET_TYPE_TASK = "TASK"

_FIELDS = (
    "event",
    "action_id",
    "action_type",
    "conversation_id",
    "message_id",
    "actor_ref",
    "target_type",
    "target_id",
    "before_status",
    "after_status",
    "result",
    "reason",
)


def audit_path(root_dir: str) -> str:
    return os.path.join(os.path.abspath(root_dir), "data", "business_actions", "business_action_audit.jsonl")


def append_business_action_audit(root_dir: str, event: dict) -> None:
    item = {key: "" for key in _FIELDS}
    for key, value in dict(event or {}).items():
        if key == "ts":
            continue
        item[key] = "" if value is None else str(value)
    item["ts"] = utc_now_iso()
    item["target_type"] = item.get("target_type") or TARGET_TYPE_TASK
    path = audit_path(root_dir)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    lock = FileLock(lock_path_for(path))
    line = json.dumps(item, ensure_ascii=False, default=str)
    with lock:
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")


def read_business_action_audit(root_dir: str) -> list:
    path = audit_path(root_dir)
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
