# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app_config


class ConfigValidateTests(unittest.TestCase):
    def setUp(self):
        self._old_root = app_config.ROOT_DIR
        self._old_local = app_config.LOCAL_CONFIG_PATH
        self._old_env = app_config.ENV_PATH
        self._old_legacy = app_config.LEGACY_PY_BACKUP
        self._old_config_py = app_config.CONFIG_PY_PATH
        self._old_example = app_config.EXAMPLE_CONFIG_PATH
        self.tmpdir = tempfile.TemporaryDirectory()
        app_config.ROOT_DIR = self.tmpdir.name
        app_config.LOCAL_CONFIG_PATH = os.path.join(self.tmpdir.name, "config.local.json")
        app_config.ENV_PATH = os.path.join(self.tmpdir.name, ".env")
        app_config.LEGACY_PY_BACKUP = os.path.join(self.tmpdir.name, "config.py.legacy.bak")
        app_config.CONFIG_PY_PATH = os.path.join(self.tmpdir.name, "config.py")
        app_config.EXAMPLE_CONFIG_PATH = os.path.join(self.tmpdir.name, "config.example.json")
        app_config._cache["data"] = None
        app_config._cache["mtime"] = None

    def tearDown(self):
        app_config.ROOT_DIR = self._old_root
        app_config.LOCAL_CONFIG_PATH = self._old_local
        app_config.ENV_PATH = self._old_env
        app_config.LEGACY_PY_BACKUP = self._old_legacy
        app_config.CONFIG_PY_PATH = self._old_config_py
        app_config.EXAMPLE_CONFIG_PATH = self._old_example
        app_config._cache["data"] = None
        app_config._cache["mtime"] = None
        self.tmpdir.cleanup()

    def test_missing_main_key(self):
        cfg = app_config.get_default_config()
        cfg["DEEPSEEK_API_KEY"] = ""
        issues = app_config.validate_config(cfg)
        codes = {item["key"]: item["code"] for item in issues}
        self.assertEqual(codes.get("DEEPSEEK_API_KEY"), "NOT_CONFIGURED")

    def test_assistant_enabled_without_key(self):
        cfg = app_config.get_default_config()
        cfg["ENABLE_ASSISTANT_MODEL"] = True
        cfg["ASSISTANT_API_KEY"] = "YOUR_API_KEY"
        issues = app_config.validate_config(cfg)
        self.assertTrue(any(item["key"] == "ASSISTANT_API_KEY" for item in issues))

    def test_search_enabled_without_key(self):
        cfg = app_config.get_default_config()
        cfg["ENABLE_ONLINE_API"] = True
        cfg["ONLINE_API_KEY"] = ""
        issues = app_config.validate_config(cfg)
        self.assertTrue(any(item["key"] == "ONLINE_API_KEY" for item in issues))

    def test_invalid_port_range(self):
        cfg = app_config.get_default_config()
        cfg["PORT"] = 70000
        issues = app_config.validate_config(cfg)
        self.assertTrue(any(item["key"] == "PORT" and item["code"] == "RANGE" for item in issues))

    def test_wrong_type(self):
        cfg = app_config.get_default_config()
        cfg["ENABLE_MEMORY"] = "yes"
        issues = app_config.validate_config(cfg)
        self.assertTrue(any(item["key"] == "ENABLE_MEMORY" and item["code"] == "TYPE" for item in issues))

    def test_save_does_not_write_secret_to_json(self):
        app_config.save_config({"DEEPSEEK_API_KEY": "sk-test-key-123456", "MODEL": "demo"})
        with open(app_config.LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("sk-test-key-123456", raw)
        with open(app_config.ENV_PATH, encoding="utf-8") as env_file:
            env = env_file.read()
        self.assertIn("sk-test-key-123456", env)


if __name__ == "__main__":
    unittest.main()
