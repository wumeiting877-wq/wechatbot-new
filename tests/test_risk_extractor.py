# -*- coding: utf-8 -*-
"""P5-G3 Gate 2：RISK_EXTRACTOR Prompt 隔离 + 独立 parser。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_store import DEFAULT_EXTRACTOR_PROMPT_NAME, resolve_extractor_prompt
from risk_extractor_client import (
    EXTRACTOR_MAX_TOKENS,
    EXTRACTOR_TEMPERATURE,
    RiskExtractorClient,
    RiskExtractorError,
    parse_risk_extractor_json,
)
from webui_data import list_prompt_names


def _read(relpath):
    with open(os.path.join(ROOT, relpath), "r", encoding="utf-8") as handle:
        return handle.read()


class RiskExtractorPromptIsolationTests(unittest.TestCase):
    def test_risk_extractor_file_exists_and_schema_intact(self):
        binding = resolve_extractor_prompt("RISK_EXTRACTOR", root_dir=ROOT)
        self.assertEqual(binding.prompt_name, "RISK_EXTRACTOR")
        content = binding.content
        compact = content.replace(" ", "")
        self.assertIn("你不是聊天机器人", compact)
        self.assertIn("不是风险定级委员会", content)
        self.assertIn("不要重新做 Topic 分类", content)
        self.assertIn("当前问题不是 Risk", content)
        self.assertIn("建议不是 Risk", content)
        self.assertIn("模糊担忧不是 Risk", content)
        self.assertIn("Task 指令不是 Risk", content)
        self.assertIn("Decision 本身不是 Risk", content)
        self.assertIn("condition_text", content)
        self.assertIn("impact_text", content)
        self.assertIn("已恢复不是 RESOLVED", content)
        self.assertIn("禁止 severity", content)
        self.assertIn("禁止自动 MITIGATED", content)
        self.assertIn("禁止自动 RESOLVED", content)
        self.assertIn("禁止自动 CLOSED", content)
        self.assertIn("task_id 可空", content)
        self.assertIn("不确定 → UNRELATED", content)
        self.assertIn("NEW_RISK", content)
        self.assertIn("RISK_UPDATE", content)
        self.assertIn("UNRELATED", content)

    def test_default_extractor_name_remains_topic(self):
        self.assertEqual(DEFAULT_EXTRACTOR_PROMPT_NAME, "TOPIC_EXTRACTOR")

    def test_five_prompts_physically_isolated(self):
        qiye = _read(os.path.join("prompts", "QIYE.md"))
        qiye2 = _read(os.path.join("prompts", "企业_1.md"))
        topic = _read(os.path.join("prompts", "extractors", "TOPIC_EXTRACTOR.md"))
        task = _read(os.path.join("prompts", "extractors", "TASK_EXTRACTOR.md"))
        decision = _read(os.path.join("prompts", "extractors", "DECISION_EXTRACTOR.md"))
        risk = _read(os.path.join("prompts", "extractors", "RISK_EXTRACTOR.md"))
        for chat in (qiye, qiye2):
            self.assertNotIn('"decision": "NEW_RISK', chat)
            self.assertNotIn("RISK_UPDATE", chat)
            self.assertNotIn("condition_text", chat)
        self.assertNotIn("NEW_RISK", topic)
        self.assertNotIn("condition_text", topic)
        self.assertNotIn("NEW_RISK", task)
        self.assertNotIn("NEW_RISK", decision)
        self.assertIn("你是后台企业风险抽取器", risk)
        self.assertNotEqual(qiye, risk)
        self.assertNotEqual(topic, risk)
        self.assertNotEqual(task, risk)
        self.assertNotEqual(decision, risk)

    def test_risk_extractor_not_in_chat_prompt_list(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            names = list_prompt_names()
        finally:
            os.chdir(cwd)
        self.assertIn("QIYE", names)
        self.assertNotIn("RISK_EXTRACTOR", names)
        self.assertNotIn("DECISION_EXTRACTOR", names)
        self.assertNotIn("TASK_EXTRACTOR", names)
        self.assertNotIn("TOPIC_EXTRACTOR", names)
        self.assertNotIn("extractors/RISK_EXTRACTOR", names)

    def test_frozen_extractors_unchanged_markers(self):
        topic = _read(os.path.join("prompts", "extractors", "TOPIC_EXTRACTOR.md"))
        task = _read(os.path.join("prompts", "extractors", "TASK_EXTRACTOR.md"))
        decision = _read(os.path.join("prompts", "extractors", "DECISION_EXTRACTOR.md"))
        self.assertIn("NEW_TOPIC", topic)
        self.assertIn("NEW_TASK", task)
        self.assertIn("NEW_DECISION", decision)
        self.assertNotIn("RISK_EXTRACTOR", topic)
        self.assertNotIn("RISK_EXTRACTOR", task)
        self.assertNotIn("RISK_EXTRACTOR", decision)


class RiskExtractorParserTests(unittest.TestCase):
    def test_parses_fenced_json_and_strips_forbidden_keys(self):
        raw = """```json
{"risks":[{"decision":"NEW_RISK","risk_id":null,"title":"今日未修复将影响明日演示",
"condition_text":"如果今天还修不好","impact_text":"会影响明天现场演示","task_id":null,
"confidence":"HIGH","evidence_message_ids":["msg_1"],"reason":"x","status":"OPEN",
"severity":"CRITICAL","owner":"周敏","due":"明天","decision_id":"dec_x","MITIGATED":true}]}
```"""
        parsed = parse_risk_extractor_json(raw)
        item = parsed["risks"][0]
        self.assertEqual(item["decision"], "NEW_RISK")
        self.assertEqual(item["title"], "今日未修复将影响明日演示")
        self.assertEqual(item["condition_text"], "如果今天还修不好")
        self.assertEqual(item["impact_text"], "会影响明天现场演示")
        self.assertNotIn("status", item)
        self.assertNotIn("severity", item)
        self.assertNotIn("owner", item)
        self.assertNotIn("due", item)
        self.assertNotIn("decision_id", item)
        self.assertNotIn("MITIGATED", item)

    def test_risk_resolved_is_illegal(self):
        with self.assertRaises(RiskExtractorError) as ctx:
            parse_risk_extractor_json(
                '{"risks":[{"decision":"RISK_RESOLVED","risk_id":"risk_x","title":"x",'
                '"condition_text":"x","impact_text":"x","confidence":"HIGH",'
                '"evidence_message_ids":["m"],"reason":""}]}'
            )
        self.assertEqual(ctx.exception.code, "INVALID_DECISION")

    def test_mitigated_resolved_closed_are_illegal(self):
        for decision in ("MITIGATED", "RESOLVED", "CLOSED"):
            with self.assertRaises(RiskExtractorError) as ctx:
                parse_risk_extractor_json(
                    '{"risks":[{"decision":"%s","risk_id":null,"title":"",'
                    '"condition_text":"","impact_text":"","confidence":"HIGH",'
                    '"evidence_message_ids":["m"],"reason":""}]}' % decision
                )
            self.assertEqual(ctx.exception.code, "INVALID_DECISION")

    def test_empty_output_fails(self):
        with self.assertRaises(RiskExtractorError) as ctx:
            parse_risk_extractor_json("")
        self.assertEqual(ctx.exception.code, "EXTRACTOR_EMPTY")

    def test_invalid_json_fails(self):
        with self.assertRaises(RiskExtractorError) as ctx:
            parse_risk_extractor_json("not-json")
        self.assertEqual(ctx.exception.code, "JSON_PARSE_ERROR")

    def test_missing_risks_fails(self):
        with self.assertRaises(RiskExtractorError) as ctx:
            parse_risk_extractor_json('{"decisions":[]}')
        self.assertEqual(ctx.exception.code, "INVALID_OUTPUT")

    def test_client_does_not_reuse_topic_parser(self):
        with open(os.path.join(ROOT, "risk_extractor_client.py"), "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("from topic_extractor_client", source)
        self.assertNotIn("from task_extractor_client", source)
        self.assertNotIn("from decision_extractor_client", source)
        self.assertNotIn("parse_extractor_json(", source)
        self.assertNotIn("parse_task_extractor_json(", source)
        self.assertNotIn("parse_decision_extractor_json(", source)
        self.assertIn("store_context=False", source)
        self.assertEqual(EXTRACTOR_TEMPERATURE, 0.2)
        self.assertEqual(EXTRACTOR_MAX_TOKENS, 1400)

    def test_client_retries_empty_then_succeeds(self):
        calls = {"n": 0}

        def llm_call(messages, **kwargs):
            self.assertFalse(kwargs.get("store_context"))
            calls["n"] += 1
            if calls["n"] == 1:
                return ""
            return (
                '{"risks":[{"decision":"UNRELATED","risk_id":null,"title":"",'
                '"condition_text":"","impact_text":"","task_id":null,"confidence":"HIGH",'
                '"evidence_message_ids":["m"],"reason":"x"}]}'
            )

        client = RiskExtractorClient(llm_call=llm_call)
        parsed = client.extract({"current_message": {"id": "m"}}, "prompt")
        self.assertEqual(parsed["risks"][0]["decision"], "UNRELATED")
        self.assertEqual(calls["n"], 2)

    def test_client_timeout_is_extractor_timeout(self):
        def llm_call(messages, **kwargs):
            raise TimeoutError("llm timeout")

        client = RiskExtractorClient(llm_call=llm_call)
        with self.assertRaises(RiskExtractorError) as ctx:
            client.extract({}, "prompt")
        self.assertEqual(ctx.exception.code, "EXTRACTOR_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
