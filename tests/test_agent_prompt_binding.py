# -*- coding: utf-8 -*-
"""P2 Agent / Prompt 绑定完整性：共享 Agent、禁止 fallback、删除保护、hash、日志。"""

from __future__ import annotations

import hashlib
import inspect
import logging
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_store import (
    AGENT_CONFIG_NOT_FOUND,
    AGENT_UNAVAILABLE_USER_MESSAGE,
    PROMPT_EMPTY,
    PROMPT_FILE_NOT_FOUND,
    PromptResolveError,
    ensure_agents_for_conversations,
    resolve_chat_prompt,
    sha256_text,
    update_agents_prompt_hash,
)
from conversation_store import migrate_from_listen_list
from llm_client import get_deepseek_response
from llm_errors import LlmApiError
from module_install import rebind


REAL_LISTEN_LIST = [
    ["ceshi", "企业_1"],
    ["哈", "企业_1"],
    ["QIYE", "QIYE"],
]


class AgentSharingTests(unittest.TestCase):
    def test_07_ceshi_and_ha_share_one_agent(self):
        convs = migrate_from_listen_list({"LISTEN_LIST": REAL_LISTEN_LIST})["conversations"]
        agents = ensure_agents_for_conversations(convs, [])
        prompt_agents = [item for item in agents if item["chat_prompt_name"] == "企业_1"]
        self.assertEqual(len(prompt_agents), 1)
        ceshi = [item for item in convs if item["display_name"] == "ceshi"][0]
        ha = [item for item in convs if item["display_name"] == "哈"][0]
        qiye = [item for item in convs if item["display_name"] == "QIYE"][0]
        self.assertEqual(ceshi["agent_config_id"], prompt_agents[0]["id"])
        self.assertEqual(ha["agent_config_id"], prompt_agents[0]["id"])
        self.assertNotEqual(qiye["agent_config_id"], ceshi["agent_config_id"])
        self.assertEqual(len(agents), 2)
        self.assertIsNone(prompt_agents[0].get("extractor_prompt_name"))
        again = ensure_agents_for_conversations(convs, agents)
        self.assertEqual(len(again), 2)
        self.assertEqual([item["id"] for item in again], [item["id"] for item in agents])


class PromptIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        os.makedirs(os.path.join(self.root, "prompts"), exist_ok=True)
        with open(os.path.join(self.root, "prompts", "QIYE_A.md"), "w", encoding="utf-8") as f:
            f.write("简单测试消息只回复：\nA-链路正常\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_08_missing_prompt_does_not_call_llm(self):
        called = {"n": 0}

        def fake_llm(*args, **kwargs):
            called["n"] += 1
            return "LLM-SHOULD-NOT-RUN"

        def boom(user_id):
            raise PromptResolveError(PROMPT_FILE_NOT_FOUND, "Prompt 文件不存在", "missing")

        class DummyRuntime:
            def is_send_blocked(self):
                return False

            def llm_aborted(self):
                return False

            def log_event(self, *args, **kwargs):
                return None

        ns = {
            "runtime": DummyRuntime(),
            "logger": logging.getLogger("p2-binding"),
            "load_chat_contexts": lambda: None,
            "MAX_GROUPS": 5,
            "get_user_prompt": boom,
            "mask_secrets": lambda x: x,
            "queue_lock": threading.Lock(),
            "chat_contexts": {},
            "save_chat_contexts": lambda: None,
            "call_chat_api_with_retry": fake_llm,
            "LlmApiError": LlmApiError,
        }
        fn = rebind(get_deepseek_response, ns)
        result = fn("测试", "user_a", store_context=True)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result, AGENT_UNAVAILABLE_USER_MESSAGE)

    def test_09_missing_prompt_never_uses_default_assistant(self):
        source = inspect.getsource(get_deepseek_response)
        self.assertNotIn("你是一个乐于助人的助手。", source)
        with self.assertRaises(PromptResolveError) as ctx:
            resolve_chat_prompt(
                "ghost",
                conversations=[],
                agents=[],
                prompt_mapping={"ghost": "NO_SUCH_PROMPT"},
                root_dir=self.root,
            )
        self.assertEqual(ctx.exception.code, PROMPT_FILE_NOT_FOUND)
        self.assertNotEqual(ctx.exception.message, "你是一个乐于助人的助手。")

    def test_11_prompt_hash_changes_with_content(self):
        path = os.path.join(self.root, "prompts", "QIYE_A.md")
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
        hash1 = sha256_text(original)
        binding = resolve_chat_prompt(
            "user_a",
            prompt_mapping={"user_a": "QIYE_A"},
            root_dir=self.root,
        )
        self.assertEqual(binding.prompt_hash, hash1)
        updated = "简单测试消息只回复：\nA-已修改\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
        hash2 = sha256_text(updated)
        self.assertNotEqual(hash1, hash2)
        agents = [{"id": "agt_1", "chat_prompt_name": "QIYE_A", "chat_prompt_hash": hash1}]
        update_agents_prompt_hash(agents, "QIYE_A", updated)
        self.assertEqual(agents[0]["chat_prompt_hash"], hash2)
        self.assertEqual(hash2, hashlib.sha256(updated.encode("utf-8")).hexdigest())

    def test_12_log_contains_binding_ids(self):
        convs = migrate_from_listen_list({"LISTEN_LIST": [["user_a", "QIYE_A"]]})["conversations"]
        agents = ensure_agents_for_conversations(convs, [], prompt_root=self.root)
        events = []

        class DummyRuntime:
            def is_send_blocked(self):
                return False

            def llm_aborted(self):
                return False

            def log_event(self, category, message, extra=None):
                events.append({"category": category, "message": message, "extra": extra or {}})

        def fake_prompt(user_id):
            return resolve_chat_prompt(
                user_id,
                conversations=convs,
                agents=agents,
                root_dir=self.root,
            ).content

        def fake_load(user_id):
            return resolve_chat_prompt(
                user_id,
                conversations=convs,
                agents=agents,
                root_dir=self.root,
            )

        ns = {
            "runtime": DummyRuntime(),
            "logger": logging.getLogger("p2-log"),
            "load_chat_contexts": lambda: None,
            "MAX_GROUPS": 5,
            "get_user_prompt": fake_prompt,
            "load_chat_prompt": fake_load,
            "mask_secrets": lambda x: x,
            "queue_lock": threading.Lock(),
            "chat_contexts": {},
            "save_chat_contexts": lambda: None,
            "call_chat_api_with_retry": lambda *a, **k: "ok",
            "LlmApiError": LlmApiError,
        }
        fn = rebind(get_deepseek_response, ns)
        fn("测试", "user_a", store_context=True)
        extras = [item["extra"] for item in events if item["extra"]]
        self.assertTrue(extras)
        extra = extras[0]
        self.assertIn("conversation_id", extra)
        self.assertIn("agent_config_id", extra)
        self.assertIn("prompt_name", extra)
        self.assertIn("prompt_hash", extra)
        self.assertTrue(extra["conversation_id"].startswith("conv_"))
        self.assertTrue(extra["agent_config_id"].startswith("agt_"))
        self.assertEqual(extra["prompt_name"], "QIYE_A")
        self.assertTrue(extra["prompt_hash"])

    def test_empty_prompt_is_explicit_error(self):
        with open(os.path.join(self.root, "prompts", "EMPTY.md"), "w", encoding="utf-8") as f:
            f.write("   \n")
        with self.assertRaises(PromptResolveError) as ctx:
            resolve_chat_prompt("u", prompt_mapping={"u": "EMPTY"}, root_dir=self.root)
        self.assertEqual(ctx.exception.code, PROMPT_EMPTY)

    def test_missing_agent_config(self):
        convs = [{
            "id": "conv_1",
            "display_name": "ceshi",
            "agent_config_id": "",
            "metadata": {"prompt_name": "QIYE_A"},
        }]
        with self.assertRaises(PromptResolveError) as ctx:
            resolve_chat_prompt("ceshi", conversations=convs, agents=[], root_dir=self.root)
        self.assertEqual(ctx.exception.code, AGENT_CONFIG_NOT_FOUND)


class PromptDeleteProtectionTests(unittest.TestCase):
    def test_10_delete_in_use_prompt_returns_409(self):
        from config_editor import app
        app.config["TESTING"] = True
        name = "P2绑定保护_001"
        filename = name + ".md"
        with app.test_client() as client:
            created = client.post("/create_prompt", data={"filename": name, "content": "unit-test-protect"})
            self.assertIn(created.status_code, (200, 201))
            try:
                with mock.patch("config_editor.parse_config", return_value={
                    "AGENT_CONFIGS": [{
                        "id": "agt_protect",
                        "name": "智群 · 项目协同 Agent",
                        "chat_prompt_name": name,
                        "extractor_prompt_name": None,
                    }],
                    "LISTEN_LIST": [],
                }):
                    deleted = client.post("/delete_prompt/" + filename)
                self.assertEqual(deleted.status_code, 409)
                body = deleted.get_json()
                self.assertEqual(body["error"], "PROMPT_IN_USE")
                self.assertIn("该 Prompt 正被以下 Agent 使用，不能删除", body["message"])
            finally:
                client.post("/delete_prompt/" + filename)


if __name__ == "__main__":
    unittest.main()
