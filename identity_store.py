# -*- coding: utf-8 -*-
"""P8-G5 人员目录、微信账号绑定、负责人精确别名。

文件在 data/identity/。不写 Task、Topic、Decision、Risk、config.local.json。
人员、wxid、别名只能由调用方显式写入。解析失败时不新建人员。
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from filelock import FileLock

from conversation_store import utc_now_iso
from store_io import lock_path_for

SCHEMA_VERSION = 1
STATUS_ACTIVE = "ACTIVE"
STATUS_DISABLED = "DISABLED"
ALLOWED_STATUS = (STATUS_ACTIVE, STATUS_DISABLED)
SOURCE_MANUAL = "MANUAL"
SOURCE_TRUSTED_DIRECTORY = "TRUSTED_DIRECTORY"
ALLOWED_BINDING_SOURCES = (SOURCE_MANUAL, SOURCE_TRUSTED_DIRECTORY)

_PERSON_ID_RE = re.compile(r"^person_[A-Za-z0-9]+$")


class IdentityStoreError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


class IdentityStore:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.store_dir = os.path.join(self.root_dir, "data", "identity")

    def people_path(self) -> str:
        return os.path.join(self.store_dir, "people.json")

    def bindings_path(self) -> str:
        return os.path.join(self.store_dir, "wechat_bindings.json")

    def aliases_path(self) -> str:
        return os.path.join(self.store_dir, "assignee_aliases.json")

    def list_people(self) -> list:
        return self._read_rows(self.people_path(), "people")

    def get_person(self, person_id: str) -> Optional[dict]:
        target = str(person_id or "").strip()
        found = None
        for item in self.list_people():
            if str(item.get("person_id") or "") != target:
                continue
            if found is not None:
                raise IdentityStoreError("INTEGRITY", "person_id 在目录中重复，已停止写入", target)
            found = dict(item)
        return found

    def create_person(self, person_id: str, canonical_name: str) -> dict:
        pid = _require_person_id(person_id)
        name = _require_name(canonical_name)
        now = utc_now_iso()

        def mutate(rows: list) -> dict:
            _assert_unique_people(rows)
            for item in rows:
                if str(item.get("person_id") or "") == pid:
                    raise IdentityStoreError("DUPLICATE_PERSON_ID", "person_id 已存在", pid)
            record = {
                "person_id": pid,
                "canonical_name": name,
                "status": STATUS_ACTIVE,
                "created_at": now,
                "updated_at": now,
            }
            rows.append(record)
            return record

        return self._mutate(self.people_path(), "people", mutate)

    def set_person_status(self, person_id: str, status: str) -> dict:
        pid = _require_person_id(person_id)
        next_status = str(status or "").strip()
        if next_status not in ALLOWED_STATUS:
            raise IdentityStoreError("INVALID_STATUS", "status 只能是 ACTIVE 或 DISABLED", next_status)
        now = utc_now_iso()

        def mutate(rows: list) -> dict:
            _assert_unique_people(rows)
            for item in rows:
                if str(item.get("person_id") or "") != pid:
                    continue
                item["status"] = next_status
                item["updated_at"] = now
                return dict(item)
            raise IdentityStoreError("PERSON_NOT_FOUND", "人员不存在", pid)

        return self._mutate(self.people_path(), "people", mutate)

    def list_bindings(self) -> list:
        return self._read_rows(self.bindings_path(), "bindings")

    def bind_wechat(
        self,
        wxid: str,
        person_id: str,
        *,
        display_name: str = "",
        binding_source: str = SOURCE_MANUAL,
    ) -> dict:
        account = _require_wxid(wxid)
        pid = _require_person_id(person_id)
        source = str(binding_source or "").strip()
        if source not in ALLOWED_BINDING_SOURCES:
            raise IdentityStoreError("INVALID_BINDING_SOURCE", "绑定来源必须是显式来源", source)
        shown = str(display_name or "").strip()
        if "\n" in shown or "\r" in shown:
            raise IdentityStoreError("INVALID_NAME", "display_name 不能跨行", shown)
        if self.get_person(pid) is None:
            raise IdentityStoreError("PERSON_NOT_FOUND", "人员不存在，不能绑定微信账号", pid)
        now = utc_now_iso()

        def mutate(rows: list) -> dict:
            _assert_unique_wxid(rows)
            for item in rows:
                if str(item.get("wxid") or "") != account:
                    continue
                if str(item.get("person_id") or "") == pid:
                    return dict(item)
                raise IdentityStoreError("CONFLICT", "wxid 已绑定其他人员，禁止覆盖", account)
            record = {
                "wxid": account,
                "person_id": pid,
                "display_name": shown,
                "binding_source": source,
                "created_at": now,
            }
            rows.append(record)
            return record

        return self._mutate(self.bindings_path(), "bindings", mutate)

    def list_aliases(self) -> list:
        return self._read_rows(self.aliases_path(), "aliases")

    def add_alias(self, exact_text: str, person_id: str) -> dict:
        text = _require_alias(exact_text)
        pid = _require_person_id(person_id)
        if self.get_person(pid) is None:
            raise IdentityStoreError("PERSON_NOT_FOUND", "人员不存在，不能登记别名", pid)
        now = utc_now_iso()

        def mutate(rows: list) -> dict:
            _assert_unique_alias(rows)
            for item in rows:
                if str(item.get("exact_text") or "") != text:
                    continue
                if str(item.get("person_id") or "") == pid:
                    return dict(item)
                raise IdentityStoreError("CONFLICT", "别名已绑定其他人员，禁止覆盖", text)
            record = {
                "exact_text": text,
                "person_id": pid,
                "created_at": now,
            }
            rows.append(record)
            return record

        return self._mutate(self.aliases_path(), "aliases", mutate)

    def _read_rows(self, path: str, key: str) -> list:
        if not os.path.isfile(path):
            return []
        lock = FileLock(lock_path_for(path))
        with lock:
            data = _load_document(path, key)
        return [dict(item) for item in data[key]]

    def _mutate(self, path: str, key: str, mutator) -> dict:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        lock = FileLock(lock_path_for(path))
        with lock:
            if os.path.isfile(path):
                data = _load_document(path, key)
            else:
                data = {"schema_version": SCHEMA_VERSION, key: []}
            rows = data[key]
            record = mutator(rows)
            data["schema_version"] = int(data.get("schema_version") or SCHEMA_VERSION)
            data[key] = rows
            _replace_json(path, data)
            return dict(record)


def _require_person_id(person_id: str) -> str:
    value = str(person_id or "").strip()
    if not _PERSON_ID_RE.match(value):
        raise IdentityStoreError("INVALID_PERSON_ID", "person_id 必须是 person_ 加稳定后缀", value)
    return value


def _require_name(name: str) -> str:
    value = str(name or "").strip()
    if not value or "\n" in value or "\r" in value or len(value) > 200:
        raise IdentityStoreError("INVALID_NAME", "canonical_name 必须是非空的单行姓名", value)
    return value


def _require_wxid(wxid: str) -> str:
    value = str(wxid or "").strip()
    if not value or "\n" in value or "\r" in value or len(value) > 128:
        raise IdentityStoreError("INVALID_WXID", "wxid 必须是非空的单行账号", value)
    return value


def _require_alias(text: str) -> str:
    value = str(text or "").strip()
    if not value or "\n" in value or "\r" in value or len(value) > 200:
        raise IdentityStoreError("INVALID_ALIAS", "别名必须是非空的单行精确文本", value)
    return value


def _assert_unique_people(rows: list) -> None:
    seen = []
    for item in rows:
        pid = str(item.get("person_id") or "")
        if not pid or pid in seen:
            raise IdentityStoreError("INTEGRITY", "人员目录已损坏，已停止写入", pid)
        seen.append(pid)


def _assert_unique_wxid(rows: list) -> None:
    seen = []
    for item in rows:
        account = str(item.get("wxid") or "")
        if not account or account in seen:
            raise IdentityStoreError("INTEGRITY", "微信绑定已损坏，已停止写入", account)
        seen.append(account)


def _assert_unique_alias(rows: list) -> None:
    seen = []
    for item in rows:
        text = str(item.get("exact_text") or "")
        if not text or text in seen:
            raise IdentityStoreError("INTEGRITY", "别名目录已损坏，已停止写入", text)
        seen.append(text)


def _load_document(path: str, key: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise IdentityStoreError("CORRUPT", "身份文件无法读取，已停止写入", str(exc))
    if not isinstance(data, dict):
        raise IdentityStoreError("CORRUPT", "身份文件结构无效，已停止写入", key)
    rows = data.get(key)
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        raise IdentityStoreError("CORRUPT", "身份文件结构无效，已停止写入", key)
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
