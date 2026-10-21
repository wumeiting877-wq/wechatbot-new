# -*- coding: utf-8 -*-
"""Outbound Loop Guard：发送前登记，回流时 NO_ACTION。"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from typing import Optional

from message.identity import InboundMessage, _norm
from message.dedupe import normalize_content

DEFAULT_TTL = 60.0


def content_hash_of(text: str) -> str:
    body = normalize_content(text)
    return hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()


class OutboundGuard:
    def __init__(self, ttl: float = DEFAULT_TTL):
        self.ttl = float(ttl)
        self._lock = threading.RLock()
        self._items = {}

    def _purge(self, now: float) -> None:
        expired = [k for k, item in self._items.items() if now - item["send_time"] > self.ttl]
        for key in expired:
            self._items.pop(key, None)

    def register(
        self,
        conversation_id: str,
        content: str,
        bot_identity: str = "",
        platform_message_id: str = "",
        outbound_id: str = "",
    ) -> dict:
        now = time.time()
        outbound_id = outbound_id or uuid.uuid4().hex
        record = {
            "outbound_id": outbound_id,
            "conversation_id": _norm(conversation_id),
            "content_hash": content_hash_of(content),
            "content_preview": (content or "")[:80],
            "send_time": now,
            "bot_identity": _norm(bot_identity),
            "platform_message_id": _norm(platform_message_id),
        }
        with self._lock:
            self._purge(now)
            self._items[outbound_id] = record
            if record["platform_message_id"]:
                self._items[f"pid:{record['platform_message_id']}"] = record
            conv_hash = f"hash:{record['conversation_id']}:{record['content_hash']}"
            self._items[conv_hash] = record
        return dict(record)

    def match(self, message: InboundMessage, bot_identity: str = "") -> dict:
        now = time.time()
        conversation_id = _norm(message.conversation_id or message.chat_name)
        pid = _norm(message.platform_message_id)
        digest = content_hash_of(message.content)
        bot = _norm(bot_identity)
        with self._lock:
            self._purge(now)
            record = None
            reason = ""
            if pid:
                record = self._items.get(f"pid:{pid}")
                if record:
                    reason = "outbound_platform_message_id"
            if record is None:
                record = self._items.get(f"hash:{conversation_id}:{digest}")
                if record:
                    reason = "outbound_conversation_content_hash"
            if record is None:
                return {
                    "is_outbound": False,
                    "reason": "not_outbound",
                    "evidence": {
                        "conversation_id": conversation_id,
                        "content_hash": digest,
                        "platform_message_id": pid,
                    },
                }
            if bot and record.get("bot_identity") and record["bot_identity"] != bot:
                return {
                    "is_outbound": False,
                    "reason": "outbound_bot_mismatch",
                    "evidence": {"record": record, "bot_identity": bot},
                }
            return {
                "is_outbound": True,
                "reason": reason,
                "outbound_id": record.get("outbound_id"),
                "evidence": dict(record),
            }

    def clear(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
            return n
