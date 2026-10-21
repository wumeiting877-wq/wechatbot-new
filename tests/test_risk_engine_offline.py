# -*- coding: utf-8 -*-
"""P5-G3 Gate 3–4：Risk Engine 离线 fixture、失败注入、幂等、源码隔离。"""

from __future__ import annotations

import copy
import inspect
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decision_engine import DECISION_ENGINE_ENABLED
from decision_store import DecisionStore
from risk_engine import (
    RISK_ENGINE_ENABLED,
    MAX_CANDIDATE_TASKS,
    MAX_EXISTING_RISKS,
    MAX_RECENT_TOPIC_MESSAGES,
    RiskEngine,
    engine_source_forbids_wechat_sidepath,
    rule_prefilter,
)
from risk_extractor_client import HeuristicRiskExtractor
from risk_store import DECISION_FAILED, RiskStore, RiskStoreError
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_store import RELATION_CREATED_BY, RELATION_RELATED, TopicStore

FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "p5", "risk_cases.json")
MIXED_PATH = os.path.join(ROOT, "tests", "fixtures", "p5", "mixed_cases.json")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


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


def _engine(risk_store, topic_store, extractor=None, enabled=True, root_dir=ROOT, task_store=None):
    return RiskEngine(
        risk_store,
        topic_store,
        task_store=task_store,
        extractor=extractor or HeuristicRiskExtractor(),
        root_dir=root_dir,
        enabled=enabled,
    )


class CaptureExtractor:
    def __init__(self, inner=None):
        self.inner = inner or HeuristicRiskExtractor()
        self.inputs = []

    def extract(self, engine_input, prompt_content):
        self.inputs.append(engine_input)
        return self.inner.extract(engine_input, prompt_content)


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


class RiskEngineHarness(unittest.TestCase):
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
        self.topics = {item["id"]: item for item in self.fixture["topics"]}
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
        for raw in case.get("candidate_tasks") or []:
            created_msg = raw.get("created_msg_id") or current["id"]
            if self.topic_store.get_message(cid, created_msg) is None:
                created_msg = current["id"]
            payload = dict(raw)
            payload.setdefault("conversation_id", cid)
            payload.setdefault("topic_id", topic_id)
            payload.setdefault("created_msg_id", created_msg)
            payload.setdefault("title", payload.get("title") or "已有任务")
            payload.setdefault("assignee_text", payload.get("assignee_text") or "王强")
            self.task_store.create_task(payload)
        return self.topic_store.get_topic(cid, topic_id), self.topic_store.get_message(cid, current["id"])

    def _run(self, case_id, extractor=None, source=None, task_store="default"):
        case = self._case(case_id, source=source)
        topic, message = self._prepare(case)
        capture = CaptureExtractor(extractor or HeuristicRiskExtractor())
        store = self.task_store if task_store == "default" else task_store
        engine = _engine(self.risk_store, self.topic_store, extractor=capture, task_store=store)
        result = engine.process_record(self.conv, topic, message)
        return case, result, capture

    def _open_risks(self, topic_id=None):
        items = self.risk_store.list_risks(self.conv["id"])
        if topic_id:
            items = [item for item in items if item.get("topic_id") == topic_id]
        return [item for item in items if item.get("status") == "OPEN"]

    def _created_this_run(self, case):
        current_id = case["current_message"]["id"]
        return [
            item
            for item in self._open_risks(case["topic_id"])
            if item.get("created_msg_id") == current_id
        ]


class RiskEngineOfflineTests(RiskEngineHarness):
    def test_risk_engine_enabled_defaults_false(self):
        self.assertFalse(RISK_ENGINE_ENABLED)
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        case = self._case("CASE-R01")
        topic, message = self._prepare(case)
        engine = RiskEngine(self.risk_store, self.topic_store, root_dir=ROOT)
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, "DISABLED")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])

    def test_engine_does_not_touch_wechat_sidepath(self):
        self.assertTrue(engine_source_forbids_wechat_sidepath())
        for module_name in ("risk_engine", "risk_extractor_client", "risk_store", "risk_sidepath"):
            source = inspect.getsource(__import__(module_name))
            self.assertNotIn("send_reply" + "(", source)
            self.assertNotIn("wx.SendMsg" + "(", source)
            self.assertNotIn("SendMsg" + "(", source)
            self.assertNotIn("from message.listener", source)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "risk_sidepath.py")))

    def test_input_window_limits(self):
        self.assertEqual(MAX_RECENT_TOPIC_MESSAGES, 12)
        self.assertEqual(MAX_EXISTING_RISKS, 10)
        self.assertEqual(MAX_CANDIDATE_TASKS, 10)

    def test_case_r01_explicit_risk(self):
        case, result, _ = self._run("CASE-R01")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["status"], "OPEN")
        self.assertTrue(any(token in created[0]["condition_text"] for token in ("今天", "修不好")))
        self.assertIn("修不好", created[0]["condition_text"])
        self.assertTrue(any(token in created[0]["impact_text"] for token in ("明天", "现场演示", "演示")))
        self.assertIn("演示", created[0]["impact_text"])
        self.assertNotIn("severity", created[0])
        self.assertEqual(created[0]["task_id"], "")
        self.assertEqual(result.new_risk_count, 1)
        links = self.risk_store.links_for_risk(self.conv["id"], created[0]["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(created_by[0]["message_id"], case["current_message"]["id"])

    def test_case_r02_current_problem_is_not_risk(self):
        case, result, _ = self._run("CASE-R02")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_risk_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))

    def test_case_r03_suggestion_is_not_risk(self):
        case, result, _ = self._run("CASE-R03")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.new_risk_count, 0)

    def test_case_r04_current_fact_plus_future_impact(self):
        case, result, _ = self._run("CASE-R04")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["status"], "OPEN")
        self.assertTrue(any(token in created[0]["condition_text"] for token in ("Wi-Fi", "断网")))
        self.assertIn("Wi-Fi", created[0]["condition_text"])
        self.assertIn("断网", created[0]["condition_text"])
        self.assertIn("无法演示", created[0]["impact_text"])
        self.assertNotIn("severity", created[0])

    def test_case_r05_vague_worry_is_not_risk(self):
        case, result, _ = self._run("CASE-R05")
        self.assertEqual(len(self._created_this_run(case)), 0)

    def test_case_r06_recovered_does_not_auto_resolve(self):
        case, result, _ = self._run("CASE-R06")
        self.assertEqual(result.new_risk_count, 0)
        old = self.risk_store.get_risk(self.conv["id"], "risk_demo_wifi")
        self.assertIsNotNone(old)
        self.assertEqual(old["status"], "OPEN")
        self.assertNotIn(old["status"], ("RESOLVED", "MITIGATED", "CLOSED"))
        self.assertEqual(len(self._created_this_run(case)), 0)
        summaries = str(result.decision_summary or result.decision)
        self.assertNotIn("RISK_RESOLVED", summaries)
        self.assertNotIn("RESOLVED", summaries)

    def test_case_r07_task_instruction_is_not_risk(self):
        case, result, _ = self._run("CASE-R07")
        self.assertEqual(len(self._created_this_run(case)), 0)

    def test_case_r08_ack_is_not_risk(self):
        case, result, capture = self._run("CASE-R08")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))
        self.assertEqual(capture.inputs, [])

    def test_case_r09_risk_update_same_concern(self):
        case, result, _ = self._run("CASE-R09")
        self.assertEqual(result.new_risk_count, 0)
        self.assertEqual(result.update_count, 1)
        self.assertEqual(result.decision, "RISK_UPDATE")
        risks = self._open_risks(case["topic_id"])
        self.assertEqual(len(risks), 1)
        updated = self.risk_store.get_risk(self.conv["id"], "risk_demo_repair")
        self.assertEqual(updated["status"], "OPEN")
        self.assertIn("今晚", updated["condition_text"])
        self.assertIn("修不好", updated["condition_text"])
        self.assertIn("演示", updated["impact_text"])
        links = self.risk_store.links_for_risk(self.conv["id"], updated["id"])
        updated_by = [item for item in links if item["relation"] == "UPDATED_BY"]
        self.assertEqual(updated_by[0]["message_id"], case["current_message"]["id"])

    def test_case_m01_risk_half(self):
        case, result, _ = self._run("CASE-M01", source=self.mixed)
        expected = case["expected"]["risk"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_risk_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertTrue(any(token in created[0]["condition_text"] for token in expected["condition_contains"]))
        self.assertTrue(any(token in created[0]["impact_text"] for token in expected["impact_contains"]))

    def test_case_m02_risk_half_task_id_may_be_empty(self):
        case, result, _ = self._run("CASE-M02", source=self.mixed)
        expected = case["expected"]["risk"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_risk_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertTrue(any(token in created[0]["condition_text"] for token in expected["condition_contains"]))
        self.assertTrue(any(token in created[0]["impact_text"] for token in expected["impact_contains"]))
        self.assertTrue(expected["task_id_may_be_null"])
        self.assertIn(created[0]["task_id"], ("", None))

    def test_taskstore_unavailable_does_not_block_risk(self):
        class BoomTaskStore:
            def list_open_tasks(self, *args, **kwargs):
                raise RuntimeError("task store down")

        case, result, capture = self._run("CASE-R01", task_store=BoomTaskStore())
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["task_id"], "")
        self.assertNotEqual(result.decision, DECISION_FAILED)
        self.assertEqual(capture.inputs[0]["candidate_tasks"], [])
        self.assertTrue(result.candidate_tasks_error)
        audits = self.risk_store.read_audit()
        self.assertTrue(any(item.get("risk_decision") == "CANDIDATE_TASKS_UNAVAILABLE" for item in audits))

    def test_taskstore_none_still_creates_topic_risk(self):
        case, result, capture = self._run("CASE-R01", task_store=None)
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["task_id"], "")
        self.assertEqual(capture.inputs[0]["candidate_tasks"], [])

    def test_illegal_task_id_is_cleared_but_risk_is_kept(self):
        topic, message = FailureInjectionTests._seed_current(
            self, content="如果今天还修不好，会影响明天现场演示。", msg_id="bad_task"
        )
        result = _engine(
            self.risk_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "risks": [
                        {
                            "decision": "NEW_RISK",
                            "risk_id": None,
                            "title": "今日未修复将影响明日演示",
                            "condition_text": "如果今天还修不好",
                            "impact_text": "会影响明天现场演示",
                            "task_id": "task_invented",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
            task_store=self.task_store,
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.new_risk_count, 1)
        created = self.risk_store.list_risks(self.conv["id"])
        self.assertEqual(created[0]["task_id"], "")
        self.assertEqual(created[0]["status"], "OPEN")

    def test_keyword_failure_alone_does_not_create_risk(self):
        self.assertIsNone(rule_prefilter("ERP 同步失败了。"))
        self.assertIsNone(rule_prefilter("感觉有点危险。"))
        self.assertEqual(rule_prefilter("收到。"), "UNRELATED")

    def test_missing_topic_evidence_does_not_guess(self):
        cid = self.conv["id"]
        topic = self.topic_store.get_topic(cid, "topic_demo_erp")
        message = self.topic_store.upsert_message(
            {
                "id": "msg_orphan",
                "conversation_id": cid,
                "platform_message_id": "msg_orphan",
                "sender_name": "周敏",
                "content": "如果今天还修不好，会影响明天现场演示。",
            }
        )
        engine = _engine(self.risk_store, self.topic_store)
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "TOPIC_EVIDENCE_MISSING")
        self.assertEqual(self.risk_store.list_risks(cid), [])
        self.assertEqual(len(self.topic_store.list_topics(cid)), 3)


class FailureInjectionTests(RiskEngineHarness):
    def _seed_current(self, content="如果今天还修不好，会影响明天现场演示。", msg_id="fail_msg"):
        topic = self.topic_store.get_topic(self.conv["id"], "topic_demo_erp")
        message = _upsert_msg(
            self.topic_store,
            self.conv["id"],
            {"id": msg_id, "sender_name": "周敏", "content": content, "created_at": "2026-09-22T14:10:00+08:00"},
            "topic_demo_erp",
            RELATION_CREATED_BY,
        )
        return topic, message

    def _snapshot_topics(self):
        return json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)

    def _snapshot_links(self):
        return json.dumps(self.topic_store.list_links(self.conv["id"]), ensure_ascii=False, sort_keys=True)

    def _snapshot_tasks(self):
        return json.dumps(self.task_store.list_tasks(self.conv["id"]), ensure_ascii=False, sort_keys=True)

    def _snapshot_decisions(self):
        return json.dumps(self.decision_store.list_decisions(self.conv["id"]), ensure_ascii=False, sort_keys=True)

    def _assert_frozen(self, before_topics, before_links, before_tasks, before_decisions):
        self.assertEqual(self._snapshot_topics(), before_topics)
        self.assertEqual(self._snapshot_links(), before_links)
        self.assertEqual(self._snapshot_tasks(), before_tasks)
        self.assertEqual(self._snapshot_decisions(), before_decisions)
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])

    def test_extractor_timeout_isolated(self):
        topic, message = self._seed_current()
        before = (
            self._snapshot_topics(),
            self._snapshot_links(),
            self._snapshot_tasks(),
            self._snapshot_decisions(),
        )

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise TimeoutError("llm timeout")

        result = _engine(self.risk_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(result.error_code, "EXTRACTOR_TIMEOUT")
        self._assert_frozen(*before)
        rec = self.risk_store.get_processing(self.conv["id"], "fail_msg")
        self.assertEqual(rec["decision_summary"], DECISION_FAILED)

    def test_extractor_exception_isolated(self):
        topic, message = self._seed_current()
        before = (
            self._snapshot_topics(),
            self._snapshot_links(),
            self._snapshot_tasks(),
            self._snapshot_decisions(),
        )

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("boom")

        result = _engine(self.risk_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self._assert_frozen(*before)

    def test_invalid_json_isolated(self):
        topic, message = self._seed_current()
        before = (
            self._snapshot_topics(),
            self._snapshot_links(),
            self._snapshot_tasks(),
            self._snapshot_decisions(),
        )
        result = _engine(
            self.risk_store, self.topic_store, extractor=ScriptedExtractor("not-json-at-all")
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "JSON_PARSE_ERROR")
        self._assert_frozen(*before)

    def test_empty_output_isolated(self):
        topic, message = self._seed_current()
        result = _engine(self.risk_store, self.topic_store, extractor=ScriptedExtractor("")).process_record(
            self.conv, topic, message
        )
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "EXTRACTOR_EMPTY")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])

    def test_invalid_risk_id_isolated(self):
        topic, message = self._seed_current()
        result = _engine(
            self.risk_store,
            self.topic_store,
            extractor=ScriptedExtractor(
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
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "INVALID_RISK_ID")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])
        self.assertIsNone(self.risk_store.get_risk(self.conv["id"], "risk_invented"))

    def test_invalid_evidence_id_isolated(self):
        topic, message = self._seed_current()
        result = _engine(
            self.risk_store,
            self.topic_store,
            extractor=ScriptedExtractor(
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
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "INVALID_EVIDENCE_ID")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])

    def test_second_invalid_does_not_leave_half_apply(self):
        topic, message = self._seed_current()
        result = _engine(
            self.risk_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "risks": [
                        {
                            "decision": "NEW_RISK",
                            "risk_id": None,
                            "title": "今日未修复将影响明日演示",
                            "condition_text": "如果今天还修不好",
                            "impact_text": "会影响明天现场演示",
                            "confidence": "HIGH",
                            "reason": "ok",
                        },
                        {
                            "decision": "RISK_UPDATE",
                            "risk_id": "risk_invented",
                            "title": "x",
                            "condition_text": "如果今晚修不好",
                            "impact_text": "影响演示",
                            "confidence": "HIGH",
                            "reason": "bad",
                        },
                    ]
                }
            ),
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])

    def test_prompt_missing_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                return {"risks": [{"decision": "UNRELATED", "risk_id": None}]}

        topic, message = self._seed_current(msg_id="no_prompt")
        engine = RiskEngine(
            self.risk_store,
            self.topic_store,
            extractor=Boom(),
            root_dir=self.tmpdir.name,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_NOT_FOUND")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])

    def test_prompt_empty_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                raise AssertionError("should not run")

        prompt_dir = os.path.join(self.tmpdir.name, "prompts", "extractors")
        os.makedirs(prompt_dir)
        with open(os.path.join(prompt_dir, "RISK_EXTRACTOR.md"), "w", encoding="utf-8") as handle:
            handle.write("\n")
        topic, message = self._seed_current(msg_id="empty_prompt")
        engine = RiskEngine(
            self.risk_store,
            self.topic_store,
            extractor=Boom(),
            root_dir=self.tmpdir.name,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_EMPTY")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])

    def test_store_write_failure_no_dirty_risk(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()

        class BoomStore(RiskStore):
            def commit_apply(self, *args, **kwargs):
                raise RiskStoreError("STORE_WRITE_FAILURE", "disk full")

        boom = BoomStore(self.tmpdir.name, topic_store=self.topic_store)
        result = _engine(boom, self.topic_store).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "STORE_WRITE_FAILURE")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"]), [])
        self.assertEqual(self._snapshot_topics(), before_topics)

    def test_process_does_not_raise_to_caller(self):
        topic, message = self._seed_current(msg_id="no_crash")

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("explode")

        engine = _engine(self.risk_store, self.topic_store, extractor=Boom())
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)

    def test_failed_then_retry_can_succeed(self):
        topic, message = self._seed_current(msg_id="retry_msg")

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("first fail")

        first = _engine(self.risk_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(first.decision, DECISION_FAILED)
        second = _engine(self.risk_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertEqual(second.decision, "NEW_RISK")
        self.assertEqual(len(self._open_risks("topic_demo_erp")), 1)

    def test_taskstore_read_exception_is_not_risk_failed(self):
        topic, message = self._seed_current(msg_id="task_boom")

        class BoomTaskStore:
            def list_open_tasks(self, *args, **kwargs):
                raise RuntimeError("unavailable")

        result = _engine(
            self.risk_store, self.topic_store, task_store=BoomTaskStore()
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, "NEW_RISK")
        self.assertEqual(self.risk_store.list_risks(self.conv["id"])[0]["task_id"], "")
        self.assertNotEqual(result.decision, DECISION_FAILED)


class IdempotencyTests(RiskEngineHarness):
    def test_same_message_replay_does_not_duplicate_risk(self):
        case, first, _ = self._run("CASE-R01")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.risk_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._created_this_run(case)), 1)

    def test_multi_risk_replay_does_not_increase_count(self):
        topic, message = FailureInjectionTests._seed_current(
            self, content="如果今天修不好会影响演示。如果断网会导致无法演示。", msg_id="multi_risk"
        )

        class TwoRisks:
            def extract(self, engine_input, prompt_content):
                current_id = engine_input["current_message"]["id"]
                return {
                    "risks": [
                        {
                            "decision": "NEW_RISK",
                            "risk_id": None,
                            "title": "今日未修复将影响明日演示",
                            "condition_text": "如果今天修不好",
                            "impact_text": "会影响演示",
                            "confidence": "HIGH",
                            "evidence_message_ids": [current_id],
                            "reason": "a",
                        },
                        {
                            "decision": "NEW_RISK",
                            "risk_id": None,
                            "title": "断网无法演示",
                            "condition_text": "如果断网",
                            "impact_text": "系统无法演示",
                            "confidence": "HIGH",
                            "evidence_message_ids": [current_id],
                            "reason": "b",
                        },
                    ]
                }

        first = _engine(self.risk_store, self.topic_store, extractor=TwoRisks()).process_record(
            self.conv, topic, message
        )
        self.assertEqual(first.new_risk_count, 2)
        second = _engine(self.risk_store, self.topic_store, extractor=TwoRisks()).process_record(
            self.conv, topic, message
        )
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._open_risks("topic_demo_erp")), 2)

    def test_risk_update_replay_does_not_duplicate_link_or_risk(self):
        case, first, _ = self._run("CASE-R09")
        self.assertEqual(len(self._open_risks(case["topic_id"])), 1)
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.risk_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._open_risks(case["topic_id"])), 1)
        links = self.risk_store.links_for_risk(self.conv["id"], "risk_demo_repair")
        updated_by = [item for item in links if item["relation"] == "UPDATED_BY"]
        self.assertEqual(len(updated_by), 1)

    def test_successful_processing_skips_and_failed_retries(self):
        case, first, _ = self._run("CASE-R02")
        self.assertTrue(self.risk_store.has_successful_processing(self.conv["id"], case["current_message"]["id"]))
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.risk_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)


if __name__ == "__main__":
    unittest.main()
