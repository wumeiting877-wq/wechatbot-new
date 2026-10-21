# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from store_io import atomic_write_json, atomic_write_text, read_json, update_json


class StoreIoTests(unittest.TestCase):
    def test_atomic_write_and_read_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "core.json")
            atomic_write_json(path, {"hello": "记忆"})
            self.assertEqual(read_json(path), {"hello": "记忆"})
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_read_missing_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing.json")
            self.assertEqual(read_json(path, default={"ok": True}), {"ok": True})

    def test_update_json_creates_and_mutates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "data.json")

            def add_item(data):
                data.setdefault("items", []).append("a")
                return data

            update_json(path, add_item)
            update_json(path, add_item)
            self.assertEqual(read_json(path)["items"], ["a", "a"])

    def test_atomic_write_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prompt.md")
            atomic_write_text(path, "你是助手")
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "你是助手")


if __name__ == "__main__":
    unittest.main()
