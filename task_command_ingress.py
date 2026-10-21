# -*- coding: utf-8 -*-
"""监听循环的任务命令入口。会话 id 只用已登记会话，不用窗口名或入站会话字段。"""

from __future__ import annotations

from business_action_conversation import handle_business_action_conversation
from topic_engine import resolve_topic_conversation


def handle_task_command_turn(inbound, verdict, *, runtime, host, chat_id: str) -> bool:
    conversations = list(getattr(host, "conversations", None) or [])
    conversation = resolve_topic_conversation(inbound, conversations)
    return handle_business_action_conversation(
        inbound,
        conversation if isinstance(conversation, dict) else None,
        runtime,
        host,
        verdict=verdict,
        chat_id=chat_id,
    )
