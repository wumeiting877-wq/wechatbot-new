# -*- coding: utf-8 -*-
"""P4-G1 Gate 2：TASK_EXTRACTOR Prompt 隔离 + 独立 parser。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_store import DEFAULT_EXTRACTOR_PROMPT_NAME, resolve_extractor_prompt
from task_extractor_client import (
    EXTRACTOR_MAX_TOKENS,
    EXTRACTOR_TEMPERATURE,
    TaskExtractorClient,
    TaskExtractorError,
    parse_task_extractor_json,
)
from webui_data import list_prompt_names


def _read(relpath):
    with open(os.path.join(ROOT, relpath), "r", encoding="utf-8") as handle:
        return handle.read()


class TaskExtractorPromptIsolationTests(unittest.TestCase):
    def test_task_extractor_file_exists_and_schema_intact(self):
        binding = resolve_extractor_prompt("TASK_EXTRACTOR", root_dir=ROOT)
        self.assertEqual(binding.prompt_name, "TASK_EXTRACTOR")
        self.assertIn("NEW_TASK", binding.content)
        self.assertIn("TASK_UPDATE", binding.content)
        self.assertIn("UNRELATED", binding.content)
        self.assertIn("assignee_text", binding.content)
        self.assertIn("due_text", binding.content)
        self.assertIn("禁止输出 due_at、status、DONE、TASK_COMPLETE", binding.content)
        self.assertNotIn("TASK_COMPLETE", binding.content.split("禁止输出")[0])

    def test_default_extractor_name_remains_topic(self):
        self.assertEqual(DEFAULT_EXTRACTOR_PROMPT_NAME, "TOPIC_EXTRACTOR")

    def test_three_prompts_physically_isolated(self):
        qiye = _read(os.path.join("prompts", "QIYE.md"))
        qiye2 = _read(os.path.join("prompts", "企业_1.md"))
        topic = _read(os.path.join("prompts", "extractors", "TOPIC_EXTRACTOR.md"))
        task = _read(os.path.join("prompts", "extractors", "TASK_EXTRACTOR.md"))
        for chat in (qiye, qiye2):
            self.assertNotIn('"decision": "NEW_TASK', chat)
            self.assertNotIn("TASK_UPDATE", chat)
            self.assertNotIn("assignee_text", chat)
        self.assertNotIn("NEW_TASK", topic)
        self.assertNotIn("TASK_UPDATE", topic)
        self.assertNotIn("assignee_text", topic)
        self.assertIn("禁止输出 tasks", topic)
        self.assertIn("你是后台工作事项抽取器", task)
        self.assertNotEqual(qiye, task)
        self.assertNotEqual(topic, task)

    def test_task_extractor_not_in_chat_prompt_list(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            names = list_prompt_names()
        finally:
            os.chdir(cwd)
        self.assertIn("QIYE", names)
        self.assertNotIn("TASK_EXTRACTOR", names)
        self.assertNotIn("TOPIC_EXTRACTOR", names)
        self.assertNotIn("extractors/TASK_EXTRACTOR", names)


class TaskExtractorParserTests(unittest.TestCase):
    def test_parses_fenced_json_and_strips_forbidden_keys(self):
        raw = """```json
{"decisions":[{"decision":"NEW_TASK","task_id":null,"title":"处理空值规则",
"description":"","assignee_text":"王强","due_text":"今天 16 点前","due_at":"2026-09-20T16:00:00",
"confidence":"HIGH","evidence_message_ids":["msg_1"],"reason":"x","assignee_id":"u1",
"status":"DONE","risks":[],"progress":1}]}
```"""
        parsed = parse_task_extractor_json(raw)
        item = parsed["decisions"][0]
        self.assertEqual(item["decision"], "NEW_TASK")
        self.assertEqual(item["assignee_text"], "王强")
        self.assertEqual(item["due_text"], "今天 16 点前")
        self.assertNotIn("due_at", item)
        self.assertNotIn("assignee_id", item)
        self.assertNotIn("status", item)
        self.assertNotIn("risks", item)

    def test_task_complete_is_illegal(self):
        with self.assertRaises(TaskExtractorError) as ctx:
            parse_task_extractor_json(
                '{"decisions":[{"decision":"TASK_COMPLETE","task_id":"task_x","title":"",'
                '"assignee_text":"","due_text":"","confidence":"HIGH","evidence_message_ids":["m"],"reason":""}]}'
            )
        self.assertEqual(ctx.exception.code, "INVALID_DECISION")

    def test_done_decision_is_illegal(self):
        with self.assertRaises(TaskExtractorError) as ctx:
            parse_task_extractor_json(
                '{"decisions":[{"decision":"DONE","task_id":null,"title":"x","assignee_text":"王强",'
                '"due_text":"","confidence":"HIGH","evidence_message_ids":["m"],"reason":""}]}'
            )
        self.assertEqual(ctx.exception.code, "INVALID_DECISION")

    def test_empty_decisions_invalid(self):
        with self.assertRaises(TaskExtractorError) as ctx:
            parse_task_extractor_json('{"decisions":[]}')
        self.assertEqual(ctx.exception.code, "INVALID_OUTPUT")

    def test_invalid_json(self):
        with self.assertRaises(TaskExtractorError) as ctx:
            parse_task_extractor_json("not-json-at-all")
        self.assertEqual(ctx.exception.code, "JSON_PARSE_ERROR")


class TaskExtractorClientTests(unittest.TestCase):
    def test_client_uses_store_context_false_and_task_schema(self):
        seen = {}

        def llm_call(messages, **kwargs):
            seen["store_context"] = kwargs.get("store_context")
            seen["temperature"] = kwargs.get("temperature")
            seen["max_tokens"] = kwargs.get("max_tokens")
            seen["timeout"] = kwargs.get("timeout")
            seen["messages"] = messages
            return (
                '{"decisions":[{"decision":"UNRELATED","task_id":null,"title":"",'
                '"description":"","assignee_text":"","due_text":"","confidence":"HIGH",'
                '"evidence_message_ids":["msg_1"],"reason":"x","tasks":[]}]}'
            )

        client = TaskExtractorClient(llm_call=llm_call)
        out = client.extract(
            {"current_message": {"id": "msg_1", "content": "hi"}, "existing_tasks": []},
            "prompt",
        )
        self.assertFalse(seen["store_context"])
        self.assertEqual(seen["temperature"], EXTRACTOR_TEMPERATURE)
        self.assertEqual(seen["max_tokens"], EXTRACTOR_MAX_TOKENS)
        self.assertEqual(seen["messages"][0]["role"], "system")
        self.assertEqual(out["decisions"][0]["decision"], "UNRELATED")
        self.assertNotIn("tasks", out["decisions"][0])

    def test_does_not_use_topic_parser_semantics(self):
        parsed = parse_task_extractor_json(
            '{"decisions":[{"decision":"NEW_TASK","task_id":null,"title":"修权限",'
            '"description":"","assignee_text":"李娜","due_text":"","confidence":"HIGH",'
            '"evidence_message_ids":["msg_1"],"reason":""}]}'
        )
        self.assertEqual(parsed["decisions"][0]["assignee_text"], "李娜")
        self.assertEqual(parsed["decisions"][0]["due_text"], "")


if __name__ == "__main__":
    unittest.main()
