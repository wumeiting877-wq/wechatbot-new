# -*- coding: utf-8 -*-
"""可观测消息 pipeline：记录每一步是否命中、耗时、是否调用 LLM。

纯决策函数不依赖微信客户端，便于单测。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from group_rules import evaluate_group_trigger
from reminder_rules import looks_like_reminder

MEDIA_MSG_TYPES = {"image", "emotion", "file"}

STEP_ADMIT = "admit"
STEP_ATTR = "attr_filter"
STEP_NORMALIZE = "normalize"
STEP_EMPTY = "empty_check"
STEP_LISTEN = "listen_or_group"
STEP_COMMAND = "command"
STEP_REMINDER = "reminder"
STEP_MEDIA = "media"
STEP_URL = "url_fetch"
STEP_ENQUEUE = "enqueue"
STEP_ONLINE = "online_search"
STEP_MAIN_LLM = "main_llm"
STEP_EMOJI = "emoji_send"


class PipelineTrace:
    """一条消息从入站到回复的步骤记录。"""

    def __init__(self, chat_id: str = "", sender: str = "", msgtype: str = "text"):
        self.chat_id = chat_id
        self.sender = sender
        self.msgtype = msgtype
        self.started_at = time.time()
        self.steps = []
        self.aborted = False
        self.abort_reason = ""

    def record(
        self,
        name: str,
        *,
        hit: bool = True,
        skipped: bool = False,
        reason: str = "",
        duration_ms: float = 0.0,
        llm_calls: Optional[list] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        item = {
            "name": name,
            "hit": bool(hit) and not skipped,
            "skipped": bool(skipped),
            "reason": reason or "",
            "duration_ms": round(float(duration_ms), 2),
            "llm_calls": list(llm_calls or []),
        }
        if extra:
            item["extra"] = extra
        self.steps.append(item)
        return item

    def step(self, name: str):
        return _StepTimer(self, name)

    def abort(self, reason: str) -> None:
        self.aborted = True
        self.abort_reason = reason

    def llm_call_count(self, kind: Optional[str] = None) -> int:
        total = 0
        for step in self.steps:
            for call in step.get("llm_calls") or []:
                if kind is None or call.get("kind") == kind:
                    total += 1
        return total

    def main_llm_count(self) -> int:
        return self.llm_call_count("main")

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "sender": self.sender,
            "msgtype": self.msgtype,
            "duration_ms": round((time.time() - self.started_at) * 1000, 2),
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "llm_calls": self.llm_call_count(),
            "main_llm_calls": self.main_llm_count(),
            "steps": list(self.steps),
        }


class _StepTimer:
    def __init__(self, trace: PipelineTrace, name: str):
        self.trace = trace
        self.name = name
        self._start = 0.0
        self.hit = True
        self.skipped = False
        self.reason = ""
        self.llm_calls = []
        self.extra = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        duration_ms = (time.perf_counter() - self._start) * 1000
        if exc_type is not None and not self.reason:
            self.reason = f"exception:{exc_type.__name__}"
            self.hit = False
        self.trace.record(
            self.name,
            hit=self.hit,
            skipped=self.skipped,
            reason=self.reason,
            duration_ms=duration_ms,
            llm_calls=self.llm_calls,
            extra=self.extra,
        )
        return False

    def skip(self, reason: str) -> None:
        self.skipped = True
        self.hit = False
        self.reason = reason

    def miss(self, reason: str) -> None:
        self.hit = False
        self.reason = reason

    def add_llm(self, kind: str, purpose: str) -> None:
        self.llm_calls.append({"kind": kind, "purpose": purpose})


def classify_incoming_attr(msgattr: str, content: str) -> dict:
    """拍一拍 / 自身消息 / 非好友：在准入前过滤。"""
    attr = (msgattr or "").strip().lower()
    text = content or ""
    if attr == "tickle":
        if "我拍了拍" in text:
            return {"action": "drop", "reason": "self_tickle", "content": text}
        return {"action": "continue", "reason": "tickle", "content": f"[收到拍一拍消息]：{text}"}
    if attr == "self":
        # self 改由 is_self_message / outbound 判定，属性层不再无条件丢弃。
        return {"action": "continue", "reason": "attr_self_hint", "content": text}
    if attr and attr != "friend":
        return {"action": "drop", "reason": "non_friend", "content": text}
    return {"action": "continue", "reason": "friend", "content": text}


def normalize_typed_content(msgtype: str, content: str, extra: Optional[dict] = None) -> str:
    """把语音/链接/引用转成后续处理器能读的文本。合并转发留给 I/O 层。"""
    extra = extra or {}
    text = content or ""
    kind = (msgtype or "text").lower()
    if kind == "voice":
        voice_text = extra.get("voice_text") or ""
        return f"[语音消息]: {voice_text}"
    if kind == "link":
        url = extra.get("url") or ""
        return f"[卡片链接]: {url}"
    if kind == "quote":
        quoted = extra.get("quote_content")
        if quoted:
            return f"[引用<{quoted}>消息]: {extra.get('content', text)}"
        return extra.get("content", text)
    return text


def is_empty_content_skippable(content: str, msgtype: str) -> bool:
    if content:
        return False
    return (msgtype or "").lower() not in MEDIA_MSG_TYPES


def decide_should_process(
    who: str,
    sender: str,
    content: str,
    msgtype: str,
    *,
    listen_users,
    is_group: bool,
    robot_name: str = "",
    accept_all: bool = False,
    enable_at: bool = True,
    enable_keyword: bool = False,
    keywords=None,
    probability: int = 100,
    keyword_ignore_probability: bool = True,
    rng: Optional[Callable[[int, int], int]] = None,
) -> dict:
    """私聊监听名单 / 群聊触发规则。"""
    original = content or ""
    if not is_group:
        if who in (listen_users or []):
            return {
                "should_process": True,
                "reason": "private_listen_list",
                "content_for_handler": original,
                "at_triggered": False,
                "keyword_triggered": False,
            }
        return {
            "should_process": False,
            "reason": "private_not_in_listen_list",
            "content_for_handler": original,
            "at_triggered": False,
            "keyword_triggered": False,
        }

    trigger = evaluate_group_trigger(
        original,
        robot_name=robot_name or "",
        accept_all=accept_all,
        enable_at=enable_at,
        enable_keyword=enable_keyword,
        keywords=keywords,
        probability=probability,
        keyword_ignore_probability=keyword_ignore_probability,
        rng=rng,
    )
    processed = trigger["processed_content"]
    content_for_handler = processed
    if trigger["should_process"] and msgtype != "image":
        content_for_handler = f"[群聊消息-来自群'{who}'-发送者:{sender}]:{processed}"
    return {
        "should_process": trigger["should_process"],
        "reason": trigger["reason"],
        "content_for_handler": content_for_handler,
        "at_triggered": trigger["at_triggered"],
        "keyword_triggered": trigger["keyword_triggered"],
        "processed_content": processed,
    }


def plan_llm_calls_for_text(
    content: str,
    *,
    enable_reminders: bool = False,
    enable_online: bool = False,
    assistant_ready: bool = False,
    enable_emoji_sending: bool = False,
    is_image: bool = False,
    image_ready: bool = False,
) -> dict:
    """规划一条普通文本消息会打哪些模型。不真正调用。

    验收约定：默认普通文本只打 1 次主模型。
    """
    calls = []
    reminder_hit = bool(enable_reminders and looks_like_reminder(content))
    if reminder_hit:
        if assistant_ready:
            calls.append({"kind": "assistant", "purpose": "reminder_parse"})
        else:
            calls.append({"kind": "skipped", "purpose": "reminder_parse", "reason": "assistant_not_ready"})

    if is_image:
        if image_ready:
            calls.append({"kind": "vision", "purpose": "image_recognition"})
        else:
            calls.append({"kind": "skipped", "purpose": "image_recognition", "reason": "not_configured"})

    if enable_online:
        if assistant_ready:
            calls.append({"kind": "assistant", "purpose": "online_detect"})
        else:
            calls.append({"kind": "skipped", "purpose": "online_detect", "reason": "assistant_not_ready"})

    if not reminder_hit:
        calls.append({"kind": "main", "purpose": "main_chat"})

    if enable_emoji_sending and assistant_ready and not reminder_hit:
        calls.append({"kind": "assistant", "purpose": "emoji_detect"})

    main_calls = [c for c in calls if c.get("kind") == "main"]
    return {
        "calls": calls,
        "main_count": len(main_calls),
        "reminder_hit": reminder_hit,
        "default_one_main": len(main_calls) == 1 and not reminder_hit,
    }


def summarize_trace_for_log(trace: PipelineTrace) -> str:
    data = trace.as_dict()
    parts = []
    for step in data["steps"]:
        flag = "skip" if step["skipped"] else ("hit" if step["hit"] else "miss")
        llm = f",llm={len(step['llm_calls'])}" if step["llm_calls"] else ""
        parts.append(f"{step['name']}:{flag}{llm}/{step['duration_ms']}ms")
    abort = f" abort={data['abort_reason']}" if data["aborted"] else ""
    return (
        f"pipeline chat={data['chat_id']} main_llm={data['main_llm_calls']} "
        f"llm={data['llm_calls']} {data['duration_ms']}ms{abort} | " + " > ".join(parts)
    )
