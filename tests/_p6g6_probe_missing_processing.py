# -*- coding: utf-8 -*-
"""P6-G6 read-only probe. Failure-inject write_processing inside process_record.

Does not modify production code. Prints one JSON object.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decision_engine import DecisionEngine
from risk_engine import RiskEngine
from store_io import atomic_write_json
from task_engine import TaskEngine
from task_store import TaskStore
from topic_engine import TopicEngine
from topic_store import TopicStore

CONV = "conv_p6g6probe"
TOPIC_ID = "topic_p6g6probe"


class Gate:
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
                "n": self.attempts,
                "decision": data.get("decision"),
                "decision_summary": data.get("decision_summary"),
                "topic_id": data.get("topic_id"),
                "task_ids": list(data.get("task_ids") or []),
                "decision_ids": list(data.get("decision_ids") or []),
                "risk_ids": list(data.get("risk_ids") or []),
                "version": data.get("topic_processing_version")
                or data.get("task_processing_version")
                or data.get("decision_processing_version")
                or data.get("risk_processing_version"),
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

    def extract(self, engine_input, prompt_content):
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
                "reason": "probe unrelated",
            }
        if self.decision in ("EXISTING_TOPIC", "TOPIC_UPDATE"):
            return {
                "decision": self.decision,
                "topic_id": topic_id,
                "proposed_title": "",
                "summary_update": "probe update" if self.decision == "TOPIC_UPDATE" else "",
                "confidence": "HIGH",
                "evidence_message_ids": evidence,
                "reason": "probe " + self.decision,
            }
        return {
            "decision": "NEW_TOPIC",
            "topic_id": None,
            "proposed_title": "探针主题",
            "summary_update": "探针摘要",
            "confidence": "HIGH",
            "evidence_message_ids": evidence,
            "reason": "probe new topic",
        }


class Boom:
    def extract(self, engine_input, prompt_content):
        raise TimeoutError("probe extractor boom")


class TaskScript:
    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = 0

    def extract(self, engine_input, prompt_content):
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
                        "reason": "probe unrelated",
                    }
                )
            else:
                rows.append(
                    {
                        "decision": "NEW_TASK",
                        "title": "修权限",
                        "description": "李娜把权限问题修一下",
                        "assignee_text": "李娜",
                        "due_text": "",
                        "confidence": "HIGH",
                        "evidence_message_ids": [current],
                        "reason": "probe new task",
                    }
                )
        return {"decisions": rows}


def _msg(msg_id, content="李娜把权限问题修一下。"):
    return {
        "id": msg_id,
        "conversation_id": CONV,
        "platform_message_id": msg_id,
        "sender_name": "周敏",
        "content": content,
        "created_at": "2026-09-23T08:00:00+08:00",
        "direction": "INBOUND",
        "message_type": "text",
    }


def _seed_topic(topic_store):
    atomic_write_json(
        os.path.join(topic_store.conversation_dir(CONV), "topics.json"),
        {
            "topics": [
                {
                    "id": TOPIC_ID,
                    "conversation_id": CONV,
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


def _audit_for(store, message_id):
    rows = []
    for item in store.read_audit(limit=0):
        if str(item.get("message_id") or "") != message_id:
            continue
        rows.append(
            {
                "topic_decision": item.get("topic_decision"),
                "task_decision": item.get("task_decision"),
                "decision_decision": item.get("decision_decision"),
                "risk_decision": item.get("risk_decision"),
                "topic_id": item.get("topic_id"),
                "error": item.get("error"),
            }
        )
    return rows


def _topic_state(store, message_id):
    topics = store.list_topics(CONV)
    links = [item for item in store.list_links(CONV) if item.get("message_id") == message_id]
    proc = store.get_processing(CONV, message_id)
    return {
        "message": store.get_message(CONV, message_id) is not None,
        "topic_count": len(topics),
        "topic_ids": [item.get("id") for item in topics],
        "topic_has_created_msg_id": any("created_msg_id" in item for item in topics),
        "link_relations": [item.get("relation") for item in links],
        "processing": proc,
        "audit": _audit_for(store, message_id),
    }


def main():
    report = {"cases": []}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        topic_store = TopicStore(root)
        topic_script = TopicScript()
        topic_engine = TopicEngine(
            topic_store,
            extractor=topic_script,
            root_dir=ROOT,
            enabled=True,
        )
        record = _msg("msg_topic_case_a", "ERP 同步今天还是有问题。")
        gate = Gate(topic_store, "first")
        result = topic_engine.process_record(record, {"id": CONV})
        report["cases"].append(
            {
                "name": "topic_case_a",
                "result_decision": result.decision,
                "error_code": result.error_code,
                "isolated": result.isolated,
                "attempts": gate.attempts,
                "calls": gate.calls,
                "state": _topic_state(topic_store, "msg_topic_case_a"),
            }
        )
        gate.restore()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        topic_store = TopicStore(root)
        topic_script = TopicScript()
        topic_engine = TopicEngine(
            topic_store,
            extractor=topic_script,
            root_dir=ROOT,
            enabled=True,
        )
        record = _msg("msg_topic_case_b", "ERP 同步今天还是有问题。")
        gate = Gate(topic_store, "all")
        result = topic_engine.process_record(record, {"id": CONV})
        before = _topic_state(topic_store, "msg_topic_case_b")
        gate.restore()
        topic_script.calls = 0
        again = topic_engine.process_record(record, {"id": CONV})
        after = _topic_state(topic_store, "msg_topic_case_b")
        report["cases"].append(
            {
                "name": "topic_case_b_then_reprocess",
                "result_decision": result.decision,
                "error_code": result.error_code,
                "attempts": gate.attempts,
                "calls": gate.calls,
                "extractor_calls_on_second": topic_script.calls,
                "second_decision": again.decision,
                "second_topic_id": again.topic_id,
                "before": before,
                "after": after,
            }
        )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        topic_store = TopicStore(root)
        unrelated = TopicScript("UNRELATED")
        engine = TopicEngine(topic_store, extractor=unrelated, root_dir=ROOT, enabled=True)
        gate = Gate(topic_store, "all")
        result = engine.process_record(_msg("msg_unrelated", "ERP 同步今天还是有问题。"), {"id": CONV})
        unrelated_state = _topic_state(topic_store, "msg_unrelated")
        gate.restore()

        boom_engine = TopicEngine(topic_store, extractor=Boom(), root_dir=ROOT, enabled=True)
        boom_gate = Gate(topic_store, "all")
        boom = boom_engine.process_record(_msg("msg_boom", "ERP 同步今天还是有问题。"), {"id": CONV})
        boom_state = _topic_state(topic_store, "msg_boom")
        boom_gate.restore()
        report["cases"].append(
            {
                "name": "topic_unrelated_vs_pre_apply",
                "unrelated_decision": result.decision,
                "unrelated_calls": gate.calls,
                "unrelated_state": unrelated_state,
                "boom_decision": boom.decision,
                "boom_calls": boom_gate.calls,
                "boom_state": boom_state,
            }
        )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        topic_store = TopicStore(root)
        creator = TopicScript("NEW_TOPIC", evidence_ids=["msg_evidence"])
        engine = TopicEngine(topic_store, extractor=creator, root_dir=ROOT, enabled=True)
        topic_store.upsert_message(_msg("msg_evidence", "供应商编码为空"))
        created = engine.process_record(_msg("msg_creator", "ERP 同步今天还是有问题。"), {"id": CONV})
        evidence_state = _topic_state(topic_store, "msg_evidence")
        existing_script = TopicScript("EXISTING_TOPIC")
        existing_engine = TopicEngine(
            topic_store, extractor=existing_script, root_dir=ROOT, enabled=True
        )
        gate = Gate(topic_store, "all")
        existing = existing_engine.process_record(_msg("msg_existing", "ERP 同步供应商编码还是空。"), {"id": CONV})
        existing_state = _topic_state(topic_store, "msg_existing")
        gate.restore()
        report["cases"].append(
            {
                "name": "topic_related_ambiguity",
                "creator_decision": created.decision,
                "creator_topic": created.topic_id,
                "evidence_never_ran": evidence_state,
                "existing_result": existing.decision,
                "existing_calls": gate.calls,
                "existing_case_b": existing_state,
            }
        )

    def downstream(name, script_factory, store_factory, engine_factory, list_fn):
        rows = []
        for mode in ("first", "all"):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
                topic_store = TopicStore(root)
                _seed_topic(topic_store)
                msg = topic_store.upsert_message(_msg("msg_%s_%s" % (name, mode)))
                topic_store.add_link(CONV, TOPIC_ID, msg["id"], "CREATED_BY")
                store = store_factory(root, topic_store)
                script = script_factory()
                engine = engine_factory(store, topic_store, script)
                gate = Gate(store, mode)
                topic = topic_store.get_topic(CONV, TOPIC_ID)
                result = engine.process_record({"id": CONV}, topic, msg)
                entities = list_fn(store)
                proc = store.get_processing(CONV, msg["id"])
                links = store.list_links(CONV)
                rows.append(
                    {
                        "engine": name,
                        "mode": mode,
                        "result_decision": result.decision,
                        "error_code": result.error_code,
                        "attempts": gate.attempts,
                        "calls": gate.calls,
                        "entity_count": len(entities),
                        "entity_ids": [item.get("id") for item in entities],
                        "created_msg_ids": [item.get("created_msg_id") for item in entities],
                        "link_relations": [item.get("relation") for item in links],
                        "processing": None
                        if proc is None
                        else {
                            "decision_summary": proc.get("decision_summary"),
                            "topic_id": proc.get("topic_id"),
                        },
                        "audit": _audit_for(store, msg["id"]),
                        "message": topic_store.get_message(CONV, msg["id"]) is not None,
                    }
                )
                gate.restore()
        return rows

    def task_script():
        return TaskScript(["NEW_TASK"])

    report["downstream"] = []
    report["downstream"].extend(
        downstream(
            "task",
            task_script,
            lambda root, topic_store: TaskStore(root, topic_store=topic_store),
            lambda store, topic_store, script: TaskEngine(
                store, topic_store, extractor=script, root_dir=ROOT, enabled=True
            ),
            lambda store: store.list_tasks(CONV),
        )
    )

    from decision_store import DecisionStore
    from risk_store import RiskStore

    class DecisionScript:
        def extract(self, engine_input, prompt_content):
            current = engine_input["current_message"]["id"]
            return {
                "decisions": [
                    {
                        "decision": "NEW_DECISION",
                        "title": "采用异常池方案",
                        "decision_text": "就按照异常池方案执行。",
                        "confidence": "HIGH",
                        "evidence_message_ids": [current],
                        "reason": "probe",
                    }
                ]
            }

    class RiskScript:
        def extract(self, engine_input, prompt_content):
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
                        "reason": "probe",
                    }
                ]
            }

    report["downstream"].extend(
        downstream(
            "decision",
            DecisionScript,
            lambda root, topic_store: DecisionStore(root, topic_store=topic_store),
            lambda store, topic_store, script: DecisionEngine(
                store, topic_store, extractor=script, root_dir=ROOT, enabled=True
            ),
            lambda store: store.list_decisions(CONV),
        )
    )
    report["downstream"].extend(
        downstream(
            "risk",
            RiskScript,
            lambda root, topic_store: RiskStore(root, topic_store=topic_store),
            lambda store, topic_store, script: RiskEngine(
                store, topic_store, extractor=script, root_dir=ROOT, enabled=True
            ),
            lambda store: store.list_risks(CONV),
        )
    )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        topic_store = TopicStore(root)
        _seed_topic(topic_store)
        pure = topic_store.upsert_message(_msg("msg_pure"))
        mixed = topic_store.upsert_message(_msg("msg_mixed"))
        topic_store.add_link(CONV, TOPIC_ID, pure["id"], "CREATED_BY")
        topic_store.add_link(CONV, TOPIC_ID, mixed["id"], "CREATED_BY")
        store = TaskStore(root, topic_store=topic_store)
        topic = topic_store.get_topic(CONV, TOPIC_ID)

        def run(msg, decisions):
            engine = TaskEngine(
                store,
                topic_store,
                extractor=TaskScript(decisions),
                root_dir=ROOT,
                enabled=True,
            )
            gate = Gate(store, "all")
            result = engine.process_record({"id": CONV}, topic, msg)
            entities = [
                item for item in store.list_tasks(CONV) if item.get("created_msg_id") == msg["id"]
            ]
            links = [
                item
                for item in store.list_links(CONV)
                if item.get("message_id") == msg["id"]
            ]
            gate.restore()
            return {
                "result": result.decision,
                "calls": gate.calls,
                "entity_count": len(entities),
                "relations": [item.get("relation") for item in links],
                "processing": store.get_processing(CONV, msg["id"]),
            }

        report["task_summary_ambiguity"] = {
            "new_only": run(pure, ["NEW_TASK"]),
            "new_plus_unrelated": run(mixed, ["NEW_TASK", "UNRELATED"]),
        }

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
