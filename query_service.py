# -*- coding: utf-8 -*-
"""P8-G1 只读查询服务。只读当前 Conversation.id 的已落盘实体。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from conversation_store import utc_now_iso
from query_router import (
    LIST_DECISIONS,
    LIST_RISKS,
    LIST_TASKS,
    LIST_TOPICS,
    OPEN_RISKS,
    TOPIC_SUMMARY,
)

OUTCOME_OK = "OK"
OUTCOME_EMPTY = "EMPTY"
OUTCOME_NOT_FOUND = "NOT_FOUND"
OUTCOME_AMBIGUOUS = "AMBIGUOUS"
OUTCOME_OUT_OF_SCOPE = "OUT_OF_SCOPE"
OUTCOME_CONVERSATION_NOT_RESOLVED = "CONVERSATION_NOT_RESOLVED"
OUTCOME_IDENTITY_DISABLED = "IDENTITY_DISABLED"
OUTCOME_IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"

MY_TASKS = "MY_TASKS"
TASKS_BY_ASSIGNEE = "TASKS_BY_ASSIGNEE"
PERSONAL_QUERY_TYPES = (MY_TASKS, TASKS_BY_ASSIGNEE)

SOURCE_TOPIC = "topic_store"
SOURCE_TASK = "task_store"
SOURCE_DECISION = "decision_store"
SOURCE_RISK = "risk_store"

TOPIC_KEYS = (
    "id",
    "conversation_id",
    "title",
    "summary",
    "status",
    "message_count",
    "last_message_at",
    "created_at",
)
TASK_KEYS = (
    "id",
    "conversation_id",
    "topic_id",
    "title",
    "description",
    "status",
    "assignee_text",
    "due_text",
    "created_msg_id",
    "created_at",
    "updated_at",
)
DECISION_KEYS = (
    "id",
    "conversation_id",
    "topic_id",
    "title",
    "decision_text",
    "summary",
    "status",
    "created_msg_id",
    "supersedes_decision_id",
    "created_at",
)
RISK_KEYS = (
    "id",
    "conversation_id",
    "topic_id",
    "task_id",
    "title",
    "description",
    "condition_text",
    "impact_text",
    "status",
    "created_msg_id",
    "created_at",
    "updated_at",
)


@dataclass
class QueryRequest:
    conversation_id: str
    message_id: str
    sender_id: str
    query_type: str
    topic_id: str = ""
    topic_title: str = ""
    person_id: str = ""


@dataclass
class QueryResult:
    query_type: str
    conversation_id: str
    items: list
    total: int
    source: str
    sources: list
    generated_at: str
    empty: bool
    outcome: str
    subject_name: str = ""


def _pick(record: dict, keys: tuple) -> dict:
    return {key: record[key] for key in keys if key in record}


def _owned(records: list, conversation_id: str) -> list:
    kept = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if str(record.get("conversation_id") or "") != conversation_id:
            continue
        kept.append(record)
    return kept


class QueryService:
    """同步只读。不写 Store，不读 processing，不扫其它会话目录。"""

    def __init__(self, topic_store, task_store, decision_store, risk_store, identity_store=None, link_store=None):
        self.topic_store = topic_store
        self.task_store = task_store
        self.decision_store = decision_store
        self.risk_store = risk_store
        self.identity_store = identity_store
        self.link_store = link_store
        inner = getattr(task_store, "inner", None)
        self._root_dir = str(getattr(task_store, "root_dir", "") or getattr(inner, "root_dir", "") or "")

    def conversation_not_resolved(self, request: QueryRequest) -> QueryResult:
        return self._result(
            request,
            [],
            source="",
            sources=[],
            outcome=OUTCOME_CONVERSATION_NOT_RESOLVED,
        )

    def out_of_scope(self, request: QueryRequest) -> QueryResult:
        return self._result(
            request,
            [],
            source="",
            sources=[],
            outcome=OUTCOME_OUT_OF_SCOPE,
        )

    def execute(self, request: QueryRequest) -> QueryResult:
        conversation_id = str(request.conversation_id or "").strip()
        if not conversation_id:
            return self.conversation_not_resolved(request)
        query_type = request.query_type
        if query_type == LIST_TOPICS:
            return self._list_topics(request, conversation_id)
        if query_type == LIST_TASKS:
            return self._list_tasks(request, conversation_id)
        if query_type == LIST_DECISIONS:
            return self._list_decisions(request, conversation_id)
        if query_type == LIST_RISKS:
            return self._list_risks(request, conversation_id, open_only=False)
        if query_type == OPEN_RISKS:
            return self._list_risks(request, conversation_id, open_only=True)
        if query_type == TOPIC_SUMMARY:
            return self._topic_summary(request, conversation_id)
        if query_type in PERSONAL_QUERY_TYPES:
            return self._tasks_for_person(request, conversation_id)
        return self._result(request, [], source="", sources=[], outcome=OUTCOME_EMPTY)

    def _list_topics(self, request: QueryRequest, conversation_id: str) -> QueryResult:
        rows = _owned(self.topic_store.list_topics(conversation_id), conversation_id)
        items = [_pick(row, TOPIC_KEYS) for row in rows]
        return self._result(request, items, SOURCE_TOPIC, [SOURCE_TOPIC])

    def _list_tasks(self, request: QueryRequest, conversation_id: str) -> QueryResult:
        rows = _owned(self.task_store.list_tasks(conversation_id), conversation_id)
        items = [_pick(row, TASK_KEYS) for row in rows]
        return self._result(request, items, SOURCE_TASK, [SOURCE_TASK])

    def _list_decisions(self, request: QueryRequest, conversation_id: str) -> QueryResult:
        rows = _owned(self.decision_store.list_decisions(conversation_id), conversation_id)
        visible = _effective_decisions(rows)
        items = [_pick(row, DECISION_KEYS) for row in visible]
        return self._result(request, items, SOURCE_DECISION, [SOURCE_DECISION])

    def _list_risks(self, request: QueryRequest, conversation_id: str, *, open_only: bool) -> QueryResult:
        rows = _owned(self.risk_store.list_risks(conversation_id), conversation_id)
        if open_only:
            rows = [row for row in rows if str(row.get("status") or "") == "OPEN"]
        items = [_pick(row, RISK_KEYS) for row in rows]
        return self._result(request, items, SOURCE_RISK, [SOURCE_RISK])

    def _topic_summary(self, request: QueryRequest, conversation_id: str) -> QueryResult:
        topics = _owned(self.topic_store.list_topics(conversation_id), conversation_id)
        bound = _bind_topic(topics, request.topic_id, request.topic_title)
        if bound.outcome != OUTCOME_OK:
            return self._result(
                request,
                bound.items,
                SOURCE_TOPIC,
                [SOURCE_TOPIC],
                outcome=bound.outcome,
            )
        topic = bound.topic
        topic_id = str(topic.get("id") or "")
        tasks = [
            _pick(row, TASK_KEYS)
            for row in _owned(self.task_store.list_tasks(conversation_id), conversation_id)
            if str(row.get("topic_id") or "") == topic_id
        ]
        decisions = _owned(self.decision_store.list_decisions(conversation_id), conversation_id)
        topic_decisions = [row for row in decisions if str(row.get("topic_id") or "") == topic_id]
        pointed = _superseded_ids(decisions)
        visible_decisions = [
            _pick(row, DECISION_KEYS)
            for row in topic_decisions
            if str(row.get("id") or "") not in pointed
        ]
        visible_decisions.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        risks = [
            _pick(row, RISK_KEYS)
            for row in _owned(self.risk_store.list_risks(conversation_id), conversation_id)
            if str(row.get("topic_id") or "") == topic_id and str(row.get("status") or "") == "OPEN"
        ]
        item = {
            "topic": _pick(topic, TOPIC_KEYS),
            "tasks": tasks,
            "decisions": visible_decisions,
            "risks": risks,
        }
        return self._result(
            request,
            [item],
            SOURCE_TOPIC,
            [SOURCE_TOPIC, SOURCE_TASK, SOURCE_DECISION, SOURCE_RISK],
            outcome=OUTCOME_OK,
        )

    def _tasks_for_person(self, request: QueryRequest, conversation_id: str) -> QueryResult:
        person_id = str(request.person_id or "").strip()
        if not person_id:
            return self._result(
                request,
                [],
                source="",
                sources=[],
                outcome=OUTCOME_IDENTITY_UNAVAILABLE,
            )
        try:
            from identity_store import STATUS_ACTIVE, STATUS_DISABLED, IdentityStoreError
            from task_identity_link import TaskIdentityLinkError

            person = self._people().get_person(person_id)
            if person is None:
                return self._result(
                    request,
                    [],
                    source="",
                    sources=[],
                    outcome=OUTCOME_IDENTITY_UNAVAILABLE,
                )
            name = str(person.get("canonical_name") or "").strip()
            status = str(person.get("status") or "")
            if status == STATUS_DISABLED:
                return self._result(
                    request,
                    [],
                    source="",
                    sources=[],
                    outcome=OUTCOME_IDENTITY_DISABLED,
                    subject_name=name,
                )
            if status != STATUS_ACTIVE:
                return self._result(
                    request,
                    [],
                    source="",
                    sources=[],
                    outcome=OUTCOME_IDENTITY_UNAVAILABLE,
                    subject_name=name,
                )
            links = self._links().list_for_person(conversation_id, person_id)
            items = []
            for link in links:
                task_id = str(link.get("task_id") or "")
                task = self.task_store.get_task(conversation_id, task_id)
                if not isinstance(task, dict):
                    continue
                if str(task.get("conversation_id") or "") != conversation_id:
                    continue
                items.append(_pick(task, TASK_KEYS))
            return self._result(
                request,
                items,
                SOURCE_TASK,
                [SOURCE_TASK],
                subject_name=name,
            )
        except (IdentityStoreError, TaskIdentityLinkError):
            return self._result(
                request,
                [],
                source="",
                sources=[],
                outcome=OUTCOME_IDENTITY_UNAVAILABLE,
            )

    def _people(self):
        if self.identity_store is None:
            from identity_store import IdentityStore

            self.identity_store = IdentityStore(self._root_dir)
        return self.identity_store

    def _links(self):
        if self.link_store is None:
            from task_identity_link import TaskIdentityLinkStore

            self.link_store = TaskIdentityLinkStore(
                self._root_dir,
                task_store=self.task_store,
                identity_store=self._people(),
            )
        return self.link_store

    def _result(
        self,
        request: QueryRequest,
        items: list,
        source: str,
        sources: list,
        outcome: Optional[str] = None,
        subject_name: str = "",
    ) -> QueryResult:
        total = len(items)
        if outcome is None:
            outcome = OUTCOME_EMPTY if total == 0 else OUTCOME_OK
        return QueryResult(
            query_type=request.query_type,
            conversation_id=str(request.conversation_id or ""),
            items=items,
            total=total,
            source=source,
            sources=list(sources),
            generated_at=utc_now_iso(),
            empty=(total == 0),
            outcome=outcome,
            subject_name=subject_name,
        )


@dataclass
class _Bind:
    outcome: str
    topic: Optional[dict] = None
    items: list = field(default_factory=list)


def _bind_topic(topics: list, topic_id: str, topic_title: str) -> _Bind:
    wanted_id = str(topic_id or "").strip()
    wanted_title = str(topic_title or "").strip()
    if wanted_id:
        for topic in topics:
            if str(topic.get("id") or "") == wanted_id:
                return _Bind(OUTCOME_OK, topic)
        return _Bind(OUTCOME_NOT_FOUND)
    if wanted_title:
        matches = [topic for topic in topics if str(topic.get("title") or "") == wanted_title]
        if len(matches) == 1:
            return _Bind(OUTCOME_OK, matches[0])
        if len(matches) > 1:
            return _Bind(OUTCOME_AMBIGUOUS, items=_topic_stubs(matches))
        if not topics:
            return _Bind(OUTCOME_EMPTY)
        return _Bind(OUTCOME_NOT_FOUND)
    if len(topics) == 1:
        return _Bind(OUTCOME_OK, topics[0])
    if not topics:
        return _Bind(OUTCOME_EMPTY)
    return _Bind(OUTCOME_AMBIGUOUS, items=_topic_stubs(topics))


def _topic_stubs(topics: list) -> list:
    stubs = []
    for topic in topics:
        stub = {}
        if "id" in topic:
            stub["id"] = topic["id"]
        if "title" in topic:
            stub["title"] = topic["title"]
        stubs.append(stub)
    return stubs


def _superseded_ids(decisions: list) -> set:
    pointed = set()
    for item in decisions:
        pointer = item.get("supersedes_decision_id")
        if pointer:
            pointed.add(str(pointer))
    return pointed


def _effective_decisions(decisions: list) -> list:
    pointed = _superseded_ids(decisions)
    visible = [item for item in decisions if str(item.get("id") or "") not in pointed]
    visible.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return visible
