# -*- coding: utf-8 -*-
"""P5-G2 Gate 2：真实 Decision Extractor 适配与离线联调 D01～D08 / M01 / M03。"""

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
from decision_engine import DecisionEngine, engine_source_forbids_wechat_sidepath
from decision_extractor_client import DecisionExtractorClient, parse_decision_extractor_json
from decision_store import DECISION_FAILED, DecisionStore
from llm_client import get_deepseek_response, get_extractor_response
from store_io import atomic_write_json
from task_store import TaskStore
from topic_store import RELATION_CREATED_BY, RELATION_RELATED, TopicStore


FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "p5", "decision_cases.json")
MIXED_PATH = os.path.join(ROOT, "tests", "fixtures", "p5", "mixed_cases.json")
PROMPT_PATH = os.path.join(ROOT, "prompts", "extractors", "DECISION_EXTRACTOR.md")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
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
            "created_at": "2026-09-22T09:00:00+08:00",
            "updated_at": "2026-09-22T09:00:00+08:00",
            "last_message_at": "2026-09-22T09:00:00+08:00",
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
            "created_at": message.get("created_at") or "2026-09-22T09:00:00+08:00",
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


class DecisionExtractorIsolationTests(unittest.TestCase):
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
        self.assertNotIn("DECISION_EXTRACTOR", source)
        self.assertEqual(DEFAULT_EXTRACTOR_PROMPT_NAME, "TOPIC_EXTRACTOR")

    def test_decision_modules_forbid_send(self):
        self.assertTrue(engine_source_forbids_wechat_sidepath())
        import decision_engine
        import decision_extractor_client
        import decision_sidepath
        import decision_store
        for module in (decision_engine, decision_extractor_client, decision_store, decision_sidepath):
            text = inspect.getsource(module)
            self.assertNotIn("send_reply" + "(", text)
            self.assertNotIn("wx.SendMsg" + "(", text)
            self.assertNotIn("SendMsg" + "(", text)
            self.assertNotIn("from message.listener", text)

    def test_prompt_is_decision_extractor_not_topic_or_task(self):
        prompt = resolve_extractor_prompt("DECISION_EXTRACTOR", root_dir=ROOT)
        self.assertEqual(prompt.prompt_name, "DECISION_EXTRACTOR")
        self.assertEqual(prompt.prompt_hash, _prompt_hash())
        self.assertIn("NEW_DECISION", prompt.content)
        self.assertIn("UNRELATED", prompt.content)
        self.assertNotIn("NEW_TOPIC", prompt.content)
        self.assertNotIn("NEW_TASK", prompt.content)

    def test_markdown_json_empty_http_timeout(self):
        parsed = parse_decision_extractor_json(
            '```json\n{"decisions":[{"decision":"UNRELATED","decision_id":null,'
            '"supersedes_decision_id":null,"title":"","decision_text":"",'
            '"confidence":"HIGH","evidence_message_ids":["msg_1"],"reason":"ack"}]}\n```'
        )
        self.assertEqual(parsed["decisions"][0]["decision"], "UNRELATED")
        with self.assertRaises(Exception) as empty_ctx:
            parse_decision_extractor_json("")
        self.assertIn(empty_ctx.exception.code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY"))

        def boom(*_a, **_k):
            raise RuntimeError("HTTP 500")

        client = DecisionExtractorClient(llm_call=boom)
        with self.assertRaises(Exception) as http_ctx:
            client.extract({"current_message": {"id": "m1", "content": "x"}}, "prompt")
        self.assertEqual(http_ctx.exception.code, "EXTRACTOR_EXCEPTION")

        def timeout(*_a, **_k):
            raise TimeoutError("deadline")

        client_t = DecisionExtractorClient(llm_call=timeout)
        with self.assertRaises(Exception) as t_ctx:
            client_t.extract({"current_message": {"id": "m1"}}, "prompt")
        self.assertEqual(t_ctx.exception.code, "EXTRACTOR_TIMEOUT")

        def empty(*_a, **_k):
            return ""

        client_e = DecisionExtractorClient(llm_call=empty)
        with self.assertRaises(Exception) as e_ctx:
            client_e.extract({"current_message": {"id": "m1"}}, "prompt")
        self.assertIn(e_ctx.exception.code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "EXTRACTOR_EXCEPTION"))


class DecisionFailurePreservesTopicAndTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.decision_store = DecisionStore(self.tmpdir.name, topic_store=self.topic_store)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.fixture = _load_json(FIXTURE_PATH)
        self.conv = dict(self.fixture["conversation"])
        for topic in self.fixture["topics"]:
            _seed_topic(self.topic_store, self.conv["id"], topic)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _seed_current(self, content="可以，就按照异常池方案执行。", msg_id="fail_live"):
        topic = self.topic_store.get_topic(self.conv["id"], "topic_demo_erp")
        message = _upsert_msg(
            self.topic_store,
            self.conv["id"],
            {"id": msg_id, "sender_name": "周敏", "content": content},
            "topic_demo_erp",
            RELATION_CREATED_BY,
        )
        return topic, message

    def _snapshot(self):
        return (
            json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True),
            json.dumps(self.topic_store.list_links(self.conv["id"]), ensure_ascii=False, sort_keys=True),
            json.dumps(self.task_store.list_tasks(self.conv["id"]), ensure_ascii=False, sort_keys=True),
        )

    def _run(self, extractor, msg_id):
        topic, message = self._seed_current(msg_id=msg_id)
        before = self._snapshot()
        engine = DecisionEngine(
            self.decision_store,
            self.topic_store,
            extractor=extractor,
            root_dir=ROOT,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])
        return result

    def test_timeout_preserves_topic_and_task(self):
        class Boom:
            def extract(self, *_a, **_k):
                raise TimeoutError("20s")

        result = self._run(Boom(), "fail_timeout")
        self.assertEqual(result.error_code, "EXTRACTOR_TIMEOUT")

    def test_http_error_preserves_topic_and_task(self):
        def boom(*_a, **_k):
            raise RuntimeError("HTTP 502")

        result = self._run(DecisionExtractorClient(llm_call=boom), "fail_http")
        self.assertEqual(result.error_code, "EXTRACTOR_EXCEPTION")

    def test_invalid_json_preserves_topic_and_task(self):
        result = self._run(ScriptedExtractor("not-json"), "fail_json")
        self.assertEqual(result.error_code, "JSON_PARSE_ERROR")

    def test_empty_output_preserves_topic_and_task(self):
        result = self._run(ScriptedExtractor(""), "fail_empty")
        self.assertIn(result.error_code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "INVALID_OUTPUT"))

    def test_invalid_supersedes_preserves_topic_and_task(self):
        result = self._run(
            ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "supersedes_decision_id": "dec_does_not_exist",
                            "title": "改用全量同步",
                            "decision_text": "改成全量同步",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            "fail_sid",
        )
        self.assertEqual(result.error_code, "INVALID_SUPERSEDES_DECISION_ID")

    def test_invalid_evidence_preserves_topic_and_task(self):
        result = self._run(
            ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "supersedes_decision_id": None,
                            "title": "采用异常池方案",
                            "decision_text": "就按照异常池方案执行",
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


@unittest.skipUnless(_real_llm_ready(), "主模型 API Key 未配置，真实 Decision Extractor 联调 NOT RUN")
class RealDecisionExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.decision_store = DecisionStore(self.tmpdir.name, topic_store=self.topic_store)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.fixture = _load_json(FIXTURE_PATH)
        self.mixed = _load_json(MIXED_PATH)
        self.conv = dict(self.fixture["conversation"])
        self.prompt = resolve_extractor_prompt("DECISION_EXTRACTOR", root_dir=ROOT)
        from app_config import load_config
        cfg = load_config()
        self.model = cfg.get("MODEL") or "INHERIT"
        self.client = DecisionExtractorClient(llm_call=get_extractor_response, model=self.model)
        self.engine = DecisionEngine(
            self.decision_store,
            self.topic_store,
            extractor=self.client,
            root_dir=ROOT,
            enabled=True,
            extractor_prompt_name="DECISION_EXTRACTOR",
            model=self.model,
        )
        for topic in self.fixture["topics"]:
            _seed_topic(self.topic_store, self.conv["id"], topic)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _case(self, case_id, source=None):
        payload = source or self.fixture
        return [item for item in payload["cases"] if item["id"] == case_id][0]

    def _prepare(self, case):
        cid = self.conv["id"]
        topic_id = case["topic_id"]
        for message in case.get("recent_topic_messages") or []:
            _upsert_msg(self.topic_store, cid, message, topic_id, RELATION_RELATED)
        current = case["current_message"]
        _upsert_msg(self.topic_store, cid, current, topic_id, RELATION_CREATED_BY)
        for raw in case.get("existing_decisions") or []:
            created_msg = raw.get("created_msg_id") or (case.get("recent_topic_messages") or [current])[0]["id"]
            if self.topic_store.get_message(cid, created_msg) is None:
                created_msg = current["id"]
            payload = dict(raw)
            payload.setdefault("conversation_id", cid)
            payload.setdefault("topic_id", topic_id)
            payload.setdefault("created_msg_id", created_msg)
            payload.setdefault("created_at", "2026-09-22T10:00:00+08:00")
            payload.setdefault("title", payload.get("title") or "已有决策")
            payload.setdefault("decision_text", payload.get("decision_text") or payload.get("title") or "已有决策")
            self.decision_store.create_decision(payload)
        return self.topic_store.get_topic(cid, topic_id), self.topic_store.get_message(cid, current["id"])

    def _run(self, case_id, source=None):
        case = self._case(case_id, source=source)
        topic, message = self._prepare(case)
        topics_before = json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        tasks_before = json.dumps(self.task_store.list_tasks(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        result = self.engine.process_record(self.conv, topic, message)
        topics_after = json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        tasks_after = json.dumps(self.task_store.list_tasks(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        self.assertEqual(topics_before, topics_after, "Decision Engine must not mutate Topic")
        self.assertEqual(tasks_before, tasks_after, "Decision Engine must not mutate Task")
        self.assertNotEqual(result.decision, DECISION_FAILED, result.as_dict())
        return case, result

    def _recorded(self, topic_id=None):
        items = self.decision_store.list_decisions(self.conv["id"])
        if topic_id:
            items = [item for item in items if item.get("topic_id") == topic_id]
        return [item for item in items if item.get("status") == "RECORDED"]

    def _created_this_run(self, case):
        current_id = case["current_message"]["id"]
        return [item for item in self._recorded(case["topic_id"]) if item.get("created_msg_id") == current_id]

    def test_prompt_and_model_are_recorded(self):
        self.assertEqual(self.prompt.prompt_name, "DECISION_EXTRACTOR")
        self.assertEqual(self.prompt.prompt_hash, _prompt_hash())
        self.assertTrue(self.model)
        self.assertNotIn("sk-", str(self.model))

    def test_d01_explicit_confirmation(self):
        case, result = self._run("CASE-D01")
        expected = case["expected"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1, [item.get("decision_text") for item in created])
        decision = created[0]
        self.assertEqual(decision["status"], "RECORDED")
        self.assertTrue(any(token in decision["decision_text"] for token in expected["decision_text_contains"]))
        self.assertNotIn("task_id", decision)
        links = self.decision_store.links_for_decision(self.conv["id"], decision["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(len(created_by), 1)
        self.assertEqual(created_by[0]["message_id"], expected["created_by_message_id"])
        self.assertTrue(all(item["message_id"] not in expected["created_by_must_not"] for item in created_by))
        self.assertGreaterEqual(result.new_decision_count, 1)

    def test_d02_suggestion_is_not_decision(self):
        case, result = self._run("CASE-D02")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_decision_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_d03_bare_ok_is_not_decision(self):
        case, result = self._run("CASE-D03")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_decision_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_d04_demo_viewer_board(self):
        case, result = self._run("CASE-D04")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["status"], "RECORDED")
        self.assertIn("demo-viewer", created[0]["decision_text"])
        self.assertGreaterEqual(result.new_decision_count, 1)

    def test_d05_supersede_does_not_overwrite_old(self):
        case, result = self._run("CASE-D05")
        expected = case["expected"]
        old = self.decision_store.get_decision(self.conv["id"], expected["old_decision_id"])
        self.assertEqual(old["decision_text"], "决定使用增量同步。")
        self.assertEqual(old["status"], "RECORDED")
        self.assertNotIn(old["status"], ("SUPERSEDED", "CANCELLED"))
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["supersedes_decision_id"], "dec_demo_incr")
        self.assertTrue(any(token in created[0]["decision_text"] for token in expected["decision_text_contains"]))
        self.assertEqual(created[0]["status"], "RECORDED")
        self.assertGreaterEqual(result.new_decision_count, 1)

    def test_d06_problem_fact_is_not_decision(self):
        case, result = self._run("CASE-D06")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_decision_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_d07_task_instruction_is_not_decision(self):
        case, result = self._run("CASE-D07")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_decision_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_d08_ack_is_not_decision(self):
        case, result = self._run("CASE-D08")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_decision_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_m01_decision_yes_risk_not_run(self):
        case, result = self._run("CASE-M01", source=self.mixed)
        expected = case["expected"]["decision"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_decision_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertTrue(any(token in created[0]["decision_text"] for token in expected["decision_text_contains"]))
        self.assertNotIn("task_id", created[0])
        self.assertGreaterEqual(result.new_decision_count, 1)
        import decision_engine as decision_engine_mod

        decision_source = inspect.getsource(decision_engine_mod)
        self.assertNotIn("RiskEngine", decision_source)
        self.assertNotIn("risk_sidepath", decision_source)
        self.assertFalse(os.path.isdir(os.path.join(self.tmpdir.name, "data", "risk_store")))

    def test_m03_decision_yes_no_task_id(self):
        case, result = self._run("CASE-M03", source=self.mixed)
        expected = case["expected"]["decision"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_decision_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertNotIn("task_id", created[0])
        self.assertGreaterEqual(result.new_decision_count, 1)
        links = self.decision_store.links_for_decision(self.conv["id"], created[0]["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(created_by[0]["message_id"], expected["created_by_message_id"])


if __name__ == "__main__":
    unittest.main()
