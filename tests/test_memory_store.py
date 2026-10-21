# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from memory_store import merge_context, sanitize_user_id_for_filename


class MemoryStoreTests(unittest.TestCase):
    def test_merge_context_joins_same_role(self):
        merged = merge_context([
            {"role": "user", "content": "你好"},
            {"role": "user", "content": "在吗"},
            {"role": "assistant", "content": "在的"},
            {"role": "assistant", "content": "请说"},
        ])
        self.assertEqual(merged, [
            {"role": "user", "content": "你好\n在吗"},
            {"role": "assistant", "content": "在的\n请说"},
        ])

    def test_merge_context_empty(self):
        self.assertEqual(merge_context([]), [])

    def test_sanitize_user_id(self):
        self.assertEqual(sanitize_user_id_for_filename(""), "default_user")
        self.assertEqual(sanitize_user_id_for_filename("张三"), "张三")
        self.assertNotIn("/", sanitize_user_id_for_filename("a/../b"))
        self.assertTrue(sanitize_user_id_for_filename("CON").startswith("user_"))


if __name__ == "__main__":
    unittest.main()
