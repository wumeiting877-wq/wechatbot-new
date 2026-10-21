# -*- coding: utf-8 -*-
"""P6-G6 Missing Processing：MP-01 ～ MP-13。

用 process_record 内的 write_processing 故障注入证明完整缺失是否可达。
不实现 recovery，不把 NOT_FOUND 改成自动首次执行。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DECISION_ENGINE_ENABLED, DecisionEngine
from decision_store import DecisionStore
from downstream_retry import ERROR_NOT_FOUND, ERROR_STOPPED, DownstreamRetryService
from risk_engine import RISK_ENGINE_ENABLED, RiskEngine
from risk_store import RiskStore
from store_io import atomic_write_json
from task_engine import TASK_ENGINE_ENABLED, TaskEngine
from task_sidepath import TaskSidepath
from task_store import TaskStore
from topic_engine import TOPIC_ENGINE_ENABLED, TopicEngine
from topic_retry import ERROR_NOT_FOUND as TOPIC_NOT_FOUND
from topic_retry import ERROR_NOT_RETRYABLE as TOPIC_NOT_RETRYABLE
from topic_retry import ERROR_STOPPED as TOPIC_STOPPED
from topic_retry import TopicRetryService
from topic_sidepath import TopicSidepath
from topic_store import TopicStore

CONV_ID = "conv_p6g6mp"
TOPIC_ID = "topic_p6g6mp"
TOPIC_TEXT = "ERP 同步今天还是有问题。"
TASK_TEXT = "李娜把权限问题修一下。"
CREATED_AT = "2026-09-23T08:00:00+08:00"


class ProcessingFault:
    def __init__(self, store, mode):
        self.store = store
        self.mode = mode
        self.original = store.write_processing
        self.calls = []
        self.attempts = 0
        store.write_processing = self

    def __call__(self, record):
        self.attempts += 1
        data = dict(record or {})
        self.calls.append(
            {
                "decision": data.get("decision"),
                "decision_summary": data.get("decision_summary"),
                "topic_id": data.get("topic_id"),
                "task_ids": list(data.get("task_ids") or []),
                "decision_ids": list(data.get("decision_ids") or []),
                "risk_ids": list(data.get("risk_ids") or []),
            }
        )
        if self.mode == "all" or (self.mode == "first" and self.attempts == 1):
            raise RuntimeError("P6-G6 injected processing write failure")
        return self.original(record)

    def restore(self):
        self.store.write_processing = self.original


class TopicScript:
    def __init__(self, decision="NEW_TOPIC", evidence_ids=None):
        self.decision = decision
        self.evidence_ids = list(evidence_ids or [])
        self.calls = 0

    def extract(self, engine_input, _prompt):
        self.calls += 1
        current = (engine_input.get("current_message") or {}).get("id")
        evidence = [current] if current else []
        for item in self.evidence_ids:
            if item not in evidence:
                evidence.append(item)
        active = list(engine_input.get("active_topics") or [])
        topic_id = active[0]["id"] if active else None
        if self.decision == "UNRELATED":
            return {
                "decision": "UNRELATED",
                "topic_id": None,
                "proposed_title": "",
                "summary_update": "",
                "confidence": "HIGH",
                "evidence_message_ids": evidence,
                "reason": "mp unrelated",
            }
        if self.decision in ("EXISTING_TOPIC", "TOPIC_UPDATE"):
            return {
                "decision": self.decision,
                "topic_id": topic_id,
                "proposed_title": "",
                "summary_update": "规则修复" if self.decision == "TOPIC_UPDATE" else "",
                "confidence": "HIGH",
                "evidence_message_ids": evidence,
                "reason": "mp " + self.decision,
            }
        return {
            "decision": "NEW_TOPIC",
            "topic_id": None,
            "proposed_title": "ERP同步异常",
            "summary_update": TOPIC_TEXT,
            "confidence": "HIGH",
            "evidence_message_ids": evidence,
            "reason": "mp new topic",
        }


class BoomExtractor:
    def __init__(self):
        self.calls = 0

    def extract(self, _engine_input, _prompt):
        self.calls += 1
        raise TimeoutError("mp extractor boom")


class TaskScript:
    def __init__(self, decisions=None):
        self.decisions = list(decisions or ["NEW_TASK"])
        self.calls = 0

    def extract(self, engine_input, _prompt):
        self.calls += 1
        current = engine_input["current_message"]["id"]
        rows = []
        for decision in self.decisions:
            if decision == "UNRELATED":
                rows.append(
                    {
                        "decision": "UNRELATED",
                        "title": "",
                        "description": "",
                        "assignee_text": "",
                        "due_text": "",
                        "confidence": "HIGH",
                        "evidence_message_ids": [current],
                        "reason": "mp unrelated",
                    }
                )
            else:
                rows.append(
                    {
                        "decision": "NEW_TASK",
                        "title": "修权限",
                        "description": TASK_TEXT,
                        "assignee_text": "李娜",
                        "due_text": "",
                        "confidence": "HIGH",
                        "evidence_message_ids": [current],
                        "reason": "mp new task",
                    }
                )
        return {"decisions": rows}


class DecisionScript:
    def __init__(self):
        self.calls = 0

    def extract(self, engine_input, _prompt):
        self.calls += 1
        current = engine_input["current_message"]["id"]
        return {
            "decisions": [
                {
                    "decision": "NEW_DECISION",
                    "title": "采用异常池方案",
                    "decision_text": "就按照异常池方案执行。",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current],
                    "reason": "mp new decision",
                }
            ]
        }


class RiskScript:
    def __init__(self):
        self.calls = 0

    def extract(self, engine_input, _prompt):
        self.calls += 1
        current = engine_input["current_message"]["id"]
        return {
            "risks": [
                {
                    "decision": "NEW_RISK",
                    "title": "演示受阻",
                    "condition_text": "如果今天还修不好",
                    "impact_text": "会影响明天现场演示",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current],
                    "reason": "mp new risk",
                }
            ]
        }


def _record(msg_id, content, platform_message_id=None):
    return {
        "id": msg_id,
        "conversation_id": CONV_ID,
        "platform_message_id": platform_message_id or msg_id,
        "sender_name": "周敏",
        "content": content,
        "created_at": CREATED_AT,
        "direction": "INBOUND",
        "message_type": "text",
    }


def _audit_decisions(store, message_id, field):
    values = []
    for item in store.read_audit(limit=0):
        if str(item.get("message_id") or "") != message_id:
            continue
        if item.get(field):
            values.append(item.get(field))
    return values


class P6G6MissingProcessingTests(unittest.TestCase):
    def setUp(self):
        clear_stop_request()
        clear_emergency_stop()
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.runtime = BotRuntime()
        self.runtime.set_state("RUNNING", "test")
        self.topic_store = TopicStore(self.root)
        self.topic_script = TopicScript()
        self.topic_engine = TopicEngine(
            self.topic_store,
            extractor=self.topic_script,
            root_dir=ROOT,
            enabled=True,
        )
        self.task_store = TaskStore(self.root, topic_store=self.topic_store)
        self.decision_store = DecisionStore(self.root, topic_store=self.topic_store)
        self.risk_store = RiskStore(self.root, topic_store=self.topic_store)
        self.task_script = TaskScript()
        self.decision_script = DecisionScript()
        self.risk_script = RiskScript()
        self.task_engine = TaskEngine(
            self.task_store,
            self.topic_store,
            extractor=self.task_script,
            root_dir=ROOT,
            enabled=True,
        )
        self.decision_engine = DecisionEngine(
            self.decision_store,
            self.topic_store,
            extractor=self.decision_script,
            root_dir=ROOT,
            enabled=True,
        )
        self.risk_engine = RiskEngine(
            self.risk_store,
            self.topic_store,
            extractor=self.risk_script,
            root_dir=ROOT,
            enabled=True,
        )
        self.sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[{"id": CONV_ID}],
            store=self.topic_store,
            engine=self.topic_engine,
            enabled=True,
            maxsize=4,
            prompt_root=ROOT,
        )
        self.topic_retry = TopicRetryService(
            topic_sidepath=self.sidepath,
            runtime=self.runtime,
            conversation={"id": CONV_ID},
        )
        self.downstream_retry = DownstreamRetryService(
            topic_store=self.topic_store,
            task_engine=self.task_engine,
            decision_engine=self.decision_engine,
            risk_engine=self.risk_engine,
            runtime=self.runtime,
            conversation={"id": CONV_ID},
        )

    def tearDown(self):
        try:
            self.sidepath.shutdown()
        except Exception:
            pass
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass
        clear_stop_request()
        clear_emergency_stop()

    def test_engine_flags_remain_false(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)
        self.assertFalse(os.path.isfile(os.path.join(ROOT, "processing_recovery.py")))

    def _seed_downstream_topic(self):
        atomic_write_json(
            os.path.join(self.topic_store.conversation_dir(CONV_ID), "topics.json"),
            {
                "topics": [
                    {
                        "id": TOPIC_ID,
                        "conversation_id": CONV_ID,
                        "title": "权限整改",
                        "summary": "质检员仍能看到采购价格",
                        "status": "ACTIVE",
                        "confidence": "HIGH",
                        "created_at": "2026-09-22T20:00:00+08:00",
                        "updated_at": "2026-09-22T20:00:00+08:00",
                        "last_message_at": "2026-09-22T20:00:00+08:00",
                        "message_count": 0,
                        "schema_version": 1,
                    }
                ]
            },
        )

    def _bind_message(self, msg_id, content):
        message = self.topic_store.upsert_message(_record(msg_id, content))
        self.topic_store.add_link(CONV_ID, TOPIC_ID, message["id"], "CREATED_BY")
        self.topic_store.write_processing(
            {
                "message_id": message["id"],
                "conversation_id": CONV_ID,
                "decision": "NEW_TOPIC",
                "topic_id": TOPIC_ID,
            }
        )
        return message

    def _bundle(self, name):
        return {
            "task": (self.task_engine, self.task_store, self.task_script, "task_decision", "list_tasks"),
            "decision": (
                self.decision_engine,
                self.decision_store,
                self.decision_script,
                "decision_decision",
                "list_decisions",
            ),
            "risk": (self.risk_engine, self.risk_store, self.risk_script, "risk_decision", "list_risks"),
        }[name]

    def _inject_downstream(self, name, msg_id, mode):
        self._seed_downstream_topic()
        message = self._bind_message(msg_id, TASK_TEXT)
        engine, store, _script, audit_field, list_name = self._bundle(name)
        gate = ProcessingFault(store, mode)
        try:
            result = engine.process_record(
                {"id": CONV_ID},
                self.topic_store.get_topic(CONV_ID, TOPIC_ID),
                message,
            )
        finally:
            gate.restore()
        entities = getattr(store, list_name)(CONV_ID)
        return result, gate, store, message, entities, audit_field

    def test_mp01_never_executed_stays_not_found(self):
        message = self.topic_store.upsert_message(_record("msg_mp01", TOPIC_TEXT))
        self.assertIsNone(self.topic_store.get_processing(CONV_ID, message["id"]))
        self.assertEqual(self.topic_store.list_topics(CONV_ID), [])
        before = self.topic_script.calls
        outcome = self.topic_retry.retry_topic(CONV_ID, message["id"], runtime=self.runtime)
        self.assertEqual(outcome.error_code, TOPIC_NOT_FOUND)
        self.assertFalse(outcome.executed)
        self.assertEqual(self.topic_script.calls, before)
        self.assertEqual(self.topic_store.list_topics(CONV_ID), [])
        self.assertIsNone(self.topic_store.get_processing(CONV_ID, message["id"]))

    def test_mp02_success_fail_isolate_success_is_failed(self):
        observed = {}
        gate = ProcessingFault(self.topic_store, "first")
        try:
            result = self.topic_engine.process_record(_record("msg_mp02_topic", TOPIC_TEXT), {"id": CONV_ID})
        finally:
            gate.restore()
        processing = self.topic_store.get_processing(CONV_ID, "msg_mp02_topic")
        self.assertEqual(result.decision, "FAILED")
        self.assertEqual(gate.calls[0]["decision"], "NEW_TOPIC")
        self.assertEqual(gate.calls[1]["decision"], "FAILED")
        self.assertEqual(processing["decision"], "FAILED")
        self.assertEqual(processing["topic_processing_version"], 1)
        self.assertIsNone(processing["topic_id"])
        self.assertEqual(len(self.topic_store.list_topics(CONV_ID)), 1)
        self.assertNotIn("created_msg_id", self.topic_store.list_topics(CONV_ID)[0])
        observed["topic"] = processing["decision"]

        for name, expected in (("task", "NEW_TASK"), ("decision", "NEW_DECISION"), ("risk", "NEW_RISK")):
            _result, injected, store, message, entities, _field = self._inject_downstream(
                name, "msg_mp02_%s" % name, "first"
            )
            processing = store.get_processing(CONV_ID, message["id"])
            self.assertEqual(injected.calls[0]["decision_summary"], expected)
            self.assertEqual(injected.calls[1]["decision_summary"], "FAILED")
            self.assertEqual(len(entities), 1)
            self.assertEqual(processing["decision_summary"], "FAILED")
            self.assertEqual(processing["topic_id"], TOPIC_ID)
            observed[name] = processing["decision_summary"]
        self.assertEqual(set(observed.values()), {"FAILED"})

    def test_mp02_task_failed_retry_keeps_one_entity(self):
        _result, _gate, store, message, before, _field = self._inject_downstream(
            "task", "msg_mp02_retry", "first"
        )
        self.assertEqual(len(before), 1)
        calls_before = self.task_script.calls
        outcome = self.downstream_retry.retry_downstream(
            "task", CONV_ID, message["id"], TOPIC_ID, runtime=self.runtime
        )
        after = store.list_tasks(CONV_ID)
        processing = store.get_processing(CONV_ID, message["id"])
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.executed)
        self.assertNotEqual(outcome.error_code, ERROR_NOT_FOUND)
        self.assertEqual(self.task_script.calls, calls_before + 1)
        self.assertEqual([item["id"] for item in after], [item["id"] for item in before])
        self.assertEqual(processing["decision_summary"], "NEW_TASK")
        self.assertEqual(processing["task_ids"], [before[0]["id"]])

    def test_mp03_both_writes_fail_processing_absent(self):
        gate = ProcessingFault(self.topic_store, "all")
        try:
            result = self.topic_engine.process_record(_record("msg_mp03_topic", TOPIC_TEXT), {"id": CONV_ID})
        finally:
            gate.restore()
        self.assertEqual(result.decision, "FAILED")
        self.assertEqual(gate.calls[0]["decision"], "NEW_TOPIC")
        self.assertEqual(gate.calls[1]["decision"], "FAILED")
        self.assertIsNone(self.topic_store.get_processing(CONV_ID, "msg_mp03_topic"))
        self.assertEqual(len(self.topic_store.list_topics(CONV_ID)), 1)
        links = self.topic_store.links_for_message(CONV_ID, "msg_mp03_topic")
        self.assertEqual([item["relation"] for item in links], ["CREATED_BY"])
        self.assertEqual(_audit_decisions(self.topic_store, "msg_mp03_topic", "topic_decision"), ["FAILED"])

        for name, expected in (("task", "NEW_TASK"), ("decision", "NEW_DECISION"), ("risk", "NEW_RISK")):
            _result, injected, store, message, entities, field = self._inject_downstream(
                name, "msg_mp03_%s" % name, "all"
            )
            self.assertEqual(injected.calls[0]["decision_summary"], expected)
            self.assertTrue(injected.calls[0]["task_ids"] or injected.calls[0]["decision_ids"] or injected.calls[0]["risk_ids"])
            self.assertEqual(len(entities), 1)
            self.assertEqual(entities[0]["created_msg_id"], message["id"])
            self.assertEqual(entities[0]["topic_id"], TOPIC_ID)
            created = [
                item for item in store.list_links(CONV_ID) if item.get("relation") == "CREATED_BY" and item.get("message_id") == message["id"]
            ]
            self.assertEqual(len(created), 1)
            self.assertIsNone(store.get_processing(CONV_ID, message["id"]))
            self.assertEqual(_audit_decisions(store, message["id"], field), ["FAILED"])
            self.assertIsNotNone(self.topic_store.get_message(CONV_ID, message["id"]))

    def test_mp03_missing_processing_retry_stays_not_found(self):
        gate = ProcessingFault(self.topic_store, "all")
        try:
            self.topic_engine.process_record(_record("msg_mp03_retry_topic", TOPIC_TEXT), {"id": CONV_ID})
        finally:
            gate.restore()
        topics_before = [item["id"] for item in self.topic_store.list_topics(CONV_ID)]
        calls_before = self.topic_script.calls
        outcome = self.topic_retry.retry_topic(CONV_ID, "msg_mp03_retry_topic", runtime=self.runtime)
        self.assertEqual(outcome.error_code, TOPIC_NOT_FOUND)
        self.assertFalse(outcome.executed)
        self.assertEqual(self.topic_script.calls, calls_before)
        self.assertEqual([item["id"] for item in self.topic_store.list_topics(CONV_ID)], topics_before)
        self.assertIsNone(self.topic_store.get_processing(CONV_ID, "msg_mp03_retry_topic"))

        _result, _gate, store, message, before, _field = self._inject_downstream(
            "task", "msg_mp03_retry_task", "all"
        )
        calls_before = self.task_script.calls
        rejected = self.downstream_retry.retry_downstream(
            "task", CONV_ID, message["id"], TOPIC_ID, runtime=self.runtime
        )
        self.assertEqual(rejected.error_code, ERROR_NOT_FOUND)
        self.assertFalse(rejected.executed)
        self.assertEqual(self.task_script.calls, calls_before)
        self.assertEqual(store.list_tasks(CONV_ID), before)
        self.assertIsNone(store.get_processing(CONV_ID, message["id"]))

    def test_mp04_topic_reprocess_allocates_second_topic(self):
        gate = ProcessingFault(self.topic_store, "all")
        try:
            self.topic_engine.process_record(_record("msg_mp04", TOPIC_TEXT), {"id": CONV_ID})
        finally:
            gate.restore()
        self.assertIsNone(self.topic_store.get_processing(CONV_ID, "msg_mp04"))
        first_ids = [item["id"] for item in self.topic_store.list_topics(CONV_ID)]
        self.assertEqual(len(first_ids), 1)
        again = self.topic_engine.process_record(_record("msg_mp04", TOPIC_TEXT), {"id": CONV_ID})
        ids = [item["id"] for item in self.topic_store.list_topics(CONV_ID)]
        relations = [item["relation"] for item in self.topic_store.links_for_message(CONV_ID, "msg_mp04")]
        self.assertEqual(again.decision, "NEW_TOPIC")
        self.assertEqual(len(ids), 2)
        self.assertIn(first_ids[0] + "_2", ids)
        self.assertEqual(again.topic_id, first_ids[0] + "_2")
        self.assertEqual(relations, ["CREATED_BY", "CREATED_BY"])
        processing = self.topic_store.get_processing(CONV_ID, "msg_mp04")
        self.assertEqual(processing["decision"], "NEW_TOPIC")
        self.assertEqual(processing["topic_id"], first_ids[0] + "_2")
        self.assertEqual(processing["topic_processing_version"], 1)

    def test_mp04_unrelated_loss_matches_pre_apply_store(self):
        self.topic_engine.extractor = TopicScript("UNRELATED")
        gate = ProcessingFault(self.topic_store, "all")
        try:
            self.topic_engine.process_record(_record("msg_mp04_unrelated", TOPIC_TEXT), {"id": CONV_ID})
        finally:
            gate.restore()
        self.topic_engine.extractor = BoomExtractor()
        boom_gate = ProcessingFault(self.topic_store, "all")
        try:
            self.topic_engine.process_record(_record("msg_mp04_boom", TOPIC_TEXT), {"id": CONV_ID})
        finally:
            boom_gate.restore()

        def shape(message_id):
            return {
                "message": self.topic_store.get_message(CONV_ID, message_id) is not None,
                "links": [
                    item["relation"]
                    for item in self.topic_store.links_for_message(CONV_ID, message_id)
                ],
                "processing": self.topic_store.get_processing(CONV_ID, message_id),
                "audit": _audit_decisions(self.topic_store, message_id, "topic_decision"),
            }

        unrelated = shape("msg_mp04_unrelated")
        boom = shape("msg_mp04_boom")
        self.assertEqual(unrelated["message"], True)
        self.assertEqual(unrelated["links"], [])
        self.assertIsNone(unrelated["processing"])
        self.assertEqual(boom["message"], True)
        self.assertEqual(boom["links"], [])
        self.assertIsNone(boom["processing"])
        self.assertEqual(unrelated["audit"], ["FAILED"])
        self.assertEqual(boom["audit"], ["FAILED"])
        self.assertEqual(gate.calls[0]["decision"], "UNRELATED")
        self.assertEqual(boom_gate.calls[0]["decision"], "FAILED")

    def test_mp04_existing_topic_link_matches_evidence_citation(self):
        self.topic_store.upsert_message(_record("msg_mp04_evidence", "供应商编码为空"))
        self.topic_engine.extractor = TopicScript("NEW_TOPIC", evidence_ids=["msg_mp04_evidence"])
        created = self.topic_engine.process_record(_record("msg_mp04_creator", TOPIC_TEXT), {"id": CONV_ID})
        self.assertEqual(created.decision, "NEW_TOPIC")
        evidence_links = [
            item["relation"] for item in self.topic_store.links_for_message(CONV_ID, "msg_mp04_evidence")
        ]
        self.assertEqual(evidence_links, ["RELATED"])
        self.assertIsNone(self.topic_store.get_processing(CONV_ID, "msg_mp04_evidence"))

        self.topic_engine.extractor = TopicScript("EXISTING_TOPIC")
        gate = ProcessingFault(self.topic_store, "all")
        try:
            self.topic_engine.process_record(
                _record("msg_mp04_existing", "ERP 同步供应商编码还是空。"),
                {"id": CONV_ID},
            )
        finally:
            gate.restore()
        existing_links = [
            item["relation"] for item in self.topic_store.links_for_message(CONV_ID, "msg_mp04_existing")
        ]
        self.assertEqual(gate.calls[0]["decision"], "EXISTING_TOPIC")
        self.assertEqual(existing_links, ["RELATED"])
        self.assertIsNone(self.topic_store.get_processing(CONV_ID, "msg_mp04_existing"))
        self.assertEqual(evidence_links, existing_links)

    def test_mp05_task_mixed_summary_matches_single_new_task(self):
        self._seed_downstream_topic()
        pure = self._bind_message("msg_mp05_pure", TASK_TEXT)
        mixed = self._bind_message("msg_mp05_mixed", TASK_TEXT)
        topic = self.topic_store.get_topic(CONV_ID, TOPIC_ID)

        def run(message, decisions):
            engine = TaskEngine(
                self.task_store,
                self.topic_store,
                extractor=TaskScript(decisions),
                root_dir=ROOT,
                enabled=True,
            )
            gate = ProcessingFault(self.task_store, "all")
            try:
                engine.process_record({"id": CONV_ID}, topic, message)
            finally:
                gate.restore()
            entities = [
                item for item in self.task_store.list_tasks(CONV_ID) if item.get("created_msg_id") == message["id"]
            ]
            relations = [
                item["relation"]
                for item in self.task_store.list_links(CONV_ID)
                if item.get("message_id") == message["id"]
            ]
            return gate.calls[0]["decision_summary"], len(entities), relations, self.task_store.get_processing(
                CONV_ID, message["id"]
            )

        pure_summary, pure_count, pure_relations, pure_processing = run(pure, ["NEW_TASK"])
        mixed_summary, mixed_count, mixed_relations, mixed_processing = run(mixed, ["NEW_TASK", "UNRELATED"])
        self.assertEqual(pure_summary, "NEW_TASK")
        self.assertEqual(mixed_summary, "NEW_TASK,UNRELATED")
        self.assertEqual(pure_count, 1)
        self.assertEqual(mixed_count, 1)
        self.assertEqual(pure_relations, ["CREATED_BY"])
        self.assertEqual(mixed_relations, ["CREATED_BY"])
        self.assertIsNone(pure_processing)
        self.assertIsNone(mixed_processing)

    def test_mp06_decision_missing_window(self):
        _result, injected, store, message, entities, field = self._inject_downstream(
            "decision", "msg_mp06", "all"
        )
        self.assertEqual(injected.calls[0]["decision_summary"], "NEW_DECISION")
        self.assertEqual(injected.calls[0]["decision_ids"], [entities[0]["id"]])
        self.assertIsNone(store.get_processing(CONV_ID, message["id"]))
        self.assertEqual(entities[0]["created_msg_id"], message["id"])
        self.assertEqual(_audit_decisions(store, message["id"], field), ["FAILED"])

    def test_mp07_risk_missing_window(self):
        _result, injected, store, message, entities, field = self._inject_downstream(
            "risk", "msg_mp07", "all"
        )
        self.assertEqual(injected.calls[0]["decision_summary"], "NEW_RISK")
        self.assertEqual(injected.calls[0]["risk_ids"], [entities[0]["id"]])
        self.assertIsNone(store.get_processing(CONV_ID, message["id"]))
        self.assertEqual(entities[0]["created_msg_id"], message["id"])
        self.assertEqual(_audit_decisions(store, message["id"], field), ["FAILED"])

    def test_mp08_success_processing_is_not_overwritten(self):
        first = self.topic_engine.process_record(_record("msg_mp08", TOPIC_TEXT), {"id": CONV_ID})
        self.assertEqual(first.decision, "NEW_TOPIC")
        before = self.topic_store.get_processing(CONV_ID, "msg_mp08")
        calls_before = self.topic_script.calls
        outcome = self.topic_retry.retry_topic(CONV_ID, "msg_mp08", runtime=self.runtime)
        after = self.topic_store.get_processing(CONV_ID, "msg_mp08")
        self.assertEqual(outcome.error_code, TOPIC_NOT_RETRYABLE)
        self.assertFalse(outcome.executed)
        self.assertEqual(self.topic_script.calls, calls_before)
        self.assertEqual(after, before)
        self.assertEqual(after["decision"], "NEW_TOPIC")
        self.assertEqual(len(self.topic_store.list_topics(CONV_ID)), 1)

    def test_mp09_failed_uses_existing_retry(self):
        self._seed_downstream_topic()
        message = self._bind_message("msg_mp09", TASK_TEXT)
        self.task_store.write_processing(
            {
                "message_id": message["id"],
                "conversation_id": CONV_ID,
                "topic_id": TOPIC_ID,
                "decision_summary": "FAILED",
                "error": "seed failed",
            }
        )
        outcome = self.downstream_retry.retry_downstream(
            "task", CONV_ID, message["id"], TOPIC_ID, runtime=self.runtime
        )
        processing = self.task_store.get_processing(CONV_ID, message["id"])
        self.assertTrue(outcome.executed)
        self.assertNotEqual(outcome.error_code, ERROR_NOT_FOUND)
        self.assertEqual(processing["decision_summary"], "NEW_TASK")
        self.assertEqual(len(self.task_store.list_tasks(CONV_ID)), 1)

    def test_mp10_same_text_different_platform_id(self):
        first = {
            "conversation_id": CONV_ID,
            "platform_message_id": "pid-mp10-a",
            "sender_wxid": "wxid_zhangsan",
            "sender_name": "张三",
            "content": "同一句话 ERP 同步失败了",
            "created_at": CREATED_AT,
            "direction": "INBOUND",
            "message_type": "text",
        }
        second = dict(first, platform_message_id="pid-mp10-b")
        left = self.topic_engine.process_record(first, {"id": CONV_ID})
        right = self.topic_engine.process_record(second, {"id": CONV_ID})
        self.assertNotEqual(left.message_id, right.message_id)
        self.assertIsNotNone(self.topic_store.get_processing(CONV_ID, left.message_id))
        self.assertIsNotNone(self.topic_store.get_processing(CONV_ID, right.message_id))
        self.assertEqual(len(self.topic_store.list_messages(CONV_ID)), 2)

    def test_mp11_topic_success_replay_does_not_fanout_again(self):
        task_path = TaskSidepath(root_dir=self.root, extractor=TaskScript(), enabled=True, maxsize=4, prompt_root=ROOT)
        self.sidepath.task_sidepath = task_path
        record = _record("msg_mp11", TOPIC_TEXT)
        try:
            first = self.sidepath.process_record_and_fanout(record, {"id": CONV_ID}, runtime=self.runtime)
            enqueued = task_path.enqueued_count
            second = self.sidepath.process_record_and_fanout(record, {"id": CONV_ID}, runtime=self.runtime)
            self.assertEqual(first.decision, "NEW_TOPIC")
            self.assertFalse(first.replayed)
            self.assertTrue(second.replayed)
            self.assertGreaterEqual(enqueued, 1)
            self.assertEqual(task_path.enqueued_count, enqueued)
            self.assertEqual(len(self.topic_store.list_topics(CONV_ID)), 1)
        finally:
            task_path.shutdown()

    def test_mp12_same_logical_task_reprocess_does_not_duplicate(self):
        _result, _gate, store, message, before, _field = self._inject_downstream(
            "task", "msg_mp12", "all"
        )
        self.assertIsNone(store.get_processing(CONV_ID, message["id"]))
        again = self.task_engine.process_record(
            {"id": CONV_ID},
            self.topic_store.get_topic(CONV_ID, TOPIC_ID),
            message,
        )
        after = store.list_tasks(CONV_ID)
        created = [item for item in store.list_links(CONV_ID) if item.get("relation") == "CREATED_BY"]
        self.assertEqual(again.decision, "NEW_TASK")
        self.assertEqual([item["id"] for item in after], [item["id"] for item in before])
        self.assertEqual(len(created), 1)
        self.assertFalse(any(str(item["id"]).endswith("_2") for item in after))
        processing = store.get_processing(CONV_ID, message["id"])
        self.assertEqual(processing["decision_summary"], "NEW_TASK")
        self.assertEqual(processing["task_ids"], [before[0]["id"]])

    def test_mp13_stopped_rejects_without_writing(self):
        self.runtime.set_state("STOPPED", "test")
        self.topic_store.upsert_message(_record("msg_mp13", TOPIC_TEXT))
        self.topic_store.write_processing(
            {
                "message_id": "msg_mp13",
                "conversation_id": CONV_ID,
                "decision": "FAILED",
                "error": "seed failed",
            }
        )
        before = self.topic_store.get_processing(CONV_ID, "msg_mp13")
        outcome = self.topic_retry.retry_topic(CONV_ID, "msg_mp13", runtime=self.runtime)
        self.assertEqual(outcome.error_code, TOPIC_STOPPED)
        self.assertFalse(outcome.executed)
        self.assertEqual(self.topic_script.calls, 0)
        self.assertEqual(self.topic_store.get_processing(CONV_ID, "msg_mp13"), before)

        self._seed_downstream_topic()
        message = self._bind_message("msg_mp13_task", TASK_TEXT)
        self.task_store.write_processing(
            {
                "message_id": message["id"],
                "conversation_id": CONV_ID,
                "topic_id": TOPIC_ID,
                "decision_summary": "FAILED",
                "error": "seed failed",
            }
        )
        task_before = self.task_store.get_processing(CONV_ID, message["id"])
        rejected = self.downstream_retry.retry_downstream(
            "task", CONV_ID, message["id"], TOPIC_ID, runtime=self.runtime
        )
        self.assertEqual(rejected.error_code, ERROR_STOPPED)
        self.assertFalse(rejected.executed)
        self.assertEqual(self.task_script.calls, 0)
        self.assertEqual(self.task_store.list_tasks(CONV_ID), [])
        self.assertEqual(self.task_store.get_processing(CONV_ID, message["id"]), task_before)


if __name__ == "__main__":
    unittest.main()
