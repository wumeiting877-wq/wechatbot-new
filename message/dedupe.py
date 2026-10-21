# -*- coding: utf-8 -*-
"""统一消息去重：优先 platform_message_id，否则 event_hash。"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Optional

from message.identity import InboundMessage, _norm

DEFAULT_TTL = 180.0
EVENT_HASH_BUCKET_SECONDS = 2


def _bucket(ts: Any, size: int = EVENT_HASH_BUCKET_SECONDS) -> int:
    if ts is None or ts == "":
        ts = time.time()
    try:
        value = float(ts)
    except (TypeError, ValueError):
        value = time.time()
    width = max(1, int(size))
    return int(value // width * width)


def normalize_content(content: str) -> str:
    return " ".join((content or "").strip().split())


def platform_message_id_of(message: InboundMessage) -> str:
    pid = _norm(message.platform_message_id)
    if pid:
        return pid
    if message.local_id is not None and _norm(message.local_id):
        return f"{message.conversation_id}:{message.local_id}"
    return ""


def event_hash_of(message: InboundMessage, bucket_seconds: int = EVENT_HASH_BUCKET_SECONDS) -> str:
    conversation = _norm(message.conversation_id or message.chat_wxid or message.chat_name)
    sender = _norm(message.sender_wxid) or _norm(message.sender_id) or _norm(message.sender_name)
    body = normalize_content(message.content)
    msg_type = _norm(message.raw_type) or "text"
    bucket = _bucket(message.create_time, bucket_seconds)
    raw = f"{conversation}|{sender}|{msg_type}|{bucket}|{body}"
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def dedupe_key_of(message: InboundMessage) -> tuple[str, str]:
    pid = platform_message_id_of(message)
    if pid:
        return "platform_message_id", pid
    return "event_hash", event_hash_of(message)


class DedupeIndex:
    def __init__(self, ttl: float = DEFAULT_TTL):
        self.ttl = float(ttl)
        self._lock = threading.RLock()
        self._seen = {}

    def _purge(self, now: float) -> None:
        expired = [k for k, ts in self._seen.items() if now - ts > self.ttl]
        for key in expired:
            self._seen.pop(key, None)

    def check(self, message: InboundMessage, now: Optional[float] = None) -> dict:
        """返回 {is_duplicate, reason, key_type, key, evidence}。首次见到会登记。"""
        now = time.time() if now is None else now
        key_type, key = dedupe_key_of(message)
        with self._lock:
            self._purge(now)
            seen_at = self._seen.get(key)
            if seen_at is not None:
                return {
                    "is_duplicate": True,
                    "reason": f"duplicate_{key_type}",
                    "key_type": key_type,
                    "key": key,
                    "evidence": {
                        "first_seen_at": seen_at,
                        "age_ms": round((now - seen_at) * 1000, 2),
                        "conversation_id": message.conversation_id,
                        "sender": _norm(message.sender_wxid) or _norm(message.sender_id),
                    },
                }
            self._seen[key] = now
            return {
                "is_duplicate": False,
                "reason": f"new_{key_type}",
                "key_type": key_type,
                "key": key,
                "evidence": {
                    "conversation_id": message.conversation_id,
                    "sender": _norm(message.sender_wxid) or _norm(message.sender_id),
                },
            }
