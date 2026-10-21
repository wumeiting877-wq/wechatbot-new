# -*- coding: utf-8 -*-
"""P6-G4 Gate 1 探针：真碰撞 suffix 后 Evidence 是否仍指向原 id。

两个不同消息、强制相同实体 id。只观察，不断言“安全”。
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

from decision_store import (
    DecisionStore,
    DecisionStoreError,
    RELATION_CREATED_BY as D_CREATED,
    RELATION_RELATED as D_RELATED,
    make_dlink_id,
)
from risk_store import (
    RELATION_CREATED_BY as R_CREATED,
    RELATION_RELATED as R_RELATED,
    RELATION_UPDATED_BY as R_UPDATED,
    RiskStore,
    RiskStoreError,
    make_rlink_id,
)
from store_io import atomic_write_json
from task_store import (
    RELATION_CREATED_BY as T_CREATED,
    RELATION_RELATED as T_RELATED,
    RELATION_UPDATED_BY as T_UPDATED,
    TaskStore,
    make_tlink_id,
)
from topic_store import RELATION_CREATED_BY as TOPIC_CREATED, TopicStore

CONV = {
    "id": "conv_p6g4probe01",
    "platform": "WECHAT",
    "conversation_type": "GROUP",
    "display_name": "探针群",
    "enabled": True,
}
TOPIC_ID = "topic_p6g4probe01"
SHARED_TASK = "task_forcedcoll1"
SHARED_DEC = "dec_forcedcoll01"
SHARED_RISK = "risk_forcedcoll1"
MSG_A = "msg_p6g4_a"
MSG_B = "msg_p6g4_b"
PRIOR = "msg_p6g4_prior"
NOW = "2026-09-22T21:00:00+08:00"


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
                    "created_at": NOW,
                    "updated_at": NOW,
                    "last_message_at": NOW,
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
            "created_at": NOW,
            "direction": "INBOUND",
            "message_type": "text",
        }
    )
    topic_store.add_link(CONV["id"], TOPIC_ID, record["id"], TOPIC_CREATED)
    return record


def _links_for(links, entity_key, entity_id):
    rows = [item for item in links if item.get(entity_key) == entity_id]
    return {
        "count": len(rows),
        "CREATED_BY": [
            item.get("message_id") for item in rows if item.get("relation") == "CREATED_BY"
        ],
        "RELATED": [item.get("message_id") for item in rows if item.get("relation") == "RELATED"],
        "UPDATED_BY": [
            item.get("message_id") for item in rows if item.get("relation") == "UPDATED_BY"
        ],
        "triples": [
            (item.get(entity_key), item.get("message_id"), item.get("relation")) for item in rows
        ],
    }


def _orphan(links, entity_key, entity_id):
    owned = _links_for(links, entity_key, entity_id)
    return {
        "has_created_by": bool(owned["CREATED_BY"]),
        "created_by_count": len(owned["CREATED_BY"]),
        "related_count": len(owned["RELATED"]),
        "updated_by_count": len(owned["UPDATED_BY"]),
        "owned": owned,
    }


def _probe_task(root):
    topic_store = TopicStore(root)
    _seed_topic(topic_store, CONV["id"], TOPIC_ID)
    _seed_message(topic_store, PRIOR, "权限问题还在。")
    _seed_message(topic_store, MSG_A, "李娜把权限问题修一下。")
    _seed_message(topic_store, MSG_B, "王强也把权限问题修一下。")
    store = TaskStore(root, topic_store=topic_store)

    def payload(msg_id, title):
        return {
            "id": SHARED_TASK,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": title,
            "description": title,
            "status": "OPEN",
            "assignee_text": "李娜",
            "due_text": "",
            "due_at": "",
            "created_msg_id": msg_id,
            "confidence": "HIGH",
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }

    def links_for(msg_id):
        return [
            {
                "id": make_tlink_id(SHARED_TASK, msg_id, T_CREATED),
                "task_id": SHARED_TASK,
                "message_id": msg_id,
                "relation": T_CREATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
            {
                "id": make_tlink_id(SHARED_TASK, PRIOR, T_RELATED),
                "task_id": SHARED_TASK,
                "message_id": PRIOR,
                "relation": T_RELATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
        ]

    first = store.commit_apply(CONV["id"], new_tasks=[payload(MSG_A, "第一条")], new_links=links_for(MSG_A))
    second_error = ""
    try:
        second = store.commit_apply(
            CONV["id"], new_tasks=[payload(MSG_B, "第二条")], new_links=links_for(MSG_B)
        )
    except Exception as exc:
        second = {"task_ids": []}
        second_error = "%s:%s" % (exc.__class__.__name__, getattr(exc, "code", str(exc)))
    entities = store.list_tasks(CONV["id"])
    links = store.list_links(CONV["id"])
    ids = [item.get("id") for item in entities]
    suffix = SHARED_TASK + "_2"
    return {
        "engine": "task",
        "first_applied": first,
        "second_applied": second,
        "second_error": second_error,
        "entity_ids": ids,
        "created_msg_ids": [item.get("created_msg_id") for item in entities],
        "all_link_triples": [
            (item.get("task_id"), item.get("message_id"), item.get("relation")) for item in links
        ],
        "original": _orphan(links, "task_id", SHARED_TASK),
        "suffix": _orphan(links, "task_id", suffix),
        "suffix_orphan_created_by": not _orphan(links, "task_id", suffix)["has_created_by"]
        if suffix in ids
        else None,
        "wrong_hang_on_original": MSG_B in _orphan(links, "task_id", SHARED_TASK)["owned"]["CREATED_BY"],
    }


def _probe_decision(root):
    topic_store = TopicStore(root)
    _seed_topic(topic_store, CONV["id"], TOPIC_ID)
    _seed_message(topic_store, PRIOR, "先讨论异常池。")
    _seed_message(topic_store, MSG_A, "就按照异常池方案执行。")
    _seed_message(topic_store, MSG_B, "另一条也决定用异常池。")
    store = DecisionStore(root, topic_store=topic_store)

    def payload(msg_id, title):
        return {
            "id": SHARED_DEC,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": title,
            "decision_text": title,
            "summary": title,
            "status": "RECORDED",
            "confidence": "HIGH",
            "created_msg_id": msg_id,
            "supersedes_decision_id": None,
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }

    def links_for(msg_id):
        return [
            {
                "id": make_dlink_id(SHARED_DEC, msg_id, D_CREATED),
                "decision_id": SHARED_DEC,
                "message_id": msg_id,
                "relation": D_CREATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
            {
                "id": make_dlink_id(SHARED_DEC, PRIOR, D_RELATED),
                "decision_id": SHARED_DEC,
                "message_id": PRIOR,
                "relation": D_RELATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
        ]

    first = store.commit_apply(
        CONV["id"], new_decisions=[payload(MSG_A, "第一条")], new_links=links_for(MSG_A)
    )
    second_error = ""
    try:
        second = store.commit_apply(
            CONV["id"], new_decisions=[payload(MSG_B, "第二条")], new_links=links_for(MSG_B)
        )
    except Exception as exc:
        second = {"decision_ids": []}
        second_error = "%s:%s" % (
            exc.__class__.__name__,
            getattr(exc, "code", "") or str(exc),
        )
    entities = store.list_decisions(CONV["id"])
    links = store.list_links(CONV["id"])
    ids = [item.get("id") for item in entities]
    suffix = SHARED_DEC + "_2"
    return {
        "engine": "decision",
        "first_applied": first,
        "second_applied": second,
        "second_error": second_error,
        "entity_ids": ids,
        "created_msg_ids": [item.get("created_msg_id") for item in entities],
        "all_link_triples": [
            (item.get("decision_id"), item.get("message_id"), item.get("relation")) for item in links
        ],
        "original": _orphan(links, "decision_id", SHARED_DEC),
        "suffix": _orphan(links, "decision_id", suffix),
        "suffix_orphan_created_by": not _orphan(links, "decision_id", suffix)["has_created_by"]
        if suffix in ids
        else None,
        "wrong_hang_on_original": MSG_B in _orphan(links, "decision_id", SHARED_DEC)["owned"]["CREATED_BY"],
        "error_is_created_by_required": "CREATED_BY_REQUIRED" in second_error,
    }


def _probe_risk(root):
    topic_store = TopicStore(root)
    _seed_topic(topic_store, CONV["id"], TOPIC_ID)
    _seed_message(topic_store, PRIOR, "演示可能受阻。")
    _seed_message(topic_store, MSG_A, "如果今天还修不好会影响明天现场演示。")
    _seed_message(topic_store, MSG_B, "如果明天也修不好会影响后天演示。")
    store = RiskStore(root, topic_store=topic_store)

    def payload(msg_id, title):
        return {
            "id": SHARED_RISK,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": title,
            "description": "",
            "condition_text": "如果今天还修不好",
            "impact_text": "会影响明天现场演示",
            "status": "OPEN",
            "confidence": "HIGH",
            "created_msg_id": msg_id,
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }

    def links_for(msg_id):
        return [
            {
                "id": make_rlink_id(SHARED_RISK, msg_id, R_CREATED),
                "risk_id": SHARED_RISK,
                "message_id": msg_id,
                "relation": R_CREATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
            {
                "id": make_rlink_id(SHARED_RISK, PRIOR, R_RELATED),
                "risk_id": SHARED_RISK,
                "message_id": PRIOR,
                "relation": R_RELATED,
                "confidence": "HIGH",
                "created_at": NOW,
            },
        ]

    first = store.commit_apply(CONV["id"], new_risks=[payload(MSG_A, "第一条")], new_links=links_for(MSG_A))
    second_error = ""
    try:
        second = store.commit_apply(
            CONV["id"], new_risks=[payload(MSG_B, "第二条")], new_links=links_for(MSG_B)
        )
    except Exception as exc:
        second = {"risk_ids": []}
        second_error = "%s:%s" % (
            exc.__class__.__name__,
            getattr(exc, "code", "") or str(exc),
        )
    entities = store.list_risks(CONV["id"])
    links = store.list_links(CONV["id"])
    ids = [item.get("id") for item in entities]
    suffix = SHARED_RISK + "_2"
    return {
        "engine": "risk",
        "first_applied": first,
        "second_applied": second,
        "second_error": second_error,
        "entity_ids": ids,
        "created_msg_ids": [item.get("created_msg_id") for item in entities],
        "all_link_triples": [
            (item.get("risk_id"), item.get("message_id"), item.get("relation")) for item in links
        ],
        "original": _orphan(links, "risk_id", SHARED_RISK),
        "suffix": _orphan(links, "risk_id", suffix),
        "suffix_orphan_created_by": not _orphan(links, "risk_id", suffix)["has_created_by"]
        if suffix in ids
        else None,
        "wrong_hang_on_original": MSG_B in _orphan(links, "risk_id", SHARED_RISK)["owned"]["CREATED_BY"],
    }


def _probe_create_direct(root):
    topic_store = TopicStore(root)
    _seed_topic(topic_store, CONV["id"], TOPIC_ID)
    _seed_message(topic_store, MSG_A, "直连 A")
    _seed_message(topic_store, MSG_B, "直连 B")
    task_store = TaskStore(root, topic_store=topic_store)
    first = task_store.create_task(
        {
            "id": SHARED_TASK,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": "直连一",
            "created_msg_id": MSG_A,
            "created_at": NOW,
        }
    )
    second = task_store.create_task(
        {
            "id": SHARED_TASK,
            "conversation_id": CONV["id"],
            "topic_id": TOPIC_ID,
            "title": "直连二",
            "created_msg_id": MSG_B,
            "created_at": NOW,
        }
    )
    links = task_store.list_links(CONV["id"])
    return {
        "path": "create_task_direct",
        "first_id": first["id"],
        "second_id": second["id"],
        "first_created_by": _orphan(links, "task_id", first["id"]),
        "second_created_by": _orphan(links, "task_id", second["id"]),
        "direct_api_suffixes": first["id"] != second["id"] and second["id"].endswith("_2"),
        "direct_api_suffix_has_created_by": _orphan(links, "task_id", second["id"])["has_created_by"],
    }


def main():
    rows = []
    for name, fn in (
        ("task", _probe_task),
        ("decision", _probe_decision),
        ("risk", _probe_risk),
        ("create_direct", _probe_create_direct),
    ):
        tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            rows.append(fn(tmpdir.name))
        except Exception as exc:
            rows.append({"engine": name, "probe_exception": str(exc), "trace": traceback.format_exc()})
        finally:
            tmpdir.cleanup()
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
