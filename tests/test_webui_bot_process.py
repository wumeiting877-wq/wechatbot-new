# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from webui_bot_process import (
    bot_creationflags,
    inspect_bot_process,
    start_bot_preflight,
    webui_pid,
)


class WebuiBotProcessTests(unittest.TestCase):
    def test_creationflags_new_process_group_on_windows(self):
        flags = bot_creationflags()
        if os.name == "nt":
            self.assertEqual(flags, subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertEqual(flags, 0)

    def test_rejects_empty_and_self_pid(self):
        web = webui_pid()
        self.assertEqual(inspect_bot_process(None, ROOT, web_pid=web)["reason"], "empty_pid")
        self.assertEqual(inspect_bot_process(0, ROOT, web_pid=web)["reason"], "non_positive_pid")
        self.assertEqual(
            inspect_bot_process(web, ROOT, web_pid=web)["reason"],
            "pid_is_webui_self",
        )

    def test_rejects_current_non_bot_process(self):
        other_web = webui_pid() + 10**7
        verdict = inspect_bot_process(os.getpid(), ROOT, web_pid=other_web)
        self.assertFalse(verdict["ok"])
        self.assertIn(verdict["reason"], ("cmdline_not_bot", "pid_is_config_editor"))

    def test_status_route_alive(self):
        from config_editor import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn("state", data)
            self.assertIn("web_pid", data)

    def test_start_bot_uses_helper_not_raw_kill(self):
        editor = os.path.join(ROOT, "config_editor.py")
        with open(editor, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("bot_creationflags()", text)
        self.assertIn("inspect_bot_process(", text)
        self.assertIn("send_ctrl_break_isolated(", text)
        self.assertIn("ignore_sigbreak_in_webui()", text)
        self.assertNotIn("os.kill(pid_to_kill, signal.CTRL_BREAK_EVENT)", text)
        self.assertIn("@app.route('/status')", text)
        self.assertIn("threaded=True", text)
        self.assertIn("start_bot_preflight(", text)
        self.assertIn("already_running", text)

    def test_preflight_refuses_living_status_pid(self):
        def inspect_fn(pid, project_dir, web_pid=None, expected_create_time=None):
            if pid == 4242:
                return {"ok": True, "reason": "bot_process", "pid": 4242, "info": {}}
            return {"ok": False, "reason": "pid_not_running", "pid": pid, "info": {}}

        result = start_bot_preflight(
            ROOT,
            web_pid=1,
            status={"pid": 4242},
            extra_pids=[],
            flask_bot_alive=False,
            include_children=False,
            inspect_fn=inspect_fn,
        )
        self.assertFalse(result["allow"])
        self.assertEqual(result["pid"], 4242)


if __name__ == "__main__":
    unittest.main()
