# -*- coding: utf-8 -*-
"""Business Action 的确定性写权限校验。

v1 只授权 COMPLETE_TASK，且只认 wxid -> person_id 与
conversation_id + task_id -> person_id 两条显式身份事实。
"""

from __future__ import annotations

import os

from identity_resolver import AMBIGUOUS, NOT_FOUND, RESOLVED, resolve_wxid
from identity_store import STATUS_ACTIVE, STATUS_DISABLED, IdentityStore, IdentityStoreError
from task_identity_link import TaskIdentityLinkError, TaskIdentityLinkStore

AUTHORIZED = "AUTHORIZED"
ACTOR_IDENTITY_NOT_FOUND = "ACTOR_IDENTITY_NOT_FOUND"
ACTOR_IDENTITY_AMBIGUOUS = "ACTOR_IDENTITY_AMBIGUOUS"
ACTOR_DISABLED = "ACTOR_DISABLED"
TASK_ASSIGNMENT_NOT_FOUND = "TASK_ASSIGNMENT_NOT_FOUND"
TASK_ASSIGNMENT_AMBIGUOUS = "TASK_ASSIGNMENT_AMBIGUOUS"
NOT_TASK_ASSIGNEE = "NOT_TASK_ASSIGNEE"
ACTION_NOT_AUTHORIZABLE = "ACTION_NOT_AUTHORIZABLE"
IDENTITY_CORRUPT = "IDENTITY_CORRUPT"

ACTION_COMPLETE_TASK = "COMPLETE_TASK"
TARGET_TASK = "TASK"
POLICY_TASK_ASSIGNEE_ONLY_V1 = "TASK_ASSIGNEE_ONLY_V1"


class AuthorizationDecision:
    def __init__(
        self,
        status,
        action_type,
        actor_ref,
        actor_person_id="",
        target_type=TARGET_TASK,
        target_id="",
        target_person_id="",
        reason="",
        policy=POLICY_TASK_ASSIGNEE_ONLY_V1,
    ):
        self.status = str(status or "")
        self.action_type = str(action_type or "")
        self.actor_ref = str(actor_ref or "")
        self.actor_person_id = str(actor_person_id or "")
        self.target_type = str(target_type or "")
        self.target_id = str(target_id or "")
        self.target_person_id = str(target_person_id or "")
        self.reason = str(reason or status or "")
        self.policy = str(policy or "")

    @property
    def authorized(self) -> bool:
        return self.status == AUTHORIZED


class BusinessActionAuthorizer:
    def __init__(self, root_dir, identity_store=None, link_store=None):
        self.root_dir = os.path.abspath(root_dir)
        self.identity_store = identity_store if identity_store is not None else IdentityStore(self.root_dir)
        self.link_store = (
            link_store
            if link_store is not None
            else TaskIdentityLinkStore(self.root_dir, identity_store=self.identity_store)
        )

    def authorize(self, actor_ref, conversation_id, target_task_id, action_type) -> AuthorizationDecision:
        actor = str(actor_ref or "").strip()
        task_id = str(target_task_id or "").strip()
        action = str(action_type or "").strip()
        base = {
            "action_type": action,
            "actor_ref": actor,
            "target_id": task_id,
        }
        if action != ACTION_COMPLETE_TASK:
            return AuthorizationDecision(ACTION_NOT_AUTHORIZABLE, reason=ACTION_NOT_AUTHORIZABLE, **base)

        try:
            actor_resolution = resolve_wxid(self.identity_store, actor)
        except IdentityStoreError:
            return AuthorizationDecision(IDENTITY_CORRUPT, reason=IDENTITY_CORRUPT, **base)
        if actor_resolution.status == NOT_FOUND:
            return AuthorizationDecision(ACTOR_IDENTITY_NOT_FOUND, reason=ACTOR_IDENTITY_NOT_FOUND, **base)
        if actor_resolution.status == AMBIGUOUS:
            return AuthorizationDecision(ACTOR_IDENTITY_AMBIGUOUS, reason=ACTOR_IDENTITY_AMBIGUOUS, **base)
        if actor_resolution.status != RESOLVED or actor_resolution.person is None:
            return AuthorizationDecision(IDENTITY_CORRUPT, reason=IDENTITY_CORRUPT, **base)

        actor_person_id = str(actor_resolution.person_id or "").strip()
        person = actor_resolution.person
        person_status = str(person.get("status") or "")
        actor_base = dict(base, actor_person_id=actor_person_id)
        if person_status == STATUS_DISABLED:
            return AuthorizationDecision(ACTOR_DISABLED, reason=ACTOR_DISABLED, **actor_base)
        if person_status != STATUS_ACTIVE:
            return AuthorizationDecision(IDENTITY_CORRUPT, reason=IDENTITY_CORRUPT, **actor_base)

        try:
            link = self.link_store.find_link(conversation_id, task_id)
        except TaskIdentityLinkError as exc:
            status = TASK_ASSIGNMENT_AMBIGUOUS if "同一任务存在冲突负责人链接" in str(exc) else IDENTITY_CORRUPT
            return AuthorizationDecision(status, reason=status, **actor_base)
        if link is None:
            return AuthorizationDecision(TASK_ASSIGNMENT_NOT_FOUND, reason=TASK_ASSIGNMENT_NOT_FOUND, **actor_base)

        target_person_id = str(link.get("person_id") or "").strip()
        target_base = dict(actor_base, target_person_id=target_person_id)
        if not target_person_id:
            return AuthorizationDecision(IDENTITY_CORRUPT, reason=IDENTITY_CORRUPT, **target_base)
        try:
            target_person = self.identity_store.get_person(target_person_id)
        except IdentityStoreError:
            return AuthorizationDecision(IDENTITY_CORRUPT, reason=IDENTITY_CORRUPT, **target_base)
        if target_person is None:
            return AuthorizationDecision(IDENTITY_CORRUPT, reason=IDENTITY_CORRUPT, **target_base)
        if actor_person_id != target_person_id:
            return AuthorizationDecision(NOT_TASK_ASSIGNEE, reason=NOT_TASK_ASSIGNEE, **target_base)
        return AuthorizationDecision(AUTHORIZED, reason=AUTHORIZED, **target_base)
