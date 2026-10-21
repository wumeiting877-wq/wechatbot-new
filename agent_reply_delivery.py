# -*- coding: utf-8 -*-
"""P8-G3 进程内回复交付。只负责现在发送、挂起、补发、过期和去重。

不进入 Chat，不进入主题旁路，不写业务 Store。Query Service 由调用方在真正发送前执行。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

KIND_QUERY = "QUERY"
KIND_FIXED = "FIXED"

PENDING_LIMIT = 3
PENDING_TTL_SECONDS = 60.0

_STATE_ATTR = "_agent_reply_pending"


@dataclass
class AgentReplyPlan:
    kind: str
    chat_id: str
    conversation_id: str
    message_id: str
    sender_id: str = ""
    query_type: str = ""
    topic_id: str = ""
    topic_title: str = ""
    fixed_text: str = ""
    person_id: str = ""
    created_at: float = 0.0


@dataclass
class _Pending:
    plan: AgentReplyPlan
    materialize: Callable[[], str]
    transmit: Callable[[str], None]
    created_at: float


def offer_agent_reply(
    runtime,
    plan: AgentReplyPlan,
    *,
    materialize: Callable[[], str],
    transmit: Callable[[str], None],
) -> None:
    """会话空闲则立刻发送。只在 allow_reply 通过但 session 被占用时挂起。"""
    _ensure_hooks(runtime)
    chat_id = str(plan.chat_id or "")
    if not _accepts(runtime):
        logger.info("PENDING_AGENT_REPLY_DROPPED_STOP chat=%s", chat_id)
        return
    allowed, reason = _allow(runtime, chat_id)
    if not allowed:
        _log_runtime(runtime, reason)
        return
    if not _try_acquire(runtime, chat_id):
        _enqueue(runtime, plan, materialize, transmit)
        _log_runtime(runtime, "会话锁：%s 已有回复任务执行中，协作回复已挂起" % chat_id)
        return
    try:
        _execute(runtime, _Pending(plan, materialize, transmit, time.time()))
    finally:
        _release(runtime, chat_id)
        flush_pending(runtime, chat_id)


def notify_session_released(runtime, chat_id: str) -> None:
    """Chat 或本模块释放 session 之后补发该 chat 的挂起回复。"""
    flush_pending(runtime, str(chat_id or ""))


def flush_idle_pending(runtime) -> None:
    """已有的空闲检查循环调用。session 仍忙的 chat 不碰。"""
    if not _accepts(runtime):
        clear_pending(runtime, reason="stop")
        return
    for chat_id in _chat_ids(runtime):
        try:
            if _busy(runtime, chat_id):
                continue
            flush_pending(runtime, chat_id)
        except Exception:
            logger.exception("空闲补发失败 chat=%s", chat_id)


def flush_pending(runtime, chat_id: str) -> None:
    state = _state(runtime)
    chat_id = str(chat_id or "")
    with state["lock"]:
        if chat_id in state["flushing"]:
            return
        state["flushing"].add(chat_id)
    exit_reason = "empty"
    failed = False
    try:
        while True:
            if not _accepts(runtime):
                clear_pending(runtime, reason="stop")
                exit_reason = "stop"
                return
            item = _peek(runtime, chat_id)
            if item is None:
                exit_reason = "empty"
                return
            if _expired(item):
                _pop(runtime, chat_id)
                logger.info(
                    "PENDING_QUERY_EXPIRED chat=%s message_id=%s query_type=%s",
                    chat_id,
                    item.plan.message_id,
                    item.plan.query_type,
                )
                continue
            allowed, reason = _allow(runtime, chat_id)
            if not allowed:
                _log_runtime(runtime, reason)
                exit_reason = "cooldown"
                return
            if _busy(runtime, chat_id) or not _try_acquire(runtime, chat_id):
                exit_reason = "busy"
                return
            popped = _pop(runtime, chat_id)
            try:
                if popped is None:
                    continue
                if not _accepts(runtime):
                    clear_pending(runtime, reason="stop")
                    exit_reason = "stop"
                    return
                logger.info(
                    "PENDING_AGENT_REPLY_FLUSH chat=%s kind=%s query_type=%s message_id=%s",
                    chat_id,
                    popped.plan.kind,
                    popped.plan.query_type,
                    popped.plan.message_id,
                )
                _execute(runtime, popped)
            except Exception:
                logger.exception("挂起回复发送失败 chat=%s", chat_id)
            finally:
                _release(runtime, chat_id)
    except Exception:
        failed = True
        logger.exception("挂起回复补发失败 chat=%s", chat_id)
    finally:
        with state["lock"]:
            state["flushing"].discard(chat_id)
        if (
            not failed
            and exit_reason == "empty"
            and _has(runtime, chat_id)
            and _accepts(runtime)
            and not _busy(runtime, chat_id)
        ):
            flush_pending(runtime, chat_id)


def clear_pending(runtime, *, reason: str = "cleared") -> int:
    state = _state(runtime)
    with state["lock"]:
        count = sum(len(queue) for queue in state["queues"].values())
        state["queues"].clear()
    if count:
        logger.info("PENDING_AGENT_REPLY_CLEARED reason=%s count=%s", reason, count)
    return count


def pending_count(runtime, chat_id: Optional[str] = None) -> int:
    state = _state(runtime)
    with state["lock"]:
        if chat_id is None:
            return sum(len(queue) for queue in state["queues"].values())
        return len(state["queues"].get(str(chat_id), ()))


def pending_snapshot(runtime, chat_id: str) -> list:
    state = _state(runtime)
    with state["lock"]:
        queue = list(state["queues"].get(str(chat_id), ()))
    return [
        {
            "kind": item.plan.kind,
            "conversation_id": item.plan.conversation_id,
            "message_id": item.plan.message_id,
            "query_type": item.plan.query_type,
            "person_id": item.plan.person_id,
            "created_at": item.created_at,
        }
        for item in queue
    ]


def _execute(runtime, item: _Pending) -> None:
    if not _accepts(runtime):
        return
    text = item.materialize()
    if not text:
        return
    if not _accepts(runtime):
        return
    item.transmit(text)


def _enqueue(runtime, plan: AgentReplyPlan, materialize, transmit) -> None:
    state = _state(runtime)
    chat_id = str(plan.chat_id or "")
    message_id = str(plan.message_id or "")
    conversation_id = str(plan.conversation_id or "")
    with state["lock"]:
        if message_id and _identity_exists(state, conversation_id, message_id):
            logger.info(
                "PENDING_AGENT_REPLY_DEDUPED chat=%s conversation_id=%s message_id=%s",
                chat_id,
                conversation_id,
                message_id,
            )
            return
        queue = state["queues"].setdefault(chat_id, deque())
        if len(queue) >= PENDING_LIMIT:
            logger.info(
                "PENDING_AGENT_REPLY_DROPPED_FULL chat=%s message_id=%s depth=%s",
                chat_id,
                message_id,
                len(queue),
            )
            return
        created = float(plan.created_at or 0)
        if created <= 0:
            created = time.time()
        plan.created_at = created
        queue.append(_Pending(plan, materialize, transmit, created))
        depth = len(queue)
    logger.info(
        "PENDING_AGENT_REPLY_QUEUED chat=%s kind=%s query_type=%s message_id=%s depth=%s",
        chat_id,
        plan.kind,
        plan.query_type,
        message_id,
        depth,
    )


def _identity_exists(state, conversation_id: str, message_id: str) -> bool:
    for queue in state["queues"].values():
        for item in queue:
            if item.plan.conversation_id == conversation_id and item.plan.message_id == message_id:
                return True
    return False


def _peek(runtime, chat_id: str) -> Optional[_Pending]:
    state = _state(runtime)
    with state["lock"]:
        queue = state["queues"].get(chat_id)
        if not queue:
            return None
        return queue[0]


def _pop(runtime, chat_id: str) -> Optional[_Pending]:
    state = _state(runtime)
    with state["lock"]:
        queue = state["queues"].get(chat_id)
        if not queue:
            return None
        item = queue.popleft()
        if not queue:
            state["queues"].pop(chat_id, None)
        return item


def _has(runtime, chat_id: str) -> bool:
    return pending_count(runtime, chat_id) > 0


def _chat_ids(runtime) -> list:
    state = _state(runtime)
    with state["lock"]:
        return list(state["queues"].keys())


def _expired(item: _Pending) -> bool:
    return time.time() - float(item.created_at or 0) >= PENDING_TTL_SECONDS


def _state(runtime) -> dict:
    state = getattr(runtime, _STATE_ATTR, None)
    if state is None:
        state = {"queues": {}, "flushing": set(), "hooked": False, "lock": threading.RLock()}
        setattr(runtime, _STATE_ATTR, state)
    return state


def _ensure_hooks(runtime) -> None:
    state = _state(runtime)
    with state["lock"]:
        if state["hooked"]:
            return
        state["hooked"] = True
    register_stop = getattr(runtime, "register_stop_hook", None)
    register_emergency = getattr(runtime, "register_emergency_hook", None)
    if callable(register_stop):
        register_stop(lambda _reason: clear_pending(runtime, reason="stop"))
    if callable(register_emergency):
        register_emergency(lambda _reason: clear_pending(runtime, reason="emergency"))


def _accepts(runtime) -> bool:
    checker = getattr(runtime, "is_accepting_work", None)
    if callable(checker):
        return bool(checker())
    return True


def _allow(runtime, chat_id: str) -> tuple:
    checker = getattr(runtime, "allow_reply", None)
    if not callable(checker):
        return True, "ok"
    return checker(chat_id)


def _busy(runtime, chat_id: str) -> bool:
    checker = getattr(runtime, "session_busy", None)
    if not callable(checker):
        return False
    return bool(checker(chat_id))


def _try_acquire(runtime, chat_id: str) -> bool:
    acquire = getattr(runtime, "try_acquire_session", None)
    if not callable(acquire):
        return True
    return bool(acquire(chat_id))


def _release(runtime, chat_id: str) -> None:
    release = getattr(runtime, "release_session", None)
    if callable(release):
        release(chat_id)


def _log_runtime(runtime, message: str) -> None:
    if not message:
        return
    log_event = getattr(runtime, "log_event", None)
    if not callable(log_event):
        return
    try:
        log_event("BOT", message)
    except Exception:
        pass
