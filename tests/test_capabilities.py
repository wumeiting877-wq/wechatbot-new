# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from capabilities import NOT_CONFIGURED, READY, DISABLED, evaluate_capabilities, optional_enabled_flags


class CapabilityTests(unittest.TestCase):
    def test_enabled_and_configured_ready(self):
        caps = evaluate_capabilities({
            "DEEPSEEK_API_KEY": "sk-real",
            "ENABLE_IMAGE_RECOGNITION": True,
            "MOONSHOT_API_KEY": "sk-vision",
        })
        self.assertEqual(caps["main_model"]["status"], READY)
        self.assertEqual(caps["image_recognition"]["status"], READY)

    def test_enabled_missing_key_not_configured(self):
        caps = evaluate_capabilities({
            "DEEPSEEK_API_KEY": "sk-real",
            "ENABLE_IMAGE_RECOGNITION": True,
            "MOONSHOT_API_KEY": "YOUR_API_KEY",
            "ENABLE_ONLINE_API": True,
            "ONLINE_API_KEY": "",
            "ENABLE_ASSISTANT_MODEL": True,
            "ASSISTANT_API_KEY": "",
        })
        self.assertEqual(caps["image_recognition"]["status"], NOT_CONFIGURED)
        self.assertEqual(caps["online_search"]["status"], NOT_CONFIGURED)
        self.assertEqual(caps["assistant_model"]["status"], NOT_CONFIGURED)
        flags = optional_enabled_flags({
            "DEEPSEEK_API_KEY": "sk-real",
            "ENABLE_IMAGE_RECOGNITION": True,
            "MOONSHOT_API_KEY": "YOUR_API_KEY",
            "ENABLE_ONLINE_API": True,
            "ONLINE_API_KEY": "",
            "ENABLE_ASSISTANT_MODEL": True,
            "ASSISTANT_API_KEY": "",
        })
        self.assertFalse(flags["ENABLE_IMAGE_RECOGNITION"])
        self.assertFalse(flags["ENABLE_ONLINE_API"])
        self.assertFalse(flags["ENABLE_ASSISTANT_MODEL"])

    def test_disabled(self):
        caps = evaluate_capabilities({
            "DEEPSEEK_API_KEY": "sk-real",
            "ENABLE_ONLINE_API": False,
            "ONLINE_API_KEY": "sk-search",
        })
        self.assertEqual(caps["online_search"]["status"], DISABLED)

    def test_unsupported_voice_and_restart_disabled(self):
        caps = evaluate_capabilities({"DEEPSEEK_API_KEY": "sk-real"})
        self.assertEqual(caps["voice_stt"]["status"], DISABLED)
        self.assertEqual(caps["merged_forward"]["status"], DISABLED)
        self.assertEqual(caps["scheduled_restart"]["status"], DISABLED)

    def test_wechat_error(self):
        caps = evaluate_capabilities(
            {"DEEPSEEK_API_KEY": "sk-real"},
            {"wechat": "disconnected", "state": "ERROR"},
        )
        self.assertEqual(caps["wechat"]["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
