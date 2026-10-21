# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from werkzeug.datastructures import MultiDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app_config
from config_editor import app, listen_list_from_form


class ListenListValidationTests(unittest.TestCase):
    def test_complete_rows(self):
        rows, err = listen_list_from_form(["QIYE", "哈"], ["企业_1", "AI"])
        self.assertIsNone(err)
        self.assertEqual([row["listen_row"] for row in rows], [["QIYE", "企业_1"], ["哈", "AI"]])

    def test_empty_list_is_ok(self):
        rows, err = listen_list_from_form([], [])
        self.assertIsNone(err)
        self.assertEqual(rows, [])

    def test_missing_name(self):
        rows, err = listen_list_from_form(["", "哈"], ["企业_1", "AI"])
        self.assertIsNone(rows)
        self.assertEqual(err["error"], "VALIDATION_ERROR")
        self.assertIn("第 1 个监听对象未填写监听对象名称", err["message"])

    def test_missing_prompt(self):
        rows, err = listen_list_from_form(["张三"], [""])
        self.assertIsNone(rows)
        self.assertIn("监听对象「张三」尚未选择 Prompt", err["message"])

    def test_duplicate_nickname_is_rejected(self):
        rows, err = listen_list_from_form(["ceshi", "ceshi"], ["QIYE_A", "QIYE_B"])
        self.assertIsNone(rows)
        self.assertEqual(err["error"], "VALIDATION_ERROR")
        self.assertIn("存在重复监听对象名称", err["message"])

    def test_length_mismatch(self):
        rows, err = listen_list_from_form(["张三"], ["企业_1", "AI"])
        self.assertIsNone(rows)
        self.assertIn("数量不一致", err["message"])


class ConfigWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.local.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_atomic_write_ten_times_keeps_valid_json(self):
        for i in range(10):
            payload = {"LISTEN_LIST": [["QIYE", "企业_1"]], "n": i}
            app_config._atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["n"], i)
            self.assertEqual(loaded["LISTEN_LIST"][0][1], "企业_1")

    def test_replace_retries_permission_error(self):
        src = os.path.join(self.tmpdir.name, "src.txt")
        dest = os.path.join(self.tmpdir.name, "dest.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("ok")
        with open(dest, "w", encoding="utf-8") as f:
            f.write("old")
        calls = {"n": 0}
        real_replace = os.replace

        def flaky_replace(a, b):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(13, "Permission denied")
            real_replace(a, b)

        with mock.patch("app_config.os.replace", side_effect=flaky_replace):
            app_config._replace_with_retry(src, dest)
        self.assertGreaterEqual(calls["n"], 3)
        with open(dest, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "ok")


class SubmitConfigProtocolTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_incomplete_listen_is_rejected(self):
        resp = self.client.post(
            "/submit_config",
            data=MultiDict([
                ("nickname", "QIYE"),
                ("nickname", ""),
                ("prompt_file", "企业_1"),
                ("prompt_file", "AI"),
            ]),
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "VALIDATION_ERROR")
        self.assertIn("message", body)
        self.assertIn("detail", body)
        self.assertIn("未填写监听对象名称", body["message"])
        self.assertNotIn("请先停止运行程序", body["message"])

    def test_missing_prompt_is_rejected(self):
        resp = self.client.post(
            "/submit_config",
            data=MultiDict([
                ("nickname", "张三"),
                ("prompt_file", ""),
            ]),
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["error"], "VALIDATION_ERROR")
        self.assertIn("尚未选择 Prompt", body["message"])
        self.assertIn("张三", body["message"])

    def test_duplicate_nickname_is_rejected(self):
        resp = self.client.post(
            "/submit_config",
            data=MultiDict([
                ("nickname", "ceshi"),
                ("nickname", "ceshi"),
                ("prompt_file", "企业_1"),
                ("prompt_file", "QIYE"),
            ]),
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["error"], "VALIDATION_ERROR")
        self.assertIn("存在重复监听对象名称", body["message"])

    def test_write_failure_returns_real_message(self):
        with mock.patch(
            "config_editor.update_config",
            side_effect=OSError(5, "拒绝访问。: config.local.json"),
        ):
            resp = self.client.post(
                "/submit_config",
                data=MultiDict([
                    ("nickname", "QIYE"),
                    ("prompt_file", "企业_1"),
                ]),
            )
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "CONFIG_WRITE_FAILED")
        self.assertEqual(body["message"], "无法写入配置文件")
        self.assertIn("拒绝访问", body["detail"])
        self.assertNotIn("请先停止运行程序", body["message"])
        self.assertNotIn("请先停止运行程序", body["detail"])


if __name__ == "__main__":
    unittest.main()
