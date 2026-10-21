# -*- coding: utf-8 -*-
"""P9-G5：COMPLETE_TASK 仅允许任务负责人本人准备和确认。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from business_action import (
    ACTION_COMPLETE_TASK,
    ACTION_TARGET_NOT_FOUND,
    ACTOR_MISMATCH,
    EXECUTED,
    NOT_AUTHORIZED,
    PREPARED,
    SUCCEEDED_NOOP,
    ActionRequest,
    BusinessActionService,
)
from business_action_audit import EVENT_REJECTED, read_business_action_audit
from business_action_authorizer import (
    ACTOR_DISABLED,
    ACTOR_IDENTITY_AMBIGUOUS,
    ACTOR_IDENTITY_NOT_FOUND,
    AUTHORIZED,
    IDENTITY_CORRUPT,
    NOT_TASK_ASSIGNEE,
    POLICY_TASK_ASSIGNEE_ONLY_V1,
    TASK_ASSIGNMENT_AMBIGUOUS,
    TASK_ASSIGNMENT_NOT_FOUND,
    BusinessActionAuthorizer,
)
from business_action_conversation import (
    ACTOR_DISABLED_REPLY,
    IDENTITY_NOT_FOUND_REPLY,
    NOT_AUTHORIZED_REPLY,
    TASK_ASSIGNMENT_NOT_FOUND_REPLY,
    _authorization_reply,
)
from business_action_store import STATE_PREPARED as STORE_PREPARED
from collaboration_query import build_query_service
from decision_engine import DECISION_ENGINE_ENABLED
from identity_store import IdentityStore
from query_router import LIST_TASKS
from query_service import MY_TASKS, TASKS_BY_ASSIGNEE, QueryRequest
from risk_engine import RISK_ENGINE_ENABLED
from task_engine import TASK_ENGINE_ENABLED
from task_identity_link import SOURCE_MANUAL, TaskIdentityLinkStore
from task_lifecycle import TaskLifecycleService
from task_store import TASK_STATUS_DONE, TASK_STATUS_OPEN, TaskStore
from task_target_resolver import SELECTOR_EXACT_TITLE, TaskTargetSelector
from topic_engine import TOPIC_ENGINE_ENABLED

CID = "conv_auth01"
WXID_A = "wxid_auth_a"
WXID_B = "wxid_auth_b"
PERSON_A = "person_001"
PERSON_B = "person_002"


def _task(status=TASK_STATUS_OPEN):
    return {
        "id": "task_auth",
        "conversation_id": CID,
        "topic_id": "topic_auth",
        "title": "接口联调",
        "description": "权限测试",
        "status": status,
        "assignee_text": "李明",
        "due_text": "",
        "due_at": "",
        "created_msg_id": "seed_auth",
        "confidence": "LOW",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "schema_version": 1,
    }


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.tasks = TaskStore(self.root)
        self.people = IdentityStore(self.root)
        self.people.create_person(PERSON_A, "张三")
        self.people.create_person(PERSON_B, "王强")
        self.people.bind_wechat(WXID_A, PERSON_A, display_name="张三")
        self.people.bind_wechat(WXID_B, PERSON_B, display_name="王强")
        self.links = TaskIdentityLinkStore(self.root, task_store=self.tasks, identity_store=self.people)
        self._dump_task()
        self.service = BusinessActionService(self.root)

    def tearDown(self):
        self.tmpdir.cleanup()
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        self.assertFalse(TASK_ENGINE_ENABLED)
        self.assertFalse(DECISION_ENGINE_ENABLED)
        self.assertFalse(RISK_ENGINE_ENABLED)

    def _dump_task(self, status=TASK_STATUS_OPEN):
        path = os.path.join(self.root, "data", "task_store", "conversations", CID, "tasks.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"tasks": [_task(status)]}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def _link(self, person_id=PERSON_A):
        return self.links.link_task_to_person(CID, "task_auth", person_id, source=SOURCE_MANUAL)

    def _request(self, actor=WXID_A, message_id="msg_auth"):
        return ActionRequest(
            ACTION_COMPLETE_TASK,
            CID,
            message_id,
            actor,
            TaskTargetSelector(SELECTOR_EXACT_TITLE, title="接口联调"),
        )

    def _prepare(self, actor=WXID_A, message_id="msg_auth"):
        return self.service.prepare_action(self._request(actor, message_id))

    def _rewrite_links(self, rows):
        path = self.links.links_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"schema_version": 1, "links": rows}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def test_auth_01_assignee_can_prepare(self):
        self._link(PERSON_A)
        result = self._prepare()
        self.assertEqual(result.status, PREPARED)
        decision = BusinessActionAuthorizer(self.root).authorize(WXID_A, CID, "task_auth", ACTION_COMPLETE_TASK)
        self.assertEqual(decision.status, AUTHORIZED)
        self.assertEqual(decision.policy, POLICY_TASK_ASSIGNEE_ONLY_V1)

    def test_auth_02_non_assignee_is_denied_without_action(self):
        self._link(PERSON_A)
        with patch.object(self.service.lifecycle, "complete_task") as complete:
            result = self._prepare(WXID_B)
        self.assertEqual(result.status, NOT_AUTHORIZED)
        self.assertEqual(result.reason, NOT_TASK_ASSIGNEE)
        self.assertEqual(self.service.action_store.list_actions(), [])
        self.assertEqual(complete.call_count, 0)

    def test_auth_03_unknown_actor_is_denied(self):
        self._link(PERSON_A)
        result = self._prepare("wxid_unknown")
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, ACTOR_IDENTITY_NOT_FOUND))
        self.assertEqual(self.service.action_store.list_actions(), [])

    def test_auth_04_assignee_text_without_link_never_authorizes(self):
        self.people.add_alias("李明", PERSON_A)
        result = self._prepare(WXID_A)
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, TASK_ASSIGNMENT_NOT_FOUND))
        self.assertEqual(self.service.action_store.list_actions(), [])

    def test_auth_05_same_name_does_not_authorize_other_person(self):
        self.people.add_alias("张三", PERSON_A)
        path = self.people.people_path()
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["people"][1]["canonical_name"] = "张三"
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        self._link(PERSON_A)
        result = self._prepare(WXID_B)
        self.assertEqual(result.reason, NOT_TASK_ASSIGNEE)

    def test_auth_06_disabled_actor_is_denied(self):
        self._link(PERSON_A)
        self.people.set_person_status(PERSON_A, "DISABLED")
        result = self._prepare()
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, ACTOR_DISABLED))

    def test_auth_07_disable_after_prepare_blocks_confirm(self):
        self._link(PERSON_A)
        prepared = self._prepare()
        self.people.set_person_status(PERSON_A, "DISABLED")
        with patch.object(self.service.lifecycle, "complete_task", wraps=self.service.lifecycle.complete_task) as complete:
            result = self.service.confirm_action(prepared.action_id, WXID_A)
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, ACTOR_DISABLED))
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(self.tasks.get_task(CID, "task_auth")["status"], TASK_STATUS_OPEN)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], STORE_PREPARED)

    def test_auth_08_assignment_change_after_prepare_blocks_confirm(self):
        link = self._link(PERSON_A)
        prepared = self._prepare()
        link["person_id"] = PERSON_B
        self._rewrite_links([link])
        with patch.object(self.service.lifecycle, "complete_task", wraps=self.service.lifecycle.complete_task) as complete:
            result = self.service.confirm_action(prepared.action_id, WXID_A)
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, NOT_TASK_ASSIGNEE))
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(self.tasks.get_task(CID, "task_auth")["status"], TASK_STATUS_OPEN)

    def test_assignment_removed_after_prepare_blocks_confirm(self):
        self._link(PERSON_A)
        prepared = self._prepare()
        self._rewrite_links([])
        with patch.object(self.service.lifecycle, "complete_task") as complete:
            result = self.service.confirm_action(prepared.action_id, WXID_A)
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, TASK_ASSIGNMENT_NOT_FOUND))
        self.assertEqual(complete.call_count, 0)
        self.assertEqual(self.service.action_store.get_action(prepared.action_id)["state"], STORE_PREPARED)

    def test_auth_09_actor_mismatch_precedes_authorization(self):
        self._link(PERSON_A)
        prepared = self._prepare()
        self.people.set_person_status(PERSON_B, "DISABLED")
        result = self.service.confirm_action(prepared.action_id, WXID_B)
        self.assertEqual(result.status, ACTOR_MISMATCH)
        self.assertEqual(self.tasks.get_task(CID, "task_auth")["status"], TASK_STATUS_OPEN)

    def test_auth_10_authorized_confirm_executes(self):
        self._link(PERSON_A)
        prepared = self._prepare()
        result = self.service.confirm_action(prepared.action_id, WXID_A)
        self.assertEqual(result.status, EXECUTED)
        self.assertEqual(self.tasks.get_task(CID, "task_auth")["status"], TASK_STATUS_DONE)

    def test_auth_11_authorized_confirm_can_noop(self):
        self._link(PERSON_A)
        prepared = self._prepare()
        TaskLifecycleService(self.tasks).complete_task(CID, "task_auth")
        result = self.service.confirm_action(prepared.action_id, WXID_A)
        self.assertEqual(result.status, SUCCEEDED_NOOP)

    def test_auth_12_identity_store_corruption_safe_denies(self):
        self._link(PERSON_A)
        with open(self.people.bindings_path(), "w", encoding="utf-8") as handle:
            handle.write("{")
        with patch.object(self.service.lifecycle, "complete_task") as complete:
            result = self._prepare()
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, IDENTITY_CORRUPT))
        self.assertEqual(complete.call_count, 0)

    def test_auth_13_link_store_corruption_safe_denies(self):
        with open(self.links.links_path(), "w", encoding="utf-8") as handle:
            handle.write("{")
        with patch.object(self.service.lifecycle, "complete_task") as complete:
            result = self._prepare()
        self.assertEqual((result.status, result.reason), (NOT_AUTHORIZED, IDENTITY_CORRUPT))
        self.assertEqual(complete.call_count, 0)

    def test_auth_14_queries_remain_read_authorization_free(self):
        self._link(PERSON_A)
        query = build_query_service(self.root)
        listed = query.execute(QueryRequest(CID, "q1", WXID_B, LIST_TASKS))
        mine = query.execute(QueryRequest(CID, "q2", WXID_B, MY_TASKS, person_id=PERSON_A))
        by_assignee = query.execute(QueryRequest(CID, "q3", WXID_B, TASKS_BY_ASSIGNEE, person_id=PERSON_A))
        self.assertEqual([item["id"] for item in listed.items], ["task_auth"])
        self.assertEqual([item["id"] for item in mine.items], ["task_auth"])
        self.assertEqual([item["id"] for item in by_assignee.items], ["task_auth"])

    def test_ambiguous_actor_and_assignment_are_denied(self):
        bindings_path = self.people.bindings_path()
        with open(bindings_path, "r", encoding="utf-8") as handle:
            bindings = json.load(handle)
        bindings["bindings"].append(dict(bindings["bindings"][0], person_id=PERSON_B))
        with open(bindings_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(bindings, handle, ensure_ascii=False, indent=2)
        self._link(PERSON_A)
        actor_result = self._prepare()
        self.assertEqual(actor_result.reason, ACTOR_IDENTITY_AMBIGUOUS)

        self.people = IdentityStore(self.root)
        bindings["bindings"] = bindings["bindings"][:-1]
        with open(bindings_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(bindings, handle, ensure_ascii=False, indent=2)
        first = self.links.find_link(CID, "task_auth")
        self._rewrite_links([first, dict(first, person_id=PERSON_B)])
        assignment_result = self._prepare(message_id="msg_ambiguous_link")
        self.assertEqual(assignment_result.reason, TASK_ASSIGNMENT_AMBIGUOUS)

    def test_unresolved_target_does_not_call_authorizer(self):
        with patch.object(self.service.authorizer, "authorize") as authorize:
            request = ActionRequest(
                ACTION_COMPLETE_TASK,
                CID,
                "msg_missing",
                WXID_A,
                TaskTargetSelector(SELECTOR_EXACT_TITLE, title="不存在"),
            )
            result = self.service.prepare_action(request)
        self.assertEqual(result.status, ACTION_TARGET_NOT_FOUND)
        self.assertEqual(authorize.call_count, 0)

    def test_authorization_denials_are_audited_without_names(self):
        self._link(PERSON_A)
        result = self._prepare(WXID_B, "msg_audit_deny")
        self.assertEqual(result.status, NOT_AUTHORIZED)
        rows = [row for row in read_business_action_audit(self.root) if row["event"] == EVENT_REJECTED]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor_ref"], WXID_B)
        self.assertEqual(rows[0]["target_id"], "task_auth")
        self.assertEqual(rows[0]["reason"], NOT_TASK_ASSIGNEE)
        self.assertNotIn("张三", json.dumps(rows[0], ensure_ascii=False))
        self.assertNotIn("李明", json.dumps(rows[0], ensure_ascii=False))

    def test_wechat_denial_replies_are_specific_but_do_not_disclose_owner(self):
        self.assertEqual(_authorization_reply(ACTOR_IDENTITY_NOT_FOUND), IDENTITY_NOT_FOUND_REPLY)
        self.assertEqual(_authorization_reply(ACTOR_IDENTITY_AMBIGUOUS), IDENTITY_NOT_FOUND_REPLY)
        self.assertEqual(_authorization_reply(ACTOR_DISABLED), ACTOR_DISABLED_REPLY)
        self.assertEqual(_authorization_reply(TASK_ASSIGNMENT_NOT_FOUND), TASK_ASSIGNMENT_NOT_FOUND_REPLY)
        self.assertEqual(_authorization_reply(NOT_TASK_ASSIGNEE), NOT_AUTHORIZED_REPLY)
        for reply in (
            IDENTITY_NOT_FOUND_REPLY,
            ACTOR_DISABLED_REPLY,
            TASK_ASSIGNMENT_NOT_FOUND_REPLY,
            NOT_AUTHORIZED_REPLY,
        ):
            self.assertNotIn("李明", reply)
            self.assertNotIn("张三", reply)


if __name__ == "__main__":
    unittest.main()
