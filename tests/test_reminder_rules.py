# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from reminder_rules import looks_like_reminder


class ReminderRulesTests(unittest.TestCase):
    def test_ordinary_chat_skips_parser(self):
        self.assertFalse(looks_like_reminder("今天天气不错，一起吃饭吧"))
        self.assertFalse(looks_like_reminder("你好啊"))

    def test_explicit_reminder_enters_parser(self):
        self.assertTrue(looks_like_reminder("提醒我明天八点开会"))
        self.assertTrue(looks_like_reminder("10分钟后叫我"))
        self.assertTrue(looks_like_reminder("每天早上叫我起床"))


if __name__ == "__main__":
    unittest.main()
