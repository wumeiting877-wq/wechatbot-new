# -*- coding: utf-8 -*-
"""确定性任务命令解析。只识别显式 COMPLETE_TASK 句型。

不读任务库，不解析 task_id，不执行动作，不调用模型，不发送消息。
认不出就不是命令。不要靠模糊匹配补成写操作。
"""

from __future__ import annotations

import re

NOT_COMMAND = "NOT_COMMAND"
UNSUPPORTED = "UNSUPPORTED"
COMMAND = "COMMAND"

ACTION_COMPLETE_TASK = "COMPLETE_TASK"
SELECTOR_EXACT_TITLE = "EXACT_TITLE"

_MARK = re.compile(r"^(?:请把|帮我把|把)(?P<title>.+?)这个任务标记为完成$")
_COLON = re.compile(r"^(?:请)?完成任务：(?P<title>.+)$")
_QUOTE_PAIRS = (
    ("\u300c", "\u300d"),
    ("\u201c", "\u201d"),
)
_UNSUPPORTED = (
    re.compile(r"^(?:请|帮我)?把(?:这个|该|这条)任务标记为完成$"),
    re.compile(r"^(?:请|帮我)?完成(?:这个|该|这条)任务$"),
    re.compile(r"^(?:请|帮我)?把刚才那个任务(?:标记为)?完成$"),
    re.compile(r"^(?:请|帮我)?完成刚才那个任务$"),
    re.compile(r"^(?:请|帮我)?完成第[0-9一二三四五六七八九十]+个任务$"),
    re.compile(r"^(?:请|帮我)?完成任务[0-9]+$"),
    re.compile(r"^(?:请|帮我)?把第[0-9一二三四五六七八九十]+个任务(?:标记为)?完成$"),
)


class TaskCommandIntent:
    def __init__(self, status: str, action_type: str = "", selector_type: str = "", title: str = ""):
        self.status = status
        self.action_type = action_type
        self.selector_type = selector_type
        self.title = title


def parse_task_command(text: str) -> TaskCommandIntent:
    raw = str(text or "").strip()
    if not raw or raw.startswith("/"):
        return TaskCommandIntent(NOT_COMMAND)
    if any(pattern.fullmatch(raw) for pattern in _UNSUPPORTED):
        return TaskCommandIntent(UNSUPPORTED)
    title = _capture_title(raw)
    if title is None:
        return TaskCommandIntent(NOT_COMMAND)
    cleaned = _unwrap_title(title)
    if cleaned == "":
        return TaskCommandIntent(NOT_COMMAND)
    return TaskCommandIntent(COMMAND, ACTION_COMPLETE_TASK, SELECTOR_EXACT_TITLE, cleaned)


def _capture_title(text: str):
    marked = _MARK.fullmatch(text)
    if marked:
        return marked.group("title")
    colon = _COLON.fullmatch(text)
    if colon:
        return colon.group("title")
    return None


def _unwrap_title(raw: str) -> str:
    text = str(raw or "")
    for left, right in _QUOTE_PAIRS:
        if len(text) >= len(left) + len(right) and text.startswith(left) and text.endswith(right):
            text = text[len(left) : -len(right)]
            break
    return text.strip()
