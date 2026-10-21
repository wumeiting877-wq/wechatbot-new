# -*- coding: utf-8 -*-
"""P3-G2 Topic Side-path：evaluate_inbound 之后的非阻塞旁路投递。

Topic Engine = 旁路观察者。不得 send_reply / wx.SendMsg，不得改 verdict。
listener 只负责 put_nowait；LLM / Store 在独立 worker 中执行。
"""

from __future__ import annotations

import inspect
import logging
import os
import queue
import threading
import time
from typing import Any, Optional

from message.trigger import NO_ACTION, REPLY
from topic_engine import (
    CONVERSATION_NOT_RESOLVED,
    TOPIC_ENGINE_ENABLED,
    TopicEngine,
    resolve_topic_conversation,
)
from topic_extractor_client import TopicExtractorClient
from topic_store import TopicStore, content_preview

logger = logging.getLogger(__name__)

EVENT_ENQUEUED = "TOPIC_SIDE_PATH_ENQUEUED"
EVENT_SKIPPED = "TOPIC_SIDE_PATH_SKIPPED"
EVENT_QUEUE_FULL = "TOPIC_QUEUE_FULL"
EVENT_PROCESS_SUCCESS = "TOPIC_PROCESS_SUCCESS"
EVENT_PROCESS_FAILED = "TOPIC_PROCESS_FAILED"
EVENT_CONV_NOT_RESOLVED = "CONVERSATION_NOT_RESOLVED"
EVENT_TOPIC_REPLAY = "TOPIC_REPLAY"

DEFAULT_QUEUE_SIZE = 32
WORKER_NAME = "TopicSidepathWorker"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

SKIP_STOPPED = "STOPPED"
SKIP_SELF = "SELF"
SKIP_OUTBOUND = "OUTBOUND"
SKIP_SYSTEM = "SYSTEM"
SKIP_DUPLICATE = "DUPLICATE"
SKIP_DISABLED = "TOPIC_ENGINE_DISABLED"
SKIP_INELIGIBLE = "INELIGIBLE"


_CONTROL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime_control")
_ENABLED_FLAG = os.path.join(_CONTROL_DIR, "TOPIC_ENGINE_ENABLED")


def _read_enabled_token(raw: str) -> Optional[bool]:
    token = str(raw or "").strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    return None


def is_topic_engine_enabled(enabled: Optional[bool] = None) -> bool:
    """默认 false。runtime_control 开关优先，其次环境变量，最后模块常量。"""
    if enabled is not None:
        return bool(enabled)
    try:
        if os.path.isfile(_ENABLED_FLAG):
            with open(_ENABLED_FLAG, "r", encoding="utf-8") as handle:
                flag = _read_enabled_token(handle.read())
            if flag is not None:
                return flag
    except OSError:
        pass
    env_flag = _read_enabled_token(os.environ.get("TOPIC_ENGINE_ENABLED", "") or "")
    if env_flag is not None:
        return env_flag
    return bool(TOPIC_ENGINE_ENABLED)


def classify_topic_skip(verdict: Optional[dict], runtime: Any = None) -> Optional[str]:
    """用已完成的 P0 verdict 判断是否禁止进入 Topic。不修改 verdict。"""
    if runtime is not None:
        try:
            if not runtime.is_accepting_work():
                return SKIP_STOPPED
        except Exception:
            return SKIP_STOPPED
    data = verdict if isinstance(verdict, dict) else {}
    reason = str(data.get("reason") or "")
    identity = str(data.get("identity") or "")
    direction = str(data.get("direction") or "")
    dedupe = str(data.get("dedupe") or "")
    action = data.get("action")
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    if reason == "stopped":
        return SKIP_STOPPED
    if extra.get("is_outbound") or reason.startswith("outbound") or reason == "direction_outbound":
        return SKIP_OUTBOUND
    if identity == "SELF" or extra.get("is_self") or reason in ("self",) or reason.startswith("sender_"):
        return SKIP_SELF
    if direction == "OUTBOUND":
        return SKIP_OUTBOUND
    if reason == "bot_or_system":
        return SKIP_SYSTEM
    if dedupe == "DUPLICATE" or "duplicate" in reason or extra.get("is_duplicate"):
        return SKIP_DUPLICATE
    if action == REPLY:
        return None
    if action == NO_ACTION and reason == "unauthorized":
        return None
    return SKIP_INELIGIBLE


class TopicSidepath:
    """bounded queue + 单 worker。Queue 满时丢弃 Topic，绝不阻塞微信主链。"""

    def __init__(
        self,
        *,
        root_dir: str = "",
        conversations: Optional[list] = None,
        extractor=None,
        enabled: Optional[bool] = None,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        store: Optional[TopicStore] = None,
        engine: Optional[TopicEngine] = None,
        extractor_prompt_name: str = "",
        prompt_root: str = "",
        task_sidepath: Any = None,
        decision_sidepath: Any = None,
        risk_sidepath: Any = None,
    ):
        self.root_dir = root_dir or os.path.dirname(os.path.abspath(__file__))
        self.prompt_root = prompt_root or os.path.dirname(os.path.abspath(__file__))
        self.conversations = list(conversations or [])
        self.extractor = extractor if extractor is not None else TopicExtractorClient()
        self._enabled_override = enabled
        self.maxsize = max(1, int(maxsize or DEFAULT_QUEUE_SIZE))
        self.store = store if store is not None else TopicStore(self.root_dir)
        self.extractor_prompt_name = extractor_prompt_name
        self.engine = engine
        self.task_sidepath = task_sidepath
        self.decision_sidepath = decision_sidepath
        self.risk_sidepath = risk_sidepath
        self._queue: queue.Queue = queue.Queue(maxsize=self.maxsize)
        self._stop = threading.Event()
        self._busy = threading.Event()
        self._pending = 0
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._hooked_runtime = None
        self.enqueued_count = 0
        self.skipped_count = 0
        self.processed_count = 0
        self.failed_count = 0
        self.queue_full_count = 0
        self.last_skip_reason = ""
        self.audit_events: list = []
        self.last_result = None

    def enabled(self) -> bool:
        return is_topic_engine_enabled(self._enabled_override)

    def queue_size(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(target=self._loop, name=WORKER_NAME, daemon=True)
            self._worker.start()

    def shutdown(self, _reason: str = "") -> None:
        self._stop.set()
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        if dropped:
            with self._lock:
                self._pending = max(0, self._pending - dropped)
            logger.info("Topic Side-path shutdown，丢弃 %s 条未处理任务", dropped)
        if self.task_sidepath is not None:
            try:
                self.task_sidepath.shutdown(_reason)
            except Exception:
                pass
        if self.decision_sidepath is not None:
            try:
                self.decision_sidepath.shutdown(_reason)
            except Exception:
                pass
        if self.risk_sidepath is not None:
            try:
                self.risk_sidepath.shutdown(_reason)
            except Exception:
                pass

    def _refresh_from_host(self) -> None:
        if self.conversations:
            return
        try:
            from message.bind import host
            B = host()
            convs = list(getattr(B, "conversations", None) or [])
            if convs:
                self.conversations = convs
            root = getattr(B, "root_dir", "") or ""
            if root and os.path.abspath(root) != os.path.abspath(self.root_dir):
                self.root_dir = root
                self.store = TopicStore(self.root_dir)
                self.engine = None
        except Exception:
            pass

    def attach_runtime(self, runtime: Any) -> None:
        if runtime is None or self._hooked_runtime is runtime:
            return
        try:
            runtime.register_stop_hook(self.shutdown)
            runtime.register_emergency_hook(self.shutdown)
            self._hooked_runtime = runtime
        except Exception:
            pass

    def try_enqueue(self, inbound: Any, verdict: Optional[dict], runtime: Any = None) -> dict:
        """listener 唯一入口：永不抛出、永不阻塞、不改 verdict。"""
        started = time.perf_counter()
        try:
            self.attach_runtime(runtime)
            if not self.enabled():
                self.skipped_count += 1
                self.last_skip_reason = SKIP_DISABLED
                return {"enqueued": False, "reason": SKIP_DISABLED}
            skip = classify_topic_skip(verdict, runtime=runtime)
            if skip:
                return self._skip(skip, inbound, verdict)
            self._refresh_from_host()
            conversation = resolve_topic_conversation(inbound, self.conversations)
            if conversation is None:
                return self._skip(EVENT_CONV_NOT_RESOLVED, inbound, verdict, event=EVENT_CONV_NOT_RESOLVED)
            self.start()
            payload = {
                "inbound": inbound,
                "conversation": conversation,
                "enqueued_at": time.time(),
            }
            try:
                self._queue.put_nowait(payload)
                with self._lock:
                    self._pending += 1
            except queue.Full:
                self.queue_full_count += 1
                self._audit(
                    EVENT_QUEUE_FULL,
                    inbound,
                    extra={"queue_size": self.queue_size(), "maxsize": self.maxsize},
                )
                return {
                    "enqueued": False,
                    "reason": EVENT_QUEUE_FULL,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                }
            self.enqueued_count += 1
            self._audit(EVENT_ENQUEUED, inbound, extra={"conversation_id": conversation.get("id")})
            return {
                "enqueued": True,
                "reason": EVENT_ENQUEUED,
                "conversation_id": conversation.get("id"),
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            }
        except Exception as exc:
            logger.warning("Topic Side-path enqueue 隔离异常: %s", exc)
            return {"enqueued": False, "reason": "SIDE_PATH_ERROR"}

    def wait_idle(self, timeout: float = 2.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                pending = self._pending
            if pending <= 0 and not self._busy.is_set():
                return True
            time.sleep(0.01)
        with self._lock:
            pending = self._pending
        return pending <= 0 and not self._busy.is_set()

    def _skip(self, reason: str, inbound: Any, verdict: Optional[dict], event: str = EVENT_SKIPPED) -> dict:
        self.skipped_count += 1
        self.last_skip_reason = reason
        extra = {"skip_reason": reason, "trigger_action": (verdict or {}).get("action")}
        self._audit(event, inbound, extra=extra)
        return {"enqueued": False, "reason": reason}

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            self._busy.set()
            try:
                if self._stop.is_set() or not self.enabled():
                    continue
                runtime = self._hooked_runtime
                if runtime is not None and not runtime.is_accepting_work():
                    self._skip(SKIP_STOPPED, payload.get("inbound"), None)
                    continue
                self._process(payload)
            except Exception as exc:
                self.failed_count += 1
                logger.warning("Topic Side-path worker 隔离异常: %s", exc)
                try:
                    self._audit(EVENT_PROCESS_FAILED, payload.get("inbound"), extra={"error": str(exc)[:200]})
                except Exception:
                    pass
            finally:
                with self._lock:
                    self._pending = max(0, self._pending - 1)
                self._busy.clear()

    def process_record_and_fanout(self, record: dict, conversation: dict, runtime: Any = None):
        """同步处理已存在的 MessageRecord，复用 worker 的 replay / fan-out 判断。"""
        if runtime is not None:
            self.attach_runtime(runtime)
        engine = self._engine()
        result = engine.process_record(record, conversation)
        self._apply_topic_engine_result({"inbound": None, "conversation": conversation}, result)
        return result

    def _process(self, payload: dict) -> None:
        inbound = payload.get("inbound")
        conversation = payload.get("conversation") or {}
        engine = self._engine()
        result = engine.process_inbound(inbound, conversations=[conversation] + list(self.conversations))
        self._apply_topic_engine_result(payload, result)

    def _apply_topic_engine_result(self, payload: dict, result: Any) -> None:
        inbound = payload.get("inbound")
        self.last_result = result
        if result.error_code == CONVERSATION_NOT_RESOLVED:
            self._audit(EVENT_CONV_NOT_RESOLVED, inbound, extra=result.as_dict())
            return
        if result.decision == "FAILED" or result.error_code:
            self.failed_count += 1
            self._audit(EVENT_PROCESS_FAILED, inbound, extra=result.as_dict())
            return
        self.processed_count += 1
        if result.replayed:
            extra = result.as_dict()
            extra["fanout_skipped"] = True
            self._audit(EVENT_TOPIC_REPLAY, inbound, extra=extra)
            return
        self._audit(EVENT_PROCESS_SUCCESS, inbound, extra=result.as_dict())
        self._fanout_topic_result(payload, result)

    def _fanout_topic_result(self, payload: dict, result: Any) -> None:
        """仅 SUCCESS 且 replayed=false 时调用。不得复制下游 allow 规则。"""
        self._maybe_enqueue_task(payload, result)
        self._maybe_enqueue_decision(payload, result)
        self._maybe_enqueue_risk(payload, result)

    def _maybe_enqueue_task(self, payload: dict, result: Any) -> None:
        """Topic 成功后快速投递 Task。失败隔离，不得阻塞或回滚 Topic。"""
        try:
            from task_sidepath import try_enqueue_task_after_topic

            try_enqueue_task_after_topic(
                result,
                conversation=payload.get("conversation"),
                topic_store=self.store,
                runtime=self._hooked_runtime,
                sidepath=self.task_sidepath,
            )
        except Exception as exc:
            logger.warning("Task Side-path enqueue 隔离异常: %s", exc)

    def _maybe_enqueue_decision(self, payload: dict, result: Any) -> None:
        """Topic 成功后快速投递 Decision。与 Task 平行，失败隔离，不得阻塞或回滚 Topic。"""
        try:
            from decision_sidepath import try_enqueue_decision_after_topic

            try_enqueue_decision_after_topic(
                result,
                conversation=payload.get("conversation"),
                topic_store=self.store,
                runtime=self._hooked_runtime,
                sidepath=self.decision_sidepath,
            )
        except Exception as exc:
            logger.warning("Decision Side-path enqueue 隔离异常: %s", exc)

    def _maybe_enqueue_risk(self, payload: dict, result: Any) -> None:
        """Topic 成功后快速投递 Risk。与 Task / Decision 平行，失败隔离，不得阻塞或回滚 Topic。"""
        try:
            from risk_sidepath import try_enqueue_risk_after_topic

            try_enqueue_risk_after_topic(
                result,
                conversation=payload.get("conversation"),
                topic_store=self.store,
                runtime=self._hooked_runtime,
                sidepath=self.risk_sidepath,
            )
        except Exception as exc:
            logger.warning("Risk Side-path enqueue 隔离异常: %s", exc)

    def _engine(self) -> TopicEngine:
        if self.engine is not None:
            return self.engine
        kwargs = {
            "store": self.store,
            "extractor": self.extractor,
            "root_dir": self.prompt_root or self.root_dir,
            "conversations": self.conversations,
            "enabled": True,
        }
        if self.extractor_prompt_name:
            kwargs["extractor_prompt_name"] = self.extractor_prompt_name
        return TopicEngine(**kwargs)

    def _audit(self, event: str, inbound: Any, extra: Optional[dict] = None) -> None:
        preview = ""
        if inbound is not None:
            preview = content_preview(getattr(inbound, "content", "") or "")
        item = {
            "event": event,
            "content_preview": preview,
        }
        if extra:
            safe = dict(extra)
            for key in ("api_key", "API_KEY", "Authorization", "authorization", "DEEPSEEK_API_KEY"):
                safe.pop(key, None)
            item.update(safe)
        self.audit_events.append(item)
        try:
            self.store.write_audit(item)
        except Exception:
            pass


_default: Optional[TopicSidepath] = None
_default_lock = threading.Lock()


def get_sidepath() -> TopicSidepath:
    global _default
    with _default_lock:
        if _default is None:
            _default = TopicSidepath()
        return _default


def reset_sidepath(instance: Optional[TopicSidepath] = None) -> TopicSidepath:
    global _default
    with _default_lock:
        if _default is not None:
            try:
                _default.shutdown()
            except Exception:
                pass
        _default = instance if instance is not None else TopicSidepath()
        return _default


def try_enqueue_topic_sidepath(
    inbound: Any,
    verdict: Optional[dict],
    runtime: Any = None,
    *,
    sidepath: Optional[TopicSidepath] = None,
) -> dict:
    """listener 调用点。失败隔离，绝不向上抛。"""
    try:
        path = sidepath if sidepath is not None else get_sidepath()
        return path.try_enqueue(inbound, verdict, runtime=runtime)
    except Exception:
        return {"enqueued": False, "reason": "SIDE_PATH_ERROR"}


def sidepath_source_forbids_wechat_send() -> bool:
    source = inspect.getsource(TopicSidepath)
    source += inspect.getsource(try_enqueue_topic_sidepath)
    forbidden = ("send_reply" + "(", "wx.SendMsg" + "(", "SendMsg" + "(")
    return all(token not in source for token in forbidden)
