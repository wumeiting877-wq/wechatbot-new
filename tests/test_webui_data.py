# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from webui_data import DATA_ROUTES, safe_filename, list_prompt_names


class WebuiDataTests(unittest.TestCase):
    def test_data_routes_cover_prompt_and_memory(self):
        paths = {item[0] for item in DATA_ROUTES}
        self.assertIn("/edit_prompt/<filename>", paths)
        self.assertIn("/create_prompt", paths)
        self.assertIn("/api/prompts", paths)
        self.assertIn("/api/save_core_memory/<filename>", paths)
        self.assertIn("/api/save_chat_context/<username>", paths)

    def test_routes_moved_out_of_config_editor(self):
        editor = os.path.join(ROOT, "config_editor.py")
        with open(editor, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("@app.route('/edit_prompt/", text)
        self.assertNotIn("@app.route('/create_prompt'", text)
        self.assertIn("register_data_routes(app, login_required", text)
        self.assertIn("@app.route('/start_bot'", text)
        self.assertIn("@app.route('/stop_bot'", text)
        self.assertIn("@app.route('/emergency_stop'", text)
        self.assertIn("@app.route('/api/runtime/audit'", text)

    def test_safe_filename_keeps_cjk(self):
        self.assertIn("角色", safe_filename("角色.md"))
        self.assertNotIn("/", safe_filename("../x.md"))

    def test_static_assets_and_template(self):
        files = [
            os.path.join(ROOT, "static", "css", "config_editor.css"),
            os.path.join(ROOT, "static", "js", "config_editor.js"),
            os.path.join(ROOT, "static", "css", "config_editor_extra.css"),
            os.path.join(ROOT, "static", "js", "config_editor_logs.js"),
            os.path.join(ROOT, "static", "js", "prompt_options.js"),
        ]
        for path in files:
            self.assertTrue(os.path.isfile(path), path)
        template = os.path.join(ROOT, "templates", "config_editor.html")
        with open(template, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("css/config_editor.css", html)
        self.assertIn("js/config_editor.js", html)
        self.assertIn("js/prompt_options.js", html)
        self.assertIn("ovRecentAudit", html)
        self.assertLess(html.count("<style"), 3)

    def test_list_prompt_names_uses_prompts_directory(self):
        names = list_prompt_names()
        self.assertIsInstance(names, list)
        self.assertIn("企业_1", names)
        self.assertTrue(all(not name.endswith(".md") for name in names))
        self.assertEqual(names, sorted(names))

    def test_listen_add_entry_js_does_not_embed_jinja(self):
        for name in ("config_editor.js", "prompt_options.js"):
            js_path = os.path.join(ROOT, "static", "js", name)
            with open(js_path, "r", encoding="utf-8") as f:
                js = f.read()
            self.assertNotIn("{{ file }}", js)
            self.assertNotIn("{% for file in prompt_files %}", js)
            self.assertNotIn("{% endfor %}", js)
        with open(os.path.join(ROOT, "static", "js", "prompt_options.js"), encoding="utf-8") as f:
            prompt_js = f.read()
        self.assertIn("async function loadPromptOptions", prompt_js)
        self.assertIn("function fillPromptSelect", prompt_js)
        with open(os.path.join(ROOT, "static", "js", "config_editor.js"), encoding="utf-8") as f:
            editor_js = f.read()
        self.assertIn("async function addEntry", editor_js)
        self.assertIn("PromptOptions.load", editor_js)
        self.assertIn("fullyStopped", editor_js)
        self.assertNotIn("stopped ? '' : 'warn'", editor_js)
        with open(os.path.join(ROOT, "templates", "quick_start.html"), encoding="utf-8") as f:
            quick = f.read()
        self.assertIn("prompt_options.js", quick)
        add_start = quick.find("async function addEntry()")
        self.assertGreater(add_start, 0)
        add_end = quick.find("function removeEntry", add_start)
        add_fn = quick[add_start:add_end]
        self.assertNotIn("{% for file in prompt_files %}", add_fn)
        self.assertNotIn("{{ file }}", add_fn)
        self.assertIn("PromptOptions.load", add_fn)

    def test_api_prompts_returns_prompt_names(self):
        from config_editor import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/prompts")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["ok"])
            self.assertIsInstance(data["prompts"], list)
            self.assertIn("企业_1", data["prompts"])
            self.assertNotIn("{{ file }}", data["prompts"])

    def test_api_prompts_tracks_create_and_delete(self):
        from config_editor import app
        app.config["TESTING"] = True
        name = "测试Prompt_001"
        filename = name + ".md"
        with app.test_client() as client:
            created = client.post("/create_prompt", data={"filename": name, "content": "unit-test"})
            self.assertIn(created.status_code, (200, 201))
            try:
                listed = client.get("/api/prompts").get_json()["prompts"]
                self.assertIn(name, listed)
            finally:
                deleted = client.post("/delete_prompt/" + filename)
                self.assertIn(deleted.status_code, (200, 204))
                listed_after = client.get("/api/prompts").get_json()["prompts"]
                self.assertNotIn(name, listed_after)


if __name__ == "__main__":
    unittest.main()
