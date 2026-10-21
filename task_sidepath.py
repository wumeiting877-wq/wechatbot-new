# -*- coding: utf-8 -*-
"""P4-G2 Task Side-path：Topic 成功之后的非阻塞旁路投递。

Task Engine = 旁路观察者。不得 send_reply / wx.SendMsg，不得改 Topic / verdict。
Topic worker 只负责 put_nowait；Task LLM / Store 在独立 worker 中执行。
"""

from __future__ import annotations

import inspect
import logging
import os
import queue
import threading
import time
from typing import Any, Optional

from task_engine import TASK_ENGINE_ENABLED, TASK_EXTRACTOR_PROMPT_NAME, TaskEngine
from task_extractor_client import TaskExtractorClient
from task_store import DECISION_FAILED, TaskStore

logger = logging.getLogger(__name__)

EVENT_ENQUEUED = "TASK_SIDE_PATH_ENQUEUED"
EVENT_SKIPPED = "TASK_SIDE_PATH_SKIPPED"
EVENT_QUEUE_FULL = "TASK_QUEUE_FULL"
EVENT_PROCESS_SUCCESS = "TASK_PROCESS_SUCCESS"
EVENT_PROCESS_FAILED = "TASK_PROCESS_FAILED"

DEFAULT_QUEUE_SIZE = 32
WORKER_NAME = "TaskSidepathWorker"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

SKIP_STOPPED = "STOPPED"
SKIP_DISABLED = "TASK_ENGINE_DISABLED"
SKIP_TOPIC_NOT_ELIGIBLE = "TOPIC_NOT_ELIGIBLE"
SKIP_MISSING_TOPIC = "MISSING_TOPIC"
SKIP_MISSING_MESSAGE = "MISSING_MESSAGE"

SUCCESS_TOPIC_DECISIONS = ("NEW_TOPIC", "EXISTING_TOPIC", "TOPIC_UPDATE")
FORBIDDEN_TOPIC_DECISIONS = (
    "UNRELATED",
    "SKIPPED",
    "FAILED",
    "DISABLED",
    "CONVERSATION_NOT_RESOLVED",
)

_CONTROL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime_control")
_ENABLED_FLAG = os.path.join(_CONTROL_DIR, "TASK_ENGINE_ENABLED")


def _read_enabled_token(raw: str) -> Optional[bool]:
    token = str(raw or "").strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    return None


def is_task_engine_enabled(enabled: Optional[bool] = None) -> bool:
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
    env_flag = _read_enabled_token(os.environ.get("TASK_ENGINE_ENABLED", "") or "")
    if env_flag is not None:
        return env_flag
    return bool(TASK_ENGINE_ENABLED)


def _result_field(result: Any, name: str, default=""):
    if result is None:
        return default
    if isinstance(result, dict):
        value = result.get(name, default)
        return value if value is not None else default
    value = getattr(result, name, default)
    return value if value is not None else default


def topic_result_allows_task(result: Any) -> bool:
    """只有 Topic 成功且带 topic_id 才允许触发 Task。"""
    if result is None:
        return False
    error_code = str(_result_field(result, "error_code", "") or "")
    if error_code:
        return False
    decision = str(_result_field(result, "decision", "") or "")
    if decision in FORBIDDEN_TOPIC_DECISIONS:
        return False
    if decision not in SUCCESS_TOPIC_DECISIONS:
        return False
    topic_id = str(_result_field(result, "topic_id", "") or "").strip()
    if not topic_id:
        return False
    return True


class TaskSidepath:
    """bounded queue + 单 worker。Queue 满时丢弃 Task，绝不阻塞 Topic / 微信主链。"""

    def __init__(
        self,
        *,
        root_dir: str = "",
        extractor=None,
        enabled: Optional[bool] = None,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        store: Optional[TaskStore] = None,
        topic_store=None,
        engine: Optional[TaskEngine] = None,
        extractor_prompt_name: str = "",
        prompt_root: str = "",
    ):
        self.root_dir = root_dir or os.path.dirname(os.path.abspath(__file__))
        self.prompt_root = prompt_root or os.path.dirname(os.path.abspath(__file__))
        self.extractor = extractor if extractor is not None else TaskExtractorClient()
        self._enabled_override = enabled
        self.maxsize = max(1, int(maxsize or DEFAULT_QUEUE_SIZE))
        self.topic_store = topic_store
        if store is not None:
            self.store = store
        else:
            self.store = TaskStore(self.root_dir, topic_store=self.topic_store)
        self.extractor_prompt_name = extractor_prompt_name or TASK_EXTRACTOR_PROMPT_NAME
        self.engine = engine
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
        return is_task_engine_enabled(self._enabled_override)

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
            logger.info("Task Side-path shutdown，丢弃 %s 条未处理任务", dropped)

    def attach_runtime(self, runtime: Any) -> None:
        if runtime is None or self._hooked_runtime is runtime:
            return
        try:
            runtime.register_stop_hook(self.shutdown)
            runtime.register_emergency_hook(self.shutdown)
            self._hooked_runtime = runtime
        except Exception:
            pass

    def try_enqueue(
        self,
        *,
        topic_result: Any,
        conversation: Optional[dict] = None,
        topic_store=None,
        runtime: Any = None,
    ) -> dict:
        """Topic worker 入口：永不抛出、永不阻塞、不改 Topic / verdict。"""
        started = time.perf_counter()
        try:
            self.attach_runtime(runtime)
            if not self.enabled():
                self.skipped_count += 1
                self.last_skip_reason = SKIP_DISABLED
                return {"enqueued": False, "reason": SKIP_DISABLED}
            if runtime is not None:
                try:
                    if not runtime.is_accepting_work():
                        return self._skip(SKIP_STOPPED, topic_result)
                except Exception:
                    return self._skip(SKIP_STOPPED, topic_result)
            if not topic_result_allows_task(topic_result):
                return self._skip(SKIP_TOPIC_NOT_ELIGIBLE, topic_result)
            store = topic_store if topic_store is not None else self.topic_store
            conversation_id = str(_result_field(topic_result, "conversation_id", "") or "")
            topic_id = str(_result_field(topic_result, "topic_id", "") or "")
            message_id = str(_result_field(topic_result, "message_id", "") or "")
            if conversation is not None and not conversation_id:
                conversation_id = str((conversation or {}).get("id") or "")
            if store is None or not conversation_id or not topic_id or not message_id:
                return self._skip(SKIP_MISSING_TOPIC, topic_result)
            topic = store.get_topic(conversation_id, topic_id)
            if not topic:
                return self._skip(SKIP_MISSING_TOPIC, topic_result)
            message = store.get_message(conversation_id, message_id)
            if not message:
                return self._skip(SKIP_MISSING_MESSAGE, topic_result)
            conv = dict(conversation or {})
            if not conv.get("id"):
                conv["id"] = conversation_id
            self.start()
            payload = {
                "conversation": conv,
                "topic": topic,
                "message": message,
                "topic_store": store,
                "root_dir": getattr(store, "root_dir", "") or self.root_dir,
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
                    extra={
                        "queue_size": self.queue_size(),
                        "maxsize": self.maxsize,
                        "topic_id": topic_id,
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    },
                )
                return {
                    "enqueued": False,
                    "reason": EVENT_QUEUE_FULL,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                }
            self.enqueued_count += 1
            self._audit(
                EVENT_ENQUEUED,
                extra={
                    "conversation_id": conversation_id,
                    "topic_id": topic_id,
                    "message_id": message_id,
                    "topic_decision": str(_result_field(topic_result, "decision", "") or ""),
                },
            )
            return {
                "enqueued": True,
                "reason": EVENT_ENQUEUED,
                "conversation_id": conversation_id,
                "topic_id": topic_id,
                "message_id": message_id,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            }
        except Exception as exc:
            logger.warning("Task Side-path enqueue 隔离异常: %s", exc)
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

    def _skip(self, reason: str, topic_result: Any, event: str = EVENT_SKIPPED) -> dict:
        self.skipped_count += 1
        self.last_skip_reason = reason
        extra = {
            "skip_reason": reason,
            "topic_decision": str(_result_field(topic_result, "decision", "") or ""),
            "topic_id": _result_field(topic_result, "topic_id", None),
            "message_id": str(_result_field(topic_result, "message_id", "") or ""),
            "conversation_id": str(_result_field(topic_result, "conversation_id", "") or ""),
        }
        self._audit(event, extra=extra)
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
                    self._skip(SKIP_STOPPED, None)
                    continue
                self._process(payload)
            except Exception as exc:
                self.failed_count += 1
                logger.warning("Task Side-path worker 隔离异常: %s", exc)
                try:
                    self._mark_failed(payload, exc)
                    self._audit(EVENT_PROCESS_FAILED, extra={"error": str(exc)[:200]})
                except Exception:
                    pass
            finally:
                with self._lock:
                    self._pending = max(0, self._pending - 1)
                self._busy.clear()

    def _process(self, payload: dict) -> None:
        conversation = payload.get("conversation") or {}
        topic = payload.get("topic") or {}
        message = payload.get("message") or {}
        engine = self._engine(payload)
        result = engine.process_record(conversation, topic, message)
        self.last_result = result
        if result.decision == DECISION_FAILED or result.error_code:
            self.failed_count += 1
            self._audit(EVENT_PROCESS_FAILED, extra=result.as_dict())
            return
        self.processed_count += 1
        self._audit(EVENT_PROCESS_SUCCESS, extra=result.as_dict())

    def _engine(self, payload: Optional[dict] = None) -> TaskEngine:
        if self.engine is not None:
            return self.engine
        data = payload or {}
        topic_store = data.get("topic_store") or self.topic_store
        root_dir = data.get("root_dir") or self.root_dir
        store = self.store
        if store is None or getattr(store, "topic_store", None) is not topic_store:
            store = TaskStore(root_dir, topic_store=topic_store)
            self.store = store
        kwargs = {
            "store": store,
            "topic_store": topic_store,
            "extractor": self.extractor,
            "root_dir": self.prompt_root or root_dir,
            "enabled": True,
            "extractor_prompt_name": self.extractor_prompt_name,
        }
        return TaskEngine(**kwargs)

    def _mark_failed(self, payload: dict, exc: Exception) -> None:
        conversation = payload.get("conversation") or {}
        topic = payload.get("topic") or {}
        message = payload.get("message") or {}
        conversation_id = str(conversation.get("id") or message.get("conversation_id") or "")
        message_id = str(message.get("id") or "")
        topic_id = str(topic.get("id") or "")
        if not conversation_id or not message_id:
            return
        topic_store = payload.get("topic_store") or self.topic_store
        root_dir = payload.get("root_dir") or self.root_dir
        store = self.store
        if store is None:
            store = TaskStore(root_dir, topic_store=topic_store)
            self.store = store
        store.write_processing(
            {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "topic_id": topic_id or None,
                "decision_summary": DECISION_FAILED,
                "error": "WORKER_EXCEPTION: %s" % str(exc)[:300],
            }
        )

    def _audit(self, event: str, extra: Optional[dict] = None) -> None:
        item = {"event": event}
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


_default: Optional[TaskSidepath] = None
_default_lock = threading.Lock()


def get_task_sidepath() -> TaskSidepath:
    global _default
    with _default_lock:
        if _default is None:
            _default = TaskSidepath()
        return _default


def reset_task_sidepath(instance: Optional[TaskSidepath] = None) -> TaskSidepath:
    global _default
    with _default_lock:
        if _default is not None:
            try:
                _default.shutdown()
            except Exception:
                pass
        _default = instance if instance is not None else TaskSidepath()
        return _default


def try_enqueue_task_after_topic(
    topic_result: Any,
    conversation: Optional[dict] = None,
    topic_store=None,
    runtime: Any = None,
    *,
    sidepath: Optional[TaskSidepath] = None,
) -> dict:
    """Topic worker 调用点。失败隔离，绝不向上抛。"""
    try:
        path = sidepath if sidepath is not None else get_task_sidepath()
        return path.try_enqueue(
            topic_result=topic_result,
            conversation=conversation,
            topic_store=topic_store,
            runtime=runtime,
        )
    except Exception:
        return {"enqueued": False, "reason": "SIDE_PATH_ERROR"}


def sidepath_source_forbids_wechat_send() -> bool:
    source = inspect.getsource(TaskSidepath)
    source += inspect.getsource(try_enqueue_task_after_topic)
    source += inspect.getsource(topic_result_allows_task)
    forbidden = ("send_reply" + "(", "wx.SendMsg" + "(", "SendMsg" + "(")
    return all(token not in source for token in forbidden)
