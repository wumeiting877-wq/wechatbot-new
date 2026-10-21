# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from message.reply_format import (
    WeChatPlainTextFormatter,
    split_message_with_context,
    strip_markdown_for_wechat,
)


class WechatReplyFormatTests(unittest.TestCase):
    def test_a01_strip_heading(self):
        cleaned = strip_markdown_for_wechat("## 当前状态")
        self.assertEqual(cleaned, "当前状态")
        self.assertNotIn("#", cleaned)

    def test_a02_strip_bold(self):
        cleaned = strip_markdown_for_wechat("**当前状态说明**")
        self.assertEqual(cleaned, "当前状态说明")
        self.assertNotIn("**", cleaned)

    def test_strip_bold_and_heading(self):
        raw = "收到，链路正常。\n\n**当前状态说明**\n链路已通。"
        cleaned = strip_markdown_for_wechat(raw)
        self.assertNotIn("**", cleaned)
        self.assertIn("当前状态说明", cleaned)
        self.assertIn("收到，链路正常。", cleaned)

    def test_a03_markdown_table(self):
        raw = "| 名称 | 状态 |\n| --- | --- |\n| ERP | 完成 |"
        cleaned = strip_markdown_for_wechat(raw)
        self.assertNotIn("|---|---|", cleaned.replace(" ", ""))
        self.assertNotIn("| --- | --- |", cleaned)
        self.assertNotRegex(cleaned, r"\|?\s*:?-{3,}")
        self.assertIn("名称：ERP", cleaned)
        self.assertIn("状态：完成", cleaned)

    def test_table_compact_and_aligned(self):
        raw = "|名称|状态|\n|:---|---:|\n|ERP|完成|"
        cleaned = strip_markdown_for_wechat(raw)
        self.assertNotIn("|", cleaned)
        self.assertIn("名称：ERP", cleaned)
        self.assertIn("状态：完成", cleaned)

    def test_table_multiple_rows(self):
        raw = (
            "| 负责人 | 任务 | 状态 |\n"
            "| --- | --- | --- |\n"
            "| 王强 | 数据处理 | 已完成 |\n"
            "| 李娜 | 权限修复 | 进行中 |"
        )
        cleaned = strip_markdown_for_wechat(raw)
        self.assertIn("负责人：王强", cleaned)
        self.assertIn("任务：数据处理", cleaned)
        self.assertIn("状态：已完成", cleaned)
        self.assertIn("负责人：李娜", cleaned)
        self.assertIn("任务：权限修复", cleaned)
        self.assertIn("状态：进行中", cleaned)
        self.assertNotIn("|---|", cleaned.replace(" ", ""))

    def test_does_not_strip_business_pipe(self):
        raw = "对比结果：A | B"
        cleaned = strip_markdown_for_wechat(raw)
        self.assertEqual(cleaned, "对比结果：A | B")

    def test_a04_mixed_markdown_still_one_message(self):
        raw = (
            "## 当前状态\n"
            "**说明**\n"
            "| 名称 | 状态 |\n"
            "| --- | --- |\n"
            "| ERP | 完成 |\n"
            "1. 第一项\n"
            "- 第二项"
        )
        cleaned = strip_markdown_for_wechat(raw)
        parts = split_message_with_context(cleaned)
        self.assertEqual(len(parts), 1)
        self.assertIn("当前状态", parts[0])
        self.assertIn("说明", parts[0])
        self.assertIn("名称：ERP", parts[0])
        self.assertIn("1. 第一项", parts[0])
        self.assertIn("- 第二项", parts[0])
        self.assertNotIn("**", parts[0])
        self.assertNotIn("|---|", parts[0].replace(" ", ""))

    def test_code_fence_removed_but_content_kept(self):
        raw = "```\nprint('hello')\n```"
        cleaned = strip_markdown_for_wechat(raw)
        self.assertNotIn("```", cleaned)
        self.assertIn("print('hello')", cleaned)

    def test_code_fence_table_not_converted(self):
        raw = "```\n| a | b |\n| --- | --- |\n| 1 | 2 |\n```"
        cleaned = strip_markdown_for_wechat(raw)
        self.assertNotIn("```", cleaned)
        self.assertIn("| a | b |", cleaned)
        self.assertNotIn("a：1", cleaned)

    def test_split_keeps_multiline_as_one_message(self):
        raw = "收到，链路正常。\n\n当前状态说明\n链路已通。"
        parts = split_message_with_context(raw)
        self.assertEqual(len(parts), 1)
        self.assertIn("收到，链路正常。", parts[0])
        self.assertIn("当前状态说明", parts[0])

    def test_dollar_does_not_split(self):
        parts = split_message_with_context("Hello$World$Python")
        self.assertEqual(parts, ["Hello$World$Python"])

    def test_tickle_still_separate(self):
        parts = split_message_with_context("先说话[tickle]再拍一拍")
        self.assertEqual(parts, ["先说话", "[tickle]", "再拍一拍"])

    def test_formatter_class_used(self):
        self.assertEqual(WeChatPlainTextFormatter().format("## 标题"), "标题")


if __name__ == "__main__":
    unittest.main()
