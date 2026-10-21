# -*- coding: utf-8 -*-
"""按 wxid 或精确别名解析 person_id。

只返回 RESOLVED、NOT_FOUND、AMBIGUOUS。
比较前只对输入做 strip。找不到时不新建人员。
"""

from __future__ import annotations

from typing import Optional

RESOLVED = "RESOLVED"
NOT_FOUND = "NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS"


class IdentityResolution:
    def __init__(self, status: str, person_id: str = "", person: Optional[dict] = None):
        self.status = status
        self.person_id = person_id or ""
        self.person = dict(person) if person else None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "person_id": self.person_id,
            "person": dict(self.person) if self.person else None,
        }


def resolve_wxid(store, wxid: str) -> IdentityResolution:
    account = str(wxid or "").strip()
    if not account:
        return IdentityResolution(NOT_FOUND)
    return _resolve_rows(store, store.list_bindings(), "wxid", account)


def resolve_exact_alias(store, text: str) -> IdentityResolution:
    exact = str(text or "").strip()
    if not exact:
        return IdentityResolution(NOT_FOUND)
    return _resolve_rows(store, store.list_aliases(), "exact_text", exact)


def _resolve_rows(store, rows: list, field: str, expected: str) -> IdentityResolution:
    matched = []
    for item in rows:
        if str(item.get(field) or "") == expected:
            matched.append(item)
    person_ids = []
    for item in matched:
        pid = str(item.get("person_id") or "").strip()
        if not pid:
            return IdentityResolution(AMBIGUOUS)
        if pid not in person_ids:
            person_ids.append(pid)
    if not person_ids:
        return IdentityResolution(NOT_FOUND)
    if len(person_ids) != 1:
        return IdentityResolution(AMBIGUOUS)
    person_id = person_ids[0]
    people = []
    for item in store.list_people():
        if str(item.get("person_id") or "") == person_id:
            people.append(item)
    if len(people) > 1:
        return IdentityResolution(AMBIGUOUS)
    person = people[0] if people else None
    return IdentityResolution(RESOLVED, person_id, person)
