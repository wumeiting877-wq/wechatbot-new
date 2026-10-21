# -*- coding: utf-8 -*-
"""P5-G1 Gate 2：DECISION_EXTRACTOR Prompt 隔离 + 独立 parser。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_store import DEFAULT_EXTRACTOR_PROMPT_NAME, resolve_extractor_prompt
from decision_extractor_client import (
    EXTRACTOR_MAX_TOKENS,
    EXTRACTOR_TEMPERATURE,
    DecisionExtractorClient,
    DecisionExtractorError,
    parse_decision_extractor_json,
)
from webui_data import list_prompt_names


def _read(relpath):
    with open(os.path.join(ROOT, relpath), "r", encoding="utf-8") as handle:
        return handle.read()


class DecisionExtractorPromptIsolationTests(unittest.TestCase):
    def test_decision_extractor_file_exists_and_schema_intact(self):
        binding = resolve_extractor_prompt("DECISION_EXTRACTOR", root_dir=ROOT)
        self.assertEqual(binding.prompt_name, "DECISION_EXTRACTOR")
        content = binding.content
        self.assertIn("你不是聊天机器人", content.replace(" ", ""))
        self.assertIn("不要重新做 Topic 分类", content)
        self.assertIn("建议不是 Decision", content)
        self.assertIn("收到 / 好的 / 嗯 / 行。不是 Decision", content)
        self.assertIn("问题事实不是 Decision", content)
        self.assertIn("Task 指派不是 Decision", content)
        self.assertIn("Risk 陈述不是 Decision", content)
        self.assertIn("CREATED_BY 必须是确认句", content)
        self.assertIn("supersedes_decision_id", content)
        self.assertIn("禁止 DECISION_UPDATE", content)
        self.assertIn("禁止自动 SUPERSEDED / CANCELLED", content)
        self.assertIn("不确定 → UNRELATED", content)
        self.assertIn("NEW_DECISION", content)
        self.assertIn("UNRELATED", content)

    def test_default_extractor_name_remains_topic(self):
        self.assertEqual(DEFAULT_EXTRACTOR_PROMPT_NAME, "TOPIC_EXTRACTOR")

    def test_four_prompts_physically_isolated(self):
        qiye = _read(os.path.join("prompts", "QIYE.md"))
        qiye2 = _read(os.path.join("prompts", "企业_1.md"))
        topic = _read(os.path.join("prompts", "extractors", "TOPIC_EXTRACTOR.md"))
        task = _read(os.path.join("prompts", "extractors", "TASK_EXTRACTOR.md"))
        decision = _read(os.path.join("prompts", "extractors", "DECISION_EXTRACTOR.md"))
        for chat in (qiye, qiye2):
            self.assertNotIn('"decision": "NEW_DECISION', chat)
            self.assertNotIn("DECISION_UPDATE", chat)
            self.assertNotIn("supersedes_decision_id", chat)
        self.assertNotIn("NEW_DECISION", topic)
        self.assertNotIn("supersedes_decision_id", topic)
        self.assertNotIn("NEW_DECISION", task)
        self.assertNotIn("supersedes_decision_id", task)
        self.assertIn("你是后台企业决策抽取器", decision)
        self.assertNotEqual(qiye, decision)
        self.assertNotEqual(topic, decision)
        self.assertNotEqual(task, decision)

    def test_decision_extractor_not_in_chat_prompt_list(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            names = list_prompt_names()
        finally:
            os.chdir(cwd)
        self.assertIn("QIYE", names)
        self.assertNotIn("DECISION_EXTRACTOR", names)
        self.assertNotIn("TASK_EXTRACTOR", names)
        self.assertNotIn("TOPIC_EXTRACTOR", names)
        self.assertNotIn("extractors/DECISION_EXTRACTOR", names)


class DecisionExtractorParserTests(unittest.TestCase):
    def test_parses_fenced_json_and_strips_forbidden_keys(self):
        raw = """```json
{"decisions":[{"decision":"NEW_DECISION","decision_id":null,"supersedes_decision_id":null,
"title":"采用异常池方案","decision_text":"就按照异常池方案执行。","confidence":"HIGH",
"evidence_message_ids":["msg_1"],"reason":"x","status":"RECORDED","task_id":"task_x",
"severity":"HIGH","owner":"周敏","assignee":"王强","due":"今天","risk_id":"risk_x"}]}
```"""
        parsed = parse_decision_extractor_json(raw)
        item = parsed["decisions"][0]
        self.assertEqual(item["decision"], "NEW_DECISION")
        self.assertEqual(item["title"], "采用异常池方案")
        self.assertNotIn("status", item)
        self.assertNotIn("task_id", item)
        self.assertNotIn("severity", item)
        self.assertNotIn("owner", item)
        self.assertNotIn("assignee", item)
        self.assertNotIn("due", item)
        self.assertNotIn("risk_id", item)

    def test_decision_update_is_illegal(self):
        with self.assertRaises(DecisionExtractorError) as ctx:
            parse_decision_extractor_json(
                '{"decisions":[{"decision":"DECISION_UPDATE","decision_id":"dec_x","title":"x",'
                '"decision_text":"x","confidence":"HIGH","evidence_message_ids":["m"],"reason":""}]}'
            )
        self.assertEqual(ctx.exception.code, "INVALID_DECISION")

    def test_superseded_decision_is_illegal(self):
        with self.assertRaises(DecisionExtractorError) as ctx:
            parse_decision_extractor_json(
                '{"decisions":[{"decision":"SUPERSEDED","decision_id":null,"title":"",'
                '"decision_text":"","confidence":"HIGH","evidence_message_ids":["m"],"reason":""}]}'
            )
        self.assertEqual(ctx.exception.code, "INVALID_DECISION")

    def test_cancelled_decision_is_illegal(self):
        with self.assertRaises(DecisionExtractorError) as ctx:
            parse_decision_extractor_json(
                '{"decisions":[{"decision":"CANCELLED","decision_id":null,"title":"",'
                '"decision_text":"","confidence":"HIGH","evidence_message_ids":["m"],"reason":""}]}'
            )
        self.assertEqual(ctx.exception.code, "INVALID_DECISION")

    def test_empty_decisions_invalid(self):
        with self.assertRaises(DecisionExtractorError) as ctx:
            parse_decision_extractor_json('{"decisions":[]}')
        self.assertEqual(ctx.exception.code, "INVALID_OUTPUT")

    def test_invalid_json(self):
        with self.assertRaises(DecisionExtractorError) as ctx:
            parse_decision_extractor_json("not-json-at-all")
        self.assertEqual(ctx.exception.code, "JSON_PARSE_ERROR")

    def test_empty_output(self):
        with self.assertRaises(DecisionExtractorError) as ctx:
            parse_decision_extractor_json("")
        self.assertEqual(ctx.exception.code, "EXTRACTOR_EMPTY")


class DecisionExtractorClientTests(unittest.TestCase):
    def test_client_uses_store_context_false_and_decision_schema(self):
        seen = {}

        def llm_call(messages, **kwargs):
            seen["store_context"] = kwargs.get("store_context")
            seen["temperature"] = kwargs.get("temperature")
            seen["max_tokens"] = kwargs.get("max_tokens")
            seen["timeout"] = kwargs.get("timeout")
            seen["messages"] = messages
            return (
                '{"decisions":[{"decision":"UNRELATED","decision_id":null,"supersedes_decision_id":null,'
                '"title":"","decision_text":"","confidence":"HIGH","evidence_message_ids":["msg_1"],'
                '"reason":"x","task_id":"task_x"}]}'
            )

        client = DecisionExtractorClient(llm_call=llm_call)
        out = client.extract(
            {"current_message": {"id": "msg_1", "content": "hi"}, "existing_decisions": []},
            "prompt",
        )
        self.assertFalse(seen["store_context"])
        self.assertEqual(seen["temperature"], EXTRACTOR_TEMPERATURE)
        self.assertEqual(seen["max_tokens"], EXTRACTOR_MAX_TOKENS)
        self.assertEqual(seen["messages"][0]["role"], "system")
        self.assertEqual(out["decisions"][0]["decision"], "UNRELATED")
        self.assertNotIn("task_id", out["decisions"][0])

    def test_does_not_use_topic_or_task_parser_semantics(self):
        parsed = parse_decision_extractor_json(
            '{"decisions":[{"decision":"NEW_DECISION","decision_id":null,"supersedes_decision_id":null,'
            '"title":"采用异常池方案","decision_text":"就按照异常池方案执行。","confidence":"HIGH",'
            '"evidence_message_ids":["msg_1"],"reason":"","assignee_text":"王强","due_text":"17 点"}]}'
        )
        item = parsed["decisions"][0]
        self.assertEqual(item["title"], "采用异常池方案")
        self.assertNotIn("assignee_text", item)
        self.assertNotIn("due_text", item)


if __name__ == "__main__":
    unittest.main()
