# -*- coding: utf-8 -*-
"""P5-G4 Gate 2：真实 Risk Extractor 适配与离线联调 R01～R09 / M01 / M02。"""

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
from decision_store import DecisionStore
from llm_client import get_deepseek_response, get_extractor_response
from risk_engine import RiskEngine, engine_source_forbids_wechat_sidepath
from risk_extractor_client import RiskExtractorClient, parse_risk_extractor_json
from risk_store import DECISION_FAILED, RELATION_UPDATED_BY, RiskStore
from store_io import atomic_write_json
from task_store import TaskStore
from topic_store import RELATION_CREATED_BY, RELATION_RELATED, TopicStore


FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "p5", "risk_cases.json")
MIXED_PATH = os.path.join(ROOT, "tests", "fixtures", "p5", "mixed_cases.json")
PROMPT_PATH = os.path.join(ROOT, "prompts", "extractors", "RISK_EXTRACTOR.md")


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
        for item in data.get("risks") or []:
            if isinstance(item, dict) and not item.get("evidence_message_ids"):
                item["evidence_message_ids"] = [current_id]
        return data


class RiskExtractorIsolationTests(unittest.TestCase):
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
        self.assertNotIn("RISK_EXTRACTOR", source)
        self.assertEqual(DEFAULT_EXTRACTOR_PROMPT_NAME, "TOPIC_EXTRACTOR")

    def test_risk_modules_forbid_send(self):
        self.assertTrue(engine_source_forbids_wechat_sidepath())
        import risk_engine
        import risk_extractor_client
        import risk_sidepath
        import risk_store
        for module in (risk_engine, risk_extractor_client, risk_store, risk_sidepath):
            text = inspect.getsource(module)
            self.assertNotIn("send_reply" + "(", text)
            self.assertNotIn("wx.SendMsg" + "(", text)
            self.assertNotIn("SendMsg" + "(", text)
            self.assertNotIn("from message.listener", text)

    def test_prompt_is_risk_extractor_not_topic_task_or_decision(self):
        prompt = resolve_extractor_prompt("RISK_EXTRACTOR", root_dir=ROOT)
        self.assertEqual(prompt.prompt_name, "RISK_EXTRACTOR")
        self.assertEqual(prompt.prompt_hash, _prompt_hash())
        self.assertIn("NEW_RISK", prompt.content)
        self.assertIn("UNRELATED", prompt.content)
        self.assertNotIn("NEW_TOPIC", prompt.content)
        self.assertNotIn("NEW_TASK", prompt.content)
        self.assertNotIn("NEW_DECISION", prompt.content)

    def test_markdown_json_empty_http_timeout(self):
        parsed = parse_risk_extractor_json(
            '```json\n{"risks":[{"decision":"UNRELATED","risk_id":null,'
            '"title":"","condition_text":"","impact_text":"",'
            '"task_id":null,"confidence":"HIGH","evidence_message_ids":["msg_1"],'
            '"reason":"ack"}]}\n```'
        )
        self.assertEqual(parsed["risks"][0]["decision"], "UNRELATED")
        with self.assertRaises(Exception) as empty_ctx:
            parse_risk_extractor_json("")
        self.assertIn(empty_ctx.exception.code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY"))

        def boom(*_a, **_k):
            raise RuntimeError("HTTP 500")

        client = RiskExtractorClient(llm_call=boom)
        with self.assertRaises(Exception) as http_ctx:
            client.extract({"current_message": {"id": "m1", "content": "x"}}, "prompt")
        self.assertEqual(http_ctx.exception.code, "EXTRACTOR_EXCEPTION")

        def timeout(*_a, **_k):
            raise TimeoutError("deadline")

        client_t = RiskExtractorClient(llm_call=timeout)
        with self.assertRaises(Exception) as t_ctx:
            client_t.extract({"current_message": {"id": "m1"}}, "prompt")
        self.assertEqual(t_ctx.exception.code, "EXTRACTOR_TIMEOUT")

        def empty(*_a, **_k):
            return ""

        client_e = RiskExtractorClient(llm_call=empty)
        with self.assertRaises(Exception) as e_ctx:
            client_e.extract({"current_message": {"id": "m1"}}, "prompt")
        self.assertIn(e_ctx.exception.code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "EXTRACTOR_EXCEPTION"))


class RiskFailurePreservesTopicTaskDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.tmpdir.name, topic_store=self.topic_store)
        self.risk_store = RiskStore(
            self.tmpdir.name, topic_store=self.topic_store, task_store=self.task_store
        )
        self.fixture = _load_json(FIXTURE_PATH)
        self.conv = dict(self.fixture["conversation"])
        for topic in self.fixture["topics"]:
            _seed_topic(self.topic_store, self.conv["id"], topic)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _seed_current(self, content="如果今天还修不好，会影响明天现场演示。", msg_id="fail_live"):
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
            json.dumps(self.decision_store.list_decisions(self.conv["id"]), ensure_ascii=False, sort_keys=True),
        )

    def _run(self, extractor, msg_id):
        topic, message = self._seed_current(msg_id=msg_id)
        before = self._snapshot()
        engine = RiskEngine(
            self.risk_store,
            self.topic_store,
            task_store=self.task_store,
            extractor=extractor,
            root_dir=ROOT,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])
        return result

    def test_timeout_preserves_topic_task_decision(self):
        class Boom:
            def extract(self, *_a, **_k):
                raise TimeoutError("20s")

        result = self._run(Boom(), "fail_timeout")
        self.assertEqual(result.error_code, "EXTRACTOR_TIMEOUT")

    def test_http_error_preserves_topic_task_decision(self):
        def boom(*_a, **_k):
            raise RuntimeError("HTTP 502")

        result = self._run(RiskExtractorClient(llm_call=boom), "fail_http")
        self.assertEqual(result.error_code, "EXTRACTOR_EXCEPTION")

    def test_invalid_json_preserves_topic_task_decision(self):
        result = self._run(ScriptedExtractor("not-json"), "fail_json")
        self.assertEqual(result.error_code, "JSON_PARSE_ERROR")

    def test_empty_output_preserves_topic_task_decision(self):
        result = self._run(ScriptedExtractor(""), "fail_empty")
        self.assertIn(result.error_code, ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "INVALID_OUTPUT"))

    def test_invalid_risk_id_preserves_topic_task_decision(self):
        result = self._run(
            ScriptedExtractor(
                {
                    "risks": [
                        {
                            "decision": "RISK_UPDATE",
                            "risk_id": "risk_invented",
                            "title": "x",
                            "condition_text": "如果今天修不好",
                            "impact_text": "影响演示",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            "fail_rid",
        )
        self.assertEqual(result.error_code, "INVALID_RISK_ID")

    def test_invalid_evidence_preserves_topic_task_decision(self):
        result = self._run(
            ScriptedExtractor(
                {
                    "risks": [
                        {
                            "decision": "NEW_RISK",
                            "risk_id": None,
                            "title": "今日未修复将影响明日演示",
                            "condition_text": "如果今天还修不好",
                            "impact_text": "会影响明天现场演示",
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


@unittest.skipUnless(_real_llm_ready(), "主模型 API Key 未配置，真实 Risk Extractor 联调 NOT RUN")
class RealRiskExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.tmpdir.name, topic_store=self.topic_store)
        self.risk_store = RiskStore(
            self.tmpdir.name, topic_store=self.topic_store, task_store=self.task_store
        )
        self.fixture = _load_json(FIXTURE_PATH)
        self.mixed = _load_json(MIXED_PATH)
        self.conv = dict(self.fixture["conversation"])
        self.prompt = resolve_extractor_prompt("RISK_EXTRACTOR", root_dir=ROOT)
        from app_config import load_config
        cfg = load_config()
        self.model = cfg.get("MODEL") or "INHERIT"
        self.client = RiskExtractorClient(llm_call=get_extractor_response, model=self.model)
        self.engine = RiskEngine(
            self.risk_store,
            self.topic_store,
            task_store=self.task_store,
            extractor=self.client,
            root_dir=ROOT,
            enabled=True,
            extractor_prompt_name="RISK_EXTRACTOR",
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
        for raw in case.get("existing_risks") or []:
            created_msg = raw.get("created_msg_id") or (case.get("recent_topic_messages") or [current])[0]["id"]
            if self.topic_store.get_message(cid, created_msg) is None:
                created_msg = current["id"]
            payload = dict(raw)
            payload.setdefault("conversation_id", cid)
            payload.setdefault("topic_id", topic_id)
            payload.setdefault("created_msg_id", created_msg)
            payload.setdefault("created_at", "2026-09-22T13:10:00+08:00")
            payload.setdefault("title", payload.get("title") or "已有风险")
            payload.setdefault("condition_text", payload.get("condition_text") or "如果断网")
            payload.setdefault("impact_text", payload.get("impact_text") or "无法演示")
            self.risk_store.create_risk(payload)
        return self.topic_store.get_topic(cid, topic_id), self.topic_store.get_message(cid, current["id"])

    def _run(self, case_id, source=None):
        case = self._case(case_id, source=source)
        topic, message = self._prepare(case)
        topics_before = json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        tasks_before = json.dumps(self.task_store.list_tasks(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        decisions_before = json.dumps(
            self.decision_store.list_decisions(self.conv["id"]), ensure_ascii=False, sort_keys=True
        )
        result = self.engine.process_record(self.conv, topic, message)
        topics_after = json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        tasks_after = json.dumps(self.task_store.list_tasks(self.conv["id"]), ensure_ascii=False, sort_keys=True)
        decisions_after = json.dumps(
            self.decision_store.list_decisions(self.conv["id"]), ensure_ascii=False, sort_keys=True
        )
        self.assertEqual(topics_before, topics_after, "Risk Engine must not mutate Topic")
        self.assertEqual(tasks_before, tasks_after, "Risk Engine must not mutate Task")
        self.assertEqual(decisions_before, decisions_after, "Risk Engine must not mutate Decision")
        self.assertNotEqual(result.decision, DECISION_FAILED, result.as_dict())
        return case, result

    def _open_risks(self, topic_id=None):
        items = self.risk_store.list_risks(self.conv["id"])
        if topic_id:
            items = [item for item in items if item.get("topic_id") == topic_id]
        return [item for item in items if item.get("status") == "OPEN"]

    def _created_this_run(self, case):
        current_id = case["current_message"]["id"]
        return [item for item in self._open_risks(case["topic_id"]) if item.get("created_msg_id") == current_id]

    def _assert_no_severity(self, item):
        self.assertNotIn("severity", item)
        self.assertNotIn("severity_text", item)

    def test_prompt_and_model_are_recorded(self):
        self.assertEqual(self.prompt.prompt_name, "RISK_EXTRACTOR")
        self.assertEqual(self.prompt.prompt_hash, _prompt_hash())
        self.assertTrue(self.model)
        self.assertNotIn("sk-", str(self.model))

    def test_r01_explicit_risk(self):
        case, result = self._run("CASE-R01")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1, [item.get("title") for item in created])
        risk = created[0]
        self.assertEqual(risk["status"], "OPEN")
        self.assertTrue(any(token in risk["condition_text"] for token in ("今天", "修不好")))
        self.assertTrue(any(token in risk["impact_text"] for token in ("明天", "现场演示", "演示")))
        self._assert_no_severity(risk)
        self.assertGreaterEqual(result.new_risk_count, 1)
        links = self.risk_store.links_for_risk(self.conv["id"], risk["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(len(created_by), 1)
        self.assertEqual(created_by[0]["message_id"], case["current_message"]["id"])

    def test_r02_current_problem_is_not_risk(self):
        case, result = self._run("CASE-R02")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_risk_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_r03_suggestion_is_not_risk(self):
        case, result = self._run("CASE-R03")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_risk_count, 0)

    def test_r04_wifi_future_impact(self):
        case, result = self._run("CASE-R04")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["status"], "OPEN")
        blob = "%s %s" % (created[0]["condition_text"], created[0]["impact_text"])
        self.assertTrue(any(token in blob for token in ("Wi-Fi", "WIFI", "wifi", "断网")))
        self.assertIn("无法演示", created[0]["impact_text"])
        self._assert_no_severity(created[0])
        self.assertGreaterEqual(result.new_risk_count, 1)

    def test_r05_vague_worry_is_not_risk(self):
        case, result = self._run("CASE-R05")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_risk_count, 0)

    def test_r06_recovered_does_not_auto_resolve(self):
        case, result = self._run("CASE-R06")
        self.assertEqual(result.new_risk_count, 0)
        old = self.risk_store.get_risk(self.conv["id"], "risk_demo_wifi")
        self.assertIsNotNone(old)
        self.assertEqual(old["status"], "OPEN")
        self.assertNotIn(old["status"], ("RESOLVED", "MITIGATED", "CLOSED"))
        self.assertEqual(len(self._created_this_run(case)), 0)
        summaries = str(result.decision_summary or result.decision)
        self.assertNotIn("RISK_RESOLVED", summaries)
        self.assertNotIn("RESOLVED", summaries)
        self.assertNotIn("MITIGATED", summaries)
        self.assertNotIn("CLOSED", summaries)

    def test_r07_task_instruction_is_not_risk(self):
        case, result = self._run("CASE-R07")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_risk_count, 0)

    def test_r08_ack_is_not_risk(self):
        case, result = self._run("CASE-R08")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_risk_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_r09_risk_update_does_not_duplicate(self):
        case, result = self._run("CASE-R09")
        self.assertEqual(result.decision, "RISK_UPDATE")
        self.assertEqual(result.new_risk_count, 0)
        self.assertGreaterEqual(result.update_count, 1)
        risks = self._open_risks(case["topic_id"])
        self.assertEqual(len(risks), 1)
        updated = self.risk_store.get_risk(self.conv["id"], "risk_demo_repair")
        self.assertEqual(updated["status"], "OPEN")
        self.assertNotIn(updated["status"], ("RESOLVED", "MITIGATED", "CLOSED"))
        self._assert_no_severity(updated)
        links = self.risk_store.links_for_risk(self.conv["id"], updated["id"])
        updated_by = [item for item in links if item["relation"] == RELATION_UPDATED_BY]
        self.assertTrue(updated_by)
        self.assertEqual(updated_by[0]["message_id"], case["current_message"]["id"])

    def test_m01_risk_yes_decision_independent(self):
        case, result = self._run("CASE-M01", source=self.mixed)
        expected = case["expected"]["risk"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_risk_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertTrue(any(token in created[0]["condition_text"] for token in expected["condition_contains"]))
        self.assertTrue(any(token in created[0]["impact_text"] for token in expected["impact_contains"]))
        self.assertGreaterEqual(result.new_risk_count, 1)
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_m02_risk_yes_task_id_may_be_empty(self):
        case, result = self._run("CASE-M02", source=self.mixed)
        expected = case["expected"]["risk"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_risk_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertTrue(any(token in created[0]["condition_text"] for token in expected["condition_contains"]))
        self.assertTrue(any(token in created[0]["impact_text"] for token in expected["impact_contains"]))
        self.assertIn(created[0].get("task_id") or "", ("", None))
        self.assertGreaterEqual(result.new_risk_count, 1)


if __name__ == "__main__":
    unittest.main()
