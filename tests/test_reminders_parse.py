# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from reminders import extract_last_json_or_null


class ReminderParseTests(unittest.TestCase):
    def test_plain_null(self):
        self.assertEqual(extract_last_json_or_null("null"), "null")
        self.assertEqual(extract_last_json_or_null("```json\nNULL\n```"), "null")

    def test_extract_last_object(self):
        text = '先说一句 {"a": 1} 然后再 {"type": "delay", "ok": true}'
        result = extract_last_json_or_null(text)
        self.assertIn('"type"', result)
        self.assertIn("delay", result)

    def test_markdown_json_block(self):
        text = '```json\n{"reminder_type": "daily"}\n```'
        result = extract_last_json_or_null(text)
        self.assertIn("daily", result)

    def test_no_json_returns_none(self):
        self.assertIsNone(extract_last_json_or_null("今天天气不错"))


if __name__ == "__main__":
    unittest.main()
