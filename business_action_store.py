# -*- coding: utf-8 -*-
"""Business Action 记录。当前状态、幂等和崩溃恢复都以这份文件为准。

确认时先持有 actions.json.lock，再由调用方进入任务生命周期。
本模块不打开任务存储，也不调用生命周期。
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

from filelock import FileLock

from store_io import lock_path_for

SCHEMA_VERSION = 1
STATE_PREPARED = "PREPARED"
STATE_EXECUTED = "EXECUTED"
STATE_SUCCEEDED_NOOP = "SUCCEEDED_NOOP"
STATE_FAILED = "FAILED"

OUTCOME_COMMITTED = "COMMITTED"
OUTCOME_UNCHANGED = "UNCHANGED"
OUTCOME_ACTOR_MISMATCH = "ACTOR_MISMATCH"
OUTCOME_NOT_FOUND = "NOT_FOUND"
OUTCOME_RECORD_PERSIST_FAILED = "RECORD_PERSIST_FAILED"
STORE_CORRUPT = "CORRUPT"


class BusinessActionStoreError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


class ConfirmationCommit:
    def __init__(self, outcome: str, record: Optional[dict], applied: Optional[dict]):
        self.outcome = outcome
        self.record = record
        self.applied = applied


def actions_path(root_dir: str) -> str:
    return os.path.join(os.path.abspath(root_dir), "data", "business_actions", "actions.json")


class BusinessActionStore:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.path = actions_path(self.root_dir)
        self._held_lock = None

    def is_corrupt(self) -> bool:
        if not os.path.isfile(self.path):
            return False
        lock = FileLock(lock_path_for(self.path))
        with lock:
            try:
                _load_existing(self.path)
            except BusinessActionStoreError:
                return True
            return False

    def get_action(self, action_id: str) -> Optional[dict]:
        if not action_id or not os.path.isfile(self.path):
            return None
        lock = FileLock(lock_path_for(self.path))
        with lock:
            if not os.path.isfile(self.path):
                return None
            data = _load_existing(self.path)
        item = data["actions"].get(action_id)
        if not isinstance(item, dict):
            return None
        return dict(item)

    def list_actions(self) -> list:
        if not os.path.isfile(self.path):
            return []
        lock = FileLock(lock_path_for(self.path))
        with lock:
            if not os.path.isfile(self.path):
                return []
            data = _load_existing(self.path)
        return [dict(item) for item in data["actions"].values()]

    def find_prepared_actions(self, conversation_id: str, actor_ref: str, action_type: str = "COMPLETE_TASK") -> list:
        """只读当前会话、当前账号下的 PREPARED 记录。不确认、不失败、不完成。"""
        wanted_cid = str(conversation_id or "")
        wanted_actor = str(actor_ref or "")
        wanted_type = str(action_type or "")
        found = []
        for item in self.list_actions():
            if str(item.get("state") or "") != STATE_PREPARED:
                continue
            if str(item.get("conversation_id") or "") != wanted_cid:
                continue
            if str(item.get("actor_ref") or "") != wanted_actor:
                continue
            if wanted_type and str(item.get("action_type") or "") != wanted_type:
                continue
            found.append(item)
        return found

    def read_or_create(self, action_id: str, factory: Callable[[], Optional[dict]]):
        """同一 action_id 只保留第一份记录。factory 返回 None 时不创建文件。"""
        if not os.path.isfile(self.path):
            record = factory()
            if record is None:
                return None, False
            return self._insert(action_id, record)
        return self._locked_slot(action_id, factory)

    def commit_confirmation(self, action_id: str, actor_ref: str, apply: Callable[[dict], dict]) -> ConfirmationCommit:
        """在 actions.json.lock 内检查状态并调用 apply。apply 期间锁一直持有。"""
        if not action_id or not os.path.isfile(self.path):
            return ConfirmationCommit(OUTCOME_NOT_FOUND, None, None)
        lock = FileLock(lock_path_for(self.path))
        with lock:
            self._held_lock = lock
            try:
                if not os.path.isfile(self.path):
                    return ConfirmationCommit(OUTCOME_NOT_FOUND, None, None)
                data = _load_existing(self.path)
                stored = data["actions"].get(action_id)
                if not isinstance(stored, dict):
                    return ConfirmationCommit(OUTCOME_NOT_FOUND, None, None)
                baseline = dict(stored)
                if str(baseline.get("state") or "") != STATE_PREPARED:
                    return ConfirmationCommit(OUTCOME_UNCHANGED, baseline, None)
                if str(baseline.get("actor_ref") or "") != str(actor_ref or ""):
                    return ConfirmationCommit(OUTCOME_ACTOR_MISMATCH, baseline, None)
                applied = apply(dict(baseline))
                updated = dict(baseline)
                for key, value in dict(applied or {}).items():
                    if str(key).startswith("_"):
                        continue
                    updated[key] = value
                data["actions"][action_id] = updated
                try:
                    _replace_json_unlocked(self.path, data)
                except (OSError, TypeError, ValueError):
                    return ConfirmationCommit(OUTCOME_RECORD_PERSIST_FAILED, baseline, applied)
                return ConfirmationCommit(OUTCOME_COMMITTED, dict(updated), applied)
            finally:
                self._held_lock = None

    def _insert(self, action_id: str, record: dict):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        lock = FileLock(lock_path_for(self.path))
        with lock:
            self._held_lock = lock
            try:
                if os.path.isfile(self.path):
                    data = _load_existing(self.path)
                    existing = data["actions"].get(action_id)
                    if isinstance(existing, dict):
                        return dict(existing), False
                else:
                    data = _empty_document()
                data["actions"][action_id] = record
                _replace_json_unlocked(self.path, data)
                return dict(record), True
            finally:
                self._held_lock = None

    def _locked_slot(self, action_id: str, factory: Callable[[], Optional[dict]]):
        lock = FileLock(lock_path_for(self.path))
        with lock:
            self._held_lock = lock
            try:
                data = _load_existing(self.path)
                existing = data["actions"].get(action_id)
                if isinstance(existing, dict):
                    return dict(existing), False
                record = factory()
                if record is None:
                    return None, False
                data["actions"][action_id] = record
                _replace_json_unlocked(self.path, data)
                return dict(record), True
            finally:
                self._held_lock = None


def _empty_document() -> dict:
    return {"schema_version": SCHEMA_VERSION, "actions": {}}


def _load_existing(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeError, ValueError) as exc:
        raise BusinessActionStoreError(STORE_CORRUPT, "actions.json 无法读取，已停止业务执行", str(exc))
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise BusinessActionStoreError(STORE_CORRUPT, "actions.json 结构无效，已停止业务执行", "schema")
    actions = data.get("actions")
    if not isinstance(actions, dict):
        raise BusinessActionStoreError(STORE_CORRUPT, "actions.json 结构无效，已停止业务执行", "actions")
    for key, item in actions.items():
        if not isinstance(item, dict) or item.get("action_id") != key:
            raise BusinessActionStoreError(STORE_CORRUPT, "actions.json 结构无效，已停止业务执行", str(key))
    return data


def _replace_json_unlocked(path: str, data: dict) -> None:
    """调用方已持有 actions.json.lock。提交点只有 os.replace。"""
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
