# -*- coding: utf-8 -*-
"""Bot 生命周期：keep_alive 绑定 Runtime，Start 前识别本项目存活 Bot。

不改 P0 去重、Trigger、四个 Engine 业务。WebUI 与 Bot 进程均可安全导入。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

KEEP_ALIVE_INTERVAL_SEC = 5.0
KEEP_ALIVE_JOIN_TIMEOUT_SEC = 2.0
STOP_STATES = ("STOPPING", "STOPPED", "ERROR")
KEEP_ALIVE_EXIT_STATES = ("STOPPED",)

KEEP_ALIVE_SKIP_LIFECYCLE = "lifecycle_stop"
KEEP_ALIVE_SKIP_NO_WX = "wx_unavailable"


def keep_alive_may_add_listen(runtime: Any) -> bool:
    """RUNNING / DEGRADED 才允许 AddListenChat。STOPPING 起 count 必须为 0。"""
    if runtime is None:
        return False
    try:
        if hasattr(runtime, "allows_keep_alive_relisten"):
            return bool(runtime.allows_keep_alive_relisten())
    except Exception:
        return False
    state = str(getattr(runtime, "state", "") or "").upper()
    if state in STOP_STATES:
        return False
    try:
        if hasattr(runtime, "lifecycle_stop_requested") and runtime.lifecycle_stop_requested():
            return False
        if hasattr(runtime, "is_accepting_work") and not runtime.is_accepting_work():
            return False
    except Exception:
        return False
    return True


def keep_alive_should_exit(runtime: Any, stop_event: Optional[threading.Event] = None) -> bool:
    """STOPPED 或明确 stop signal 时 keep_alive 必须退出。"""
    if stop_event is not None and stop_event.is_set():
        return True
    if runtime is None:
        return False
    try:
        if hasattr(runtime, "keep_alive_should_exit") and runtime.keep_alive_should_exit():
            return True
    except Exception:
        pass
    state = str(getattr(runtime, "state", "") or "").upper()
    return state in KEEP_ALIVE_EXIT_STATES


def keep_alive_tick(
    *,
    runtime: Any,
    wx: Any,
    expected_users,
    callback: Optional[Callable] = None,
    log: Optional[logging.Logger] = None,
) -> dict:
    """一次 keep_alive 检查。STOPPING 以后不得调用 AddListenChat。"""
    log = log or logger
    state = str(getattr(runtime, "state", "") or "").upper() if runtime is not None else ""
    result = {"added": [], "skipped_reason": "", "state": state, "add_listen_count": 0}
    if not keep_alive_may_add_listen(runtime):
        result["skipped_reason"] = KEEP_ALIVE_SKIP_LIFECYCLE
        return result
    if wx is None:
        result["skipped_reason"] = KEEP_ALIVE_SKIP_NO_WX
        return result
    try:
        current = set((getattr(wx, "listen", None) or {}).keys())
    except Exception as exc:
        log.error("keep_alive 读取 wx.listen 失败: %s", exc, exc_info=True)
        result["skipped_reason"] = "listen_read_error"
        return result
    expected = set(expected_users or [])
    missing = expected - current
    if not missing:
        return result
    log.warning("检测到 %s 个用户从监听列表中丢失: %s", len(missing), ", ".join(sorted(missing)))
    for user in list(missing):
        if not keep_alive_may_add_listen(runtime):
            result["skipped_reason"] = KEEP_ALIVE_SKIP_LIFECYCLE
            break
        try:
            log.info("正在尝试重新添加用户 '%s' 到监听列表...", user)
            wx.AddListenChat(nickname=user, callback=callback)
            result["added"].append(user)
            result["add_listen_count"] += 1
            log.info("已成功将用户 '%s' 重新添加回监听列表。", user)
        except Exception as exc:
            log.error("重新添加用户 '%s' 到监听列表时失败: %s", user, exc, exc_info=True)
    return result


def run_keep_alive_loop(
    *,
    runtime: Any,
    get_wx: Callable[[], Any],
    get_expected_users: Callable[[], list],
    callback: Optional[Callable] = None,
    stop_event: Optional[threading.Event] = None,
    interval: float = KEEP_ALIVE_INTERVAL_SEC,
    wait: Optional[Callable[[float], bool]] = None,
    log: Optional[logging.Logger] = None,
) -> None:
    """keep_alive 主循环。wait(timeout) 返回 True 表示收到停止信号。禁止 while True 无条件运行。"""
    log = log or logger
    stop_event = stop_event if stop_event is not None else threading.Event()
    if wait is None:
        wait = stop_event.wait
    log.info("窗口保活/监听守护线程已启动，每 %s 秒检查一次监听状态。", interval)
    while not keep_alive_should_exit(runtime, stop_event):
        try:
            keep_alive_tick(
                runtime=runtime,
                wx=get_wx() if get_wx is not None else None,
                expected_users=get_expected_users() if get_expected_users is not None else [],
                callback=callback,
                log=log,
            )
        except Exception as exc:
            log.error("keep_alive 线程在检查监听列表时发生未知错误: %s", exc, exc_info=True)
        if keep_alive_should_exit(runtime, stop_event):
            break
        try:
            signaled = bool(wait(interval))
        except Exception:
            signaled = True
        if signaled:
            break
        if keep_alive_should_exit(runtime, stop_event):
            break
    log.info("keep_alive 线程已退出。state=%s", getattr(runtime, "state", ""))


def join_keep_alive_thread(
    thread: Optional[threading.Thread],
    timeout: float = KEEP_ALIVE_JOIN_TIMEOUT_SEC,
) -> bool:
    """有限等待 keep_alive 退出。禁止无限 join。返回 True 表示线程已终止。"""
    if thread is None:
        return True
    try:
        if not thread.is_alive():
            return True
    except Exception:
        return True
    try:
        thread.join(timeout=max(0.05, float(timeout)))
    except Exception:
        return not thread.is_alive()
    return not thread.is_alive()
