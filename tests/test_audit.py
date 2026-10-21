# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import audit


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig = audit.AUDIT_FILE
        audit.AUDIT_FILE = os.path.join(self.tmp.name, "audit.jsonl")
        self.addCleanup(lambda: setattr(audit, "AUDIT_FILE", self._orig))

    def test_log_and_read_emergency_stop(self):
        item = audit.log_audit("emergency_stop", actor="tester", detail="紧急停止")
        self.assertEqual(item["action"], "emergency_stop")
        self.assertEqual(item["actor"], "tester")
        items = audit.read_audit(limit=10)
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0]["action"], "emergency_stop")
        self.assertEqual(items[0]["detail"], "紧急停止")

    def test_detail_masks_api_key(self):
        audit.log_audit("save_config", actor="webui-user", detail="key=sk-abcdefghijklmnop")
        items = audit.read_audit(limit=5)
        self.assertNotIn("sk-abcdefghijklmnop", items[0]["detail"])
        self.assertIn("sk-", items[0]["detail"])

    def test_current_actor_without_flask_is_local(self):
        self.assertEqual(audit.current_actor(), "local")


if __name__ == "__main__":
    unittest.main()
