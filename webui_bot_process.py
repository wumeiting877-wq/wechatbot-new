# -*- coding: utf-8 -*-
"""WebUI 启动/停止 Bot 子进程：独立 process group、PID 身份校验、隔离 CTRL_BREAK。"""

from __future__ import annotations

import os
import signal
import subprocess
import time

try:
    import psutil
except ImportError:
    psutil = None


def webui_pid():
    return os.getpid()


def bot_creationflags():
    if os.name == "nt":
        return subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def ignore_sigbreak_in_webui():
    """WebUI 主进程忽略 SIGBREAK，避免 Bot 的 CTRL_BREAK 把 Flask serve_forever 打掉。"""
    if os.name != "nt":
        return
    try:
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    except Exception:
        pass


def describe_process(pid):
    info = {
        "pid": pid,
        "exists": False,
        "name": "",
        "exe": "",
        "cmdline": [],
        "cmdline_text": "",
        "cwd": "",
        "ppid": None,
        "create_time": None,
    }
    if not pid or psutil is None:
        return info
    try:
        if not psutil.pid_exists(pid):
            return info
        proc = psutil.Process(pid)
        info["exists"] = True
        info["name"] = proc.name() or ""
        try:
            info["exe"] = proc.exe() or ""
        except (psutil.Error, OSError):
            info["exe"] = ""
        try:
            info["cmdline"] = list(proc.cmdline() or [])
        except (psutil.Error, OSError):
            info["cmdline"] = []
        info["cmdline_text"] = " ".join(info["cmdline"])
        try:
            info["cwd"] = proc.cwd() or ""
        except (psutil.Error, OSError):
            info["cwd"] = ""
        try:
            info["ppid"] = proc.ppid()
        except (psutil.Error, OSError):
            info["ppid"] = None
        try:
            info["create_time"] = proc.create_time()
        except (psutil.Error, OSError):
            info["create_time"] = None
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
        return info
    return info


def status_pid(status):
    if not isinstance(status, dict):
        return None
    raw = status.get("pid")
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    return pid


def collect_candidate_bot_pids(status=None, extra_pids=None, web_pid=None, include_children=True):
    """只收集已知身份候选 PID：status.json、WebUI 句柄、WebUI 子进程。不扫全机 python。"""
    pids = set()
    spid = status_pid(status)
    if spid:
        pids.add(spid)
    for raw in extra_pids or []:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            pids.add(pid)
    self_pid = web_pid if web_pid is not None else webui_pid()
    if include_children and self_pid and psutil is not None:
        try:
            parent = psutil.Process(int(self_pid))
            for child in parent.children(recursive=True):
                try:
                    pids.add(int(child.pid))
                except (TypeError, ValueError, psutil.Error):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error, TypeError, ValueError):
            pass
    pids.discard(None)
    pids.discard(0)
    if self_pid:
        try:
            pids.discard(int(self_pid))
        except (TypeError, ValueError):
            pass
    return pids


def find_living_project_bots(
    project_dir,
    status=None,
    extra_pids=None,
    web_pid=None,
    include_children=True,
    inspect_fn=None,
):
    """返回经 cmdline + 项目路径确认的存活本项目 Bot。PID 复用且 cmdline 不是 bot.py 的不会入列。"""
    inspect_fn = inspect_fn or inspect_bot_process
    found = []
    seen = set()
    for pid in collect_candidate_bot_pids(
        status=status,
        extra_pids=extra_pids,
        web_pid=web_pid,
        include_children=include_children,
    ):
        if pid in seen:
            continue
        seen.add(pid)
        verdict = inspect_fn(pid, project_dir, web_pid=web_pid)
        if verdict.get("ok"):
            found.append(verdict)
    return found


def start_bot_preflight(
    project_dir,
    *,
    web_pid=None,
    status=None,
    extra_pids=None,
    flask_bot_alive=False,
    include_children=True,
    inspect_fn=None,
):
    """Start 前防护。已有本项目 Bot → 拒绝第二次 Popen。stale / 复用 PID → 允许启动。"""
    living = find_living_project_bots(
        project_dir,
        status=status,
        extra_pids=extra_pids,
        web_pid=web_pid,
        include_children=include_children,
        inspect_fn=inspect_fn,
    )
    if living:
        return {
            "allow": False,
            "reason": "living_project_bot",
            "bots": living,
            "pid": living[0].get("pid"),
        }
    if flask_bot_alive:
        return {
            "allow": False,
            "reason": "flask_bot_process_alive",
            "bots": [],
            "pid": None,
        }
    return {"allow": True, "reason": "no_living_project_bot", "bots": [], "pid": None}


def project_bot_is_alive(pid, project_dir, web_pid=None, inspect_fn=None):
    inspect_fn = inspect_fn or inspect_bot_process
    verdict = inspect_fn(pid, project_dir, web_pid=web_pid)
    return bool(verdict.get("ok")), verdict


def inspect_bot_process(pid, project_dir, web_pid=None, expected_create_time=None):
    """确认 PID 指向本项目 bot.py / bot.exe，而不是 config_editor.py / WebUI 自身。"""
    result = {
        "ok": False,
        "reason": "",
        "pid": pid,
        "info": {},
    }
    if pid is None or pid == "":
        result["reason"] = "empty_pid"
        return result
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        result["reason"] = "invalid_pid"
        return result
    if pid <= 0:
        result["reason"] = "non_positive_pid"
        return result
    self_pid = web_pid if web_pid is not None else webui_pid()
    if pid == self_pid:
        result["reason"] = "pid_is_webui_self"
        return result
    info = describe_process(pid)
    result["info"] = info
    if not info.get("exists"):
        result["reason"] = "pid_not_running"
        return result
    haystack = " ".join(
        [
            info.get("cmdline_text") or "",
            info.get("exe") or "",
            info.get("cwd") or "",
            info.get("name") or "",
        ]
    ).lower()
    project = os.path.normcase(os.path.abspath(project_dir or ""))
    if project:
        in_project = project.lower() in haystack or os.path.normcase(
            os.path.abspath(info.get("cwd") or "")
        ).startswith(project)
    else:
        in_project = True
    is_bot = "bot.py" in haystack or haystack.endswith("bot.exe") or "\\bot.exe" in haystack or "/bot.exe" in haystack
    is_webui = "config_editor.py" in haystack or "config_editor.exe" in haystack
    if is_webui and not is_bot:
        result["reason"] = "pid_is_config_editor"
        return result
    if not is_bot:
        result["reason"] = "cmdline_not_bot"
        return result
    if not in_project:
        result["reason"] = "not_this_project"
        return result
    if expected_create_time:
        actual = info.get("create_time")
        if actual and abs(actual - expected_create_time) > 2.0:
            result["reason"] = "create_time_mismatch"
            return result
    result["ok"] = True
    result["reason"] = "bot_process"
    return result


def send_ctrl_break_isolated(pid):
    """向目标 process group 发送 CTRL_BREAK，发送期间让调用进程忽略控制台事件。"""
    if os.name != "nt":
        return False
    kernel32 = None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleCtrlHandler(None, True)
    except Exception:
        kernel32 = None
    try:
        os.kill(int(pid), signal.CTRL_BREAK_EVENT)
        return True
    finally:
        if kernel32 is not None:
            time.sleep(0.05)
            try:
                kernel32.SetConsoleCtrlHandler(None, False)
            except Exception:
                pass
            ignore_sigbreak_in_webui()


def log_spawn_pids(logger, bot_pid, web_pid=None):
    web_pid = web_pid if web_pid is not None else webui_pid()
    bot_info = describe_process(bot_pid)
    logger.info("WEB_PID = %s", web_pid)
    logger.info("BOT_PID = %s", bot_pid)
    logger.info("BOT_PPID = %s", bot_info.get("ppid"))
    logger.info(
        "Bot spawn identity: cmdline=%s create_time=%s",
        bot_info.get("cmdline_text"),
        bot_info.get("create_time"),
    )
    return {
        "WEB_PID": web_pid,
        "BOT_PID": bot_pid,
        "BOT_PPID": bot_info.get("ppid"),
        "create_time": bot_info.get("create_time"),
        "cmdline": bot_info.get("cmdline_text"),
    }
