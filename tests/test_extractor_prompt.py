# -*- coding: utf-8 -*-
"""P3-G1 Gate 2：Extractor Prompt 独立 loader，与 Chat Prompt 隔离。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_store import (
    EXTRACTOR_PROMPT_EMPTY,
    EXTRACTOR_PROMPT_NOT_FOUND,
    PROMPT_FILE_NOT_FOUND,
    PromptResolveError,
    resolve_chat_prompt,
    resolve_extractor_prompt,
    sha256_text,
)
from webui_data import list_prompt_names


class ExtractorPromptLoaderTests(unittest.TestCase):
    def test_topic_extractor_can_be_read(self):
        binding = resolve_extractor_prompt("TOPIC_EXTRACTOR", root_dir=ROOT)
        self.assertIn("你是后台主题分类器", binding.content)
        self.assertEqual(binding.prompt_name, "TOPIC_EXTRACTOR")
        self.assertEqual(binding.prompt_hash, sha256_text(binding.content))
        self.assertIn("禁止输出 tasks", binding.content)

    def test_prompt_hash_is_stable(self):
        first = resolve_extractor_prompt(root_dir=ROOT)
        second = resolve_extractor_prompt(root_dir=ROOT)
        self.assertEqual(first.prompt_hash, second.prompt_hash)
        self.assertEqual(len(first.prompt_hash), 64)

    def test_chat_prompt_loader_does_not_read_extractors(self):
        with self.assertRaises(PromptResolveError) as ctx:
            resolve_chat_prompt(
                "TOPIC_EXTRACTOR",
                prompt_mapping={"TOPIC_EXTRACTOR": "TOPIC_EXTRACTOR"},
                root_dir=ROOT,
            )
        self.assertEqual(ctx.exception.code, PROMPT_FILE_NOT_FOUND)

    def test_extractor_not_in_chat_prompt_list(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            names = list_prompt_names()
        finally:
            os.chdir(cwd)
        self.assertIn("QIYE", names)
        self.assertIn("企业_1", names)
        self.assertNotIn("TOPIC_EXTRACTOR", names)
        self.assertNotIn("extractors/TOPIC_EXTRACTOR", names)

    def test_missing_extractor_returns_independent_error_and_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PromptResolveError) as ctx:
                resolve_extractor_prompt("TOPIC_EXTRACTOR", root_dir=tmp)
            self.assertEqual(ctx.exception.code, EXTRACTOR_PROMPT_NOT_FOUND)

    def test_empty_extractor_returns_independent_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prompts", "extractors")
            os.makedirs(path)
            with open(os.path.join(path, "TOPIC_EXTRACTOR.md"), "w", encoding="utf-8") as f:
                f.write("   \n")
            with self.assertRaises(PromptResolveError) as ctx:
                resolve_extractor_prompt("TOPIC_EXTRACTOR", root_dir=tmp)
            self.assertEqual(ctx.exception.code, EXTRACTOR_PROMPT_EMPTY)


if __name__ == "__main__":
    unittest.main()
