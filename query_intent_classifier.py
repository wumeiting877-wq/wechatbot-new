# -*- coding: utf-8 -*-
"""P8-G2 查询意图分类。只返回枚举，不读 Store，不生成回复。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass

from query_router import (
    LIST_DECISIONS,
    LIST_RISKS,
    LIST_TASKS,
    LIST_TOPICS,
    OPEN_RISKS,
    TOPIC_SUMMARY,
)

NOT_QUERY_TYPE = "NOT_QUERY"
STATUS_OK = "OK"
STATUS_INVALID = "CLASSIFIER_INVALID"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_CONNECTION = "CONNECTION_ERROR"
STATUS_ERROR = "ERROR"

QUERY_ENUMS = frozenset({
    LIST_TOPICS,
    LIST_TASKS,
    LIST_DECISIONS,
    LIST_RISKS,
    OPEN_RISKS,
    TOPIC_SUMMARY,
})
ALLOWED = QUERY_ENUMS | {NOT_QUERY_TYPE}

CLASSIFIER_TIMEOUT_SEC = 8
CLASSIFIER_MAX_TOKENS = 128

SYSTEM_PROMPT = """你只判断查询类型。
判断这句话是否在查询已经存在的协同信息。不要判断它是否应该创建新的业务实体。

只输出一个 JSON 对象。不要 Markdown。不要解释。不要回答用户。
{"query_type":"<枚举>"}

query_type 只能是：
LIST_TOPICS
LIST_TASKS
LIST_DECISIONS
LIST_RISKS
OPEN_RISKS
TOPIC_SUMMARY
NOT_QUERY

LIST_TASKS：在问当前有哪些任务或待办。
OPEN_RISKS：在问当前风险、问题或风险点，且没有要求全部。
LIST_RISKS：明确要全部风险或所有风险。
LIST_DECISIONS：在问已经定下来的决定、决策或结论。
LIST_TOPICS：在问当前有哪些主题，或群里在推进哪些事情。
TOPIC_SUMMARY：在问当前主题或某个主题的整体情况、进展。
NOT_QUERY：陈述、安排、寒暄、写操作，或不是在查询已有记录。

不得回答用户问题。
不得生成任务、风险、决定或主题内容。
不得修改任何数据。
不得输出 topic_title、filters、assignee、SQL 或 conversation_id。
"""

_completer = None


class _CallCounter:
    def __init__(self):
        self.calls = 0


CALLS = _CallCounter()


class ClassifierInvalid(Exception):
    pass


@dataclass
class ClassifierOutcome:
    query_type: str = ""
    status: str = STATUS_OK


@contextmanager
def use_completer(fn):
    global _completer
    previous = _completer
    _completer = fn
    try:
        yield
    finally:
        _completer = previous


def reset_completer():
    global _completer
    _completer = None


def classify(text: str) -> ClassifierOutcome:
    CALLS.calls += 1
    completer = _completer or _live_complete
    try:
        raw = completer(_messages(text))
    except Exception as exc:
        return ClassifierOutcome(status=status_from_exception(exc))
    try:
        query_type = parse_query_type(raw)
    except ClassifierInvalid:
        return ClassifierOutcome(status=STATUS_INVALID)
    return ClassifierOutcome(query_type=query_type, status=STATUS_OK)


def parse_query_type(raw) -> str:
    if not isinstance(raw, str):
        raise ClassifierInvalid("empty")
    text = raw.strip()
    if not text or "```" in text:
        raise ClassifierInvalid("not-json")
    if not text.startswith("{") or not text.endswith("}"):
        raise ClassifierInvalid("not-json")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ClassifierInvalid("json") from exc
    if not isinstance(data, dict):
        raise ClassifierInvalid("type")
    query_type = data.get("query_type")
    if not isinstance(query_type, str) or query_type not in ALLOWED:
        raise ClassifierInvalid("enum")
    return query_type


def status_from_exception(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return STATUS_TIMEOUT
    code = str(getattr(exc, "code", "") or "")
    text = str(exc).lower()
    if code == "TIMEOUT" or "timeout" in text or "timed out" in text:
        return STATUS_TIMEOUT
    if (
        isinstance(exc, ConnectionError)
        or code in ("NETWORK_ERROR", "AUTH_ERROR", "SERVICE_ERROR", "UNTRUSTED_PROVIDER")
        or "connection" in text
    ):
        return STATUS_CONNECTION
    return STATUS_ERROR


def _messages(text: str) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": str(text or "")},
    ]


def _live_complete(messages):
    from llm_client import call_narrow_completion

    return call_narrow_completion(
        messages,
        timeout=CLASSIFIER_TIMEOUT_SEC,
        max_tokens=CLASSIFIER_MAX_TOKENS,
        temperature=0,
        purpose="query_intent",
    )
