# -*- coding: utf-8 -*-
"""P7-G1 人工重试动作审计。只记录谁请求了什么，不是 processing 真值。"""

from __future__ import annotations

import json
import os

from filelock import FileLock

from conversation_store import utc_now_iso
from store_io import lock_path_for

EVENT_REQUESTED = "MANUAL_RETRY_REQUESTED"
EVENT_RESULT = "MANUAL_RETRY_RESULT"


def audit_path(root_dir: str) -> str:
    return os.path.join(os.path.abspath(root_dir), "data", "operations", "operations_action_audit.jsonl")


def append_action_audit(root_dir: str, event: dict) -> None:
    item = dict(event or {})
    item.setdefault("ts", utc_now_iso())
    path = audit_path(root_dir)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    lock = FileLock(lock_path_for(path))
    line = json.dumps(item, ensure_ascii=False, default=str)
    with lock:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def read_action_audit(root_dir: str) -> list:
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
