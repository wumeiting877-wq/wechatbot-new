# -*- coding: utf-8 -*-
"""P4-G1 Gate 3–5：Task Engine 离线 fixture、失败注入、幂等、源码隔离。"""

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

from store_io import atomic_write_json
from task_engine import (
    MAX_EXISTING_TASKS,
    MAX_RECENT_TOPIC_MESSAGES,
    TASK_ENGINE_ENABLED,
    TaskEngine,
    engine_source_forbids_wechat_sidepath,
    rule_prefilter,
)
from task_extractor_client import HeuristicTaskExtractor
from task_store import DECISION_FAILED, TaskStore, TaskStoreError
from topic_engine import TOPIC_ENGINE_ENABLED
from topic_store import RELATION_CREATED_BY, RELATION_RELATED, TopicStore

FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "task_engine", "zhiqun_task_cases.json")


def _load_cases():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
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


def _engine(task_store, topic_store, extractor=None, enabled=True, root_dir=ROOT):
    return TaskEngine(
        task_store,
        topic_store,
        extractor=extractor or HeuristicTaskExtractor(),
        root_dir=root_dir,
        enabled=enabled,
    )


class CaptureExtractor:
    def __init__(self, inner=None):
        self.inner = inner or HeuristicTaskExtractor()
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


class TaskEngineHarness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(self.tmpdir.name)
        self.task_store = TaskStore(self.tmpdir.name, topic_store=self.topic_store)
        self.fixture = _load_cases()
        self.conv = dict(self.fixture["conversation"])
        self.topics = {item["id"]: item for item in self.fixture["topics"]}
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

    def _run(self, case_id, extractor=None):
        case = self._case(case_id)
        topic, message = self._prepare(case)
        capture = CaptureExtractor(extractor or HeuristicTaskExtractor())
        engine = _engine(self.task_store, self.topic_store, extractor=capture)
        result = engine.process_record(self.conv, topic, message)
        return case, result, capture

    def _open_tasks(self, topic_id=None):
        items = self.task_store.list_tasks(self.conv["id"])
        if topic_id:
            items = [item for item in items if item.get("topic_id") == topic_id]
        return [item for item in items if item.get("status") == "OPEN"]


class TaskEngineOfflineTests(TaskEngineHarness):
    def test_task_engine_enabled_defaults_false(self):
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        case = self._case("CASE-T01")
        topic, message = self._prepare(case)
        engine = TaskEngine(self.task_store, self.topic_store, root_dir=ROOT)
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, "DISABLED")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])

    def test_engine_does_not_touch_wechat_sidepath(self):
        self.assertTrue(engine_source_forbids_wechat_sidepath())
        for module_name in ("task_engine", "task_extractor_client", "task_store"):
            source = inspect.getsource(__import__(module_name))
            self.assertNotIn("send_reply" + "(", source)
            self.assertNotIn("wx.SendMsg" + "(", source)
            self.assertNotIn("SendMsg" + "(", source)
            self.assertNotIn("from message.listener", source)

    def test_prefilter_exact_ack_but_not_prefix(self):
        self.assertEqual(rule_prefilter("收到"), "UNRELATED")
        self.assertEqual(rule_prefilter("收到。"), "UNRELATED")
        self.assertIsNone(rule_prefilter("收到，16 点前给结果"))

    def test_case_t01_nullrule_open_task(self):
        case, result, capture = self._run("CASE-T01")
        expected = case["expected"]
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), expected["new_task_count"])
        task = tasks[0]
        self.assertEqual(task["assignee_text"], expected["assignee_text"])
        self.assertNotEqual(task["assignee_text"], "周敏")
        self.assertIn(expected["due_text_contains"], task["due_text"])
        self.assertEqual(task["due_at"], "")
        self.assertEqual(task["status"], "OPEN")
        self.assertTrue(any(item in task["title"] or task["title"] in item for item in expected["title_whitelist"]))
        self.assertEqual(task["conversation_id"], self.conv["id"])
        self.assertEqual(task["topic_id"], case["topic_id"])
        self.assertTrue(all(len(inp["recent_topic_messages"]) <= MAX_RECENT_TOPIC_MESSAGES for inp in capture.inputs))
        self.assertTrue(all(len(inp["existing_tasks"]) <= MAX_EXISTING_TASKS for inp in capture.inputs))
        self.assertIn(result.message_id, [link["message_id"] for link in self.task_store.links_for_task(self.conv["id"], task["id"])])

    def test_case_t02_no_assignee_zero_task(self):
        case, result, _ = self._run("CASE-T02")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 0)
        self.assertEqual(result.decision, "UNRELATED")

    def test_case_t03_no_due_still_creates(self):
        case, result, _ = self._run("CASE-T03")
        expected = case["expected"]
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), expected["new_task_count"])
        self.assertEqual(tasks[0]["assignee_text"], "李娜")
        self.assertEqual(tasks[0]["due_text"], "")
        self.assertEqual(tasks[0]["status"], "OPEN")
        self.assertTrue(any(item in tasks[0]["title"] or tasks[0]["title"] in item for item in expected["title_whitelist"]))

    def test_case_t04_two_tasks_same_topic(self):
        case, result, _ = self._run("CASE-T04")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 2)
        by_assignee = {item["assignee_text"]: item for item in tasks}
        self.assertIn("王强", by_assignee)
        self.assertIn("李娜", by_assignee)
        self.assertTrue(any(token in by_assignee["王强"]["title"] for token in ("供应商", "编码", "空值")))
        self.assertIn("权限", by_assignee["李娜"]["title"])
        self.assertTrue(all(item["topic_id"] == "topic_demo_erp" for item in tasks))
        self.assertEqual(len(self.topic_store.list_topics(self.conv["id"])), 3)

    def test_case_t05_update_due_not_duplicate(self):
        case, result, _ = self._run("CASE-T05")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(result.new_task_count, 0)
        self.assertEqual(result.update_count, 1)
        self.assertEqual(tasks[0]["id"], "task_demo_nullrule")
        self.assertIn("17 点", tasks[0]["due_text"])
        self.assertEqual(tasks[0]["status"], "OPEN")

    def test_case_t06_ack_zero_new_task(self):
        case, result, capture = self._run("CASE-T06")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 1)
        self.assertEqual(result.new_task_count, 0)
        self.assertIn(result.decision, ("UNRELATED", "SKIPPED"))
        self.assertEqual(capture.inputs, [])
        self.assertEqual(self._open_tasks(case["topic_id"])[0]["due_text"], "今天 16 点前")

    def test_case_t07_problem_fact_not_task(self):
        case, result, _ = self._run("CASE-T07")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 0)
        self.assertEqual(result.decision, "UNRELATED")

    def test_case_t08_suggestion_not_new_task(self):
        case, result, _ = self._run("CASE-T08")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(result.new_task_count, 0)
        self.assertEqual(len(tasks), 1)
        self.assertNotIn("异常池", tasks[0]["title"])
        self.assertEqual(result.decision, "UNRELATED")

    def test_case_t09_no_new_task_no_invented_assignee(self):
        case, result, _ = self._run("CASE-T09")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(result.new_task_count, 0)
        self.assertIn(result.decision, ("TASK_UPDATE", "UNRELATED"))
        self.assertEqual(len(tasks), 1)
        self.assertNotEqual(tasks[0].get("assignee_text"), "周敏")
        self.assertEqual(tasks[0]["assignee_text"], "王强")

    def test_case_t09b_confirm_without_existing_is_unrelated(self):
        case, result, _ = self._run("CASE-T09b")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 0)
        self.assertEqual(result.decision, "UNRELATED")

    def test_case_t10_completion_keeps_open(self):
        case, result, _ = self._run("CASE-T10")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(result.new_task_count, 0)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "OPEN")
        self.assertEqual(result.decision, "UNRELATED")
        self.assertNotIn("DONE", result.decision_summary)
        self.assertNotIn("TASK_COMPLETE", result.decision_summary)

    def test_missing_topic_evidence_does_not_guess(self):
        cid = self.conv["id"]
        topic = self.topic_store.get_topic(cid, "topic_demo_erp")
        message = self.topic_store.upsert_message(
            {
                "id": "msg_orphan",
                "conversation_id": cid,
                "platform_message_id": "msg_orphan",
                "sender_name": "周敏",
                "content": "王强今天 16 点前把空值处理规则做完。",
            }
        )
        engine = _engine(self.task_store, self.topic_store)
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "TOPIC_EVIDENCE_MISSING")
        self.assertEqual(self.task_store.list_tasks(cid), [])
        self.assertEqual(len(self.topic_store.list_topics(cid)), 3)


class FailureInjectionTests(TaskEngineHarness):
    def _seed_current(self, content="李娜把权限问题修一下。", msg_id="fail_msg"):
        topic = self.topic_store.get_topic(self.conv["id"], "topic_demo_perm")
        message = _upsert_msg(
            self.topic_store,
            self.conv["id"],
            {"id": msg_id, "sender_name": "周敏", "content": content, "created_at": "2026-09-20T09:13:00+08:00"},
            "topic_demo_perm",
            RELATION_CREATED_BY,
        )
        return topic, message

    def _snapshot_topics(self):
        return json.dumps(self.topic_store.list_topics(self.conv["id"]), ensure_ascii=False, sort_keys=True)

    def _snapshot_links(self):
        return json.dumps(self.topic_store.list_links(self.conv["id"]), ensure_ascii=False, sort_keys=True)

    def test_extractor_timeout_isolated(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()
        before_links = self._snapshot_links()

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise TimeoutError("llm timeout")

        result = _engine(self.task_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(result.error_code, "EXTRACTOR_TIMEOUT")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])
        self.assertEqual(self._snapshot_topics(), before_topics)
        self.assertEqual(self._snapshot_links(), before_links)
        rec = self.task_store.get_processing(self.conv["id"], "fail_msg")
        self.assertEqual(rec["decision_summary"], DECISION_FAILED)

    def test_extractor_exception_isolated(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("boom")

        result = _engine(self.task_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(self._snapshot_topics(), before_topics)
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])

    def test_invalid_json_isolated(self):
        topic, message = self._seed_current()
        result = _engine(self.task_store, self.topic_store, extractor=ScriptedExtractor("not-json-at-all")).process_record(
            self.conv, topic, message
        )
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "JSON_PARSE_ERROR")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])

    def test_invalid_task_id_does_not_create_it(self):
        topic, message = self._seed_current()
        result = _engine(
            self.task_store,
            self.topic_store,
            extractor=ScriptedExtractor(
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
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "INVALID_TASK_ID")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])
        self.assertIsNone(self.task_store.get_task(self.conv["id"], "task_does_not_exist"))

    def test_invalid_evidence_id_isolated(self):
        topic, message = self._seed_current()
        result = _engine(
            self.task_store,
            self.topic_store,
            extractor=ScriptedExtractor(
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
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "INVALID_EVIDENCE_ID")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])

    def test_invalid_assignee_text_isolated(self):
        topic, message = self._seed_current()
        result = _engine(
            self.task_store,
            self.topic_store,
            extractor=ScriptedExtractor(
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
        ).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "INVALID_ASSIGNEE")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])

    def test_prompt_missing_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                return {"decisions": [{"decision": "UNRELATED", "task_id": None}]}

        topic, message = self._seed_current(msg_id="no_prompt")
        engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=Boom(),
            root_dir=self.tmpdir.name,
            enabled=True,
        )
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_NOT_FOUND")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])

    def test_prompt_empty_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                raise AssertionError("should not run")

        prompt_dir = os.path.join(self.tmpdir.name, "prompts", "extractors")
        os.makedirs(prompt_dir)
        with open(os.path.join(prompt_dir, "TASK_EXTRACTOR.md"), "w", encoding="utf-8") as handle:
            handle.write("\n")
        topic, message = self._seed_current(msg_id="empty_prompt")
        engine = TaskEngine(self.task_store, self.topic_store, extractor=Boom(), root_dir=self.tmpdir.name, enabled=True)
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_EMPTY")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])

    def test_store_write_failure_no_dirty_task(self):
        topic, message = self._seed_current()
        before_topics = self._snapshot_topics()

        class BoomStore(TaskStore):
            def commit_apply(self, *args, **kwargs):
                raise TaskStoreError("STORE_WRITE_FAILURE", "disk full")

        boom = BoomStore(self.tmpdir.name, topic_store=self.topic_store)
        result = _engine(boom, self.topic_store).process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "STORE_WRITE_FAILURE")
        self.assertEqual(self.task_store.list_tasks(self.conv["id"]), [])
        self.assertEqual(self._snapshot_topics(), before_topics)

    def test_process_does_not_raise_to_caller(self):
        topic, message = self._seed_current(msg_id="no_crash")

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("explode")

        engine = _engine(self.task_store, self.topic_store, extractor=Boom())
        result = engine.process_record(self.conv, topic, message)
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)

    def test_failed_then_retry_can_succeed(self):
        topic, message = self._seed_current(msg_id="retry_msg")

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("first fail")

        first = _engine(self.task_store, self.topic_store, extractor=Boom()).process_record(self.conv, topic, message)
        self.assertEqual(first.decision, DECISION_FAILED)
        second = _engine(self.task_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertEqual(second.decision, "NEW_TASK")
        self.assertEqual(len(self._open_tasks("topic_demo_perm")), 1)


class IdempotencyTests(TaskEngineHarness):
    def test_same_message_replay_does_not_duplicate_task(self):
        case, first, _ = self._run("CASE-T01")
        tasks = self._open_tasks(case["topic_id"])
        self.assertEqual(len(tasks), 1)
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.task_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 1)
        self.assertEqual(len(self.task_store.list_links(self.conv["id"])), len(self.task_store.links_for_task(self.conv["id"], tasks[0]["id"])))

    def test_two_task_message_replay_keeps_two(self):
        case, first, _ = self._run("CASE-T04")
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 2)
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.task_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 2)

    def test_update_replay_does_not_duplicate_link_or_change(self):
        case, first, _ = self._run("CASE-T05")
        links_before = self.task_store.list_links(self.conv["id"])
        due_before = self._open_tasks(case["topic_id"])[0]["due_text"]
        topic = self.topic_store.get_topic(self.conv["id"], case["topic_id"])
        message = self.topic_store.get_message(self.conv["id"], case["current_message"]["id"])
        second = _engine(self.task_store, self.topic_store).process_record(self.conv, topic, message)
        self.assertTrue(second.replayed)
        self.assertEqual(len(self.task_store.list_links(self.conv["id"])), len(links_before))
        self.assertEqual(self._open_tasks(case["topic_id"])[0]["due_text"], due_before)
        self.assertEqual(len(self._open_tasks(case["topic_id"])), 1)


if __name__ == "__main__":
    unittest.main()
