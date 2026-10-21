# -*- coding: utf-8 -*-
"""P8-G1 协作查询接入。P8-G2 的分类器只在规则未命中的查询候选上运行，并且跑在会话锁之前。

已识别的 Query、Command、跨会话、身份查询和分类失败在这里结束：
不入主题旁路，不进 Chat，不写 Store。
会话忙时只挂起已完成路由的 AgentReplyPlan，发送前才读 Store。
"""

from __future__ import annotations

import logging
import os

from decision_store import DecisionStore
from group_rules import detect_group_at
from message.trigger import REPLY
from agent_reply_delivery import KIND_FIXED, AgentReplyPlan, offer_agent_reply
from identity_resolver import AMBIGUOUS, NOT_FOUND, RESOLVED, resolve_exact_alias, resolve_wxid
from identity_store import IdentityStore, IdentityStoreError
from query_formatter import (
    ASSIGNEE_TASK_QUERY_REPLY,
    CLASSIFIER_FAILURE_REPLY,
    COMMAND_REPLY,
    IDENTITY_AMBIGUOUS_REPLY,
    IDENTITY_UNAVAILABLE_REPLY,
    OUT_OF_SCOPE_REPLY,
    SELF_TASK_QUERY_REPLY,
    format_query_result,
)
from query_router import (
    KIND_COMMAND,
    KIND_OUT_OF_SCOPE,
    KIND_QUERY,
    ROUTE_CLASSIFIER_FAILURE,
    ROUTE_NOT_QUERY,
    ROUTE_UNSUPPORTED_IDENTITY,
    RouteDecision,
    classify_agent_message,
    route_hybrid,
)
from query_service import MY_TASKS, TASKS_BY_ASSIGNEE, QueryRequest, QueryService
from risk_store import RiskStore
from task_store import TaskStore
from topic_engine import resolve_topic_conversation
from topic_store import TopicStore

logger = logging.getLogger(__name__)


def handle_collaboration_route(inbound, verdict, *, runtime, host, chat_id: str) -> bool:
    """识别为 Query、Command 或跨会话时返回 True。调用方必须就此返回。"""
    if not isinstance(verdict, dict) or verdict.get("action") != REPLY:
        return False
    try:
        text = extract_route_text(inbound, verdict, _bot_name(runtime))
        result = route_hybrid(text)
    except Exception:
        logger.exception("协作查询识别失败，回退原回复流程")
        return False
    if result.route == ROUTE_NOT_QUERY:
        return False
    try:
        if result.route == ROUTE_CLASSIFIER_FAILURE:
            logger.info("查询意图分类失败 status=%s", result.classifier_status)
        plan = _plan_for(result, inbound, host, chat_id)
        if plan is not None:
            _send(host, runtime, chat_id, inbound, plan)
    except Exception:
        logger.exception("协作查询已识别，但回复失败")
    return True


def extract_route_text(inbound, verdict, bot_name: str) -> str:
    extra = verdict.get("extra") if isinstance(verdict, dict) else {}
    if not isinstance(extra, dict):
        extra = {}
    processed = extra.get("processed_content")
    if isinstance(processed, str) and processed.strip():
        return processed.strip()
    raw = str(getattr(inbound, "content", "") or "")
    if bot_name:
        hit, stripped = detect_group_at(raw, bot_name)
        if hit:
            return str(stripped or "").strip()
    wrapped = extra.get("content_for_handler") or ""
    if isinstance(wrapped, str) and wrapped.startswith("[群聊消息-") and "]:" in wrapped:
        return wrapped.split("]:", 1)[1].strip()
    return raw.strip()


def _decision_from_route(result) -> RouteDecision:
    if result.route == KIND_COMMAND:
        return RouteDecision(KIND_COMMAND)
    if result.route == KIND_OUT_OF_SCOPE:
        return RouteDecision(KIND_OUT_OF_SCOPE)
    return RouteDecision(
        KIND_QUERY,
        result.query_type,
        result.topic_title,
        result.topic_id,
    )


def build_query_service(root_dir: str) -> QueryService:
    topic_store = TopicStore(root_dir)
    return QueryService(
        topic_store=topic_store,
        task_store=TaskStore(root_dir, topic_store=topic_store),
        decision_store=DecisionStore(root_dir, topic_store=topic_store),
        risk_store=RiskStore(root_dir, topic_store=topic_store),
    )


def _plan_for(result, inbound, host, chat_id: str) -> AgentReplyPlan | None:
    message_id, sender_id = _message_identity(inbound)
    if result.route == ROUTE_UNSUPPORTED_IDENTITY:
        return _identity_plan(result, inbound, host, chat_id, message_id, sender_id)
    if result.route == ROUTE_CLASSIFIER_FAILURE:
        return _fixed_plan(chat_id, message_id, sender_id, CLASSIFIER_FAILURE_REPLY)
    decision = _decision_from_route(result)
    if decision.kind == KIND_COMMAND:
        return _fixed_plan(chat_id, message_id, sender_id, COMMAND_REPLY)
    if decision.kind == KIND_OUT_OF_SCOPE:
        return _fixed_plan(chat_id, message_id, sender_id, OUT_OF_SCOPE_REPLY)
    if decision.kind != KIND_QUERY:
        return None
    return AgentReplyPlan(
        kind=KIND_QUERY,
        chat_id=chat_id,
        conversation_id=_conversation_id(host, inbound),
        message_id=message_id,
        sender_id=sender_id,
        query_type=decision.query_type or "",
        topic_id=str(getattr(decision, "topic_id", "") or ""),
        topic_title=str(getattr(decision, "topic_title", "") or ""),
    )


def _identity_plan(result, inbound, host, chat_id: str, message_id: str, sender_id: str) -> AgentReplyPlan:
    """身份在入站时解析一次。解析不到就固定拒绝，不读任务列表。"""
    scope = str(getattr(result, "identity_scope", "") or "")
    try:
        store = IdentityStore(_root_dir(host))
        if scope == "self":
            wxid = str(getattr(inbound, "sender_wxid", "") or "").strip()
            if not wxid:
                return _fixed_plan(chat_id, message_id, sender_id, SELF_TASK_QUERY_REPLY)
            resolution = resolve_wxid(store, wxid)
            query_type = MY_TASKS
            unknown = SELF_TASK_QUERY_REPLY
        else:
            resolution = resolve_exact_alias(store, getattr(result, "assignee_query", "") or "")
            query_type = TASKS_BY_ASSIGNEE
            unknown = ASSIGNEE_TASK_QUERY_REPLY
    except IdentityStoreError:
        return _fixed_plan(chat_id, message_id, sender_id, IDENTITY_UNAVAILABLE_REPLY)
    if resolution.status == AMBIGUOUS:
        return _fixed_plan(chat_id, message_id, sender_id, IDENTITY_AMBIGUOUS_REPLY)
    if resolution.status != RESOLVED or not resolution.person_id or resolution.person is None:
        if resolution.status == NOT_FOUND or resolution.person is None or not resolution.person_id:
            return _fixed_plan(chat_id, message_id, sender_id, unknown)
        return _fixed_plan(chat_id, message_id, sender_id, IDENTITY_UNAVAILABLE_REPLY)
    return AgentReplyPlan(
        kind=KIND_QUERY,
        chat_id=chat_id,
        conversation_id=_conversation_id(host, inbound),
        message_id=message_id,
        sender_id=sender_id,
        query_type=query_type,
        person_id=resolution.person_id,
    )


def _fixed_plan(chat_id: str, message_id: str, sender_id: str, text: str) -> AgentReplyPlan:
    return AgentReplyPlan(
        kind=KIND_FIXED,
        chat_id=chat_id,
        conversation_id="",
        message_id=message_id,
        sender_id=sender_id,
        fixed_text=text,
    )


def _message_identity(inbound) -> tuple[str, str]:
    sender_id = getattr(inbound, "sender_id", "")
    message_id = str(getattr(inbound, "message_id", "") or getattr(inbound, "platform_message_id", "") or "")
    return message_id, "" if sender_id is None else str(sender_id)


def _conversation_id(host, inbound) -> str:
    conversations = list(getattr(host, "conversations", None) or [])
    conversation = resolve_topic_conversation(inbound, conversations)
    if isinstance(conversation, dict):
        return str(conversation.get("id") or "").strip()
    return ""


def _materialize(host, plan: AgentReplyPlan) -> str:
    if plan.kind == KIND_FIXED:
        return plan.fixed_text or ""
    service = build_query_service(_root_dir(host))
    request = QueryRequest(
        conversation_id=plan.conversation_id,
        message_id=plan.message_id,
        sender_id=plan.sender_id,
        query_type=plan.query_type or "",
        topic_id=plan.topic_id or "",
        topic_title=plan.topic_title or "",
        person_id=plan.person_id or "",
    )
    if not plan.conversation_id:
        result = service.conversation_not_resolved(request)
    else:
        result = service.execute(request)
    return format_query_result(result)


def _transmit(host, chat_id: str, inbound, text: str) -> None:
    if not text:
        return
    sender = getattr(host, "send_reply", None)
    if not callable(sender):
        from bot import send_reply as sender
    sender_name = str(getattr(inbound, "sender_name", "") or chat_id)
    original = str(getattr(inbound, "content", "") or "")
    sender(chat_id, sender_name, chat_id, original, text, is_system_message=True)


def _send(host, runtime, chat_id: str, inbound, plan: AgentReplyPlan) -> None:
    offer_agent_reply(
        runtime,
        plan,
        materialize=lambda: _materialize(host, plan),
        transmit=lambda text: _transmit(host, chat_id, inbound, text),
    )


def _bot_name(runtime) -> str:
    identity = getattr(runtime, "identity", None)
    return str(getattr(identity, "bot_name", "") or "")


def _root_dir(host) -> str:
    root = str(getattr(host, "root_dir", "") or "").strip()
    if root:
        return root
    return os.path.dirname(os.path.abspath(__file__))
