# -*- coding: utf-8 -*-
"""Bot Runtime Engine —— 企业化运行时控制层。

职责：
- Bot 状态机（STOPPED / STARTING / RUNNING / STOPPING / ERROR / DEGRADED）
- Emergency Stop（独立标志文件 + 独立监视线程，不依赖消息循环）
- 消息去重 / 防自回复 / 短时相同内容去重
- 会话锁 / 回复限流
- 发送队列
- 运行统计与结构化事件日志

本模块不依赖微信客户端，WebUI 与 Bot 进程均可安全导入。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Callable, Optional

from message.dedupe import DedupeIndex
from message.identity import InboundMessage, RuntimeIdentity, is_self_message
from message.outbound import OutboundGuard
from message.trigger import NO_ACTION, REPLY, decide_trigger

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONTROL_DIR = os.path.join(ROOT_DIR, "runtime_control")
EMERGENCY_FLAG = os.path.join(CONTROL_DIR, "EMERGENCY_STOP")
STOP_FLAG = os.path.join(CONTROL_DIR, "STOP_REQUEST")
STATUS_FILE = os.path.join(CONTROL_DIR, "status.json")
EVENT_LOG_FILE = os.path.join(CONTROL_DIR, "events.jsonl")

STATES = ("STOPPED", "STARTING", "RUNNING", "STOPPING", "ERROR", "DEGRADED")
OPERATIONAL_STATES = ("RUNNING", "DEGRADED")

CONTENT_DEDUP_WINDOW = 5.0
REPLY_COOLDOWN_SECONDS = 10.0
MAX_REPLIES_PER_MINUTE = 5
PROCESSED_ID_TTL = 120.0
SENT_ECHO_TTL = 30.0
MAX_EVENT_LOG_LINES = 2000

_SECRET_PATTERNS = (
    r"(sk-[A-Za-z0-9_\-]{8,})",
    r"(Bearer\s+[A-Za-z0-9\-._~+/]+=*)",
)


def ensure_control_dir() -> None:
    os.makedirs(CONTROL_DIR, exist_ok=True)


def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def mask_secrets(text) -> str:
    """脱敏日志中可能出现的 API Key / Token。"""
    if text is None:
        return ""
    import re
    value = str(text)
    for pattern in _SECRET_PATTERNS:
        value = re.sub(pattern, _mask_match, value)
    return value


def _mask_match(match) -> str:
    raw = match.group(1)
    if len(raw) <= 8:
        return "****"
    return raw[:4] + "*" * min(12, len(raw) - 8) + raw[-4:]


def trigger_graceful_stop(reason: str = "webui_stop") -> dict:
    """WebUI 普通 Stop Bot：写 STOP_REQUEST，由 Bot 进程走 STOPPING→STOPPED。"""
    ensure_control_dir()
    payload = {
        "ts": time.time(),
        "reason": reason,
        "pid": os.getpid(),
    }
    with open(STOP_FLAG, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    _write_status_file({
        "state": "STOPPING",
        "emergency": False,
        "stop_reason": reason,
        "updated_at": time.time(),
    })
    return payload


def clear_stop_request() -> None:
    try:
        if os.path.exists(STOP_FLAG):
            os.remove(STOP_FLAG)
    except OSError as exc:
        logger.warning("清除停止请求标志失败: %s", exc)


def stop_requested() -> bool:
    return os.path.exists(STOP_FLAG)


def trigger_emergency_stop(reason: str = "manual") -> dict:
    """WebUI / 运维入口：立即写入紧急停止标志，不依赖 Bot 消息线程。"""
    ensure_control_dir()
    payload = {
        "ts": time.time(),
        "reason": reason,
        "pid": os.getpid(),
    }
    with open(EMERGENCY_FLAG, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    _write_status_file({
        "state": "STOPPING",
        "emergency": True,
        "emergency_reason": reason,
        "updated_at": time.time(),
    })
    return payload


def clear_emergency_stop() -> None:
    try:
        if os.path.exists(EMERGENCY_FLAG):
            os.remove(EMERGENCY_FLAG)
    except OSError as exc:
        logger.warning("清除紧急停止标志失败: %s", exc)


def emergency_stop_requested() -> bool:
    return os.path.exists(EMERGENCY_FLAG)


def read_status_file() -> dict:
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def read_event_logs(limit: int = 200, category: str = "") -> list:
    ensure_control_dir()
    if not os.path.exists(EVENT_LOG_FILE):
        return []
    items = []
    try:
        with open(EVENT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-max(1, min(limit, 1000)):]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if category and str(item.get("category", "")).upper() != category.upper():
                continue
            items.append(item)
    except Exception:
        return []
    return items


def _write_status_file(data: dict) -> None:
    ensure_control_dir()
    tmp = STATUS_FILE + ".tmp"
    try:
        merged = read_status_file()
        merged.update(data)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)
        os.replace(tmp, STATUS_FILE)
    except Exception as exc:
        logger.debug("写入运行状态文件失败: %s", exc)


class SendQueue:
    """发送队列：业务逻辑入队，独立 worker 真正调用微信发送。"""

    def __init__(self, runtime: "BotRuntime"):
        self.runtime = runtime
        self._queue: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, name="SendWorker", daemon=True)
        self._worker.start()

    def submit(self, fn: Callable, *args, **kwargs) -> bool:
        if self.runtime.is_send_blocked() or not self.runtime.is_operational():
            self.runtime.log_event("SECURITY", "发送队列已拒绝任务：机器人未处于 RUNNING")
            return False
        self._queue.put((fn, args, kwargs))
        return True

    def clear(self) -> int:
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        if dropped:
            self.runtime.log_event("BOT", f"发送队列已清空，丢弃 {dropped} 条待发送任务")
        return dropped

    def pending(self) -> int:
        return self._queue.qsize()

    def stop(self) -> None:
        self._stop.set()
        self.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.runtime.is_send_blocked() or not self.runtime.is_operational():
                self.clear()
                time.sleep(0.05)
                continue
            try:
                fn, args, kwargs = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.runtime.is_send_blocked() or not self.runtime.is_operational():
                self.runtime.log_event("SECURITY", "STOPPING：丢弃已出队但尚未执行的发送任务")
                continue
            try:
                fn(*args, **kwargs)
            except Exception as exc:
                self.runtime.note_error(f"发送任务失败: {exc}")
                logger.error("发送队列执行失败: %s", exc, exc_info=True)


class BotRuntime:
    def __init__(self):
        self._lock = threading.RLock()
        self.state = "STOPPED"
        self.started_at: Optional[float] = None
        self.wechat_connected = False
        self.ai_ok = False
        self.ai_detail = "未检测"
        self.degraded_reasons = []
        self.emergency = False
        self.emergency_reason = ""
        self.self_names = set()
        self.identity = RuntimeIdentity()
        self.dedupe = DedupeIndex(ttl=PROCESSED_ID_TTL)
        self.outbound = OutboundGuard(ttl=SENT_ECHO_TTL * 2)
        self._send_blocked = threading.Event()
        self._llm_abort = threading.Event()
        self._automation_cancel = threading.Event()
        self._processed_ids = {}
        self._recent_contents = {}
        self._recent_sent = {}
        self._session_locks = {}
        self._session_busy = set()
        self._reply_times = {}
        self._day_key = ""
        self.stats = self._empty_stats()
        self.recent_chats = deque(maxlen=20)
        self.recent_errors = deque(maxlen=20)
        self.recent_llm = deque(maxlen=20)
        self.send_queue = SendQueue(self)
        self._watch_thread: Optional[threading.Thread] = None
        self._status_thread: Optional[threading.Thread] = None
        self._on_emergency_hooks = []
        self._on_stop_hooks = []
        self._stop_completed = threading.Event()
        self._lifecycle_stop = threading.Event()

    @staticmethod
    def _empty_stats():
        return {
            "received": 0,
            "replied": 0,
            "errors": 0,
            "dropped_dup": 0,
            "dropped_self": 0,
            "dropped_rate": 0,
            "dropped_content": 0,
            "dropped_outbound": 0,
            "dropped_unauthorized": 0,
            "dropped_stopped": 0,
            "llm_calls": 0,
            "llm_main": 0,
            "llm_assistant": 0,
            "llm_vision": 0,
            "llm_online": 0,
            "llm_failed": 0,
            "llm_prompt_tokens": 0,
            "llm_completion_tokens": 0,
        }

    def _reset_daily_if_needed(self) -> None:
        day = time.strftime("%Y-%m-%d")
        if day != self._day_key:
            self._day_key = day
            self.stats = self._empty_stats()

    def register_emergency_hook(self, fn: Callable) -> None:
        self._on_emergency_hooks.append(fn)

    def register_stop_hook(self, fn: Callable) -> None:
        self._on_stop_hooks.append(fn)

    def set_identity(self, bot_wxid: str = "", bot_name: str = "", login_account: str = "") -> None:
        self.identity = RuntimeIdentity(
            bot_wxid=_safe_text(bot_wxid),
            bot_name=_safe_text(bot_name),
            login_account=_safe_text(login_account or bot_name),
        )
        names = {self.identity.bot_name, self.identity.bot_wxid, "Self"}
        self.set_self_names(names)

    def start_control_threads(self) -> None:
        ensure_control_dir()
        self.send_queue.start()
        if not self._watch_thread or not self._watch_thread.is_alive():
            self._watch_thread = threading.Thread(
                target=self._emergency_watch_loop,
                name="EmergencyStopWatcher",
                daemon=True,
            )
            self._watch_thread.start()
        if not self._status_thread or not self._status_thread.is_alive():
            self._status_thread = threading.Thread(
                target=self._status_persist_loop,
                name="RuntimeStatusWriter",
                daemon=True,
            )
            self._status_thread.start()

    def set_state(self, state: str, reason: str = "") -> None:
        if state not in STATES:
            state = "ERROR"
        with self._lock:
            old = self.state
            self.state = state
            if state == "STARTING":
                self.started_at = self.started_at or time.time()
                self._send_blocked.clear()
                self._llm_abort.clear()
                self._automation_cancel.clear()
                self._stop_completed.clear()
                self._lifecycle_stop.clear()
                self.emergency = False
                self.emergency_reason = ""
                self.send_queue.start()
            if state == "RUNNING" and not self.started_at:
                self.started_at = time.time()
            if state in ("STOPPED", "ERROR"):
                self.wechat_connected = False if state == "STOPPED" else self.wechat_connected
        if old != state:
            self.log_event("SYSTEM", f"机器人状态: {old} → {state}" + (f"（{reason}）" if reason else ""))
        self.persist_status()

    def mark_wechat(self, connected: bool, detail: str = "") -> None:
        self.wechat_connected = connected
        self.log_event("SYSTEM", "微信连接：" + ("正常" if connected else "异常") + (f" {detail}" if detail else ""))
        self.persist_status()

    def mark_ai(self, ok: bool, detail: str = "") -> None:
        self.ai_ok = ok
        self.ai_detail = detail or ("正常" if ok else "异常")
        self.log_event("AI", f"AI 服务：{self.ai_detail}")
        self.persist_status()

    def mark_degraded(self, reason: str) -> None:
        with self._lock:
            if reason not in self.degraded_reasons:
                self.degraded_reasons.append(reason)
            if self.state == "RUNNING":
                self.state = "DEGRADED"
        self.log_event("WARNING", f"能力降级：{reason}")
        self.persist_status()

    def set_self_names(self, names) -> None:
        self.self_names = {str(n).strip() for n in names if n}

    def is_send_blocked(self) -> bool:
        return self._send_blocked.is_set() or self.emergency or emergency_stop_requested() or stop_requested()

    def is_operational(self) -> bool:
        return (not self.is_send_blocked()) and self.state in OPERATIONAL_STATES

    def is_accepting_work(self) -> bool:
        return self.is_operational()

    def signal_lifecycle_stop(self) -> None:
        self._lifecycle_stop.set()

    def lifecycle_stop_requested(self) -> bool:
        return self._lifecycle_stop.is_set() or self.state in ("STOPPING", "STOPPED")

    def allows_keep_alive_relisten(self) -> bool:
        """RUNNING / DEGRADED / 启动窗内允许补监听。STOPPING 起禁止 AddListenChat。"""
        if self._lifecycle_stop.is_set():
            return False
        if self.state in ("STOPPING", "STOPPED", "ERROR"):
            return False
        if self.state == "STARTING":
            return True
        return self.is_accepting_work()

    def keep_alive_should_exit(self) -> bool:
        """STOPPED 后 keep_alive 必须退出；stop signal 同样退出。"""
        return self._lifecycle_stop.is_set() or self.state == "STOPPED"

    def lifecycle_stop_event(self) -> threading.Event:
        return self._lifecycle_stop

    def allow_ui_automation(self) -> bool:
        if self._automation_cancel.is_set():
            return False
        if self.is_send_blocked():
            return False
        return self.state == "RUNNING" or self.state == "DEGRADED"

    def llm_aborted(self) -> bool:
        return self._llm_abort.is_set() or self.is_send_blocked() or not self.is_operational()

    def cancel_llm(self) -> None:
        self._llm_abort.set()

    def cancel_automation(self) -> None:
        self._automation_cancel.set()

    def activate_emergency(self, reason: str = "flag") -> None:
        if self.emergency and self._send_blocked.is_set():
            return
        self.emergency = True
        self.emergency_reason = reason
        self._send_blocked.set()
        self._lifecycle_stop.set()
        self.set_state("STOPPING", reason)
        dropped = self.send_queue.clear()
        self.log_event(
            "SECURITY",
            f"紧急停止已生效。原因：{reason}。已禁止新发送，已清空 {dropped} 条发送队列。",
        )
        for hook in list(self._on_emergency_hooks):
            try:
                hook(reason)
            except Exception as exc:
                logger.warning("紧急停止回调失败: %s", exc)
        self.persist_status()

    def begin_graceful_stop(self, reason: str = "stop_request") -> None:
        """STOPPING → 停收、停消费、取消 Agent、停发送与 UI → STOPPED。"""
        if self.state in ("STOPPING", "STOPPED"):
            return
        self.set_state("STOPPING", reason)
        self._lifecycle_stop.set()
        self._send_blocked.set()
        self._llm_abort.set()
        self._automation_cancel.set()
        dropped_send = self.send_queue.clear()
        self.send_queue.stop()
        self.outbound.clear()
        cancelled_sessions = 0
        with self._lock:
            cancelled_sessions = len(self._session_busy)
            self._session_busy.clear()
        self.log_event(
            "SECURITY",
            f"Stop Bot 进入 STOPPING。原因：{reason}。"
            f"已禁止新任务，已清空 {dropped_send} 条发送队列，已释放 {cancelled_sessions} 个会话锁。",
        )
        for hook in list(self._on_stop_hooks) + list(self._on_emergency_hooks):
            try:
                hook(reason)
            except Exception as exc:
                logger.warning("停止回调失败: %s", exc)
        self.set_state("STOPPED", reason)
        self._stop_completed.set()
        self.persist_status()
        clear_stop_request()

    def _emergency_watch_loop(self) -> None:
        """独立于消息循环：紧急停止硬退出；普通 Stop 走 STOPPING→STOPPED。"""
        while True:
            try:
                if emergency_stop_requested():
                    self.activate_emergency("emergency_flag")
                    time.sleep(0.15)
                    logger.critical("紧急停止监视线程即将强制退出 Bot 进程，以中断可能卡住的发送操作。")
                    os._exit(0)
                if stop_requested() and self.state not in ("STOPPING", "STOPPED"):
                    self.begin_graceful_stop("stop_flag")
            except Exception as exc:
                logger.error("停止监视异常: %s", exc)
            time.sleep(0.1)

    def _status_persist_loop(self) -> None:
        while True:
            try:
                self.persist_status()
            except Exception:
                pass
            time.sleep(2)

    def persist_status(self) -> None:
        snap = self.snapshot()
        _write_status_file(snap)

    def uptime_seconds(self) -> int:
        if not self.started_at:
            return 0
        return int(max(0, time.time() - self.started_at))

    def snapshot(self) -> dict:
        with self._lock:
            self._reset_daily_if_needed()
            return {
                "state": self.state,
                "emergency": self.emergency,
                "emergency_reason": self.emergency_reason,
                "wechat": "connected" if self.wechat_connected else "disconnected",
                "ai": "ok" if self.ai_ok else "error",
                "ai_detail": self.ai_detail,
                "degraded_reasons": list(self.degraded_reasons),
                "uptime_seconds": self.uptime_seconds(),
                "started_at": self.started_at,
                "pid": os.getpid(),
                "send_queue_pending": self.send_queue.pending(),
                "today_received": self.stats["received"],
                "today_replied": self.stats["replied"],
                "today_errors": self.stats["errors"],
                "today_llm_calls": self.stats.get("llm_calls", 0),
                "today_llm_main": self.stats.get("llm_main", 0),
                "today_llm_assistant": self.stats.get("llm_assistant", 0),
                "today_llm_failed": self.stats.get("llm_failed", 0),
                "today_llm_prompt_tokens": self.stats.get("llm_prompt_tokens", 0),
                "today_llm_completion_tokens": self.stats.get("llm_completion_tokens", 0),
                "dropped_dup": self.stats.get("dropped_dup", 0),
                "dropped_self": self.stats.get("dropped_self", 0),
                "dropped_rate": self.stats.get("dropped_rate", 0),
                "dropped_content": self.stats.get("dropped_content", 0),
                "dropped_outbound": self.stats.get("dropped_outbound", 0),
                "dropped_unauthorized": self.stats.get("dropped_unauthorized", 0),
                "dropped_stopped": self.stats.get("dropped_stopped", 0),
                "recent_chats": list(self.recent_chats),
                "recent_errors": list(self.recent_errors),
                "recent_llm": list(self.recent_llm),
                "updated_at": time.time(),
            }

    def log_event(self, category: str, message: str, extra: Optional[dict] = None) -> None:
        ensure_control_dir()
        item = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": time.time(),
            "category": (category or "INFO").upper(),
            "message": mask_secrets(message),
        }
        if extra:
            item["extra"] = extra
        line = json.dumps(item, ensure_ascii=False)
        try:
            with open(EVENT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._trim_event_log()
        except Exception:
            pass
        log_fn = {
            "ERROR": logger.error,
            "WARNING": logger.warning,
            "SECURITY": logger.warning,
        }.get(item["category"], logger.info)
        log_fn("[%s] %s", item["category"], item["message"])

    def _trim_event_log(self) -> None:
        try:
            if not os.path.exists(EVENT_LOG_FILE):
                return
            if os.path.getsize(EVENT_LOG_FILE) < 2_000_000:
                return
            with open(EVENT_LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > MAX_EVENT_LOG_LINES:
                with open(EVENT_LOG_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-MAX_EVENT_LOG_LINES:])
        except Exception:
            pass

    def note_received(self, chat_id: str, preview: str) -> None:
        with self._lock:
            self._reset_daily_if_needed()
            self.stats["received"] += 1
            self.recent_chats.appendleft({
                "ts": time.strftime("%H:%M:%S"),
                "chat": chat_id,
                "preview": (preview or "")[:80],
            })

    def note_replied(self, chat_id: str) -> None:
        now = time.time()
        with self._lock:
            self._reset_daily_if_needed()
            self.stats["replied"] += 1
            times = self._reply_times.setdefault(chat_id, deque())
            times.append(now)
            while times and now - times[0] > 60:
                times.popleft()

    def note_llm_call(
        self,
        purpose: str,
        kind: str = "main",
        duration_ms: float = 0.0,
        ok: bool = True,
        error: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """记录一次 LLM 调用：用途、耗时、token、成败。"""
        kind_key = {
            "main": "llm_main",
            "assistant": "llm_assistant",
            "vision": "llm_vision",
            "online": "llm_online",
        }.get(kind, "llm_main")
        with self._lock:
            self._reset_daily_if_needed()
            self.stats["llm_calls"] += 1
            self.stats[kind_key] = self.stats.get(kind_key, 0) + 1
            self.stats["llm_prompt_tokens"] += max(0, int(prompt_tokens or 0))
            self.stats["llm_completion_tokens"] += max(0, int(completion_tokens or 0))
            if not ok:
                self.stats["llm_failed"] += 1
            self.recent_llm.appendleft({
                "ts": time.strftime("%H:%M:%S"),
                "purpose": purpose,
                "kind": kind,
                "duration_ms": round(float(duration_ms), 2),
                "ok": bool(ok),
                "error": mask_secrets(error)[:120] if error else "",
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": int(completion_tokens or 0),
            })
        status = "成功" if ok else f"失败:{error or 'unknown'}"
        self.log_event(
            "LLM",
            f"{kind}/{purpose} {status} {round(float(duration_ms), 1)}ms "
            f"tokens={int(prompt_tokens or 0)}+{int(completion_tokens or 0)}",
        )

    def note_error(self, message: str) -> None:
        with self._lock:
            self._reset_daily_if_needed()
            self.stats["errors"] += 1
            self.recent_errors.appendleft({
                "ts": time.strftime("%H:%M:%S"),
                "message": mask_secrets(message)[:200],
            })
        self.log_event("ERROR", message)

    def make_message_id(self, chat_id: str, msg) -> str:
        local_id = getattr(msg, "local_id", None)
        create_time = getattr(msg, "create_time", None)
        sort_seq = getattr(msg, "sort_seq", None)
        content = getattr(msg, "content", "") or ""
        if local_id is not None:
            return f"{chat_id}:{local_id}:{create_time or ''}:{sort_seq or ''}"
        digest = hashlib.md5(f"{chat_id}|{content}|{create_time}".encode("utf-8", "ignore")).hexdigest()
        return f"{chat_id}:h:{digest}"

    def _purge_maps(self, now: float) -> None:
        for store, ttl in (
            (self._processed_ids, PROCESSED_ID_TTL),
            (self._recent_contents, CONTENT_DEDUP_WINDOW * 4),
            (self._recent_sent, SENT_ECHO_TTL),
        ):
            expired = [k for k, ts in store.items() if now - ts > ttl]
            for k in expired:
                store.pop(k, None)

    def admit_message(
        self,
        chat_id: str,
        message_id: str,
        sender: str,
        attr: str,
        content: str,
        inbound: Optional[InboundMessage] = None,
    ) -> tuple[bool, str]:
        """兼容旧测试：转交给 evaluate_inbound。"""
        if inbound is None:
            inbound = InboundMessage(
                message_id=message_id,
                platform_message_id=message_id,
                sender_name=str(sender or ""),
                sender_wxid="",
                sender_id="",
                conversation_id=chat_id,
                chat_name=chat_id,
                attr=str(attr or "friend"),
                content=content or "",
                direction="OUTBOUND" if str(attr).lower() == "self" else "INBOUND",
            )
            # 旧测试用 attr=self 且 sender 在 self_names 里。新规则不再用昵称。
            # 若调用方显式传入 bot_wxid 匹配的 sender_wxid，才判 self。
            if inbound.direction == "OUTBOUND":
                inbound.sender_wxid = self.identity.bot_wxid
        verdict = self.evaluate_inbound(inbound)
        ok = verdict.get("action") == REPLY
        return ok, verdict.get("reason") or ""

    def evaluate_inbound(
        self,
        inbound: InboundMessage,
        *,
        listen_users=None,
        is_group: bool = False,
        accept_all: bool = False,
        enable_at: bool = True,
        enable_keyword: bool = False,
        keywords=None,
        probability: int = 100,
        keyword_ignore_probability: bool = True,
        rng=None,
        skip_listen_rules: bool = False,
    ) -> dict:
        """统一准入：stopped → outbound → self → system → duplicate → trigger。"""
        if not inbound.message_id:
            inbound.message_id = inbound.platform_message_id or self.make_message_id(
                inbound.chat_name or inbound.conversation_id, inbound
            )
        if not self.is_accepting_work():
            with self._lock:
                self.stats["dropped_stopped"] = self.stats.get("dropped_stopped", 0) + 1
            verdict = decide_trigger(
                inbound,
                identity=self.identity,
                bot_state=self.state if self.state in ("STOPPING", "STOPPED", "ERROR", "STARTING") else "STOPPING",
            )
            self._log_verdict(verdict)
            return verdict

        outbound_result = self.outbound.match(
            inbound,
            bot_identity=self.identity.bot_wxid or self.identity.bot_name,
        )
        self_result = is_self_message(inbound, self.identity)
        if outbound_result.get("is_outbound"):
            inbound.direction = "OUTBOUND"
        elif self_result.get("is_self"):
            inbound.direction = "OUTBOUND"
        else:
            inbound.direction = "INBOUND"

        dedupe_result = None
        if not outbound_result.get("is_outbound") and not self_result.get("is_self"):
            dedupe_result = self.dedupe.check(inbound)

        if skip_listen_rules:
            listen_users = list(listen_users or []) + [inbound.chat_name, inbound.conversation_id]

        verdict = decide_trigger(
            inbound,
            identity=self.identity,
            bot_state=self.state,
            self_result=self_result,
            outbound_result=outbound_result,
            dedupe_result=dedupe_result,
            listen_users=listen_users if listen_users is not None else [inbound.chat_name],
            is_group=is_group,
            accept_all=accept_all,
            enable_at=enable_at,
            enable_keyword=enable_keyword,
            keywords=keywords,
            probability=probability,
            keyword_ignore_probability=keyword_ignore_probability,
            rng=rng,
        )
        with self._lock:
            if verdict["action"] == NO_ACTION:
                reason = verdict.get("reason") or ""
                if reason in ("self",) or str(reason).startswith("sender_") or reason == "direction_outbound":
                    self.stats["dropped_self"] += 1
                elif "outbound" in reason:
                    self.stats["dropped_outbound"] = self.stats.get("dropped_outbound", 0) + 1
                    self.stats["dropped_self"] += 1
                elif "duplicate" in reason:
                    self.stats["dropped_dup"] += 1
                elif reason == "unauthorized":
                    self.stats["dropped_unauthorized"] = self.stats.get("dropped_unauthorized", 0) + 1
                elif reason == "stopped":
                    self.stats["dropped_stopped"] = self.stats.get("dropped_stopped", 0) + 1
        self._log_verdict(verdict)
        return verdict

    def _log_verdict(self, verdict: dict) -> None:
        msg = verdict.get("message") or {}
        line = (
            f"{verdict.get('direction', 'INBOUND')} "
            f"{verdict.get('identity', 'EXTERNAL')} "
            f"{verdict.get('dedupe', 'NEW')} "
            f"{verdict.get('action', NO_ACTION)} "
            f"reason={verdict.get('reason')} "
            f"chat={msg.get('chat_name') or msg.get('conversation_id')} "
            f"sender_id={msg.get('sender_id')} "
            f"sender_wxid={msg.get('sender_wxid')} "
            f"pid={msg.get('platform_message_id')}"
        )
        self.log_event("MESSAGE", line, extra=verdict)

    def register_outbound(self, conversation_id: str, content: str, platform_message_id: str = "") -> dict:
        bot = self.identity.bot_wxid or self.identity.bot_name
        record = self.outbound.register(
            conversation_id,
            content,
            bot_identity=bot,
            platform_message_id=platform_message_id,
        )
        self.remember_sent(conversation_id, content)
        self.log_event(
            "OUTBOUND",
            f"register outbound_id={record['outbound_id']} chat={conversation_id} hash={record['content_hash'][:12]}",
            extra=record,
        )
        return record

    def remember_sent(self, chat_id: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._recent_sent[f"{chat_id}::{text}"] = time.time()

    def session_busy(self, chat_id: str) -> bool:
        with self._lock:
            return chat_id in self._session_busy

    def try_acquire_session(self, chat_id: str) -> bool:
        with self._lock:
            if chat_id in self._session_busy:
                return False
            self._session_busy.add(chat_id)
            return True

    def release_session(self, chat_id: str) -> None:
        with self._lock:
            self._session_busy.discard(chat_id)

    @contextmanager
    def session_lock(self, chat_id: str):
        lock = self._session_locks.setdefault(chat_id, threading.Lock())
        acquired = lock.acquire(blocking=False)
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            lock.release()

    def allow_reply(self, chat_id: str) -> tuple[bool, str]:
        if self.is_send_blocked() or not self.is_operational():
            return False, "发送已被停止禁止"
        now = time.time()
        with self._lock:
            times = self._reply_times.setdefault(chat_id, deque())
            while times and now - times[0] > 60:
                times.popleft()
            if times and now - times[-1] < REPLY_COOLDOWN_SECONDS:
                self.stats["dropped_rate"] += 1
                wait = REPLY_COOLDOWN_SECONDS - (now - times[-1])
                return False, f"回复限流：该会话 {int(REPLY_COOLDOWN_SECONDS)} 秒内最多回复 1 次，请等待 {wait:.1f} 秒"
            if len(times) >= MAX_REPLIES_PER_MINUTE:
                self.stats["dropped_rate"] += 1
                return False, f"回复限流：该会话 1 分钟内最多回复 {MAX_REPLIES_PER_MINUTE} 次"
        return True, "ok"

    def submit_send(self, fn: Callable, *args, **kwargs) -> bool:
        return self.send_queue.submit(fn, *args, **kwargs)

    def ensure_can_send(self, chat_id: str = "") -> bool:
        if self.is_send_blocked() or not self.is_operational() or not self.allow_ui_automation():
            if chat_id:
                self.log_event("SECURITY", f"已阻止向 {chat_id} 发送：bot_state={self.state}")
            return False
        return True


runtime = BotRuntime()
