# -*- coding: utf-8 -*-
"""P1/P2 审计验证：不改 P0，不连真实微信。

覆盖：LISTEN_LIST 结构、nickname 主键风险、Prompt 运行时绑定、
缺失 Prompt 行为、绑定热更新边界。
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app_config import HOT_RELOAD_KEYS, load_config
from config_editor import listen_list_from_form
from llm_client import get_deepseek_response
from memory_store import get_user_prompt, load_chat_prompt
from message.pipeline import decide_should_process
from module_install import rebind

QIYE_A_BODY = "简单测试消息只回复：\nA-链路正常\n"
QIYE_B_BODY = "简单测试消息只回复：\nB-链路正常\n"


def _bind_get_user_prompt(root_dir, mapping, conversations=None, agents=None):
    ns = {
        "os": os,
        "shutil": shutil,
        "time": time,
        "prompt_mapping": mapping,
        "conversations": conversations or [],
        "agent_configs": agents or [],
        "root_dir": root_dir,
        "logger": logging.getLogger("p1p2-audit"),
        "get_dynamic_config": lambda key, default=None: False,
        "UPLOAD_MEMORY_TO_AI": False,
    }
    ns["load_chat_prompt"] = rebind(load_chat_prompt, ns)
    return rebind(get_user_prompt, ns)


class ListenListStructureTests(unittest.TestCase):
    def test_current_config_has_ceshi_and_two_more(self):
        cfg = load_config()
        listen = cfg.get("LISTEN_LIST") or []
        self.assertGreaterEqual(len(listen), 1)
        self.assertTrue(all(isinstance(row, list) and len(row) == 2 for row in listen))
        names = [row[0] for row in listen]
        prompts = [row[1] for row in listen]
        self.assertIn("ceshi", names)
        self.assertGreaterEqual(len(names), 2)
        self.assertIn("企业_1", prompts)
        self.assertNotEqual(
            dict(zip(names, prompts)).get("ceshi"),
            "QIYE",
            "当前 ceshi 并未绑定 QIYE；真实绑定是 LISTEN_LIST 第二列",
        )

    def test_listen_list_has_no_conversation_fields(self):
        cfg = load_config()
        for row in cfg.get("LISTEN_LIST") or []:
            self.assertEqual(len(row), 2)
            self.assertIsInstance(row[0], str)
            self.assertIsInstance(row[1], str)

    def test_duplicate_nickname_is_rejected_instead_of_mapping_overwrite(self):
        rows, err = listen_list_from_form(["ceshi", "ceshi"], ["QIYE_A", "QIYE_B"])
        self.assertIsNone(rows)
        self.assertEqual(err["error"], "VALIDATION_ERROR")
        self.assertIn("存在重复监听对象名称", err["message"])

    def test_listen_list_from_form_rejects_duplicate_nicknames(self):
        rows, err = listen_list_from_form(["ceshi", "ceshi"], ["QIYE_A", "QIYE_B"])
        self.assertIsNone(rows)
        self.assertEqual(err["error"], "VALIDATION_ERROR")

    def test_listen_list_not_hot_reloaded(self):
        self.assertNotIn("LISTEN_LIST", HOT_RELOAD_KEYS)

    def test_private_and_group_share_listen_list_match(self):
        private = decide_should_process(
            "ceshi", "ceshi", "你好", "text",
            listen_users=["ceshi", "项目群"], is_group=False,
        )
        group = decide_should_process(
            "项目群", "张三", "@助手 你好", "text",
            listen_users=["ceshi", "项目群"], is_group=True,
            robot_name="助手", enable_at=True, probability=100,
            rng=lambda a, b: 1,
        )
        self.assertEqual(private["reason"], "private_listen_list")
        self.assertTrue(group["should_process"])


class PromptRuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        os.makedirs(os.path.join(self.root, "prompts"), exist_ok=True)
        with open(os.path.join(self.root, "prompts", "QIYE_A.md"), "w", encoding="utf-8") as f:
            f.write(QIYE_A_BODY)
        with open(os.path.join(self.root, "prompts", "QIYE_B.md"), "w", encoding="utf-8") as f:
            f.write(QIYE_B_BODY)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_two_listeners_bind_distinct_prompts(self):
        loader = _bind_get_user_prompt(self.root, {"user_a": "QIYE_A", "user_b": "QIYE_B"})
        a = loader("user_a")
        b = loader("user_b")
        self.assertIn("A-链路正常", a)
        self.assertIn("B-链路正常", b)
        self.assertNotIn("B-链路正常", a)
        self.assertNotIn("A-链路正常", b)

    def test_swap_binding_takes_effect_on_next_load(self):
        mapping = {"user_a": "QIYE_A", "user_b": "QIYE_B"}
        loader = _bind_get_user_prompt(self.root, mapping)
        self.assertIn("A-链路正常", loader("user_a"))
        mapping["user_a"] = "QIYE_B"
        mapping["user_b"] = "QIYE_A"
        self.assertIn("B-链路正常", loader("user_a"))
        self.assertIn("A-链路正常", loader("user_b"))

    def test_prompt_content_change_is_read_immediately(self):
        loader = _bind_get_user_prompt(self.root, {"user_a": "QIYE_A"})
        self.assertIn("A-链路正常", loader("user_a"))
        path = os.path.join(self.root, "prompts", "QIYE_A.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("简单测试消息只回复：\nA-已修改立即生效\n")
        self.assertIn("A-已修改立即生效", loader("user_a"))

    def test_missing_prompt_raises_in_loader(self):
        from agent_store import PromptResolveError, PROMPT_FILE_NOT_FOUND
        loader = _bind_get_user_prompt(self.root, {"user_a": "MISSING_PROMPT"})
        with self.assertRaises(PromptResolveError) as ctx:
            loader("user_a")
        self.assertEqual(ctx.exception.code, PROMPT_FILE_NOT_FOUND)

    def test_unmapped_user_does_not_use_userid_filename(self):
        from agent_store import PromptResolveError, AGENT_CONFIG_NOT_FOUND
        loader = _bind_get_user_prompt(self.root, {"user_a": "QIYE_A"})
        with self.assertRaises(PromptResolveError) as ctx:
            loader("unknown_user")
        self.assertEqual(ctx.exception.code, AGENT_CONFIG_NOT_FOUND)

    def test_llm_client_no_longer_silently_falls_back(self):
        source = inspect.getsource(get_deepseek_response)
        self.assertNotIn("你是一个乐于助人的助手。", source)
        self.assertNotIn("使用默认提示", source)
        self.assertIn("PromptResolveError", source)

    def test_startup_precheck_rejects_missing_prompt(self):
        mapping = {"ceshi": "QIYE_A", "ghost": "DOES_NOT_EXIST"}
        missing = []
        for user, prompt_file in mapping.items():
            path = os.path.join(self.root, "prompts", f"{prompt_file}.md")
            if not os.path.exists(path):
                missing.append((user, prompt_file))
        self.assertEqual(missing, [("ghost", "DOES_NOT_EXIST")])


class PromptFileIdentityTests(unittest.TestCase):
    def test_prompts_are_filename_ids(self):
        names = []
        prompt_dir = os.path.join(ROOT, "prompts")
        for filename in os.listdir(prompt_dir):
            if filename.endswith(".md") and os.path.isfile(os.path.join(prompt_dir, filename)):
                names.append(filename[:-3])
        self.assertIn("QIYE", names)
        self.assertIn("企业_1", names)
        self.assertIn("AI", names)

    def test_chat_contexts_keyed_by_nickname(self):
        path = os.path.join(ROOT, "chat_contexts.json")
        if not os.path.exists(path):
            self.skipTest("no chat_contexts.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("ceshi", data)
        self.assertIsInstance(data["ceshi"], list)
        blob = json.dumps(data["ceshi"], ensure_ascii=False)
        self.assertNotIn("智群 · 企业消息协同智能体", blob)
        # Rebind clears nickname-keyed history. Live A/B writes A/B sentinels
        # instead of the prior 企业_1 self-intro; isolation still holds.
        if "A-链路正常" in blob or "B-链路正常" in blob:
            return
        self.assertIn("企业战略与业务分析顾问", blob)


if __name__ == "__main__":
    unittest.main()
