# -*- coding: utf-8 -*-
"""P8-G1 确定性回复。QueryResult → 微信纯文本。不调用模型。"""

from __future__ import annotations

from query_router import (
    LIST_DECISIONS,
    LIST_RISKS,
    LIST_TASKS,
    LIST_TOPICS,
    OPEN_RISKS,
    TOPIC_SUMMARY,
)
from query_service import (
    MY_TASKS,
    OUTCOME_AMBIGUOUS,
    OUTCOME_CONVERSATION_NOT_RESOLVED,
    OUTCOME_EMPTY,
    OUTCOME_IDENTITY_DISABLED,
    OUTCOME_IDENTITY_UNAVAILABLE,
    OUTCOME_NOT_FOUND,
    OUTCOME_OUT_OF_SCOPE,
    TASKS_BY_ASSIGNEE,
)

COMMAND_REPLY = "当前不能在这里修改任务、风险或决定。"
SELF_TASK_QUERY_REPLY = "当前无法确定你的人员身份，因此暂时不能查询“我的任务”。"
ASSIGNEE_TASK_QUERY_REPLY = "当前无法确定人员身份，因此暂时不能查询该人员的任务。"
IDENTITY_AMBIGUOUS_REPLY = "当前人员身份存在冲突，无法安全查询个人任务。"
IDENTITY_DISABLED_REPLY = "当前人员身份已停用，暂不支持按该身份查询任务。"
IDENTITY_UNAVAILABLE_REPLY = "当前人员身份暂时无法确认，因此不能查询个人任务。"
MY_TASKS_EMPTY_REPLY = "当前未查询到你在本会话已确认负责人绑定的任务。"
CLASSIFIER_FAILURE_REPLY = (
    "暂时无法识别这条查询。\n"
    "你可以直接问：\n"
    "“现在有哪些任务？”\n"
    "“目前有哪些风险？”\n"
    "“有哪些决定？”\n"
    "“有哪些主题？”"
)
OUT_OF_SCOPE_REPLY = "当前只能查询本会话已记录的内容。"
CONVERSATION_NOT_RESOLVED_REPLY = "当前会话尚未绑定，无法查询已记录内容。"
NOT_FOUND_REPLY = "当前未查询到该主题。"

_EMPTY_LINES = {
    LIST_TASKS: "当前未查询到已记录的任务。",
    LIST_DECISIONS: "当前未查询到已记录的决定。",
    LIST_RISKS: "当前未查询到已记录的风险。",
    OPEN_RISKS: "当前未查询到已记录的风险。",
    LIST_TOPICS: "当前未查询到已记录的主题。",
    TOPIC_SUMMARY: "当前未查询到已记录的主题。",
}


def format_query_result(result) -> str:
    outcome = getattr(result, "outcome", "")
    if outcome == OUTCOME_OUT_OF_SCOPE:
        return OUT_OF_SCOPE_REPLY
    if outcome == OUTCOME_CONVERSATION_NOT_RESOLVED:
        return CONVERSATION_NOT_RESOLVED_REPLY
    if outcome == OUTCOME_NOT_FOUND:
        return NOT_FOUND_REPLY
    if outcome == OUTCOME_AMBIGUOUS:
        return _format_ambiguous(result.items)
    if outcome == OUTCOME_IDENTITY_DISABLED:
        return IDENTITY_DISABLED_REPLY
    if outcome == OUTCOME_IDENTITY_UNAVAILABLE:
        return IDENTITY_UNAVAILABLE_REPLY
    if result.query_type in (MY_TASKS, TASKS_BY_ASSIGNEE):
        if outcome == OUTCOME_EMPTY or not result.items:
            return _personal_empty(result)
        return _format_personal_tasks(result)
    if outcome == OUTCOME_EMPTY or not result.items:
        return _EMPTY_LINES.get(result.query_type, "当前未查询到已记录的主题。")
    if result.query_type == LIST_TASKS:
        return _format_tasks(result.items)
    if result.query_type == LIST_DECISIONS:
        return _format_decisions(result.items)
    if result.query_type == OPEN_RISKS:
        return _format_risks(result.items, open_only=True)
    if result.query_type == LIST_RISKS:
        return _format_risks(result.items, open_only=False)
    if result.query_type == LIST_TOPICS:
        return _format_topics(result.items)
    if result.query_type == TOPIC_SUMMARY:
        return _format_topic_summary(result.items[0])
    return _EMPTY_LINES.get(result.query_type, "当前未查询到已记录的主题。")


def _text(value) -> str:
    return str(value or "").strip()


def _format_ambiguous(items: list) -> str:
    lines = ["当前会话有多个主题，请用主题名称再问一次："]
    for index, item in enumerate(items or [], 1):
        title = _text(item.get("title")) or _text(item.get("id")) or "未记录"
        lines.append("%s. %s" % (index, title))
    return "\n".join(lines)


def _personal_empty(result) -> str:
    if result.query_type == MY_TASKS:
        return MY_TASKS_EMPTY_REPLY
    name = _text(getattr(result, "subject_name", "")) or "该人员"
    return "当前未查询到%s在本会话已确认负责人绑定的任务。" % name


def _format_personal_tasks(result) -> str:
    items = result.items or []
    if result.query_type == MY_TASKS:
        header = "当前查询到你在本会话有 %s 个已确认负责人绑定的任务：" % len(items)
    else:
        name = _text(getattr(result, "subject_name", "")) or "该人员"
        header = "当前查询到%s在本会话有 %s 个已确认负责人绑定的任务：" % (name, len(items))
    lines = [header, ""]
    for index, item in enumerate(items, 1):
        lines.append("%s. %s" % (index, _text(item.get("title")) or "未记录"))
        lines.append("状态：%s" % (_text(item.get("status")) or "未记录"))
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_tasks(items: list) -> str:
    lines = ["当前记录到 %s 个任务：" % len(items), ""]
    for index, item in enumerate(items, 1):
        lines.append("%s. %s" % (index, _text(item.get("title")) or "未记录"))
        assignee = _text(item.get("assignee_text")) or "未记录"
        lines.append("负责人：%s" % assignee)
        lines.append("状态：%s" % (_text(item.get("status")) or "未记录"))
        due = _text(item.get("due_text"))
        if due:
            lines.append("时间说明：%s" % due)
        lines.append("")
    return "\n".join(lines).rstrip()


def _decision_headline(item: dict) -> str:
    for key in ("decision_text", "title", "summary"):
        value = _text(item.get(key))
        if value:
            return value
    return "未记录"


def _format_decisions(items: list) -> str:
    lines = ["当前记录到 %s 条决定（按记录时间从新到旧）：" % len(items), ""]
    for index, item in enumerate(items, 1):
        lines.append("%s. %s" % (index, _decision_headline(item)))
        lines.append("状态：%s" % (_text(item.get("status")) or "未记录"))
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_risks(items: list, *, open_only: bool) -> str:
    if open_only:
        header = "当前记录到 %s 条未关闭的风险：" % len(items)
    else:
        header = "当前记录到 %s 条风险：" % len(items)
    lines = [header, ""]
    for index, item in enumerate(items, 1):
        lines.append("%s. %s" % (index, _text(item.get("title")) or "未记录"))
        condition = _text(item.get("condition_text"))
        impact = _text(item.get("impact_text"))
        if condition:
            lines.append("条件：%s" % condition)
        if impact:
            lines.append("影响：%s" % impact)
        lines.append("状态：%s" % (_text(item.get("status")) or "未记录"))
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_topics(items: list) -> str:
    lines = ["当前记录到 %s 个主题：" % len(items), ""]
    for index, item in enumerate(items, 1):
        lines.append("%s. %s" % (index, _text(item.get("title")) or "未记录"))
        lines.append("状态：%s" % (_text(item.get("status")) or "未记录"))
        summary = _text(item.get("summary"))
        if summary:
            lines.append("摘要：%s" % summary[:200])
        if "message_count" in item:
            lines.append("关联消息数：%s" % item.get("message_count"))
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_topic_summary(item: dict) -> str:
    topic = item.get("topic") if isinstance(item.get("topic"), dict) else {}
    tasks = list(item.get("tasks") or [])
    decisions = list(item.get("decisions") or [])
    risks = list(item.get("risks") or [])
    lines = ["主题：%s" % (_text(topic.get("title")) or "未记录")]
    lines.append("状态：%s" % (_text(topic.get("status")) or "未记录"))
    summary = _text(topic.get("summary"))
    if summary:
        lines.append("摘要：%s" % summary[:200])
    if "message_count" in topic:
        lines.append("关联消息数：%s" % topic.get("message_count"))
    lines.append("")
    lines.extend(_section("任务", tasks, _task_block, "当前未查询到已记录的任务。"))
    lines.append("")
    lines.extend(_section("决定", decisions, _decision_block, "当前未查询到已记录的决定。"))
    lines.append("")
    lines.extend(_section("风险", risks, _risk_block, "当前未查询到已记录的风险。"))
    return "\n".join(lines).rstrip()


def _section(label: str, items: list, block, empty_line: str) -> list:
    lines = ["%s（%s）" % (label, len(items))]
    if not items:
        lines.append(empty_line)
        return lines
    for index, item in enumerate(items, 1):
        lines.extend(block(index, item))
    return lines


def _task_block(index: int, item: dict) -> list:
    lines = ["%s. %s" % (index, _text(item.get("title")) or "未记录")]
    lines.append("负责人：%s" % (_text(item.get("assignee_text")) or "未记录"))
    lines.append("状态：%s" % (_text(item.get("status")) or "未记录"))
    due = _text(item.get("due_text"))
    if due:
        lines.append("时间说明：%s" % due)
    return lines


def _decision_block(index: int, item: dict) -> list:
    return [
        "%s. %s" % (index, _decision_headline(item)),
        "状态：%s" % (_text(item.get("status")) or "未记录"),
    ]


def _risk_block(index: int, item: dict) -> list:
    lines = ["%s. %s" % (index, _text(item.get("title")) or "未记录")]
    condition = _text(item.get("condition_text"))
    impact = _text(item.get("impact_text"))
    if condition:
        lines.append("条件：%s" % condition)
    if impact:
        lines.append("影响：%s" % impact)
    lines.append("状态：%s" % (_text(item.get("status")) or "未记录"))
    return lines
