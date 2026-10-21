# -*- coding: utf-8 -*-
"""P6-G3 Gate 1/2 探针：apply 成功后 finalize 失败，再走 P6-G2 retry。

只观察，不断言“安全”。输出 JSON 供 TRACE 文档使用。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot_runtime import BotRuntime, clear_emergency_stop, clear_stop_request
from decision_engine import DecisionEngine
from decision_store import DecisionStore, RELATION_CREATED_BY as D_CREATED, RELATION_RELATED as D_RELATED
from downstream_retry import DownstreamRetryService, retry_downstream
from risk_engine import RiskEngine
from risk_store import (
    RELATION_CREATED_BY as R_CREATED,
    RELATION_RELATED as R_RELATED,
    RELATION_UPDATED_BY as R_UPDATED,
    RiskStore,
)
from store_io import atomic_write_json
from task_engine import TaskEngine
from task_store import (
    RELATION_CREATED_BY as T_CREATED,
    RELATION_RELATED as T_RELATED,
    RELATION_UPDATED_BY as T_UPDATED,
    TaskStore,
)
from topic_store import RELATION_CREATED_BY as TOPIC_CREATED, TopicStore

CONV = {
    "id": "conv_p6g3probe01",
    "platform": "WECHAT",
    "conversation_type": "GROUP",
    "display_name": "探针群",
    "enabled": True,
}
TOPIC_ID = "topic_p6g3probe01"


class ScriptedTask:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        return {
            "decisions": [
                {
                    "decision": "NEW_TASK",
                    "title": "修权限",
                    "description": "李娜把权限问题修一下",
                    "assignee_text": "李娜",
                    "due_text": "",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current_id],
                    "reason": "probe new task",
                }
            ]
        }


class ScriptedDecision:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        return {
            "decisions": [
                {
                    "decision": "NEW_DECISION",
                    "title": "采用异常池方案",
                    "decision_text": "就按照异常池方案执行。",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current_id],
                    "reason": "probe new decision",
                }
            ]
        }


class ScriptedRisk:
    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        return {
            "risks": [
                {
                    "decision": "NEW_RISK",
                    "title": "演示受阻",
                    "condition_text": "如果今天还修不好",
                    "impact_text": "会影响明天现场演示",
                    "confidence": "HIGH",
                    "evidence_message_ids": [current_id],
                    "reason": "probe new risk",
                }
            ]
        }


def _seed_topic(topic_store, cid, topic_id):
    atomic_write_json(
        os.path.join(topic_store.conversation_dir(cid), "topics.json"),
        {
            "topics": [
                {
                    "id": topic_id,
                    "conversation_id": cid,
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


def _seed_message(topic_store, msg_id, content):
    record = topic_store.upsert_message(
        {
            "id": msg_id,
            "conversation_id": CONV["id"],
            "platform_message_id": msg_id,
            "sender_name": "周敏",
            "content": content,
            "created_at": "2026-09-22T20:10:00+08:00",
            "direction": "INBOUND",
            "message_type": "text",
        }
    )
    topic_store.add_link(CONV["id"], TOPIC_ID, record["id"], TOPIC_CREATED)
    topic_store.write_processing(
        {
            "message_id": record["id"],
            "conversation_id": CONV["id"],
            "decision": "NEW_TOPIC",
            "topic_id": TOPIC_ID,
        }
    )
    return topic_store.get_topic(CONV["id"], TOPIC_ID), topic_store.get_message(CONV["id"], record["id"])


def _install_finalize_boom(engine):
    original = engine._finalize

    def boom(*args, **kwargs):
        raise RuntimeError("P6-G3 post-apply finalize boom")

    engine._finalize = boom
    return original


def _snapshot_task(store, cid, msg_id):
    entities = store.list_tasks(cid)
    links = store.list_links(cid)
    proc = store.get_processing(cid, msg_id)
    return {
        "entity_count": len(entities),
        "entity_ids": [item.get("id") for item in entities],
        "created_msg_ids": [item.get("created_msg_id") for item in entities],
        "titles": [item.get("title") for item in entities],
        "assignees": [item.get("assignee_text") for item in entities],
        "suffix_ids": [item.get("id") for item in entities if item.get("id") and "_" in item.get("id")[5:]],
        "link_count": len(links),
        "created_by": sum(1 for item in links if item.get("relation") == T_CREATED),
        "related": sum(1 for item in links if item.get("relation") == T_RELATED),
        "updated_by": sum(1 for item in links if item.get("relation") == T_UPDATED),
        "link_triples": [
            (item.get("task_id"), item.get("message_id"), item.get("relation")) for item in links
        ],
        "processing_summary": (proc or {}).get("decision_summary"),
        "processing_error": (proc or {}).get("error"),
        "processing_task_ids": (proc or {}).get("task_ids"),
        "has_success": store.has_successful_processing(cid, msg_id),
    }


def _snapshot_decision(store, cid, msg_id):
    entities = store.list_decisions(cid)
    links = store.list_links(cid)
    proc = store.get_processing(cid, msg_id)
    return {
        "entity_count": len(entities),
        "entity_ids": [item.get("id") for item in entities],
        "created_msg_ids": [item.get("created_msg_id") for item in entities],
        "titles": [item.get("title") for item in entities],
        "suffix_ids": [item.get("id") for item in entities if item.get("id") and "_" in item.get("id")[4:]],
        "link_count": len(links),
        "created_by": sum(1 for item in links if item.get("relation") == D_CREATED),
        "related": sum(1 for item in links if item.get("relation") == D_RELATED),
        "link_triples": [
            (item.get("decision_id"), item.get("message_id"), item.get("relation")) for item in links
        ],
        "processing_summary": (proc or {}).get("decision_summary"),
        "processing_error": (proc or {}).get("error"),
        "processing_decision_ids": (proc or {}).get("decision_ids"),
        "has_success": store.has_successful_processing(cid, msg_id),
    }


def _snapshot_risk(store, cid, msg_id):
    entities = store.list_risks(cid)
    links = store.list_links(cid)
    proc = store.get_processing(cid, msg_id)
    return {
        "entity_count": len(entities),
        "entity_ids": [item.get("id") for item in entities],
        "created_msg_ids": [item.get("created_msg_id") for item in entities],
        "titles": [item.get("title") for item in entities],
        "suffix_ids": [item.get("id") for item in entities if item.get("id") and "_" in item.get("id")[5:]],
        "link_count": len(links),
        "created_by": sum(1 for item in links if item.get("relation") == R_CREATED),
        "related": sum(1 for item in links if item.get("relation") == R_RELATED),
        "updated_by": sum(1 for item in links if item.get("relation") == R_UPDATED),
        "link_triples": [
            (item.get("risk_id"), item.get("message_id"), item.get("relation")) for item in links
        ],
        "processing_summary": (proc or {}).get("decision_summary"),
        "processing_error": (proc or {}).get("error"),
        "processing_risk_ids": (proc or {}).get("risk_ids"),
        "has_success": store.has_successful_processing(cid, msg_id),
    }


def _probe_one(name):
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    root = tmpdir.name
    clear_stop_request()
    clear_emergency_stop()
    runtime = BotRuntime()
    runtime.set_state("RUNNING", "p6g3-probe")
    topic_store = TopicStore(root)
    _seed_topic(topic_store, CONV["id"], TOPIC_ID)
    task_store = TaskStore(root, topic_store=topic_store)
    decision_store = DecisionStore(root, topic_store=topic_store)
    risk_store = RiskStore(root, topic_store=topic_store)
    task_engine = TaskEngine(task_store, topic_store, extractor=ScriptedTask(), root_dir=ROOT, enabled=True)
    decision_engine = DecisionEngine(
        decision_store, topic_store, extractor=ScriptedDecision(), root_dir=ROOT, enabled=True
    )
    risk_engine = RiskEngine(
        risk_store, topic_store, task_store=task_store, extractor=ScriptedRisk(), root_dir=ROOT, enabled=True
    )
    service = DownstreamRetryService(
        topic_store=topic_store,
        task_engine=task_engine,
        decision_engine=decision_engine,
        risk_engine=risk_engine,
        runtime=runtime,
        conversation=CONV,
    )
    msg_id = "msg_p6g3_%s" % name
    content = {
        "task": "李娜把权限问题修一下。",
        "decision": "就按照异常池方案执行。",
        "risk": "如果今天还修不好会影响明天现场演示。",
    }[name]
    topic, message = _seed_message(topic_store, msg_id, content)
    engine = {"task": task_engine, "decision": decision_engine, "risk": risk_engine}[name]
    store = {"task": task_store, "decision": decision_store, "risk": risk_store}[name]
    snap = {"task": _snapshot_task, "decision": _snapshot_decision, "risk": _snapshot_risk}[name]

    original = _install_finalize_boom(engine)
    first = engine.process_record(CONV, topic, message)
    after_inject = snap(store, CONV["id"], msg_id)
    engine._finalize = original

    retry_out = retry_downstream(name, CONV["id"], msg_id, TOPIC_ID, service=service, runtime=runtime)
    after_retry = snap(store, CONV["id"], msg_id)

    audits = []
    try:
        audits = store.read_audit(limit=50)
    except Exception:
        audits = []
    audit_decisions = [
        item.get("task_decision") or item.get("decision_decision") or item.get("risk_decision") or item.get("event")
        for item in audits
    ]
    tmpdir.cleanup()
    return {
        "engine": name,
        "inject": {
            "first_decision": first.decision,
            "first_error": first.error,
            "first_error_code": first.error_code,
            "snapshot": after_inject,
        },
        "retry": {
            "ok": retry_out.ok,
            "rejected": retry_out.rejected,
            "executed": retry_out.executed,
            "result": retry_out.result,
            "error_code": retry_out.error_code,
            "error": retry_out.error,
            "engine_decision": retry_out.engine_decision,
            "snapshot": after_retry,
            "retry_audit_events": [item.get("event") for item in service.audit_events],
        },
        "audit_tail": audit_decisions[-8:],
    }


def main():
    rows = []
    for name in ("task", "decision", "risk"):
        try:
            rows.append(_probe_one(name))
        except Exception as exc:
            rows.append({"engine": name, "probe_exception": str(exc), "trace": traceback.format_exc()})
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
