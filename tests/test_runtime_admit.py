# -*- coding: utf-8 -*-
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from message.identity import InboundMessage, RuntimeIdentity, is_self_message
from message.trigger import NO_ACTION, REPLY


class AdmitMessageTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.runtime.set_identity(bot_wxid="wxid_bot", bot_name="BotSelf")

    def test_accept_normal_friend_message(self):
        ok, reason = self.runtime.admit_message("chat1", "id-1", "Alice", "friend", "你好")
        self.assertTrue(ok)
        self.assertIn(reason, ("ok", "private_listen_list"))

    def test_drop_duplicate_message_id(self):
        self.runtime.admit_message("chat1", "id-1", "Alice", "friend", "你好")
        ok, reason = self.runtime.admit_message("chat1", "id-1", "Alice", "friend", "你好")
        self.assertFalse(ok)
        self.assertIn("duplicate", reason)

    def test_drop_confirmed_self_wxid(self):
        inbound = InboundMessage(
            platform_message_id="id-2",
            conversation_id="chat1",
            chat_name="chat1",
            sender_wxid="wxid_bot",
            content="我自己发的",
        )
        verdict = self.runtime.evaluate_inbound(inbound, listen_users=["chat1"])
        self.assertEqual(verdict["action"], NO_ACTION)
        self.assertEqual(verdict["reason"], "sender_wxid_equals_bot_wxid")

    def test_nickname_alone_is_not_self(self):
        ok, reason = self.runtime.admit_message("chat1", "id-3", "BotSelf", "friend", "机器人号发的")
        self.assertTrue(ok, reason)

    def test_drop_when_stopped(self):
        self.runtime.set_state("STOPPED", "test stop")
        ok, reason = self.runtime.admit_message("chat1", "id-4", "Alice", "friend", "停机后")
        self.assertFalse(ok)
        self.assertEqual(reason, "stopped")


if __name__ == "__main__":
    unittest.main()
