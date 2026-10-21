# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from llm_client import strip_before_thought_tags, _llm_purpose, _usage_tokens


class LlmClientTests(unittest.TestCase):
    def test_strip_thought_tags(self):
        self.assertEqual(strip_before_thought_tags("</think>你好"), "你好")
        self.assertEqual(strip_before_thought_tags("</thought>\n正文"), "\n正文")
        self.assertEqual(strip_before_thought_tags("没有标签"), "没有标签")
        self.assertIsNone(strip_before_thought_tags(None))

    def test_purpose_mapping(self):
        self.assertEqual(_llm_purpose("Alice"), "main_chat")
        self.assertEqual(_llm_purpose("system", is_summary=True), "summary")
        self.assertEqual(_llm_purpose("memory_summary"), "summary")

    def test_extractor_log_purpose_distinguishes_engines(self):
        from llm_client import _extractor_log_purpose
        self.assertEqual(_extractor_log_purpose("topic_extractor"), "topic_extractor")
        self.assertEqual(_extractor_log_purpose("task_extractor"), "task_extractor")
        self.assertEqual(_extractor_log_purpose("decision_extractor"), "decision_extractor")
        self.assertEqual(_extractor_log_purpose("risk_extractor"), "risk_extractor")

    def test_usage_tokens_from_dict(self):
        prompt, completion = _usage_tokens({"usage": {"prompt_tokens": 3, "completion_tokens": 7}})
        self.assertEqual((prompt, completion), (3, 7))


if __name__ == "__main__":
    unittest.main()
