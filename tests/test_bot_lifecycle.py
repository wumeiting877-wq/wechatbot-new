# -*- coding: utf-8 -*-
"""P6-G0 FIX-LIFECYCLE：LIFE-01 ～ LIFE-08、N2 防误修、OBS purpose。不连真实微信。"""

from __future__ import annotations

import inspect
import os
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_lifecycle import (
    KEEP_ALIVE_JOIN_TIMEOUT_SEC,
    KEEP_ALIVE_SKIP_LIFECYCLE,
    join_keep_alive_thread,
    keep_alive_may_add_listen,
    keep_alive_should_exit,
    keep_alive_tick,
    run_keep_alive_loop,
)
from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED
from llm_client import _extractor_log_purpose, get_extractor_response
from message.identity import InboundMessage
from message.trigger import NO_ACTION, REPLY
from risk_engine import RISK_ENGINE_ENABLED
from task_engine import TASK_ENGINE_ENABLED
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_sidepath import SKIP_STOPPED, TopicSidepath, try_enqueue_topic_sidepath
from topic_store import TopicStore, make_message_id
from webui_bot_process import (
    collect_candidate_bot_pids,
    inspect_bot_process,
    start_bot_preflight,
    status_pid,
)


def _inbound(**kwargs):
    data = {
        "platform_message_id": kwargs.pop("platform_message_id", "pid-1"),
        "conversation_id": kwargs.pop("conversation_id", "wxid_ceshi"),
        "chat_name": kwargs.pop("chat_name", "ceshi"),
        "chat_wxid": kwargs.pop("chat_wxid", "wxid_ceshi"),
        "sender_id": kwargs.pop("sender_id", 42),
        "sender_wxid": kwargs.pop("sender_wxid", "wxid_ceshi"),
        "sender_name": kwargs.pop("sender_name", "ceshi"),
        "content": kwargs.pop("content", "你好"),
        "raw_type": kwargs.pop("raw_type", "text"),
        "direction": kwargs.pop("direction", "INBOUND"),
        "create_time": kwargs.pop("create_time", 1000),
    }
    data.update(kwargs)
    return InboundMessage(**data)


class FakeWx:
    def __init__(self, listen=None):
        self.listen = dict(listen or {})
        self.add_calls = []
        self.stop_calls = 0

    def AddListenChat(self, nickname=None, callback=None, **kwargs):
        self.add_calls.append(nickname)
        self.listen[nickname] = (object(), callback)
        return True

    def StopListening(self, remove=True):
        self.stop_calls += 1
        if remove:
            self.listen.clear()


def _inspect_script(pid, project_dir, web_pid=None, expected_create_time=None):
    mapping = getattr(_inspect_script, "mapping", {})
    if pid in mapping:
        return mapping[pid]
    return {"ok": False, "reason": "pid_not_running", "pid": pid, "info": {}}


class LifecycleKeepAliveTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.runtime = BotRuntime()
        self.runtime.set_state("STARTING", "test")
        self.runtime.set_state("RUNNING", "test")
        self.wx = FakeWx()
        self.callback = lambda *args, **kwargs: None

    def test_life_01_running_keep_alive_adds_one_listener(self):
        result = keep_alive_tick(
            runtime=self.runtime,
            wx=self.wx,
            expected_users=["ceshi"],
            callback=self.callback,
        )
        self.assertEqual(result["add_listen_count"], 1)
        self.assertEqual(self.wx.add_calls, ["ceshi"])
        self.assertEqual(len(self.wx.listen), 1)
        stop = self.runtime.lifecycle_stop_event()
        waits = []

        def wait(timeout):
            waits.append(timeout)
            return len(waits) >= 1

        thread = threading.Thread(
            target=run_keep_alive_loop,
            kwargs={
                "runtime": self.runtime,
                "get_wx": lambda: self.wx,
                "get_expected_users": lambda: ["ceshi"],
                "callback": self.callback,
                "stop_event": stop,
                "interval": 0.01,
                "wait": wait,
            },
            name="keep_alive",
            daemon=True,
        )
        thread.start()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(self.wx.listen), 1)
        self.assertGreaterEqual(len(waits), 1)

    def test_life_02_stopping_keep_alive_does_not_add_listen(self):
        self.runtime.begin_graceful_stop("life-02")
        self.assertEqual(self.runtime.state, "STOPPED")
        self.runtime.set_state("STOPPING", "life-02-hold")
        self.runtime.signal_lifecycle_stop()
        self.assertFalse(keep_alive_may_add_listen(self.runtime))
        result = keep_alive_tick(
            runtime=self.runtime,
            wx=self.wx,
            expected_users=["ceshi"],
            callback=self.callback,
        )
        self.assertEqual(result["add_listen_count"], 0)
        self.assertEqual(result["skipped_reason"], KEEP_ALIVE_SKIP_LIFECYCLE)
        self.assertEqual(self.wx.add_calls, [])

    def test_life_03_stop_listening_does_not_reregister(self):
        keep_alive_tick(
            runtime=self.runtime,
            wx=self.wx,
            expected_users=["ceshi"],
            callback=self.callback,
        )
        self.assertEqual(len(self.wx.listen), 1)
        self.wx.StopListening(True)
        self.assertEqual(self.wx.listen, {})
        self.runtime.set_state("STOPPING", "life-03")
        self.runtime.signal_lifecycle_stop()
        for _ in range(4):
            result = keep_alive_tick(
                runtime=self.runtime,
                wx=self.wx,
                expected_users=["ceshi"],
                callback=self.callback,
            )
            self.assertEqual(result["add_listen_count"], 0)
        self.assertEqual(self.wx.listen, {})
        self.assertEqual(self.wx.add_calls, ["ceshi"])

    def test_life_04_start_stop_start_single_listener(self):
        keep_alive_tick(
            runtime=self.runtime,
            wx=self.wx,
            expected_users=["ceshi"],
            callback=self.callback,
        )
        self.assertEqual(len(self.wx.listen), 1)
        self.runtime.begin_graceful_stop("life-04-stop")
        self.wx.StopListening(True)
        keep_alive_tick(
            runtime=self.runtime,
            wx=self.wx,
            expected_users=["ceshi"],
            callback=self.callback,
        )
        self.assertEqual(self.wx.listen, {})
        self.runtime.set_state("STARTING", "life-04-start")
        self.runtime.set_state("RUNNING", "life-04-run")
        keep_alive_tick(
            runtime=self.runtime,
            wx=self.wx,
            expected_users=["ceshi"],
            callback=self.callback,
        )
        self.assertEqual(len(self.wx.listen), 1)
        self.assertEqual(self.wx.add_calls.count("ceshi"), 2)

    def test_stopped_keep_alive_thread_exits(self):
        stop = threading.Event()
        started = threading.Event()

        def wait(timeout):
            started.set()
            return stop.wait(timeout)

        thread = threading.Thread(
            target=run_keep_alive_loop,
            kwargs={
                "runtime": self.runtime,
                "get_wx": lambda: self.wx,
                "get_expected_users": lambda: ["ceshi"],
                "callback": self.callback,
                "stop_event": stop,
                "interval": 0.05,
                "wait": wait,
            },
            name="keep_alive",
            daemon=True,
        )
        thread.start()
        self.assertTrue(started.wait(1))
        self.assertTrue(thread.is_alive())
        self.runtime.begin_graceful_stop("life-exit")
        stop.set()
        exited = join_keep_alive_thread(thread, timeout=KEEP_ALIVE_JOIN_TIMEOUT_SEC)
        self.assertTrue(exited)
        self.assertFalse(thread.is_alive())
        self.assertTrue(keep_alive_should_exit(self.runtime, stop))

    def test_join_keep_alive_has_timeout(self):
        blocker = threading.Event()

        def hang():
            blocker.wait(30)

        thread = threading.Thread(target=hang, name="keep_alive_hang", daemon=True)
        thread.start()
        started = time.perf_counter()
        done = join_keep_alive_thread(thread, timeout=0.2)
        elapsed = time.perf_counter() - started
        blocker.set()
        self.assertFalse(done)
        self.assertLess(elapsed, 1.5)
        self.assertGreaterEqual(KEEP_ALIVE_JOIN_TIMEOUT_SEC, 0.05)
        self.assertLess(KEEP_ALIVE_JOIN_TIMEOUT_SEC, 10)

    def test_bot_py_keep_alive_no_unconditional_while_true(self):
        path = os.path.join(ROOT, "bot.py")
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        start = text.find("def keep_alive(")
        end = text.find("def handle_emoji_message(", start)
        body = text[start:end]
        self.assertIn("run_keep_alive_loop(", body)
        self.assertNotIn("while True:", body)
        self.assertIn("join_keep_alive_thread(", text)
        self.assertIn("KEEP_ALIVE_JOIN_TIMEOUT_SEC", text)


class LifecycleStartGuardTests(unittest.TestCase):
    def setUp(self):
        self.project = ROOT
        _inspect_script.mapping = {}

    def _ok(self, pid):
        return {
            "ok": True,
            "reason": "bot_process",
            "pid": pid,
            "info": {
                "cmdline_text": os.path.join(self.project, "bot.py"),
                "cwd": self.project,
            },
        }

    def test_life_05_status_pid_alive_refuses_second_popen(self):
        _inspect_script.mapping = {4242: self._ok(4242)}
        result = start_bot_preflight(
            self.project,
            web_pid=1,
            status={"pid": 4242, "state": "RUNNING"},
            extra_pids=[],
            flask_bot_alive=False,
            include_children=False,
            inspect_fn=_inspect_script,
        )
        self.assertFalse(result["allow"])
        self.assertEqual(result["reason"], "living_project_bot")
        self.assertEqual(result["pid"], 4242)

    def test_life_05b_flask_handle_alive_refuses(self):
        result = start_bot_preflight(
            self.project,
            web_pid=1,
            status={},
            extra_pids=[],
            flask_bot_alive=True,
            include_children=False,
            inspect_fn=_inspect_script,
        )
        self.assertFalse(result["allow"])
        self.assertEqual(result["reason"], "flask_bot_process_alive")

    def test_life_06_stale_pid_allows_start(self):
        _inspect_script.mapping = {
            7777: {"ok": False, "reason": "pid_not_running", "pid": 7777, "info": {}},
        }
        result = start_bot_preflight(
            self.project,
            web_pid=1,
            status={"pid": 7777, "state": "STOPPED"},
            extra_pids=[],
            flask_bot_alive=False,
            include_children=False,
            inspect_fn=_inspect_script,
        )
        self.assertTrue(result["allow"])
        self.assertEqual(result["reason"], "no_living_project_bot")

    def test_life_07_pid_reuse_not_identified_as_bot(self):
        reused = 8888
        _inspect_script.mapping = {
            reused: {
                "ok": False,
                "reason": "cmdline_not_bot",
                "pid": reused,
                "info": {"cmdline_text": "python other_app.py"},
            },
        }
        result = start_bot_preflight(
            self.project,
            web_pid=1,
            status={"pid": reused},
            extra_pids=[],
            flask_bot_alive=False,
            include_children=False,
            inspect_fn=_inspect_script,
        )
        self.assertTrue(result["allow"])
        self.assertEqual(result["bots"], [])
        verdict = _inspect_script(reused, self.project, web_pid=1)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"], "cmdline_not_bot")

    def test_life_07_real_inspect_current_process_is_not_bot(self):
        verdict = inspect_bot_process(os.getpid(), ROOT, web_pid=webui_pid_offset())
        self.assertFalse(verdict["ok"])
        self.assertIn(verdict["reason"], ("cmdline_not_bot", "pid_is_config_editor", "not_this_project"))

    def test_status_pid_helper_and_candidates_do_not_include_webui(self):
        self.assertEqual(status_pid({"pid": 12}), 12)
        self.assertIsNone(status_pid({"pid": 0}))
        pids = collect_candidate_bot_pids(
            status={"pid": 99},
            extra_pids=[99, 1],
            web_pid=1,
            include_children=False,
        )
        self.assertIn(99, pids)
        self.assertNotIn(1, pids)

    def test_start_bot_route_uses_preflight(self):
        editor = os.path.join(ROOT, "config_editor.py")
        with open(editor, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("start_bot_preflight(", text)
        self.assertIn("already_running", text)
        self.assertIn("read_status_file()", text)
        self.assertNotIn("taskkill", text.lower())


def webui_pid_offset():
    return os.getpid() + 10**7


class LifecycleStopCallbackTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.runtime.set_identity(bot_wxid="wxid_bot", bot_name="扶级", login_account="扶级")

    def test_life_08_after_stop_callback_reason_stopped(self):
        self.runtime.begin_graceful_stop("life-08")
        inbound = _inbound(platform_message_id="after-stop-life08", content="停后新消息")
        verdict = self.runtime.evaluate_inbound(inbound, listen_users=["ceshi"])
        self.assertEqual(verdict["action"], NO_ACTION)
        self.assertEqual(verdict["reason"], "stopped")
        tmp = tempfile.TemporaryDirectory()
        try:
            sidepath = TopicSidepath(enabled=True, root_dir=tmp.name, maxsize=1)
            result = try_enqueue_topic_sidepath(
                inbound, verdict, runtime=self.runtime, sidepath=sidepath
            )
            self.assertFalse(result["enqueued"])
            self.assertEqual(result["reason"], SKIP_STOPPED)
            sidepath.shutdown()
        finally:
            tmp.cleanup()
        self.assertFalse(self.runtime.submit_send(lambda: None))
        self.assertTrue(self.runtime.llm_aborted())

    def test_n2_same_text_different_platform_id_two_new(self):
        first = self.runtime.evaluate_inbound(
            _inbound(platform_message_id="room@chatroom:115", content="同一句话"),
            listen_users=["ceshi"],
        )
        second = self.runtime.evaluate_inbound(
            _inbound(platform_message_id="room@chatroom:116", content="同一句话"),
            listen_users=["ceshi"],
        )
        self.assertEqual(first["action"], REPLY)
        self.assertEqual(second["action"], REPLY)
        self.assertEqual(first["dedupe"], "NEW")
        self.assertEqual(second["dedupe"], "NEW")
        self.assertEqual(first["message"]["platform_message_id"], "room@chatroom:115")
        self.assertEqual(second["message"]["platform_message_id"], "room@chatroom:116")

    def test_engine_flags_remain_false(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)


class N2StoreAntiRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = TopicStore(self.tmpdir.name)
        self.cid = "conv_n2lock00001"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_n2_same_content_different_platform_ids_two_message_records(self):
        a = self.store.upsert_message(
            {
                "conversation_id": self.cid,
                "platform_message_id": "room@chatroom:115",
                "content": "同一句话",
                "sender_name": "陈总",
            }
        )
        b = self.store.upsert_message(
            {
                "conversation_id": self.cid,
                "platform_message_id": "room@chatroom:116",
                "content": "同一句话",
                "sender_name": "陈总",
            }
        )
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(a["id"], make_message_id(self.cid, "room@chatroom:115"))
        self.assertEqual(b["id"], make_message_id(self.cid, "room@chatroom:116"))
        self.assertEqual(len(self.store.list_messages(self.cid)), 2)


class ExtractorObsTests(unittest.TestCase):
    def test_purpose_labels_are_distinct(self):
        self.assertEqual(_extractor_log_purpose("topic_extractor"), "topic_extractor")
        self.assertEqual(_extractor_log_purpose("task_extractor"), "task_extractor")
        self.assertEqual(_extractor_log_purpose("decision_extractor"), "decision_extractor")
        self.assertEqual(_extractor_log_purpose("risk_extractor"), "risk_extractor")
        self.assertEqual(_extractor_log_purpose("unknown"), "topic_extractor")

    def test_get_extractor_response_signature_keeps_request_contract(self):
        source = inspect.getsource(get_extractor_response)
        self.assertIn("store_context=False", source)
        self.assertIn("purpose=", source)
        self.assertIn("_extractor_log_purpose", source)
        self.assertNotIn("get_user_prompt", source)
        self.assertNotIn("get_deepseek_response", source)
        idx = source.find("chat.completions.create")
        self.assertGreaterEqual(idx, 0)
        create_block = source[idx : idx + 280]
        self.assertNotIn("purpose=", create_block)

    def test_clients_pass_distinct_purpose(self):
        from decision_extractor_client import _default_extractor_llm_call as decision_call
        from risk_extractor_client import _default_extractor_llm_call as risk_call
        from task_extractor_client import _default_extractor_llm_call as task_call
        from topic_extractor_client import _default_extractor_llm_call as topic_call

        self.assertIn('purpose", "topic_extractor"', inspect.getsource(topic_call))
        self.assertIn('purpose", "task_extractor"', inspect.getsource(task_call))
        self.assertIn('purpose", "decision_extractor"', inspect.getsource(decision_call))
        self.assertIn('purpose", "risk_extractor"', inspect.getsource(risk_call))


if __name__ == "__main__":
    unittest.main()
