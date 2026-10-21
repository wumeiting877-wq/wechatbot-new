# -*- coding: utf-8 -*-
"""P8-G1 规则意图路由，P8-G2 只在规则未命中且像查询时才落到分类器。

classify_agent_message 本身不调用模型。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LIST_TOPICS = "LIST_TOPICS"
LIST_TASKS = "LIST_TASKS"
LIST_DECISIONS = "LIST_DECISIONS"
LIST_RISKS = "LIST_RISKS"
OPEN_RISKS = "OPEN_RISKS"
TOPIC_SUMMARY = "TOPIC_SUMMARY"

KIND_QUERY = "QUERY"
KIND_COMMAND = "COMMAND"
KIND_OUT_OF_SCOPE = "OUT_OF_SCOPE"
KIND_NOT_QUERY = "NOT_QUERY"

_SITUATION = r"(?:什么情况|怎么样|如何|什么进展)"
_QUOTED_TOPIC = re.compile(
    rf"^主题\s*[「『“\"'](.+?)[」』”\"']\s*(?:现在|目前|当前)?{_SITUATION}$"
)
_THIS_TOPIC = re.compile(
    rf"^(?:这个主题|该主题)\s*(?:现在|目前|当前)?{_SITUATION}$"
)
_NAMED_TOPIC = re.compile(
    rf"^(.+?)这个主题\s*(?:现在|目前|当前)?{_SITUATION}$"
)
_BARE_TOPIC = re.compile(
    rf"^主题\s*(\S+?)\s*(?:现在|目前|当前)?{_SITUATION}$"
)

_TASK_CORES = {
    "现在有哪些任务",
    "目前有哪些任务",
    "当前有哪些任务",
    "有哪些任务",
    "现在有什么任务",
    "目前有什么任务",
    "当前有什么任务",
    "有什么任务",
    "当前任务有哪些",
    "现在任务有哪些",
    "任务有哪些",
    "当前任务有什么",
    "查看任务",
    "查看一下任务",
    "列出任务",
    "列出当前任务",
    "看看任务",
    "看看有哪些任务",
    "看看有什么任务",
}
_OPEN_RISK_CORES = {
    "现在有哪些风险",
    "目前有哪些风险",
    "当前有哪些风险",
    "有哪些风险",
    "现在有什么风险",
    "目前有什么风险",
    "当前有什么风险",
    "有什么风险",
    "当前风险有哪些",
    "风险有哪些",
    "查看风险",
    "查看一下风险",
    "列出风险",
    "看看风险",
    "看看有哪些风险",
    "看看有什么风险",
}
_ALL_RISK_CORES = {
    "全部风险",
    "所有风险",
    "查看全部风险",
    "列出全部风险",
    "查看所有风险",
    "有哪些全部风险",
}
_DECISION_CORES = {
    "有哪些决定",
    "有什么决定",
    "现在有哪些决定",
    "目前有哪些决定",
    "当前有哪些决定",
    "决定有哪些",
    "查看决定",
    "列出决定",
    "确定了什么",
    "刚才确定了什么",
    "现在确定了什么",
    "刚才有哪些决定",
}
_TOPIC_CORES = {
    "现在有哪些主题",
    "目前有哪些主题",
    "当前有哪些主题",
    "有哪些主题",
    "有什么主题",
    "主题有哪些",
    "查看主题",
    "列出主题",
    "看看主题",
    "看看有哪些主题",
}

_LEAD = r"(?:帮我|请|麻烦)?"
_COMMAND_PATTERNS = (
    re.compile(_LEAD + r"(?:创建|新建|新增|添加)(?:一[个条])?(?:任务|风险|决定|主题)"),
    re.compile(_LEAD + r"把(?:这个|该|这条)?任务(?:改成|改为|标记为|设为)完成"),
    re.compile(_LEAD + r"完成(?:这个|该|这条)?任务"),
    re.compile(_LEAD + r"把(?:这个|该|这条)?风险(?:关掉|关闭)"),
    re.compile(_LEAD + r"关闭(?:这个|该|这条)?风险"),
    re.compile(_LEAD + r"(?:修改|更改)(?:这个|该|这条)?决定"),
    re.compile(_LEAD + r"把(?:这个|该|这条)?决定(?:修改|更改|改掉)"),
    re.compile(_LEAD + r"指派负责人"),
    re.compile(_LEAD + r"给[\u4e00-\u9fffA-Za-z0-9]{1,12}分配任务"),
    re.compile(_LEAD + r"分配任务"),
    re.compile(_LEAD + r"(?:删除|删掉)(?:一[个条])?(?:这个|该|这条)?(?:任务|风险|决定|主题)"),
)

_IDENTITY_PATTERNS = (
    re.compile(r"我(?:现在|目前|当前)?有(?:什么|哪些)任务"),
    re.compile(r"我的任务"),
    re.compile(r"我负责"),
    re.compile(r"谁负责"),
    re.compile(r"(?:^|(?<=[^\u4e00-\u9fff]))(?!现在|目前|当前|查看)[\u4e00-\u9fff]{2,8}负责"),
    re.compile(
        r"(?:^|(?<=[^\u4e00-\u9fff]))(?!现在|目前|当前|查看)[\u4e00-\u9fff]{2,8}(?:有什么任务|有哪些任务|的任务)"
    ),
)

_CROSS_MARKERS = (
    "另一个群",
    "其他群",
    "其它群",
    "别的群",
    "另外一个群",
    "另一个会话",
    "其他会话",
    "其它会话",
    "别的会话",
    "另一个项目",
    "其他项目",
    "别的项目",
)
_CROSS_QUERY = re.compile(r"(有哪些|有什么|查看|看看|查询|帮我查|什么情况|的任务|的风险|的决定|的主题)")
_PROJECT_LETTER = re.compile(r"项目[A-Za-z]")

_POLITE_PREFIXES = ("请问", "问一下", "帮我看看", "帮我看一下", "看看", "帮我", "请", "麻烦")


@dataclass
class RouteDecision:
    kind: str
    query_type: str = ""
    topic_title: str = ""
    topic_id: str = ""


def classify_unmatched_as_not_query(_text: str) -> str:
    """规则未覆盖时的空分类位。P8-G1 不调用模型，固定回到普通聊天。"""
    return KIND_NOT_QUERY


def classify_agent_message(text: str) -> RouteDecision:
    raw = str(text or "").strip()
    if not raw:
        return RouteDecision(KIND_NOT_QUERY)
    if raw.startswith("/"):
        return RouteDecision(KIND_NOT_QUERY)

    normalized = _strip_tail_punct(raw)
    compact = _compact(normalized)
    if _is_cross_conversation_query(compact):
        return RouteDecision(KIND_OUT_OF_SCOPE)
    if _is_identity_deferred(compact):
        return RouteDecision(KIND_NOT_QUERY)
    if _is_command(compact):
        return RouteDecision(KIND_COMMAND)

    polite = _strip_polite(normalized)
    topic = _match_topic_summary(polite)
    if topic is not None:
        return topic
    polite_compact = _compact(polite)
    if _hit_core(polite_compact, _TASK_CORES) or _hit_core(compact, _TASK_CORES):
        return RouteDecision(KIND_QUERY, LIST_TASKS)
    if _hit_core(polite_compact, _ALL_RISK_CORES) or _hit_core(compact, _ALL_RISK_CORES):
        return RouteDecision(KIND_QUERY, LIST_RISKS)
    if _hit_core(polite_compact, _OPEN_RISK_CORES) or _hit_core(compact, _OPEN_RISK_CORES):
        return RouteDecision(KIND_QUERY, OPEN_RISKS)
    if _hit_core(polite_compact, _DECISION_CORES) or _hit_core(compact, _DECISION_CORES):
        return RouteDecision(KIND_QUERY, LIST_DECISIONS)
    if _hit_core(polite_compact, _TOPIC_CORES) or _hit_core(compact, _TOPIC_CORES):
        return RouteDecision(KIND_QUERY, LIST_TOPICS)
    return RouteDecision(classify_unmatched_as_not_query(raw))


def _strip_tail_punct(text: str) -> str:
    return re.sub(r"[？?。！!，,\s]+$", "", text).strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _strip_polite(text: str) -> str:
    value = text.strip()
    for prefix in _POLITE_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix):
            return value[len(prefix):].strip()
    return value


def _hit_core(compact: str, cores: set) -> bool:
    body = compact
    for suffix in ("吗", "呢", "呀", "啊"):
        if body.endswith(suffix) and len(body) > 1:
            body = body[:-1]
    return body in cores


def _is_identity_deferred(compact: str) -> bool:
    return any(pattern.search(compact) for pattern in _IDENTITY_PATTERNS)


def _is_cross_conversation_query(compact: str) -> bool:
    marked = any(marker in compact for marker in _CROSS_MARKERS) or bool(_PROJECT_LETTER.search(compact))
    if not marked:
        return False
    return bool(_CROSS_QUERY.search(compact))


def _is_command(compact: str) -> bool:
    body = compact
    for suffix in ("吧", "一下", "呀", "啊"):
        if body.endswith(suffix) and len(body) > len(suffix):
            body = body[: -len(suffix)]
    return any(pattern.fullmatch(body) for pattern in _COMMAND_PATTERNS)


def _match_topic_summary(text: str) -> RouteDecision | None:
    body = _strip_tail_punct(text)
    for suffix in ("吗", "呢", "呀", "啊"):
        if body.endswith(suffix) and len(body) > 1:
            body = body[:-1]
    quoted = _QUOTED_TOPIC.match(body)
    if quoted:
        return RouteDecision(KIND_QUERY, TOPIC_SUMMARY, topic_title=quoted.group(1).strip())
    if _THIS_TOPIC.match(body):
        return RouteDecision(KIND_QUERY, TOPIC_SUMMARY)
    named = _NAMED_TOPIC.match(body)
    if named:
        title = named.group(1).strip()
        if title:
            return RouteDecision(KIND_QUERY, TOPIC_SUMMARY, topic_title=title)
        return RouteDecision(KIND_QUERY, TOPIC_SUMMARY)
    bare = _BARE_TOPIC.match(body)
    if bare:
        title = bare.group(1).strip()
        if title and title not in ("现在", "目前", "当前"):
            return RouteDecision(KIND_QUERY, TOPIC_SUMMARY, topic_title=title)
    return None


ROUTE_QUERY = "QUERY"
ROUTE_COMMAND = "COMMAND"
ROUTE_OUT_OF_SCOPE = "OUT_OF_SCOPE"
ROUTE_NOT_QUERY = "NOT_QUERY"
ROUTE_UNSUPPORTED_IDENTITY = "UNSUPPORTED_IDENTITY"
ROUTE_CLASSIFIER_FAILURE = "CLASSIFIER_FAILURE"

_OBJECT_WORDS = (
    "待办",
    "任务",
    "风险",
    "问题",
    "决策",
    "决定",
    "结论",
    "主题",
    "话题",
    "事情",
)
_STRONG_CUES = (
    "哪些",
    "哪几",
    "哪个",
    "多少",
    "有啥",
    "怎么样",
    "是什么",
    "看看",
    "看一下",
    "查看",
    "盘一下",
    "盘一盘",
    "梳理一下",
)
_SELF_TASK_QUERY = re.compile(
    r"(?:我(?:现在|目前|当前)?有(?:什么|哪些|啥)任务|我的任务)[吗呢呀啊]?"
)
_ASSIGNEE_TASK_QUERY = re.compile(
    r"(?!现在|目前|当前|查看|看看|帮我|请问|哪些|什么|有啥|任务|风险|决定|主题|这个|那个)"
    r"(?P<name>[\u4e00-\u9fff]{2,8})"
    r"(?:负责(?:什么|哪些|啥)|有(?:什么|哪些|啥)任务|的任务)"
    r"[吗呢呀啊]?"
)


@dataclass
class RouteResult:
    route: str
    query_type: str = ""
    classifier_used: bool = False
    classifier_status: str = ""
    topic_title: str = ""
    topic_id: str = ""
    identity_scope: str = ""
    assignee_query: str = ""


def looks_like_query_candidate(text: str) -> bool:
    """像查询、但还没被确定性规则接住的句子。

    「目前 / 现在 / 情况」单独出现不够。陈述句里常带这些词。
    必须再有明确的询问或盘点用语，并且同时有业务对象词。
    """
    raw = str(text or "").strip()
    if not raw or raw.startswith("/"):
        return False
    compact = _compact(_strip_tail_punct(raw))
    if not compact:
        return False
    if not any(word in compact for word in _OBJECT_WORDS):
        return False
    return _has_strong_query_cue(compact)


def route_hybrid(text: str, classifier=None) -> RouteResult:
    """确定性规则优先。只有规则未命中且 candidate 为真时才调用分类器。"""
    raw = str(text or "").strip()
    if not raw or raw.startswith("/"):
        return RouteResult(ROUTE_NOT_QUERY)
    decision = classify_agent_message(raw)
    if decision.kind == KIND_OUT_OF_SCOPE:
        return RouteResult(ROUTE_OUT_OF_SCOPE)
    identity, assignee_query = _identity_disposition(raw)
    if identity == "self":
        return RouteResult(ROUTE_UNSUPPORTED_IDENTITY, identity_scope="self")
    if identity == "assignee":
        return RouteResult(
            ROUTE_UNSUPPORTED_IDENTITY,
            identity_scope="assignee",
            assignee_query=assignee_query,
        )
    if identity == "block":
        return RouteResult(ROUTE_NOT_QUERY)
    if decision.kind == KIND_COMMAND:
        return RouteResult(ROUTE_COMMAND)
    if decision.kind == KIND_QUERY:
        return RouteResult(
            ROUTE_QUERY,
            query_type=decision.query_type,
            topic_title=decision.topic_title,
            topic_id=decision.topic_id,
        )
    if not looks_like_query_candidate(raw):
        return RouteResult(ROUTE_NOT_QUERY)
    status, query_type = _run_classifier(raw, classifier)
    if status != "OK":
        return RouteResult(
            ROUTE_CLASSIFIER_FAILURE,
            classifier_used=True,
            classifier_status=status,
        )
    if query_type == "NOT_QUERY":
        return RouteResult(
            ROUTE_NOT_QUERY,
            query_type="NOT_QUERY",
            classifier_used=True,
            classifier_status="OK",
        )
    if query_type not in (
        LIST_TOPICS,
        LIST_TASKS,
        LIST_DECISIONS,
        LIST_RISKS,
        OPEN_RISKS,
        TOPIC_SUMMARY,
    ):
        return RouteResult(
            ROUTE_CLASSIFIER_FAILURE,
            classifier_used=True,
            classifier_status="CLASSIFIER_INVALID",
        )
    return RouteResult(
        ROUTE_QUERY,
        query_type=query_type,
        classifier_used=True,
        classifier_status="OK",
    )


def _has_strong_query_cue(compact: str) -> bool:
    if any(token in compact for token in _STRONG_CUES):
        return True
    if "什么" in compact and "没什么" not in compact and "没有什么" not in compact:
        return True
    return False


def _identity_disposition(text: str) -> tuple:
    normalized = _strip_tail_punct(text)
    compact = _compact(normalized)
    polite = _compact(_strip_polite(normalized))
    bodies = [compact]
    if polite and polite not in bodies:
        bodies.append(polite)
    for body in bodies:
        if _SELF_TASK_QUERY.fullmatch(body):
            return "self", ""
        matched = _ASSIGNEE_TASK_QUERY.fullmatch(body)
        if matched:
            return "assignee", matched.group("name")
    if any(_is_identity_deferred(body) for body in bodies):
        return "block", ""
    return "", ""


def _run_classifier(text: str, classifier):
    from query_intent_classifier import STATUS_OK, classify, status_from_exception

    fn = classifier or classify
    try:
        outcome = fn(text)
    except Exception as exc:
        return status_from_exception(exc), ""
    if outcome is None:
        return "CLASSIFIER_INVALID", ""
    status = str(getattr(outcome, "status", "") or "")
    query_type = str(getattr(outcome, "query_type", "") or "")
    if status != STATUS_OK:
        return status or "ERROR", ""
    return STATUS_OK, query_type
