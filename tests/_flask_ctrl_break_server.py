# -*- coding: utf-8 -*-
"""Flask replica of WebUI stop: request thread sends CTRL_BREAK to child."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify

PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ctrl_break_probe.py")
MARKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_flask_break_out")
PORT = 5098

app = Flask(__name__)
child_holder = {"proc": None}
events = []


@app.route("/ping")
def ping():
    return jsonify({"ok": True, "pid": os.getpid(), "web": True})


@app.route("/start", methods=["POST"])
def start():
    os.makedirs(MARKER, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, PROBE, "--child", MARKER],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    child_holder["proc"] = proc
    payload = {
        "WEB_PID": os.getpid(),
        "BOT_PID": proc.pid,
        "BOT_PPID": os.getpid(),
        "thread": threading.current_thread().name,
    }
    events.append(("start", payload))
    return jsonify(payload)


@app.route("/stop", methods=["POST"])
def stop():
    proc = child_holder.get("proc")
    if not proc:
        return jsonify({"error": "no child"}), 400
    info = {
        "WEB_PID": os.getpid(),
        "BOT_PID": proc.pid,
        "thread": threading.current_thread().name,
        "is_main_thread": threading.current_thread() is threading.main_thread(),
    }
    try:
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        info["kill_error"] = None
    except Exception as exc:
        info["kill_error"] = str(exc)
    try:
        proc.wait(timeout=5)
        info["child_waited"] = True
        info["child_rc"] = proc.returncode
    except Exception as exc:
        info["child_waited"] = False
        info["wait_error"] = str(exc)
    events.append(("stop", info))
    return jsonify(info)


def main():
    os.makedirs(MARKER, exist_ok=True)
    started = os.path.join(MARKER, "flask_started.json")
    with open(started, "w", encoding="utf-8") as f:
        json.dump({"WEB_PID": os.getpid(), "port": PORT}, f)
    app.run(host="127.0.0.1", debug=False, port=PORT, use_reloader=False)


if __name__ == "__main__":
    main()
