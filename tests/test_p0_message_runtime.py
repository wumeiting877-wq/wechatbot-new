# -*- coding: utf-8 -*-
"""P0 消息底座：TEST-01 ~ TEST-12（不依赖真实微信）。"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from message.identity import InboundMessage, RuntimeIdentity, is_self_message
from message.trigger import NO_ACTION, REPLY, decide_trigger


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


class P0MessageRuntimeTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.runtime.set_identity(bot_wxid="wxid_bot", bot_name="扶级", login_account="扶级")
        self.runtime.send_queue.start()
        self.listen = ["ceshi"]

    def _eval(self, inbound, **kwargs):
        return self.runtime.evaluate_inbound(inbound, listen_users=self.listen, **kwargs)

    def test_01_different_device_ceshi_to_robot_inbound(self):
        inbound = _inbound(platform_message_id="t01", sender_wxid="wxid_ceshi", sender_id=88)
        verdict = self._eval(inbound)
        self.assertEqual(verdict["direction"], "INBOUND")
        self.assertEqual(verdict["identity"], "EXTERNAL")
        self.assertEqual(verdict["action"], REPLY)
        self.assertFalse(is_self_message(inbound, self.runtime.identity)["is_self"])

    def test_02_same_phone_clone_sender_id_2_is_not_self(self):
        inbound = _inbound(
            platform_message_id="t02",
            sender_id=2,
            sender_wxid="",
            sender_name="ceshi",
            content="同机分身发来的普通消息",
        )
        self_result = is_self_message(inbound, self.runtime.identity)
        self.assertFalse(self_result["is_self"])
        self.assertEqual(self_result["reason"], "sender_id_2_unconfirmed_identity")
        verdict = self._eval(inbound)
        self.assertEqual(verdict["direction"], "INBOUND")
        self.assertEqual(verdict["identity"], "EXTERNAL")
        self.assertEqual(verdict["action"], REPLY)

    def test_03_bot_send_echo_is_no_action(self):
        self.runtime.register_outbound("wxid_ceshi", "机器人回复内容")
        inbound = _inbound(
            platform_message_id="t03-echo",
            sender_id=2,
            sender_wxid="",
            content="机器人回复内容",
        )
        verdict = self._eval(inbound)
        self.assertEqual(verdict["action"], NO_ACTION)
        self.assertEqual(verdict["direction"], "OUTBOUND")
        self.assertIn("outbound", verdict["reason"])

    def test_04_same_inbound_captured_three_times_processed_once(self):
        replies = 0
        for i in range(3):
            inbound = _inbound(platform_message_id="same-local-id-9", content="只应处理一次")
            verdict = self._eval(inbound)
            if verdict["action"] == REPLY:
                replies += 1
            else:
                self.assertEqual(verdict["dedupe"], "DUPLICATE")
        self.assertEqual(replies, 1)

    def test_05_ten_distinct_messages_not_collapsed(self):
        actions = []
        for i in range(10):
            inbound = _inbound(
                platform_message_id=f"n-{i}",
                content=f"普通消息{i}",
                create_time=2000 + i,
            )
            verdict = self._eval(inbound)
            actions.append(verdict["action"])
        self.assertEqual(actions, [REPLY] * 10)

    def test_05b_user_repeat_same_text_not_all_killed(self):
        first = self._eval(_inbound(platform_message_id="r1", content="重复一句话", create_time=3000))
        second = self._eval(_inbound(platform_message_id="r2", content="重复一句话", create_time=3010))
        self.assertEqual(first["action"], REPLY)
        self.assertEqual(second["action"], REPLY)

    def test_06_stop_blocks_later_send_after_ai_started(self):
        sent = []

        def fake_send():
            sent.append("sent")

        self.assertTrue(self.runtime.submit_send(fake_send))
        time.sleep(0.05)
        self.runtime.begin_graceful_stop("test-06")
        blocked = self.runtime.submit_send(fake_send)
        self.assertFalse(blocked)
        self.assertFalse(self.runtime.ensure_can_send("ceshi"))
        self.assertEqual(self.runtime.state, "STOPPED")

    def test_07_stop_drops_pending_send_queue(self):
        started = threading.Event()
        gate = threading.Event()

        def blocker():
            started.set()
            gate.wait(2)

        self.runtime.submit_send(blocker)
        self.assertTrue(started.wait(1))
        for i in range(5):
            self.runtime.submit_send(lambda i=i: None)
        self.assertGreaterEqual(self.runtime.send_queue.pending(), 5)
        self.runtime.begin_graceful_stop("test-07")
        gate.set()
        time.sleep(0.05)
        self.assertEqual(self.runtime.send_queue.pending(), 0)
        self.assertFalse(self.runtime.ensure_can_send("ceshi"))

    def test_08_stop_interrupts_automation_loop(self):
        cancelled = threading.Event()

        def fake_mouse():
            for _ in range(40):
                if not self.runtime.allow_ui_automation():
                    cancelled.set()
                    return
                time.sleep(0.03)
            return

        worker = threading.Thread(target=fake_mouse)
        worker.start()
        time.sleep(0.05)
        self.runtime.begin_graceful_stop("test-08")
        worker.join(timeout=2)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(self.runtime.allow_ui_automation())

    def test_09_after_stop_new_wechat_message_no_ai_no_mouse(self):
        self.runtime.begin_graceful_stop("test-09")
        inbound = _inbound(platform_message_id="after-stop", content="停后新消息")
        verdict = self._eval(inbound)
        self.assertEqual(verdict["action"], NO_ACTION)
        self.assertEqual(verdict["reason"], "stopped")
        self.assertFalse(self.runtime.submit_send(lambda: None))
        self.assertFalse(self.runtime.allow_ui_automation())
        self.assertTrue(self.runtime.llm_aborted())

    def test_10_start_again_resumes(self):
        self.runtime.begin_graceful_stop("test-10-stop")
        self.runtime.set_state("STARTING", "test-10-start")
        self.runtime.set_state("RUNNING", "test-10-run")
        inbound = _inbound(platform_message_id="after-restart", content="重新启动后")
        verdict = self._eval(inbound)
        self.assertEqual(verdict["action"], REPLY)
        self.assertTrue(self.runtime.ensure_can_send("ceshi"))

    def test_11_bot_reply_does_not_retrigger_twenty_rounds(self):
        ai_calls = 0
        for i in range(20):
            text = f"第{i}轮回复"
            self.runtime.register_outbound("wxid_ceshi", text)
            inbound = _inbound(
                platform_message_id=f"echo-{i}",
                sender_id=2,
                sender_wxid="",
                content=text,
                create_time=4000 + i,
            )
            verdict = self._eval(inbound)
            self.assertEqual(verdict["action"], NO_ACTION, verdict)
            self.assertNotEqual(verdict["action"], REPLY)
            if verdict["action"] == REPLY:
                ai_calls += 1
        self.assertEqual(ai_calls, 0)

    def test_12_verdict_fields_are_explicit(self):
        inbound = _inbound(platform_message_id="log-1", sender_wxid="wxid_ceshi")
        verdict = self._eval(inbound)
        self.assertIn(verdict["direction"], ("INBOUND", "OUTBOUND"))
        self.assertIn(verdict["identity"], ("SELF", "EXTERNAL"))
        self.assertIn(verdict["dedupe"], ("NEW", "DUPLICATE"))
        self.assertIn(verdict["action"], (NO_ACTION, REPLY))
        self.assertTrue(verdict["reason"])
        self_result = is_self_message(inbound, self.runtime.identity)
        self.assertIn("reason", self_result)
        self.assertIn("evidence", self_result)

    def test_confirmed_wxid_is_self(self):
        inbound = _inbound(sender_wxid="wxid_bot", sender_id=2)
        result = is_self_message(inbound, self.runtime.identity)
        self.assertTrue(result["is_self"])
        self.assertEqual(result["reason"], "sender_wxid_equals_bot_wxid")

    def test_two_senders_same_text_not_deduped(self):
        a = self._eval(_inbound(platform_message_id="a1", sender_wxid="wxid_a", sender_id=3, content="同样的话"))
        other = _inbound(
            platform_message_id="b1",
            conversation_id="wxid_other",
            chat_name="other",
            chat_wxid="wxid_other",
            sender_wxid="wxid_b",
            sender_id=4,
            content="同样的话",
        )
        b = self.runtime.evaluate_inbound(other, listen_users=["ceshi", "other"])
        self.assertEqual(a["action"], REPLY)
        self.assertEqual(b["action"], REPLY)

    def test_n2_same_text_different_platform_message_id_two_new(self):
        first = self._eval(_inbound(platform_message_id="n2-A", content="同一句话"))
        second = self._eval(_inbound(platform_message_id="n2-B", content="同一句话"))
        self.assertEqual(first["action"], REPLY)
        self.assertEqual(second["action"], REPLY)
        self.assertEqual(first["dedupe"], "NEW")
        self.assertEqual(second["dedupe"], "NEW")

    def test_outbound_requires_running(self):
        self.runtime.set_state("STOPPING", "test")
        self.runtime._send_blocked.set()
        self.assertFalse(self.runtime.ensure_can_send("ceshi"))


if __name__ == "__main__":
    unittest.main()
