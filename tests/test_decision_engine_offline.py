# -*- coding: utf-8 -*-
"""P5-G1 Gate 3–5：Decision Engine 离线 fixture、失败注入、幂等、源码隔离。"""

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

from decision_engine import (
    DECISION_ENGINE_ENABLED,
    MAX_EXISTING_DECISIONS,
    MAX_RECENT_TOPIC_MESSAGES,
    DecisionEngine,
    engine_source_forbids_wechat_sidepath,
    rule_prefilter,
)
from decision_extractor_client import HeuristicDecisionExtractor
from decision_store import DECISION_FAILED, DecisionStore, DecisionStoreError
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_store import RELATION_CREATED_BY, RELATION_RELATED, TopicStore

FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "p5", "decision_cases.json")
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


def _engine(decision_store, topic_store, extractor=None, enabled=True, root_dir=ROOT):
    return DecisionEngine(
        decision_store,
        topic_store,
        extractor=extractor or HeuristicDecisionExtractor(),
        root_dir=root_dir,
        enabled=enabled,
    )


class CaptureExtractor:
    def __init__(self, inner=None):
        self.inner = inner or HeuristicDecisionExtractor()
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
        for item in data.get("decisions") or []:
            if isinstance(item, dict) and not item.get("evidence_message_ids"):
                item["evidence_message_ids"] = [current_id]
        return data


class DecisionEngineHarness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.decision_store = DecisionStore(self.tmpdir.name, topic_store=self.topic_store)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
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

    def _run(self, case_id, extractor=None, source=None):
        case = self._case(case_id, source=source)
        topic, message = self._prepare(case)
        capture = CaptureExtractor(extractor or HeuristicDecisionExtractor())
        engine = _engine(self.decision_store, self.topic_store, extractor=capture)
        result = engine.process_record(self.conv, topic, message)
        return case, result, capture

    def _recorded(self, topic_id=None):
        items = self.decision_store.list_decisions(self.conv["id"])
        if topic_id:
            items = [item for item in items if item.get("topic_id") == topic_id]
        return [item for item in items if item.get("status") == "RECORDED"]

    def _created_this_run(self, case):
        current_id = case["current_message"]["id"]
        return [
            item
            for item in self._recorded(case["topic_id"])
            if item.get("created_msg_id") == current_id
        ]


class DecisionEngineOfflineTests(DecisionEngineHarness):
    def test_decision_engine_enabled_defaults_false(self):
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        case = self._case("CASE-D01")
        topic, message = self._prepare(case)
        engine = DecisionEngine(self.decision_store, self.topic_store, root_dir=ROOT)
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, "DISABLED")
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_engine_does_not_touch_wechat_sidepath(self):
        self.assertTrue(engine_source_forbids_wechat_sidepath())
        for module_name in ("decision_engine", "decision_extractor_client", "decision_store"):
            source = inspect.getsource(__import__(module_name))
            self.assertNotIn("send_reply" + "(", source)
            self.assertNotIn("wx.SendMsg" + "(", source)
            self.assertNotIn("SendMsg" + "(", source)
            self.assertNotIn("from message.listener", source)

    def test_prefilter_exact_ack_but_not_confirm_prefix(self):
        self.assertEqual(rule_prefilter("收到"), "UNRELATED")
        self.assertEqual(rule_prefilter("收到。"), "UNRELATED")
        self.assertEqual(rule_prefilter("行。"), "UNRELATED")
        self.assertEqual(rule_prefilter("可以。"), "UNRELATED")
        self.assertIsNone(rule_prefilter("可以，就按照异常池方案执行。"))

    def test_case_d01_explicit_decision(self):
        case, result, capture = self._run("CASE-D01")
        expected = case["expected"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_decision_count"])
        decision = created[0]
        self.assertEqual(decision["status"], expected["status"])
        self.assertIsNone(decision["supersedes_decision_id"])
        self.assertNotIn("task_id", decision)
        self.assertTrue(any(token in decision["decision_text"] for token in expected["decision_text_contains"]))
        self.assertTrue(
            any(item in decision["title"] or decision["title"] in item for item in expected["title_whitelist"])
        )
        links = self.decision_store.links_for_decision(self.conv["id"], decision["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(len(created_by), 1)
        self.assertEqual(created_by[0]["message_id"], expected["created_by_message_id"])
        self.assertTrue(all(item["message_id"] not in expected["created_by_must_not"] for item in created_by))
        related_ids = [item["message_id"] for item in links if item["relation"] == RELATION_RELATED]
        for mid in expected.get("related_may_include") or []:
            self.assertIn(mid, related_ids)
        self.assertTrue(all(len(inp["recent_topic_messages"]) <= MAX_RECENT_TOPIC_MESSAGES for inp in capture.inputs))
        self.assertTrue(all(len(inp["existing_decisions"]) <= MAX_EXISTING_DECISIONS for inp in capture.inputs))
        self.assertNotIn("existing_tasks", capture.inputs[0])

    def test_case_d02_suggestion_is_not_decision(self):
        case, result, _ = self._run("CASE-D02")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertEqual(result.decision, "UNRELATED")

    def test_case_d03_bare_ok_is_not_decision(self):
        case, result, capture = self._run("CASE-D03")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))
        self.assertEqual(capture.inputs, [])

    def test_case_d04_explicit_board(self):
        case, result, _ = self._run("CASE-D04")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["status"], "RECORDED")
        self.assertIn("demo-viewer", created[0]["decision_text"])
        links = self.decision_store.links_for_decision(self.conv["id"], created[0]["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(created_by[0]["message_id"], case["current_message"]["id"])

    def test_case_d05_supersede_does_not_overwrite_old(self):
        case, result, _ = self._run("CASE-D05")
        expected = case["expected"]
        old = self.decision_store.get_decision(self.conv["id"], expected["old_decision_id"])
        self.assertEqual(old["decision_text"], "决定使用增量同步。")
        self.assertEqual(old["status"], expected["old_status"])
        self.assertNotIn(old["status"], expected["old_status_not"])
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_decision_count"])
        self.assertEqual(created[0]["supersedes_decision_id"], expected["supersedes_decision_id"])
        self.assertTrue(any(token in created[0]["decision_text"] for token in expected["decision_text_contains"]))
        self.assertEqual(created[0]["status"], "RECORDED")
        self.assertEqual(len(self._recorded(case["topic_id"])), 2)

    def test_case_d06_current_problem_is_not_decision(self):
        case, result, _ = self._run("CASE-D06")
        self.assertEqual(len(self._created_this_run(case)), 0)

    def test_case_d07_task_instruction_is_not_decision(self):
        case, result, _ = self._run("CASE-D07")
        self.assertEqual(len(self._created_this_run(case)), 0)

    def test_case_d08_ack_is_not_decision(self):
        case, result, capture = self._run("CASE-D08")
        self.assertEqual(len(self._created_this_run(case)), 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))
        self.assertEqual(capture.inputs, [])

    def test_case_m01_decision_half(self):
        case, result, _ = self._run("CASE-M01", source=self.mixed)
        expected = case["expected"]["decision"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_decision_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertTrue(any(token in created[0]["decision_text"] for token in expected["decision_text_contains"]))
        links = self.decision_store.links_for_decision(self.conv["id"], created[0]["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(created_by[0]["message_id"], expected["created_by_message_id"])
        self.assertNotIn("task_id", created[0])

    def test_case_m03_decision_half(self):
        case, result, _ = self._run("CASE-M03", source=self.mixed)
        expected = case["expected"]["decision"]
        created = self._created_this_run(case)
        self.assertEqual(len(created), expected["new_decision_count"])
        self.assertEqual(created[0]["status"], expected["status"])
        self.assertTrue(any(token in created[0]["decision_text"] for token in expected["decision_text_contains"]))
        self.assertFalse(expected["has_task_id_field"])
        self.assertNotIn("task_id", created[0])
        links = self.decision_store.links_for_decision(self.conv["id"], created[0]["id"])
        created_by = [item for item in links if item["relation"] == RELATION_CREATED_BY]
        self.assertEqual(created_by[0]["message_id"], expected["created_by_message_id"])

    def test_risk_engine_not_implemented(self):
        # G4：Risk Side-path 已存在，但 Decision Engine 仍不得调用 / 引用 Risk。
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "risk_sidepath.py")))
        import decision_engine as decision_engine_mod

        source = inspect.getsource(decision_engine_mod)
        self.assertNotIn("RiskEngine", source)
        self.assertNotIn("risk_engine", source)
        self.assertNotIn("risk_store", source)
        self.assertNotIn("risk_sidepath", source)

    def test_missing_topic_evidence_does_not_guess(self):
        cid = self.conv["id"]
        topic = self.topic_store.get_topic(cid, "topic_demo_erp")
        message = self.topic_store.upsert_message(
            {
                "id": "msg_orphan",
                "conversation_id": cid,
                "platform_message_id": "msg_orphan",
                "sender_name": "周敏",
                "content": "可以，就按照异常池方案执行。",
            }
        )
        engine = _engine(self.decision_store, self.topic_store)
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "TOPIC_EVIDENCE_MISSING")
        self.assertEqual(self.decision_store.list_decisions(cid), [])
        self.assertEqual(len(self.topic_store.list_topics(cid)), 3)


class FailureInjectionTests(DecisionEngineHarness):
    def _seed_current(self, content="可以，就按照异常池方案执行。", msg_id="fail_msg"):
        topic = self.topic_store.get_topic(self.conv["id"], "topic_demo_erp")
        message = _upsert_msg(
            self.topic_store,
            self.conv["id"],
            {"id": msg_id, "sender_name": "周敏", "content": content, "created_at": "2026-09-22T10:21:00+08:00"},
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

    def _assert_frozen(self, before_topics, before_links, before_tasks):
        self.assertEqual(self._snapshot_topics(), before_topics)
        self.assertEqual(self._snapshot_links(), before_links)
        self.assertEqual(self._snapshot_tasks(), before_tasks)
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_extractor_timeout_isolated(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()
        before_links = self._snapshot_links()
        before_tasks = self._snapshot_tasks()

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise TimeoutError("llm timeout")

        result = _engine(self.decision_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(result.error_code, "EXTRACTOR_TIMEOUT")
        self._assert_frozen(before_topics, before_links, before_tasks)
        rec = self.decision_store.get_processing(self.conv["id"], "fail_msg")
        self.assertEqual(rec["decision_summary"], DECISION_FAILED)

    def test_extractor_exception_isolated(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()
        before_links = self._snapshot_links()
        before_tasks = self._snapshot_tasks()

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("boom")

        result = _engine(self.decision_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self._assert_frozen(before_topics, before_links, before_tasks)

    def test_invalid_json_isolated(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()
        before_links = self._snapshot_links()
        before_tasks = self._snapshot_tasks()
        result = _engine(
            self.decision_store, self.topic_store, extractor=ScriptedExtractor("not-json-at-all")
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "JSON_PARSE_ERROR")
        self._assert_frozen(before_topics, before_links, before_tasks)

    def test_empty_output_isolated(self):
        topic, message = self._seed_current()
        result = _engine(self.decision_store, self.topic_store, extractor=ScriptedExtractor("")).process_record(
            self.conv, topic, message
        )
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "EXTRACTOR_EMPTY")
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_invalid_supersedes_id_isolated(self):
        topic, message = self._seed_current()
        result = _engine(
            self.decision_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "supersedes_decision_id": "dec_invented",
                            "title": "改用全量同步",
                            "decision_text": "改成全量同步。",
                            "confidence": "HIGH",
                            "reason": "x",
                        }
                    ]
                }
            ),
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "INVALID_SUPERSEDES_DECISION_ID")
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])
        self.assertIsNone(self.decision_store.get_decision(self.conv["id"], "dec_invented"))

    def test_invalid_evidence_id_isolated(self):
        topic, message = self._seed_current()
        result = _engine(
            self.decision_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "title": "采用异常池方案",
                            "decision_text": "就按照异常池方案执行。",
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
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_second_invalid_does_not_leave_half_apply(self):
        topic, message = self._seed_current()
        result = _engine(
            self.decision_store,
            self.topic_store,
            extractor=ScriptedExtractor(
                {
                    "decisions": [
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "title": "采用异常池方案",
                            "decision_text": "就按照异常池方案执行。",
                            "confidence": "HIGH",
                            "reason": "ok",
                        },
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "supersedes_decision_id": "dec_invented",
                            "title": "改用全量同步",
                            "decision_text": "改成全量同步。",
                            "confidence": "HIGH",
                            "reason": "bad",
                        },
                    ]
                }
            ),
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_prompt_missing_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                return {"decisions": [{"decision": "UNRELATED", "decision_id": None}]}

        topic, message = self._seed_current(msg_id="no_prompt")
        engine = DecisionEngine(
            self.decision_store,
            self.topic_store,
            extractor=Boom(),
            root_dir=self.tmpdir.name,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_NOT_FOUND")
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_prompt_empty_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                raise AssertionError("should not run")

        prompt_dir = os.path.join(self.tmpdir.name, "prompts", "extractors")
        os.makedirs(prompt_dir)
        with open(os.path.join(prompt_dir, "DECISION_EXTRACTOR.md"), "w", encoding="utf-8") as handle:
            handle.write("\n")
        topic, message = self._seed_current(msg_id="empty_prompt")
        engine = DecisionEngine(
            self.decision_store,
            self.topic_store,
            extractor=Boom(),
            root_dir=self.tmpdir.name,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_EMPTY")
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])

    def test_store_write_failure_no_dirty_decision(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()

        class BoomStore(DecisionStore):
            def commit_apply(self, *args, **kwargs):
                raise DecisionStoreError("STORE_WRITE_FAILURE", "disk full")

        boom = BoomStore(self.tmpdir.name, topic_store=self.topic_store)
        result = _engine(boom, self.topic_store).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "STORE_WRITE_FAILURE")
        self.assertEqual(self.decision_store.list_decisions(self.conv["id"]), [])
        self.assertEqual(self._snapshot_topics(), before_topics)

    def test_process_does_not_raise_to_caller(self):
        topic, message = self._seed_current(msg_id="no_crash")

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("explode")

        engine = _engine(self.decision_store, self.topic_store, extractor=Boom())
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)

    def test_failed_then_retry_can_succeed(self):
        topic, message = self._seed_current(msg_id="retry_msg")

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("first fail")

        first = _engine(self.decision_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(first.decision, DECISION_FAILED)
        second = _engine(self.decision_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertEqual(second.decision, "NEW_DECISION")
        self.assertEqual(len(self._recorded("topic_demo_erp")), 1)


class IdempotencyTests(DecisionEngineHarness):
    def test_same_message_replay_does_not_duplicate_decision(self):
        case, first, _ = self._run("CASE-D01")
        created = self._created_this_run(case)
        self.assertEqual(len(created), 1)
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.decision_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._created_this_run(case)), 1)

    def test_multi_decision_replay_does_not_increase_count(self):
        topic, message = FailureInjectionTests._seed_current(self, content="那就这么定，现场演示使用 demo-viewer 账号。", msg_id="multi_dec")

        class TwoDecisions:
            def extract(self, engine_input, prompt_content):
                current_id = engine_input["current_message"]["id"]
                return {
                    "decisions": [
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "title": "采用异常池方案",
                            "decision_text": "就按照异常池方案执行。",
                            "confidence": "HIGH",
                            "evidence_message_ids": [current_id],
                            "reason": "a",
                        },
                        {
                            "decision": "NEW_DECISION",
                            "decision_id": None,
                            "title": "使用 demo-viewer",
                            "decision_text": "现场演示使用 demo-viewer 账号。",
                            "confidence": "HIGH",
                            "evidence_message_ids": [current_id],
                            "reason": "b",
                        },
                    ]
                }

        first = _engine(self.decision_store, self.topic_store, extractor=TwoDecisions()).process_record(
            self.conv, topic, message
        )
        self.assertEqual(first.new_decision_count, 2)
        second = _engine(self.decision_store, self.topic_store, extractor=TwoDecisions()).process_record(
            self.conv, topic, message
        )
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._recorded("topic_demo_erp")), 2)

    def test_supersede_replay_does_not_create_second(self):
        case, first, _ = self._run("CASE-D05")
        self.assertEqual(len(self._created_this_run(case)), 1)
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.decision_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._created_this_run(case)), 1)
        old = self.decision_store.get_decision(self.conv["id"], "dec_demo_incr")
        self.assertEqual(old["decision_text"], "决定使用增量同步。")
        self.assertEqual(old["status"], "RECORDED")


if __name__ == "__main__":
    unittest.main()
