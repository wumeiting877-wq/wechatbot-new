# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ForumRoutesTests(unittest.TestCase):
    def test_forum_module_exposes_blueprint_routes(self):
        path = os.path.join(ROOT, "forum_routes.py")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("forum_bp = Blueprint", text)
        self.assertIn("/forum/<character_name>", text)
        self.assertIn("/api/forum/posts/<character_name>", text)
        self.assertIn("/api/npc/get_settings", text)
        self.assertIn("/api/npc/save_settings", text)
        self.assertNotIn("@app.route('/forum/", text)


if __name__ == "__main__":
    unittest.main()
