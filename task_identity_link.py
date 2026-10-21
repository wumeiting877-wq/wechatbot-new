# -*- coding: utf-8 -*-
"""Task 与 Person 的确定性链接。

链接是附加身份事实，不是 Task 成功的条件。
同一会话里的同一个 task_id 最多对应一个 person_id。
不改 Task schema，不按标题、描述或消息发送者推断负责人。
"""

from __future__ import annotations

import json
import logging
import os

from filelock import FileLock

from conversation_store import utc_now_iso
from identity_resolver import AMBIGUOUS, RESOLVED, resolve_exact_alias
from identity_store import (
    STATUS_ACTIVE,
    STATUS_DISABLED,
    IdentityStore,
    IdentityStoreError,
)
from store_io import lock_path_for

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SOURCE_MANUAL = "MANUAL"
SOURCE_TRUSTED_DIRECTORY = "TRUSTED_DIRECTORY"
SOURCE_EXACT_EXPLICIT_ALIAS = "EXACT_EXPLICIT_ALIAS"
ALLOWED_LINK_SOURCES = (
    SOURCE_MANUAL,
    SOURCE_TRUSTED_DIRECTORY,
    SOURCE_EXACT_EXPLICIT_ALIAS,
)

CATEGORY_EXACT_RESOLVABLE = "EXACT_RESOLVABLE"
CATEGORY_UNRESOLVED = "UNRESOLVED"
CATEGORY_AMBIGUOUS = "AMBIGUOUS"
CATEGORY_ALREADY_LINKED = "ALREADY_LINKED"
PREVIEW_CATEGORIES = (
    CATEGORY_EXACT_RESOLVABLE,
    CATEGORY_UNRESOLVED,
    CATEGORY_AMBIGUOUS,
    CATEGORY_ALREADY_LINKED,
)


class TaskIdentityLinkError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


class TaskIdentityLinkStore:
    def __init__(self, root_dir: str, task_store=None, identity_store=None):
        self.root_dir = os.path.abspath(root_dir)
        self.store_dir = os.path.join(self.root_dir, "data", "identity")
        self.task_store = task_store
        self.identity_store = identity_store if identity_store is not None else IdentityStore(self.root_dir)

    def links_path(self) -> str:
        return os.path.join(self.store_dir, "task_person_links.json")

    def list_links(self) -> list:
        path = self.links_path()
        if not os.path.isfile(path):
            return []
        lock = FileLock(lock_path_for(path))
        with lock:
            data = _load_document(path)
        _assert_link_rows(data["links"])
        return [dict(item) for item in data["links"]]

    def find_link(self, conversation_id: str, task_id: str):
        cid = str(conversation_id or "").strip()
        tid = str(task_id or "").strip()
        found = None
        for item in self.list_links():
            if str(item.get("conversation_id") or "") != cid:
                continue
            if str(item.get("task_id") or "") != tid:
                continue
            if found is not None:
                raise TaskIdentityLinkError("CORRUPT", "同一任务存在冲突负责人链接", tid)
            found = dict(item)
        return found

    def list_for_person(self, conversation_id: str, person_id: str) -> list:
        cid = str(conversation_id or "").strip()
        pid = str(person_id or "").strip()
        rows = []
        seen = set()
        for item in self.list_links():
            if str(item.get("conversation_id") or "") != cid:
                continue
            if str(item.get("person_id") or "") != pid:
                continue
            tid = str(item.get("task_id") or "")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            rows.append(dict(item))
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("task_id") or "")))
        return rows

    def link_task_to_person(
        self,
        conversation_id: str,
        task_id: str,
        person_id: str,
        source: str = SOURCE_MANUAL,
    ) -> dict:
        cid = str(conversation_id or "").strip()
        tid = str(task_id or "").strip()
        pid = str(person_id or "").strip()
        origin = str(source or "").strip()
        if origin not in ALLOWED_LINK_SOURCES:
            raise TaskIdentityLinkError("INVALID_SOURCE", "链接来源必须是显式来源", origin)
        if not cid or not tid or not pid:
            raise TaskIdentityLinkError("TASK_NOT_FOUND", "缺少会话、任务或人员", tid)
        person = self._require_active_person(pid)
        task = self._require_task(cid, tid)
        if origin == SOURCE_EXACT_EXPLICIT_ALIAS:
            self._require_exact_alias(task, pid)
        now = utc_now_iso()

        def mutate(rows: list) -> dict:
            _assert_link_rows(rows)
            for item in rows:
                if str(item.get("conversation_id") or "") != cid:
                    continue
                if str(item.get("task_id") or "") != tid:
                    continue
                if str(item.get("person_id") or "") == pid:
                    return dict(item)
                raise TaskIdentityLinkError("CONFLICT", "任务已绑定其他人员，禁止覆盖", tid)
            record = {
                "conversation_id": cid,
                "task_id": tid,
                "person_id": pid,
                "source": origin,
                "created_at": now,
            }
            rows.append(record)
            return record

        _ = person
        return self._mutate(mutate)

    def preview_task_identity_links(self, conversation_id: str = "") -> dict:
        """只读预览。不写 task_person_links.json。"""
        wanted = str(conversation_id or "").strip()
        counts = {key: 0 for key in PREVIEW_CATEGORIES}
        items = []
        linked = {}
        for item in self.list_links():
            key = (str(item.get("conversation_id") or ""), str(item.get("task_id") or ""))
            linked[key] = str(item.get("person_id") or "")
        for cid in self._conversation_ids(wanted):
            for task in self._tasks_of(cid):
                tid = str(task.get("id") or "")
                category, person_id = self._preview_category(task, linked.get((cid, tid), ""))
                counts[category] += 1
                items.append(
                    {
                        "conversation_id": cid,
                        "task_id": tid,
                        "category": category,
                        "person_id": person_id,
                    }
                )
        return {"counts": counts, "items": items}

    def _preview_category(self, task: dict, linked_person_id: str):
        if linked_person_id:
            return CATEGORY_ALREADY_LINKED, linked_person_id
        exact = str(task.get("assignee_text") or "").strip()
        try:
            resolution = resolve_exact_alias(self.identity_store, exact)
        except IdentityStoreError as exc:
            raise TaskIdentityLinkError("CORRUPT", "身份文件无法读取，已停止预览", exc.code)
        if resolution.status == AMBIGUOUS:
            return CATEGORY_AMBIGUOUS, ""
        if resolution.status != RESOLVED or not resolution.person_id:
            return CATEGORY_UNRESOLVED, ""
        person = resolution.person
        if person is None or str(person.get("status") or "") != STATUS_ACTIVE:
            return CATEGORY_UNRESOLVED, ""
        return CATEGORY_EXACT_RESOLVABLE, resolution.person_id

    def _require_active_person(self, person_id: str) -> dict:
        try:
            person = self.identity_store.get_person(person_id)
        except IdentityStoreError as exc:
            raise TaskIdentityLinkError(exc.code or "CORRUPT", exc.message, exc.detail)
        if person is None:
            raise TaskIdentityLinkError("PERSON_NOT_FOUND", "人员不存在", person_id)
        if str(person.get("status") or "") == STATUS_DISABLED:
            raise TaskIdentityLinkError("PERSON_DISABLED", "停用人员不能新建任务身份链接", person_id)
        if str(person.get("status") or "") != STATUS_ACTIVE:
            raise TaskIdentityLinkError("PERSON_DISABLED", "人员不是可绑定状态", person_id)
        return person

    def _require_exact_alias(self, task: dict, person_id: str) -> None:
        exact = str(task.get("assignee_text") or "").strip()
        try:
            resolution = resolve_exact_alias(self.identity_store, exact)
        except IdentityStoreError as exc:
            raise TaskIdentityLinkError(exc.code or "CORRUPT", exc.message, exc.detail)
        if resolution.status != RESOLVED or resolution.person_id != person_id:
            raise TaskIdentityLinkError("NOT_FOUND", "assignee_text 没有指向该人员的唯一精确别名", exact)

    def _require_task(self, conversation_id: str, task_id: str) -> dict:
        store = self._tasks()
        try:
            direct = store.get_task(conversation_id, task_id)
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            if code == "INVALID_CONVERSATION_ID":
                raise TaskIdentityLinkError("CONVERSATION_MISMATCH", "会话与任务不一致", conversation_id)
            raise TaskIdentityLinkError("TASK_NOT_FOUND", "任务不存在", task_id)
        if direct is not None:
            owner = str(direct.get("conversation_id") or "")
            if owner != conversation_id:
                raise TaskIdentityLinkError("CONVERSATION_MISMATCH", "任务不属于该会话", task_id)
            return direct
        other = self._other_conversation(task_id, conversation_id)
        if other:
            raise TaskIdentityLinkError("CONVERSATION_MISMATCH", "任务属于其他会话", task_id)
        raise TaskIdentityLinkError("TASK_NOT_FOUND", "任务不存在", task_id)

    def _other_conversation(self, task_id: str, conversation_id: str) -> str:
        store = self._tasks()
        for cid in self._conversation_ids(""):
            if cid == conversation_id:
                continue
            try:
                found = store.get_task(cid, task_id)
            except Exception:
                continue
            if found is not None:
                return cid
        return ""

    def _conversation_ids(self, conversation_id: str) -> list:
        if conversation_id:
            return [conversation_id]
        store = self._tasks()
        root = getattr(store, "conversations_dir", "")
        if not root or not os.path.isdir(root):
            return []
        names = []
        for name in os.listdir(root):
            if name.startswith("conv_") and os.path.isdir(os.path.join(root, name)):
                names.append(name)
        names.sort()
        return names

    def _tasks_of(self, conversation_id: str) -> list:
        try:
            rows = self._tasks().list_tasks(conversation_id)
        except Exception:
            return []
        return [item for item in rows if isinstance(item, dict)]

    def _tasks(self):
        if self.task_store is not None:
            return self.task_store
        from task_store import TaskStore

        self.task_store = TaskStore(self.root_dir)
        return self.task_store

    def _mutate(self, mutator) -> dict:
        path = self.links_path()
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        lock = FileLock(lock_path_for(path))
        with lock:
            if os.path.isfile(path):
                data = _load_document(path)
            else:
                data = {"schema_version": SCHEMA_VERSION, "links": []}
            rows = data["links"]
            record = mutator(rows)
            data["schema_version"] = int(data.get("schema_version") or SCHEMA_VERSION)
            data["links"] = rows
            _replace_json(path, data)
            return dict(record)


def attach_exact_links_for_created_tasks(task_store, conversation_id: str, created_task_ids) -> None:
    """新任务落盘后的 best-effort 链接。任何失败都不向外抛出。"""
    try:
        ids = []
        seen = set()
        for raw in created_task_ids or []:
            task_id = str(raw or "").strip()
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            ids.append(task_id)
        if not ids:
            return
        root = getattr(task_store, "root_dir", "")
        identity = IdentityStore(root)
        linker = TaskIdentityLinkStore(root, task_store=task_store, identity_store=identity)
        for task_id in ids:
            try:
                task = task_store.get_task(conversation_id, task_id)
            except Exception:
                logger.warning("读取新任务失败，任务本身保持成功 task_id=%s", task_id)
                continue
            if not isinstance(task, dict):
                continue
            exact = str(task.get("assignee_text") or "").strip()
            if not exact:
                continue
            try:
                resolution = resolve_exact_alias(identity, exact)
            except IdentityStoreError:
                logger.warning("精确别名不可读，任务保持未绑定 task_id=%s", task_id)
                continue
            if resolution.status != RESOLVED or not resolution.person_id:
                continue
            person = resolution.person
            if person is None or str(person.get("status") or "") != STATUS_ACTIVE:
                continue
            try:
                linker.link_task_to_person(
                    conversation_id,
                    task_id,
                    resolution.person_id,
                    source=SOURCE_EXACT_EXPLICIT_ALIAS,
                )
            except TaskIdentityLinkError as exc:
                logger.warning(
                    "TaskIdentityLink skipped code=%s task_id=%s",
                    exc.code,
                    task_id,
                )
            except Exception:
                logger.warning("TaskIdentityLink skipped task_id=%s", task_id)
    except Exception:
        logger.exception("TaskIdentityLink best-effort failed")


def note_assignee_text_drift(task_store, conversation_id: str, drifts) -> None:
    """负责人文本变了也保留旧链接，只记一条需要人工确认的日志。"""
    try:
        if not drifts:
            return
        root = getattr(task_store, "root_dir", "")
        linker = TaskIdentityLinkStore(root, task_store=task_store)
        for item in drifts or []:
            task_id = str((item or {}).get("task_id") or "").strip()
            if not task_id:
                continue
            try:
                link = linker.find_link(conversation_id, task_id)
            except TaskIdentityLinkError:
                logger.warning(
                    "TaskIdentityLink unreadable after assignee_text change; kept untouched task_id=%s",
                    task_id,
                )
                continue
            if link is None:
                continue
            logger.warning(
                "TaskIdentityLink kept after assignee_text change; manual confirmation required conversation_id=%s task_id=%s",
                conversation_id,
                task_id,
            )
    except Exception:
        logger.exception("TaskIdentityLink drift check failed")


def _assert_link_rows(rows: list) -> None:
    if not isinstance(rows, list):
        raise TaskIdentityLinkError("CORRUPT", "任务身份链接结构无效，已停止写入", "links")
    seen = {}
    for item in rows:
        if not isinstance(item, dict):
            raise TaskIdentityLinkError("CORRUPT", "任务身份链接结构无效，已停止写入", "links")
        cid = str(item.get("conversation_id") or "")
        tid = str(item.get("task_id") or "")
        pid = str(item.get("person_id") or "")
        if not cid or not tid or not pid:
            raise TaskIdentityLinkError("CORRUPT", "任务身份链接结构无效，已停止写入", tid)
        key = (cid, tid)
        previous = seen.get(key)
        if previous is not None and previous != pid:
            raise TaskIdentityLinkError("CORRUPT", "同一任务存在冲突负责人链接", tid)
        seen[key] = pid


def _load_document(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise TaskIdentityLinkError("CORRUPT", "任务身份链接无法读取，已停止写入", str(exc))
    if not isinstance(data, dict):
        raise TaskIdentityLinkError("CORRUPT", "任务身份链接结构无效，已停止写入", "links")
    rows = data.get("links")
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        raise TaskIdentityLinkError("CORRUPT", "任务身份链接结构无效，已停止写入", "links")
    return data


def _replace_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
