# -*- coding: utf-8 -*-
"""管理面操作审计：谁改了配置、谁点了紧急停止。"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from bot_runtime import CONTROL_DIR, ensure_control_dir, mask_secrets
from store_io import lock_path_for
from filelock import FileLock

AUDIT_FILE = os.path.join(CONTROL_DIR, "audit.jsonl")
MAX_AUDIT_LINES = 2000


def current_actor(default: str = "local") -> str:
    try:
        from flask import has_request_context, session
        if has_request_context():
            if session.get("logged_in"):
                return "webui-user"
            return "local-webui"
    except Exception:
        pass
    return default


def log_audit(action: str, actor: Optional[str] = None, detail: str = "", extra: Optional[dict] = None) -> dict:
    ensure_control_dir()
    item = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": time.time(),
        "actor": actor or current_actor(),
        "action": action,
        "detail": mask_secrets(detail or ""),
    }
    if extra:
        item["extra"] = extra
    line = json.dumps(item, ensure_ascii=False)
    lock = FileLock(lock_path_for(AUDIT_FILE))
    with lock:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        _trim()
    return item


def read_audit(limit: int = 100) -> list:
    ensure_control_dir()
    if not os.path.exists(AUDIT_FILE):
        return []
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-max(1, min(limit, 500)):]
        items = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        items.reverse()
        return items
    except OSError:
        return []


def _trim() -> None:
    try:
        if not os.path.exists(AUDIT_FILE):
            return
        if os.path.getsize(AUDIT_FILE) < 1_000_000:
            return
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_AUDIT_LINES:
            with open(AUDIT_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-MAX_AUDIT_LINES:])
    except OSError:
        pass
