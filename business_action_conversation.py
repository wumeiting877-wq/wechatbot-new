# -*- coding: utf-8 -*-
"""微信上的任务完成对话。命令只准备，确认才执行。

第一条明确完成命令只调用 BusinessActionService.prepare_action。
只有去掉首尾空白后恰好等于「确认完成」才调用 confirm_action。
生命周期仍封装在 confirm_action 里面。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from agent_reply_delivery import KIND_FIXED, AgentReplyPlan, offer_agent_reply
from business_action import (
    ACTION_COMPLETE_TASK,
    ACTION_NOT_APPLICABLE,
    ACTION_TARGET_AMBIGUOUS,
    ACTION_TARGET_NOT_FOUND,
    CORRUPT,
    EXECUTED,
    FAILED,
    NO_ACTION_NEEDED,
    NOT_AUTHORIZED,
    PREPARED,
    RECORD_PERSIST_FAILED,
    SUCCEEDED_NOOP,
    UNSUPPORTED_REFERENCE,
    ActionRequest,
    BusinessActionService,
)
from business_action_authorizer import (
    ACTOR_DISABLED,
    ACTOR_IDENTITY_AMBIGUOUS,
    ACTOR_IDENTITY_NOT_FOUND,
    TASK_ASSIGNMENT_NOT_FOUND,
)
from business_action_store import BusinessActionStore, BusinessActionStoreError
from collaboration_query import extract_route_text
from message.trigger import REPLY
from task_command_parser import COMMAND, SELECTOR_EXACT_TITLE, UNSUPPORTED, parse_task_command
from task_target_resolver import TaskTargetSelector

logger = logging.getLogger(__name__)

PENDING_CONFIRMATION_TTL_SECONDS = 180
CONFIRM_TEXT = "确认完成"

ACTOR_REQUIRED_REPLY = "当前无法确定你的账号身份，因此不能执行任务修改操作。"
CONVERSATION_REQUIRED_REPLY = "当前无法确定会话范围，因此不能执行该操作。"
NO_PENDING_REPLY = "当前没有待确认的任务完成操作。"
AMBIGUOUS_PENDING_REPLY = "当前存在多个待确认的任务操作，暂时无法确定要确认哪一个。\n请重新明确任务标题发起操作。"
EXISTING_PENDING_REPLY = "你当前还有一项任务完成操作等待确认。\n请先回复\u201c确认完成\u201d，或等待该确认失效后再发起新的操作。"
EXPIRED_REPLY = "该任务操作的确认已超时，请重新发起。"
REFERENCE_REPLY = "当前暂不支持\u201c这个任务\u201d这类指代。\n请明确任务标题，例如：\n\u201c把接口联调这个任务标记为完成\u201d"
STALE_REPLY = "任务状态已经发生变化，本次没有执行完成操作。\n请重新查询任务状态后再操作。"
WRITE_FAILED_REPLY = "本次任务完成操作未能安全写入，请稍后重新发起。"
TASK_MISSING_REPLY = "目标任务当前已不存在，本次操作未执行。"
PERSIST_REPLY = "任务状态可能已经更新，但操作记录暂未成功收口。\n请先查询任务状态，确认后再决定是否重新操作。"
UNSAFE_READ_REPLY = "当前无法安全读取任务数据，本次没有执行。"
NOT_APPLICABLE_REPLY = "该任务当前状态不能直接标记为完成。\n请重新查询任务状态后再操作。"
IDENTITY_NOT_FOUND_REPLY = "当前无法确定你的人员身份，因此不能执行任务修改操作。"
ACTOR_DISABLED_REPLY = "当前人员身份已停用，不能执行任务修改操作。"
TASK_ASSIGNMENT_NOT_FOUND_REPLY = "当前任务尚未建立可确认的负责人身份绑定，因此不能执行完成操作。"
NOT_AUTHORIZED_REPLY = "当前无法确认你具有该任务的完成权限。"


def handle_business_action_conversation(inbound, conversation, runtime, reply_sender, verdict=None, chat_id: str = "") -> bool:
    """显式完成命令或「确认完成」时返回 True。其它文本继续原路径。"""
    if verdict is None:
        verdict = {"action": REPLY}
    if not isinstance(verdict, dict) or verdict.get("action") != REPLY:
        return False
    text = _route_text(inbound, verdict, runtime)
    if not text or text.startswith("/"):
        return False
    if text.strip() == CONFIRM_TEXT:
        return _handle_confirmation(inbound, conversation, runtime, reply_sender, chat_id)
    intent = parse_task_command(text)
    if intent.status == UNSUPPORTED:
        if not _accepts(runtime):
            return True
        _deliver(runtime, reply_sender, inbound, chat_id, _conversation_key(conversation), REFERENCE_REPLY)
        return True
    if intent.status != COMMAND or intent.action_type != ACTION_COMPLETE_TASK:
        return False
    if intent.selector_type != SELECTOR_EXACT_TITLE or not intent.title:
        if not _accepts(runtime):
            return True
        _deliver(runtime, reply_sender, inbound, chat_id, _conversation_key(conversation), REFERENCE_REPLY)
        return True
    logger.info(
        "TASK_COMMAND_PARSED action_type=%s selector_type=%s",
        intent.action_type,
        intent.selector_type,
    )
    if not _accepts(runtime):
        return True
    return _handle_command(inbound, conversation, runtime, reply_sender, chat_id, intent)


def _handle_command(inbound, conversation, runtime, reply_sender, chat_id: str, intent) -> bool:
    actor = _actor_ref(inbound)
    if actor == "":
        _deliver(runtime, reply_sender, inbound, chat_id, "", ACTOR_REQUIRED_REPLY)
        return True
    conversation_id = _conversation_key(conversation)
    if conversation_id == "":
        _deliver(runtime, reply_sender, inbound, chat_id, "", CONVERSATION_REQUIRED_REPLY)
        return True
    message_id = _message_id(inbound)
    if message_id == "":
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, UNSAFE_READ_REPLY)
        return True
    root = _root_dir(reply_sender)
    store = BusinessActionStore(root)
    try:
        fresh, _expired = _split_pending(store.find_prepared_actions(conversation_id, actor, ACTION_COMPLETE_TASK))
    except BusinessActionStoreError:
        logger.exception("读取待确认任务操作失败")
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, UNSAFE_READ_REPLY)
        return True
    if fresh:
        reply = EXISTING_PENDING_REPLY if len(fresh) == 1 else AMBIGUOUS_PENDING_REPLY
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, reply)
        return True
    service = BusinessActionService(root, action_store=store)
    request = ActionRequest(
        ACTION_COMPLETE_TASK,
        conversation_id,
        message_id,
        actor,
        TaskTargetSelector(SELECTOR_EXACT_TITLE, title=intent.title),
    )
    try:
        result = service.prepare_action(request)
    except Exception:
        logger.exception("准备任务完成操作失败")
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, UNSAFE_READ_REPLY)
        return True
    _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, _prepare_reply(result, intent.title))
    if result.status == PREPARED:
        logger.info("TASK_ACTION_PREVIEW_SENT action_id=%s", result.action_id)
    return True


def _handle_confirmation(inbound, conversation, runtime, reply_sender, chat_id: str) -> bool:
    if not _accepts(runtime):
        return True
    actor = _actor_ref(inbound)
    if actor == "":
        _deliver(runtime, reply_sender, inbound, chat_id, "", ACTOR_REQUIRED_REPLY)
        return True
    conversation_id = _conversation_key(conversation)
    if conversation_id == "":
        _deliver(runtime, reply_sender, inbound, chat_id, "", CONVERSATION_REQUIRED_REPLY)
        return True
    logger.info("TASK_CONFIRMATION_RECEIVED conversation_id=%s", conversation_id)
    root = _root_dir(reply_sender)
    store = BusinessActionStore(root)
    try:
        fresh, expired = _split_pending(store.find_prepared_actions(conversation_id, actor, ACTION_COMPLETE_TASK))
    except BusinessActionStoreError:
        logger.exception("读取待确认任务操作失败")
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, UNSAFE_READ_REPLY)
        return True
    if len(fresh) > 1:
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, AMBIGUOUS_PENDING_REPLY)
        return True
    if len(fresh) == 1:
        if not _accepts(runtime):
            return True
        service = BusinessActionService(root, action_store=store)
        try:
            result = service.confirm_action(fresh[0].get("action_id") or "", actor)
        except Exception:
            logger.exception("确认任务完成操作失败")
            _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, WRITE_FAILED_REPLY)
            return True
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, _confirm_reply(result))
        return True
    if expired:
        _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, EXPIRED_REPLY)
        return True
    _deliver(runtime, reply_sender, inbound, chat_id, conversation_id, NO_PENDING_REPLY)
    return True


def _prepare_reply(result, title: str) -> str:
    if result.status == PREPARED and result.preview is not None:
        return "将执行以下操作：\n\n%s\n\n回复\u201c确认完成\u201d后执行。" % result.preview.text()
    if result.status == NO_ACTION_NEEDED:
        shown = result.target_title or title
        return "该任务已经是完成状态，无需再次操作。\n\n任务：%s\n状态：DONE" % shown
    if result.status == ACTION_TARGET_AMBIGUOUS:
        return _ambiguous_reply(result.candidates)
    if result.status == ACTION_TARGET_NOT_FOUND:
        return "当前会话中未找到标题完全等于\u201c%s\u201d的任务。" % title
    if result.status == UNSUPPORTED_REFERENCE:
        return REFERENCE_REPLY
    if result.status == ACTION_NOT_APPLICABLE:
        return NOT_APPLICABLE_REPLY
    if result.status == NOT_AUTHORIZED:
        return _authorization_reply(result.reason)
    if result.status == CORRUPT:
        return UNSAFE_READ_REPLY
    return UNSAFE_READ_REPLY


def _confirm_reply(result) -> str:
    title = result.target_title or ""
    if result.status == EXECUTED:
        return "任务已完成。\n\n任务：%s\n状态：DONE" % title
    if result.status == SUCCEEDED_NOOP:
        return "该任务已经是完成状态，无需重复操作。\n\n任务：%s\n状态：DONE" % title
    if result.status == RECORD_PERSIST_FAILED:
        return PERSIST_REPLY
    if result.status == NOT_AUTHORIZED:
        return _authorization_reply(result.reason)
    reason = str(result.reason or "")
    if reason == "TASK_NOT_FOUND":
        return TASK_MISSING_REPLY
    if reason == "WRITE_FAILED":
        return WRITE_FAILED_REPLY
    if reason == "STALE_STATE" or result.status == FAILED:
        return STALE_REPLY
    return NO_PENDING_REPLY


def _authorization_reply(reason: str) -> str:
    value = str(reason or "")
    if value in (ACTOR_IDENTITY_NOT_FOUND, ACTOR_IDENTITY_AMBIGUOUS):
        return IDENTITY_NOT_FOUND_REPLY
    if value == ACTOR_DISABLED:
        return ACTOR_DISABLED_REPLY
    if value == TASK_ASSIGNMENT_NOT_FOUND:
        return TASK_ASSIGNMENT_NOT_FOUND_REPLY
    return NOT_AUTHORIZED_REPLY


def _ambiguous_reply(candidates) -> str:
    lines = ["当前找到多个同名任务，无法确定要完成哪一个：", ""]
    index = 0
    for item in list(candidates or []):
        if not isinstance(item, dict):
            continue
        index += 1
        lines.append(
            "%d. %s｜状态：%s｜负责人：%s"
            % (
                index,
                str(item.get("title") or ""),
                str(item.get("status") or ""),
                str(item.get("assignee_text") or ""),
            )
        )
    lines.append("")
    lines.append("当前不会自动选择其中一条。")
    return "\n".join(lines)


def _split_pending(rows):
    now = datetime.now(timezone.utc)
    fresh = []
    expired = []
    for item in list(rows or []):
        if _within_ttl(item.get("created_at"), now):
            fresh.append(item)
        else:
            expired.append(item)
    return fresh, expired


def _within_ttl(created_at, now: datetime) -> bool:
    age = _age_seconds(created_at, now)
    if age is None:
        return False
    return age <= PENDING_CONFIRMATION_TTL_SECONDS


def _age_seconds(created_at, now: datetime):
    text = str(created_at or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        created = datetime.fromisoformat(text)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds()


def _deliver(runtime, host, inbound, chat_id: str, conversation_id: str, text: str) -> None:
    target = chat_id or str(getattr(inbound, "chat_name", "") or "")
    message_id = _message_id(inbound)
    sender_id = getattr(inbound, "sender_id", "")
    plan = AgentReplyPlan(
        kind=KIND_FIXED,
        chat_id=target,
        conversation_id=conversation_id,
        message_id=message_id,
        sender_id="" if sender_id is None else str(sender_id),
        fixed_text=text,
    )
    try:
        offer_agent_reply(
            runtime,
            plan,
            materialize=lambda: text,
            transmit=lambda body: _transmit(host, target, inbound, body),
        )
    except Exception:
        logger.exception("任务操作回复投递失败")


def _transmit(host, chat_id: str, inbound, text: str) -> None:
    if not text:
        return
    sender = getattr(host, "send_reply", None)
    if not callable(sender):
        from bot import send_reply as sender
    sender_name = str(getattr(inbound, "sender_name", "") or chat_id)
    original = str(getattr(inbound, "content", "") or "")
    sender(chat_id, sender_name, chat_id, original, text, is_system_message=True)


def _route_text(inbound, verdict, runtime) -> str:
    identity = getattr(runtime, "identity", None)
    bot_name = str(getattr(identity, "bot_name", "") or "")
    return extract_route_text(inbound, verdict, bot_name)


def _actor_ref(inbound) -> str:
    return str(getattr(inbound, "sender_wxid", "") or "").strip()


def _conversation_key(conversation) -> str:
    if not isinstance(conversation, dict):
        return ""
    return str(conversation.get("id") or "").strip()


def _message_id(inbound) -> str:
    return str(getattr(inbound, "message_id", "") or getattr(inbound, "platform_message_id", "") or "").strip()


def _accepts(runtime) -> bool:
    checker = getattr(runtime, "is_accepting_work", None)
    if not callable(checker):
        return True
    return bool(checker())


def _root_dir(host) -> str:
    root = str(getattr(host, "root_dir", "") or "").strip()
    if root:
        return root
    return os.path.dirname(os.path.abspath(__file__))
