# -*- coding: utf-8 -*-
"""Self 判断：只用稳定身份字段，不用窗口/昵称/鼠标/设备。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ids_equal(left: Any, right: Any) -> bool:
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return False
    return a == b


@dataclass
class RuntimeIdentity:
    bot_wxid: str = ""
    bot_name: str = ""
    login_account: str = ""

    def as_dict(self) -> dict:
        return {
            "bot_wxid": self.bot_wxid,
            "bot_name": self.bot_name,
            "login_account": self.login_account,
        }


@dataclass
class InboundMessage:
    message_id: str = ""
    platform_message_id: str = ""
    sender_id: Any = ""
    sender_name: str = ""
    sender_wxid: str = ""
    receiver_id: str = ""
    receiver_name: str = ""
    conversation_id: str = ""
    chat_name: str = ""
    chat_wxid: str = ""
    direction: str = "INBOUND"
    raw_type: str = "text"
    attr: str = "friend"
    content: str = ""
    create_time: Any = None
    sort_seq: Any = None
    local_id: Any = None
    window_title: str = ""
    source: str = "wechat_db_listener"
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "platform_message_id": self.platform_message_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "sender_wxid": self.sender_wxid,
            "receiver_id": self.receiver_id,
            "receiver_name": self.receiver_name,
            "conversation_id": self.conversation_id,
            "chat_name": self.chat_name,
            "chat_wxid": self.chat_wxid,
            "direction": self.direction,
            "raw_type": self.raw_type,
            "attr": self.attr,
            "content_preview": (self.content or "")[:80],
            "create_time": self.create_time,
            "sort_seq": self.sort_seq,
            "local_id": self.local_id,
            "window_title": self.window_title,
            "source": self.source,
        }


def inbound_from_wx_message(msg, chat, identity: Optional[RuntimeIdentity] = None) -> InboundMessage:
    """从兼容层消息对象抽出身份字段。不根据昵称或窗口改写 sender。"""
    identity = identity or RuntimeIdentity()
    chat_name = _norm(getattr(chat, "who", None) or getattr(chat, "name", None))
    chat_wxid = _norm(getattr(chat, "_wxid", None) or getattr(msg, "chat_wxid", None))
    sender_id = getattr(msg, "sender_id", None)
    if sender_id is None:
        sender_id = getattr(msg, "raw_sender_id", None)
    sender_wxid = _norm(
        getattr(msg, "sender_wxid", None)
        or getattr(msg, "sender_username", None)
    )
    local_id = getattr(msg, "local_id", None)
    create_time = getattr(msg, "create_time", None)
    sort_seq = getattr(msg, "sort_seq", None)
    platform_message_id = _norm(getattr(msg, "platform_message_id", None))
    if not platform_message_id and local_id is not None:
        platform_message_id = f"{chat_wxid or chat_name}:{local_id}"
    raw_type = _norm(getattr(msg, "type", None) or "text") or "text"
    attr = _norm(getattr(msg, "attr", None) or "friend") or "friend"
    content = getattr(msg, "content", None) or ""
    if not isinstance(content, str):
        content = str(content)
    direction = _norm(getattr(msg, "direction", None) or "INBOUND") or "INBOUND"
    sender_name = _norm(getattr(msg, "sender", None))
    if not sender_name:
        sender_name = chat_name
    inbound = InboundMessage(
        platform_message_id=platform_message_id,
        sender_id=sender_id,
        sender_name=sender_name,
        sender_wxid=sender_wxid,
        receiver_id=identity.bot_wxid,
        receiver_name=identity.bot_name,
        conversation_id=chat_wxid or chat_name,
        chat_name=chat_name,
        chat_wxid=chat_wxid,
        direction=direction,
        raw_type=raw_type,
        attr=attr,
        content=content,
        create_time=create_time,
        sort_seq=sort_seq,
        local_id=local_id,
        window_title=chat_name,
        source="wechat_db_listener",
    )
    inbound.message_id = inbound.platform_message_id or f"{inbound.conversation_id}:{inbound.create_time}"
    return inbound


def is_self_message(message, runtime_identity: Optional[RuntimeIdentity] = None) -> dict:
    """稳定身份判断。禁止用窗口、鼠标、设备、昵称文本作为充分条件。

    返回:
        {
            "is_self": bool,
            "reason": str,
            "evidence": dict,
        }
    """
    identity = runtime_identity or RuntimeIdentity()
    if not isinstance(message, InboundMessage):
        message = inbound_from_wx_message(message, getattr(message, "_chat", None) or type("C", (), {"who": "", "_wxid": ""})(), identity)

    sender_wxid = _norm(message.sender_wxid)
    bot_wxid = _norm(identity.bot_wxid)
    sender_id = message.sender_id
    sender_id_text = _norm(sender_id)
    direction = _norm(message.direction).upper() or "INBOUND"

    evidence = {
        "sender_wxid": sender_wxid,
        "bot_wxid": bot_wxid,
        "sender_id": sender_id,
        "direction": direction,
        "platform_message_id": message.platform_message_id,
        "conversation_id": message.conversation_id,
        "chat_name": message.chat_name,
        "raw_type": message.raw_type,
        "attr_hint": message.attr,
        "login_account": identity.login_account,
        "used_nickname": False,
        "used_window": False,
        "used_mouse": False,
        "used_device": False,
    }

    if direction == "OUTBOUND":
        return {"is_self": True, "reason": "direction_outbound", "evidence": evidence}

    if sender_wxid and bot_wxid and _ids_equal(sender_wxid, bot_wxid):
        return {"is_self": True, "reason": "sender_wxid_equals_bot_wxid", "evidence": evidence}

    if bot_wxid and sender_id_text and _ids_equal(sender_id_text, bot_wxid):
        return {"is_self": True, "reason": "sender_id_equals_bot_wxid", "evidence": evidence}

    if sender_id in (2, "2") or sender_id_text == "2":
        evidence["sender_id_2_seen"] = True
        evidence["sender_id_2_confirmed_by_wxid"] = False
        return {
            "is_self": False,
            "reason": "sender_id_2_unconfirmed_identity",
            "evidence": evidence,
        }

    return {"is_self": False, "reason": "external_sender", "evidence": evidence}
