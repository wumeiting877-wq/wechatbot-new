# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime


class LlmMetricsTests(unittest.TestCase):
    def setUp(self):
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")

    def test_note_llm_call_counts_and_snapshot(self):
        self.runtime.note_llm_call("main_chat", "main", 120.5, True, "", 10, 20)
        self.runtime.note_llm_call("online_detect", "assistant", 30, True, "", 4, 2)
        self.runtime.note_llm_call("main_chat", "main", 80, False, "TIMEOUT")
        snap = self.runtime.snapshot()
        self.assertEqual(snap["today_llm_calls"], 3)
        self.assertEqual(snap["today_llm_main"], 2)
        self.assertEqual(snap["today_llm_assistant"], 1)
        self.assertEqual(snap["today_llm_failed"], 1)
        self.assertEqual(snap["today_llm_prompt_tokens"], 14)
        self.assertEqual(snap["today_llm_completion_tokens"], 22)
        self.assertEqual(snap["recent_llm"][0]["ok"], False)
        self.assertEqual(snap["recent_llm"][0]["error"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
