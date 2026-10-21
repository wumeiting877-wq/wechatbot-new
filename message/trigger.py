# -*- coding: utf-8 -*-
"""Trigger Engine：NO_ACTION / UPDATE_ONLY / REPLY。本轮不实现 Topic Engine。"""

from __future__ import annotations

from typing import Optional

from message.identity import InboundMessage, RuntimeIdentity, is_self_message
from message.pipeline import decide_should_process

NO_ACTION = "NO_ACTION"
UPDATE_ONLY = "UPDATE_ONLY"
REPLY = "REPLY"

SYSTEM_TYPES = {"system", "recall"}


def decide_trigger(
    message: InboundMessage,
    *,
    identity: Optional[RuntimeIdentity] = None,
    bot_state: str = "RUNNING",
    self_result: Optional[dict] = None,
    outbound_result: Optional[dict] = None,
    dedupe_result: Optional[dict] = None,
    listen_users=None,
    is_group: bool = False,
    accept_all: bool = False,
    enable_at: bool = True,
    enable_keyword: bool = False,
    keywords=None,
    probability: int = 100,
    keyword_ignore_probability: bool = True,
    rng=None,
) -> dict:
    """先安全拦截，再套用现有私聊/群聊触发规则。"""
    state = (bot_state or "").upper()
    if state in ("STOPPED", "STOPPING", "ERROR", "STARTING"):
        return _verdict(NO_ACTION, "stopped", message, extra={"bot_state": state})

    if outbound_result and outbound_result.get("is_outbound"):
        return _verdict(NO_ACTION, outbound_result.get("reason") or "outbound", message, extra=outbound_result)

    self_result = self_result or is_self_message(message, identity)
    if self_result.get("is_self"):
        return _verdict(NO_ACTION, self_result.get("reason") or "self", message, extra=self_result)

    if (message.raw_type or "").lower() in SYSTEM_TYPES:
        return _verdict(NO_ACTION, "bot_or_system", message)

    if dedupe_result and dedupe_result.get("is_duplicate"):
        return _verdict(NO_ACTION, dedupe_result.get("reason") or "duplicate", message, extra=dedupe_result)

    listen_decision = decide_should_process(
        message.chat_name or message.conversation_id,
        message.sender_name or message.sender_wxid or str(message.sender_id or ""),
        message.content,
        message.raw_type,
        listen_users=listen_users or [],
        is_group=is_group,
        robot_name=(identity.bot_name if identity else ""),
        accept_all=accept_all,
        enable_at=enable_at,
        enable_keyword=enable_keyword,
        keywords=keywords,
        probability=probability,
        keyword_ignore_probability=keyword_ignore_probability,
        rng=rng,
    )
    if not listen_decision.get("should_process"):
        return _verdict(
            NO_ACTION,
            "unauthorized",
            message,
            extra={"listen_reason": listen_decision.get("reason")},
        )

    return _verdict(
        REPLY,
        listen_decision.get("reason") or "existing_trigger_rule",
        message,
        extra={
            "listen_reason": listen_decision.get("reason"),
            "content_for_handler": listen_decision.get("content_for_handler"),
            "at_triggered": listen_decision.get("at_triggered"),
            "keyword_triggered": listen_decision.get("keyword_triggered"),
        },
    )


def _verdict(action: str, reason: str, message: InboundMessage, extra: Optional[dict] = None) -> dict:
    direction = "OUTBOUND" if action == NO_ACTION and reason in (
        "direction_outbound",
        "outbound_platform_message_id",
        "outbound_conversation_content_hash",
        "sender_wxid_equals_bot_wxid",
        "sender_id_equals_bot_wxid",
    ) else (message.direction or "INBOUND")
    if extra and extra.get("is_outbound"):
        direction = "OUTBOUND"
    if extra and extra.get("is_self"):
        identity_flag = "SELF"
    elif extra and extra.get("is_outbound"):
        identity_flag = "SELF"
    else:
        identity_flag = "EXTERNAL"
        if reason in ("direction_outbound", "sender_wxid_equals_bot_wxid", "sender_id_equals_bot_wxid"):
            identity_flag = "SELF"
    duplicate_flag = "DUPLICATE" if extra and extra.get("is_duplicate") else "NEW"
    if reason and str(reason).startswith("duplicate_"):
        duplicate_flag = "DUPLICATE"
    return {
        "action": action,
        "reason": reason,
        "direction": direction,
        "identity": identity_flag,
        "dedupe": duplicate_flag,
        "message": message.as_dict(),
        "extra": extra or {},
    }
