# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from message.pipeline import (
    PipelineTrace,
    classify_incoming_attr,
    decide_should_process,
    is_empty_content_skippable,
    normalize_typed_content,
    plan_llm_calls_for_text,
)


class PipelineDecisionTests(unittest.TestCase):
    def test_drop_self_tickle(self):
        result = classify_incoming_attr("tickle", "我拍了拍自己")
        self.assertEqual(result["action"], "drop")
        self.assertEqual(result["reason"], "self_tickle")

    def test_attr_self_is_hint_only(self):
        result = classify_incoming_attr("self", "机器人回复")
        self.assertEqual(result["action"], "continue")
        self.assertEqual(result["reason"], "attr_self_hint")

    def test_friend_continues(self):
        result = classify_incoming_attr("friend", "你好")
        self.assertEqual(result["action"], "continue")

    def test_empty_text_skips_media_continues(self):
        self.assertTrue(is_empty_content_skippable("", "text"))
        self.assertFalse(is_empty_content_skippable("", "image"))
        self.assertFalse(is_empty_content_skippable("hi", "text"))

    def test_private_listen_list(self):
        result = decide_should_process(
            "Alice",
            "Alice",
            "你好",
            "text",
            listen_users=["Alice"],
            is_group=False,
        )
        self.assertTrue(result["should_process"])
        self.assertEqual(result["reason"], "private_listen_list")

    def test_private_not_in_list(self):
        result = decide_should_process(
            "Bob",
            "Bob",
            "你好",
            "text",
            listen_users=["Alice"],
            is_group=False,
        )
        self.assertFalse(result["should_process"])

    def test_group_at_trigger(self):
        result = decide_should_process(
            "工作群",
            "张三",
            "@助手 你好",
            "text",
            listen_users=["工作群"],
            is_group=True,
            robot_name="助手",
            enable_at=True,
            probability=100,
            rng=lambda a, b: 1,
        )
        self.assertTrue(result["should_process"])
        self.assertIn("工作群", result["content_for_handler"])
        self.assertIn("你好", result["content_for_handler"])

    def test_normalize_voice_and_link(self):
        self.assertEqual(
            normalize_typed_content("voice", "", {"voice_text": "明天开会"}),
            "[语音消息]: 明天开会",
        )
        self.assertEqual(
            normalize_typed_content("link", "", {"url": "https://example.com"}),
            "[卡片链接]: https://example.com",
        )

    def test_default_text_uses_one_main_model(self):
        plan = plan_llm_calls_for_text(
            "今天天气不错，一起吃饭吧",
            enable_reminders=True,
            enable_online=False,
            assistant_ready=False,
            enable_emoji_sending=False,
        )
        self.assertEqual(plan["main_count"], 1)
        self.assertTrue(plan["default_one_main"])
        self.assertFalse(plan["reminder_hit"])

    def test_online_without_assistant_does_not_add_main(self):
        plan = plan_llm_calls_for_text(
            "今天天气不错",
            enable_online=True,
            assistant_ready=False,
        )
        self.assertEqual(plan["main_count"], 1)
        skipped = [c for c in plan["calls"] if c["purpose"] == "online_detect"]
        self.assertEqual(skipped[0]["kind"], "skipped")

    def test_trace_records_steps_and_llm(self):
        trace = PipelineTrace(chat_id="Alice")
        with trace.step("admit") as step:
            step.reason = "ok"
        with trace.step("main_llm") as step:
            step.add_llm("main", "main_chat")
        self.assertEqual(trace.main_llm_count(), 1)
        data = trace.as_dict()
        self.assertEqual(len(data["steps"]), 2)
        self.assertEqual(data["steps"][1]["llm_calls"][0]["kind"], "main")


if __name__ == "__main__":
    unittest.main()
