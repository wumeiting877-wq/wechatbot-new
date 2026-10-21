# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from group_rules import detect_group_at, evaluate_group_trigger


class GroupRulesTests(unittest.TestCase):
    def test_at_robot_triggers(self):
        result = evaluate_group_trigger(
            "@助手 你好",
            robot_name="助手",
            accept_all=False,
            enable_at=True,
            enable_keyword=False,
            probability=100,
            rng=lambda a, b: 1,
        )
        self.assertTrue(result["should_process"])
        self.assertTrue(result["at_triggered"])
        self.assertEqual(result["processed_content"], "你好")

    def test_keyword_triggers_and_ignores_probability(self):
        result = evaluate_group_trigger(
            "机器人在吗",
            robot_name="助手",
            enable_at=True,
            enable_keyword=True,
            keywords=["机器人"],
            probability=0,
            keyword_ignore_probability=True,
            rng=lambda a, b: 100,
        )
        self.assertTrue(result["should_process"])
        self.assertTrue(result["keyword_triggered"])

    def test_no_trigger(self):
        result = evaluate_group_trigger(
            "随便聊聊",
            robot_name="助手",
            enable_at=True,
            enable_keyword=True,
            keywords=["客服"],
            probability=100,
            rng=lambda a, b: 1,
        )
        self.assertFalse(result["should_process"])

    def test_probability_miss(self):
        result = evaluate_group_trigger(
            "@助手 你好",
            robot_name="助手",
            enable_at=True,
            probability=20,
            keyword_ignore_probability=False,
            rng=lambda a, b: 80,
        )
        self.assertFalse(result["should_process"])
        self.assertIn("未通过", result["reason"])

    def test_detect_at_unicode_separator(self):
        hit, text = detect_group_at("@助手\u2005你好", "助手")
        self.assertTrue(hit)
        self.assertEqual(text, "你好")


if __name__ == "__main__":
    unittest.main()
