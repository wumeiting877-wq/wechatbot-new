# -*- coding: utf-8 -*-
"""P4-G2 Gate 2：真实 Task Extractor 适配与离线联调 T01～T10。"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_store import DEFAULT_EXTRACTOR_PROMPT_NAME, resolve_extractor_prompt
from llm_client import get_deepseek_response, get_extractor_response
from store_io import atomic_write_json
from task_engine import TaskEngine, engine_source_forbids_wechat_sidepath
from task_extractor_client import TaskExtractorClient, parse_task_extractor_json
from task_store import DECISION_FAILED, TaskStore
from topic_store import RELATION_CREATED_BY, RELATION_RELATED, TopicStore


FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "task_engine", "zhiqun_task_cases.json")
PROMPT_PATH = os.path.join(ROOT, "prompts", "extractors", "TASK_EXTRACTOR.md")


def _load_cases():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _prompt_hash():
    with open(PROMPT_PATH, "r", encoding="utf-8") as handle:
        return hashlib.sha256(handle.read().encode("utf-8")).hexdigest()


def _real_llm_ready():
    try:
        from app_config import is_configured_secret, load_config
        cfg = load_config()
        return bool(is_configured_secret(cfg.get("DEEPSEEK_API_KEY")) and cfg.get("MODEL"))
    except Exception:
        return False


def _seed_topic(topic_store, cid, topic):
    topics = list(topic_store.list_topics(cid))
    if any(item.get("id") == topic["id"] for item in topics):
        return
    topics.append(
        {
            "id": topic["id"],
            "conversation_id": cid,
            "title": topic.get("title") or "",
            "summary": topic.get("summary") or "",
            "status": "ACTIVE",
            "confidence": "HIGH",
            "created_at": "2026-09-20T09:00:00+08:00",
            "updated_at": "2026-09-20T09:00:00+08:00",
            "last_message_at": "2026-09-20T09:00:00+08:00",
            "message_count": 0,
            "schema_version": 1,
        }
    )
    atomic_write_json(os.path.join(topic_store.conversation_dir(cid), "topics.json"), {"topics": topics})


def _upsert_msg(topic_store, cid, message, relation_topic_id=None, relation=RELATION_RELATED):
    record = topic_store.upsert_message(
        {
            "id": message["id"],
            "conversation_id": cid,
            "platform_message_id": message["id"],
            "sender_name": message.get("sender_name") or "",
            "content": message.get("content") or "",
            "created_at": message.get("created_at") or "2026-09-20T09:00:00+08:00",
            "direction": message.get("direction") or "INBOUND",
            "message_type": "text",
        }
    )
    if relation_topic_id:
        topic_store.add_link(cid, relation_topic_id, record["id"], relation)
    return record


class ScriptedExtractor:
    def __init__(self, payload):
        self.payload = payload

    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        if callable(self.payload):
            return self.payload(engine_input)
        if not isinstance(self.payload, dict):
            return self.payload
        data = copy.deepcopy(self.payload)
        for item in data.get("decisions") or []:
            if isinstance(item, dict) and not item.get("evidence_message_ids"):
                item["evidence_message_ids"] = [current_id]
        return data


class TaskExtractorIsolationTests(unittest.TestCase):
    def test_extractor_entry_is_not_chat_wrapper(self):
        source = inspect.getsource(get_extractor_response)
        self.assertNotIn("get_user_prompt", source)
        self.assertNotIn("chat_contexts", source)
        self.assertNotIn("resolve_chat_prompt", source)
        self.assertNotIn("get_deepseek_response", source)
        self.assertNotIn("send_reply" + "(", source)
        self.assertIn("store_context", source)

    def test_chat_function_unchanged(self):
        source = inspect.getsource(get_deepseek_response)
        self.assertIn("get_user_prompt", source)
        self.assertNotIn("TASK_EXTRACTOR", source)
        self.assertEqual(DEFAULT_EXTRACTOR_PROMPT_NAME, "TOPIC_EXTRACTOR")

    def test_task_modules_forbid_send(self):
        self.assertTrue(engine_source_forbids_wechat_sidepath())
        import task_engine
        import task_extractor_client
        import task_sidepath
        import task_store
        for module in (task_engine, task_extractor_client, task_store, task_sidepath):
            text = inspect.getsource(module)
            self.assertNotIn("send_reply" + "(", text)
            self.assertNotIn("wx.SendMsg" + "(", text)
            self.assertNotIn("SendMsg" + "(", text)

    def test_prompt_is_task_extractor_not_topic(self):
        prompt = resolve_extractor_prompt("TASK_EXTRACTOR", root_dir=ROOT)
        self.assertEqual(prompt.prompt_name, "TASK_EXTRACTOR")
        self.assertEqual(prompt.prompt_hash, _prompt_hash())
        self.assertIn("NEW_TASK", prompt.content)
        self.assertIn("TASK_UPDATE", prompt.content)
        self.assertIn("UNRELATED", prompt.content)
        self.assertNotIn("NEW_TOPIC", prompt.content)

    def test_markdown_json_empty_http_timeout(self):
        parsed = parse_task_extractor_json(
            '```json\n{"decisions":[{"decision":"UNRELATED","task_id":null,"title":"","assignee_text":"",'
            '"due_text":"","confidence":"HIGH","evidence_message_ids":["msg_1"],"reason":"ack"}]}\n```'
        )
        self.assertEqual(parsed["decisions"][0]["decision"], "UNRELATED")
        with self.assertRaises(Exception) as empty_ctx:
            parse_task_extractor_json("")
        self.assertEqual(empty_ctx.exception.code, "JSON_PARSE_ERROR")

        def boom(*_a, **_k):
            raise RuntimeError("HTTP 500")

        client = TaskExtractorClient(llm_call=boom)
        with self.assertRaises(Exception) as http_ctx:
            client.extract({"current_message": {"id": "m1", "content": "x"}}, "prompt")
        self.assertEqual(http_ctx.exception.code, "EXTRACTOR_EXCEPTION")

        def timeout(*_a, **_k):
            raise TimeoutError("deadline")

        client_t = TaskExtractorClient(llm_call=timeout)
        with self.assertRaises(Exception) as t_ctx:
            client_t.extract({"current_message": {"id": "m1"}}, "prompt")
        self.assertEqual(t_ctx.exception.code, "EXTRACTOR_TIMEOUT")

        def empty(*_a, **_k):
            return ""

        client_e = TaskExtractorClient(llm_call=empty)
        with self.assertRaises(Exception) as e_ctx:
            client_e.extract({"current_message": {"id": "m1"}}, "prompt")
        self.assertIn(e_ctx.exception.code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "EXTRACTOR_EXCEPTION"))


class TaskFailurePreservesTopicTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.fixture = _load_cases()
        self.conv = dict(self.fixture["conversation"])
        for topic in self.fixture["topics"]:
            _seed_topic(self.topic_store, self.conv["id"], topic)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _seed_current(self, content="李娜把权限问题修一下。", msg_id="fail_live"):
        topic = self.topic_store.get_topic(self.conv["id"], "topic_demo_perm")
        message = _upsert_msg(
            self.topic_store,
            self.conv["id"],
            {"id": msg_id, "sender_name": "周敏", "content": content},
            "topic_demo_perm",
            RELATION_CREATED_BY,
        )
        return topic, message

    def _snapshot(self):
        return (
            json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True),
            json.dumps(self.topic_store.list_links(self.conv["id"]), ensure_ascii=False, sort_keys=True),
        )

    def _run(self, extractor, msg_id):
        topic, message = self._seed_current(msg_id=msg_id)
        before = self._snapshot()
        engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=extractor,
            root_dir=ROOT,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])
        return result

    def test_timeout_preserves_topic(self):
        class Boom:
            def extract(self, *_a, **_k):
                raise TimeoutError("20s")

        result = self._run(Boom(), "fail_timeout")
        self.assertEqual(result.error_code, "EXTRACTOR_TIMEOUT")

    def test_http_error_preserves_topic(self):
        def boom(*_a, **_k):
            raise RuntimeError("HTTP 502")

        result = self._run(TaskExtractorClient(llm_call=boom), "fail_http")
        self.assertEqual(result.error_code, "EXTRACTOR_EXCEPTION")

    def test_invalid_json_preserves_topic(self):
        result = self._run(ScriptedExtractor("not-json"), "fail_json")
        self.assertEqual(result.error_code, "JSON_PARSE_ERROR")

    def test_empty_output_preserves_topic(self):
        result = self._run(ScriptedExtractor(""), "fail_empty")
        self.assertIn(result.error_code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "INVALID_OUTPUT"))

    def test_invalid_task_id_preserves_topic(self):
        result = self._run(
            ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "TASK_UPDATE",
                            "task_id": "task_does_not_exist",
                            "title": "",
                            "assignee_text": "",
                            "due_text": "17 点前",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            "fail_tid",
        )
        self.assertEqual(result.error_code, "INVALID_TASK_ID")

    def test_invalid_assignee_preserves_topic(self):
        result = self._run(
            ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_TASK",
                            "task_id": None,
                            "title": "修复权限问题",
                            "assignee_text": "不存在的人",
                            "due_text": "",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            "fail_asg",
        )
        self.assertEqual(result.error_code, "INVALID_ASSIGNEE")

    def test_invalid_evidence_preserves_topic(self):
        result = self._run(
            ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_TASK",
                            "task_id": None,
                            "title": "修复权限问题",
                            "assignee_text": "李娜",
                            "due_text": "",
                            "confidence": "HIGH",
                            "evidence_message_ids": ["msg_invented"],
                            "reason": "x",
                        }
                    ]
                }
            ),
            "fail_ev",
        )
        self.assertEqual(result.error_code, "INVALID_EVIDENCE_ID")


@unittest.skipUnless(_real_llm_ready(), "主模型 API Key 未配置，真实 Task Extractor 联调 NOT RUN")
class RealTaskExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.fixture = _load_cases()
        self.conv = dict(self.fixture["conversation"])
        self.prompt = resolve_extractor_prompt("TASK_EXTRACTOR", root_dir=ROOT)
        from app_config import load_config
        cfg = load_config()
        self.model = cfg.get("MODEL") or "INHERIT"
        self.client = TaskExtractorClient(llm_call=get_extractor_response, model=self.model)
        self.engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=self.client,
            root_dir=ROOT,
            enabled=True,
            extractor_prompt_name="TASK_EXTRACTOR",
            model=self.model,
        )
        for topic in self.fixture["topics"]:
            _seed_topic(self.topic_store, self.conv["id"], topic)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _case(self, case_id):
        return [item for item in self.fixture["cases"] if item["id"] == case_id][0]

    def _prepare(self, case):
        cid = self.conv["id"]
        topic_id = case["topic_id"]
        for message in case.get("recent_topic_messages") or []:
            _upsert_msg(self.topic_store, cid, message, topic_id, RELATION_RELATED)
        current = case["current_message"]
        _upsert_msg(self.topic_store, cid, current, topic_id, RELATION_CREATED_BY)
        for raw in case.get("existing_tasks") or []:
            created_msg = (case.get("recent_topic_messages") or [current])[0]["id"]
            if self.topic_store.get_message(cid, created_msg) is None:
                created_msg = current["id"]
            payload = dict(raw)
            payload.setdefault("conversation_id", cid)
            payload.setdefault("topic_id", topic_id)
            payload.setdefault("created_msg_id", created_msg)
            payload.setdefault("created_at", "2026-09-20T09:08:00+08:00")
            self.task_store.create_task(payload)
        return self.topic_store.get_topic(cid, topic_id), self.topic_store.get_message(cid, current["id"])

    def _run(self, case_id):
        case = self._case(case_id)
        topic, message = self._prepare(case)
        topics_before = json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        result = self.engine.process_record(self.conv, topic, message)
        topics_after = json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        self.assertEqual(topics_before, topics_after, "Task Engine must not mutate Topic")
        self.assertNotEqual(result.decision, DECISION_FAILED, result.as_dict())
        return case, result

    def _open_tasks(self, topic_id=None):
        items = self.task_store.list_tasks(self.conv["id"])
        if topic_id:
            items = [item for item in items if item.get("topic_id") == topic_id]
        return [item for item in items if item.get("status") == "OPEN"]

    def test_prompt_and_model_are_recorded(self):
        self.assertEqual(self.prompt.prompt_name, "TASK_EXTRACTOR")
        self.assertEqual(self.prompt.prompt_hash, _prompt_hash())
        self.assertTrue(self.model)
        self.assertNotIn("sk-", str(self.model))

    def test_t01_assignee_wangqiang_due_16(self):
        case, result = self._run("CASE-T01")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 1, [item.get("title") for item in tasks])
        self.assertEqual(tasks[0]["assignee_text"], "王强")
        self.assertNotEqual(tasks[0]["assignee_text"], "周敏")
        self.assertIn("16 点", tasks[0]["due_text"])
        self.assertEqual(tasks[0]["due_at"], "")
        self.assertEqual(tasks[0]["status"], "OPEN")
        self.assertGreaterEqual(result.new_task_count, 1)

    def test_t02_no_assignee_zero_task(self):
        case, result = self._run("CASE-T02")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 0)
        self.assertEqual(result.new_task_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_t03_lina_no_due(self):
        case, _result = self._run("CASE-T03")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["assignee_text"], "李娜")
        self.assertEqual(tasks[0]["due_text"], "")
        self.assertEqual(tasks[0]["status"], "OPEN")

    def test_t04_two_tasks(self):
        case, result = self._run("CASE-T04")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 2, [item.get("assignee_text") for item in tasks])
        by_assignee = {item["assignee_text"]: item for item in tasks}
        self.assertIn("王强", by_assignee)
        self.assertIn("李娜", by_assignee)
        self.assertTrue(all(item["topic_id"] == "topic_demo_erp" for item in tasks))
        self.assertEqual(result.new_task_count, 2)

    def test_t05_update_not_new(self):
        case, result = self._run("CASE-T05")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(result.new_task_count, 0)
        self.assertGreaterEqual(result.update_count, 1)
        self.assertEqual(tasks[0]["id"], "task_demo_nullrule")
        self.assertIn("17 点", tasks[0]["due_text"])
        self.assertNotEqual(result.decision, "NEW_TASK")

    def test_t06_ack_zero_task(self):
        case, result = self._run("CASE-T06")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 1)
        self.assertEqual(result.new_task_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_t07_fact_zero_task(self):
        case, result = self._run("CASE-T07")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 0)
        self.assertEqual(result.new_task_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_t08_suggestion_no_new_task(self):
        case, result = self._run("CASE-T08")
        self.assertEqual(result.new_task_count, 0)
        open_tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(open_tasks), 1)
        self.assertNotIn(result.decision, ("NEW_TASK",))

    def test_t09_confirm_no_ownerless_new(self):
        case, result = self._run("CASE-T09")
        self.assertEqual(result.new_task_count, 0)
        self.assertIn(result.decision, ("TASK_UPDATE", "UNRELATED", "SKIPPED"))
        for task in self._open_tasks(case["topic_id"]):
            self.assertNotEqual(task.get("assignee_text"), "周敏")

    def test_t10_completion_not_done(self):
        case, result = self._run("CASE-T10")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "OPEN")
        self.assertEqual(result.new_task_count, 0)
        self.assertNotIn("DONE", result.decision_summary)
        self.assertNotEqual(result.decision, "DONE")


if __name__ == "__main__":
    unittest.main()
