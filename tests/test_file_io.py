# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from file_io import safe_read_file_with_encoding, safe_write_file_with_encoding


class FileIoTests(unittest.TestCase):
    def test_write_and_read_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "memo.txt")
            safe_write_file_with_encoding(path, "你好，企业助手")
            self.assertEqual(safe_read_file_with_encoding(path), "你好，企业助手")

    def test_read_gbk_and_convert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.txt")
            with open(path, "wb") as f:
                f.write("历史配置".encode("gbk"))
            content = safe_read_file_with_encoding(path)
            self.assertEqual(content, "历史配置")
            with open(path, "rb") as f:
                self.assertTrue(f.read().startswith("历史配置".encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
