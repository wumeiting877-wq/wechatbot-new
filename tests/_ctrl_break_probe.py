# -*- coding: utf-8 -*-
"""Windows CTRL_BREAK isolation probe. Writes JSON evidence; does not kill WebUI."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

MARKER_ENV = "CTRL_BREAK_PROBE_MARKER"


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(payload, dict):
            json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            f.write(str(payload))


def _append_event(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


def _console_pids():
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    size = 64
    buf = (wintypes.DWORD * size)()
    n = kernel32.GetConsoleProcessList(ctypes.byref(buf), size)
    return [int(buf[i]) for i in range(n)]


def _run_child(marker_dir):
    child_log = os.path.join(marker_dir, "child.log")
    info = {
        "role": "child",
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "console_pids": _console_pids(),
    }
    _write(os.path.join(marker_dir, "child_started.json"), info)
    _append_event(child_log, "child_started %s" % json.dumps(info, ensure_ascii=False))

    def handler(signum, _frame):
        payload = {
            "role": "child",
            "event": "SIGBREAK",
            "signum": int(signum),
            "pid": os.getpid(),
        }
        _write(os.path.join(marker_dir, "child_sigbreak.json"), payload)
        _append_event(child_log, "CHILD_GOT_SIGBREAK %s" % json.dumps(payload))
        os._exit(0)

    signal.signal(signal.SIGBREAK, handler)
    deadline = time.time() + 20
    while time.time() < deadline:
        time.sleep(0.1)
    _write(os.path.join(marker_dir, "child_timeout.json"), {"pid": os.getpid()})
    os._exit(2)


def _run_parent(marker_dir):
    try:
        return _run_parent_body(marker_dir)
    except Exception as exc:
        _write(os.path.join(marker_dir, "parent_crash.json"), {
            "error": str(exc),
            "pid": os.getpid(),
        })
        raise


def _run_parent_body(marker_dir):
    parent_log = os.path.join(marker_dir, "parent.log")
    _write(os.path.join(marker_dir, "parent_started.json"), {
        "role": "parent",
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "console_pids_before": _console_pids(),
    })
    parent_got = {"value": False}

    def handler(signum, _frame):
        parent_got["value"] = True
        payload = {
            "role": "parent",
            "event": "SIGBREAK",
            "signum": int(signum),
            "pid": os.getpid(),
        }
        _write(os.path.join(marker_dir, "parent_sigbreak.json"), payload)
        _append_event(parent_log, "PARENT_GOT_SIGBREAK %s" % json.dumps(payload))

    signal.signal(signal.SIGBREAK, handler)
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--child", marker_dir],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    time.sleep(0.8)
    after_spawn = {
        "WEB_PID": os.getpid(),
        "BOT_PID": child.pid,
        "BOT_PPID": os.getpid(),
        "parent_console_pids": _console_pids(),
        "creationflags": "CREATE_NEW_PROCESS_GROUP",
    }
    _write(os.path.join(marker_dir, "spawn.json"), after_spawn)
    _append_event(parent_log, "spawn %s" % json.dumps(after_spawn, ensure_ascii=False))
    _append_event(parent_log, "sending CTRL_BREAK to %s" % child.pid)
    keyboard_interrupt = False
    try:
        os.kill(child.pid, signal.CTRL_BREAK_EVENT)
        kill_error = None
        time.sleep(2.0)
    except KeyboardInterrupt:
        keyboard_interrupt = True
        parent_got["value"] = True
        kill_error = None
        _append_event(parent_log, "PARENT_GOT_KeyboardInterrupt after CTRL_BREAK")
        _write(os.path.join(marker_dir, "parent_sigbreak.json"), {
            "role": "parent",
            "event": "KeyboardInterrupt",
            "pid": os.getpid(),
        })
        time.sleep(0.5)
    except Exception as exc:
        kill_error = str(exc)
        _append_event(parent_log, "os.kill failed: %s" % exc)
    child_rc = child.poll()
    if child_rc is None:
        try:
            child.kill()
            child.wait(timeout=3)
        except Exception:
            pass
    result = {
        "WEB_PID": os.getpid(),
        "BOT_PID": child.pid,
        "BOT_PPID": os.getpid(),
        "parent_received_sigbreak": parent_got["value"],
        "child_received_sigbreak": os.path.exists(os.path.join(marker_dir, "child_sigbreak.json")),
        "child_exit_code": child_rc,
        "kill_error": kill_error,
        "parent_still_alive": True,
        "parent_console_pids_after": _console_pids(),
        "creationflags": "CREATE_NEW_PROCESS_GROUP",
    }
    _write(os.path.join(marker_dir, "result.json"), result)
    _append_event(parent_log, "result %s" % json.dumps(result, ensure_ascii=False))
    return 0


def launch_isolated(marker_dir):
    marker_dir = os.path.abspath(marker_dir)
    os.makedirs(marker_dir, exist_ok=True)
    flags = subprocess.CREATE_NEW_CONSOLE
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--parent", marker_dir],
        creationflags=flags,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    deadline = time.time() + 25
    result_path = os.path.join(marker_dir, "result.json")
    started_path = os.path.join(marker_dir, "parent_started.json")
    while time.time() < deadline:
        if os.path.exists(result_path):
            break
        time.sleep(0.2)
    if proc.poll() is None:
        try:
            proc.wait(timeout=8)
        except Exception:
            pass
    leftover = sorted(os.listdir(marker_dir)) if os.path.isdir(marker_dir) else []
    if not os.path.exists(result_path):
        return {
            "error": "probe_timeout",
            "parent_probe_pid": proc.pid,
            "parent_probe_alive": proc.poll() is None,
            "parent_started": os.path.exists(started_path),
            "files": leftover,
        }
    with open(result_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["files"] = leftover
    return data


def run_inline(marker_dir):
    """Current process acts as WebUI: same console, child gets CREATE_NEW_PROCESS_GROUP."""
    marker_dir = os.path.abspath(marker_dir)
    os.makedirs(marker_dir, exist_ok=True)
    return _run_parent_body(marker_dir)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        sys.exit(_run_child(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "--parent":
        sys.exit(_run_parent(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "--inline":
        run_inline(sys.argv[2])
        with open(os.path.join(os.path.abspath(sys.argv[2]), "result.json"), encoding="utf-8") as f:
            print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
        sys.exit(0)
    marker = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "_ctrl_break_out")
    print(json.dumps(launch_isolated(marker), ensure_ascii=False, indent=2))
