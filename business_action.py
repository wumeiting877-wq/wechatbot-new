# -*- coding: utf-8 -*-
"""结构化业务动作。v1 只接受 COMPLETE_TASK。

准备阶段解析目标并写入 Action Record，不调用生命周期。
确认阶段按已保存的 task_id 调用 TaskLifecycleService.complete_task。
动作身份不用自然语言正文。
"""

from __future__ import annotations

import hashlib
import logging
import os

from conversation_store import utc_now_iso
from task_lifecycle import TaskLifecycleService
from task_store import (
    TASK_STATUS_DONE,
    TASK_STATUS_OPEN,
    TRANSITION_ALREADY_IN_STATE,
    TRANSITION_STALE_STATE,
    TRANSITION_TASK_NOT_FOUND,
    TRANSITION_TRANSITIONED,
    TRANSITION_WRITE_FAILED,
    TaskStore,
)
from task_target_resolver import (
    AMBIGUOUS,
    CORRUPT as RESOLUTION_CORRUPT,
    INVALID_SELECTOR,
    NOT_FOUND,
    RESOLVED,
    UNSUPPORTED_REFERENCE,
    TaskTargetResolver,
)

from business_action_audit import (
    EVENT_CONFIRM_REQUESTED,
    EVENT_EXECUTED,
    EVENT_FAILED,
    EVENT_NOOP,
    EVENT_PREPARED,
    EVENT_REJECTED,
    TARGET_TYPE_TASK,
    append_business_action_audit,
)
from business_action_authorizer import AUTHORIZED, BusinessActionAuthorizer
from business_action_store import (
    OUTCOME_ACTOR_MISMATCH,
    OUTCOME_COMMITTED,
    OUTCOME_NOT_FOUND,
    OUTCOME_RECORD_PERSIST_FAILED,
    OUTCOME_UNCHANGED,
    STATE_EXECUTED,
    STATE_FAILED,
    STATE_PREPARED,
    STATE_SUCCEEDED_NOOP,
    STORE_CORRUPT,
    BusinessActionStore,
    BusinessActionStoreError,
)

logger = logging.getLogger(__name__)

ACTION_COMPLETE_TASK = "COMPLETE_TASK"
ALLOWED_ACTION_TYPES = (ACTION_COMPLETE_TASK,)
COMPLETE_TASK_OPERATION = "完成任务"

PREPARED = STATE_PREPARED
EXECUTED = STATE_EXECUTED
SUCCEEDED_NOOP = STATE_SUCCEEDED_NOOP
FAILED = STATE_FAILED
ALREADY_EXECUTED = "ALREADY_EXECUTED"
ACTOR_REQUIRED = "ACTOR_REQUIRED"
MESSAGE_ID_REQUIRED = "MESSAGE_ID_REQUIRED"
ACTOR_MISMATCH = OUTCOME_ACTOR_MISMATCH
ACTION_TARGET_AMBIGUOUS = "ACTION_TARGET_AMBIGUOUS"
ACTION_TARGET_NOT_FOUND = "ACTION_TARGET_NOT_FOUND"
NO_ACTION_NEEDED = "NO_ACTION_NEEDED"
ACTION_NOT_APPLICABLE = "ACTION_NOT_APPLICABLE"
ACTION_TYPE_NOT_ALLOWED = "ACTION_TYPE_NOT_ALLOWED"
ACTION_NOT_FOUND = "ACTION_NOT_FOUND"
CORRUPT = STORE_CORRUPT
RECORD_PERSIST_FAILED = OUTCOME_RECORD_PERSIST_FAILED
ACTIONS_CORRUPT = "ACTIONS_CORRUPT"
ALREADY_IN_TARGET_STATE = "ALREADY_IN_TARGET_STATE"
NOT_AUTHORIZED = "NOT_AUTHORIZED"


class _AuthorizationDenied(Exception):
    def __init__(self, decision, record):
        super().__init__(decision.reason)
        self.decision = decision
        self.record = dict(record)


class ActionRequest:
    def __init__(self, action_type, conversation_id, message_id, actor_ref, target_selector):
        self.action_type = action_type
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.actor_ref = actor_ref
        self.target_selector = target_selector


class ActionPreview:
    def __init__(
        self,
        action_id,
        action_type,
        conversation_id,
        message_id,
        actor_ref,
        target_task_id,
        target_title,
        current_status,
        target_status,
        requires_confirmation,
        state,
        created_at,
    ):
        self.action_id = action_id
        self.action_type = action_type
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.actor_ref = actor_ref
        self.target_task_id = target_task_id
        self.target_title = target_title
        self.current_status = current_status
        self.target_status = target_status
        self.requires_confirmation = requires_confirmation
        self.state = state
        self.created_at = created_at

    def text(self) -> str:
        return "\n".join(
            (
                "操作：%s" % COMPLETE_TASK_OPERATION,
                "任务：%s" % self.target_title,
                "当前状态：%s" % self.current_status,
                "目标状态：%s" % self.target_status,
            )
        )


class ActionResult:
    def __init__(
        self,
        status,
        reason="",
        action_id="",
        action_type="",
        conversation_id="",
        message_id="",
        actor_ref="",
        target_task_id="",
        target_title="",
        current_status="",
        target_status="",
        requires_confirmation=False,
        state="",
        created_at="",
        preview=None,
        candidates=None,
        record=None,
        lifecycle_status="",
    ):
        self.status = status
        self.reason = reason
        self.action_id = action_id
        self.action_type = action_type
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.actor_ref = actor_ref
        self.target_task_id = target_task_id
        self.target_title = target_title
        self.current_status = current_status
        self.target_status = target_status
        self.requires_confirmation = requires_confirmation
        self.state = state
        self.created_at = created_at
        self.preview = preview
        self.candidates = candidates
        self.record = record
        self.lifecycle_status = lifecycle_status


class BusinessActionService:
    def __init__(
        self,
        root_dir,
        task_store=None,
        resolver=None,
        lifecycle=None,
        action_store=None,
        authorizer=None,
    ):
        self.root_dir = os.path.abspath(root_dir)
        self.task_store = task_store if task_store is not None else TaskStore(self.root_dir)
        self.resolver = resolver if resolver is not None else TaskTargetResolver(self.task_store)
        self.lifecycle = lifecycle if lifecycle is not None else TaskLifecycleService(self.task_store)
        self.action_store = action_store if action_store is not None else BusinessActionStore(self.root_dir)
        self.authorizer = authorizer if authorizer is not None else BusinessActionAuthorizer(self.root_dir)

    def prepare_action(self, request: ActionRequest) -> ActionResult:
        parts = _parts(request)
        if parts is None:
            return ActionResult(INVALID_SELECTOR, reason=INVALID_SELECTOR)
        rejected = self._validate_request(parts)
        if rejected is not None:
            return rejected
        if self.action_store.is_corrupt():
            return self._reject(parts, CORRUPT, ACTIONS_CORRUPT)
        resolved = self.resolver.resolve_task_target(parts["conversation_id"], parts["selector"])
        if resolved.status != RESOLVED:
            return self._from_resolution(parts, resolved)
        task = resolved.task if isinstance(resolved.task, dict) else None
        task_id = _text(resolved.task_id)
        if task is None or task_id == "":
            return self._reject(
                parts,
                ACTION_TARGET_NOT_FOUND,
                NOT_FOUND,
                conversation_id=_text(resolved.conversation_id),
            )
        conversation_id = _text(resolved.conversation_id)
        authorization = self.authorizer.authorize(
            parts["actor_ref"],
            conversation_id,
            task_id,
            parts["action_type"],
        )
        if authorization.status != AUTHORIZED:
            return self._reject(
                parts,
                NOT_AUTHORIZED,
                authorization.reason,
                conversation_id=conversation_id,
                target_id=task_id,
            )
        status = str(task.get("status") or "").strip().upper()
        title = str(task.get("title") or "")
        action_id = make_action_id(conversation_id, parts["message_id"], parts["action_type"], task_id)

        def factory():
            if status != TASK_STATUS_OPEN:
                return None
            return _prepared_record(
                action_id,
                parts,
                conversation_id,
                task_id,
                title,
                utc_now_iso(),
            )

        try:
            record, created = self.action_store.read_or_create(action_id, factory)
        except BusinessActionStoreError:
            return self._reject(parts, CORRUPT, ACTIONS_CORRUPT, conversation_id=conversation_id, target_id=task_id)
        if record is not None:
            if created:
                self._audit(
                    event=EVENT_PREPARED,
                    result=PREPARED,
                    action_id=action_id,
                    action_type=parts["action_type"],
                    conversation_id=conversation_id,
                    message_id=parts["message_id"],
                    actor_ref=parts["actor_ref"],
                    target_id=task_id,
                    before_status=TASK_STATUS_OPEN,
                    after_status=TASK_STATUS_OPEN,
                )
            return _from_record(record)
        if status == TASK_STATUS_DONE:
            return self._reject(
                parts,
                NO_ACTION_NEEDED,
                ALREADY_IN_TARGET_STATE,
                conversation_id=conversation_id,
                target_id=task_id,
                target_title=title,
                current_status=TASK_STATUS_DONE,
                target_status=TASK_STATUS_DONE,
                before_status=TASK_STATUS_DONE,
                after_status=TASK_STATUS_DONE,
            )
        return self._reject(
            parts,
            ACTION_NOT_APPLICABLE,
            ACTION_NOT_APPLICABLE,
            conversation_id=conversation_id,
            target_id=task_id,
            target_title=title,
            current_status=status,
            target_status=TASK_STATUS_DONE,
            before_status=status,
            after_status=status,
        )

    def confirm_action(self, action_id, actor_ref) -> ActionResult:
        action_key = _text(action_id)
        actor = _text(actor_ref)
        if self.action_store.is_corrupt():
            self._audit(
                event=EVENT_REJECTED,
                result=CORRUPT,
                reason=ACTIONS_CORRUPT,
                action_id=action_key,
                actor_ref=actor,
            )
            return ActionResult(CORRUPT, reason=ACTIONS_CORRUPT, action_id=action_key, actor_ref=actor)
        if actor == "":
            return self._reject_empty_actor(action_key)
        try:
            commit = self.action_store.commit_confirmation(action_key, actor, self._apply_complete)
        except _AuthorizationDenied as exc:
            self._audit_record(
                EVENT_REJECTED,
                exc.record,
                NOT_AUTHORIZED,
                exc.decision.reason,
                actor,
            )
            result = _from_record(exc.record, status=NOT_AUTHORIZED, reason=exc.decision.reason)
            result.actor_ref = actor
            result.requires_confirmation = False
            result.preview = None
            return result
        except BusinessActionStoreError:
            self._audit(
                event=EVENT_REJECTED,
                result=CORRUPT,
                reason=ACTIONS_CORRUPT,
                action_id=action_key,
                actor_ref=actor,
            )
            return ActionResult(CORRUPT, reason=ACTIONS_CORRUPT, action_id=action_key, actor_ref=actor)
        return self._from_commit(commit, action_key, actor)

    def _apply_complete(self, record: dict) -> dict:
        authorization = self.authorizer.authorize(
            record.get("actor_ref") or "",
            record.get("conversation_id") or "",
            record.get("target_task_id") or "",
            record.get("action_type") or "",
        )
        if authorization.status != AUTHORIZED:
            raise _AuthorizationDenied(authorization, record)
        transition = self.lifecycle.complete_task(record.get("conversation_id") or "", record.get("target_task_id") or "")
        state, reason = _outcome_from_transition(transition.status)
        now = utc_now_iso()
        return {
            "state": state,
            "result_status": state,
            "result_reason": reason,
            "confirmed_at": now,
            "completed_at": now,
            "_transition": transition,
        }

    def _validate_request(self, parts: dict):
        if parts["action_type"] not in ALLOWED_ACTION_TYPES:
            return self._reject(parts, ACTION_TYPE_NOT_ALLOWED, ACTION_TYPE_NOT_ALLOWED)
        if parts["actor_ref"] == "":
            return self._reject(parts, ACTOR_REQUIRED, ACTOR_REQUIRED)
        if parts["message_id"] == "":
            return self._reject(parts, MESSAGE_ID_REQUIRED, MESSAGE_ID_REQUIRED)
        return None

    def _from_resolution(self, parts: dict, resolved) -> ActionResult:
        conversation_id = _text(resolved.conversation_id)
        if resolved.status == AMBIGUOUS:
            return self._reject(
                parts,
                ACTION_TARGET_AMBIGUOUS,
                _text(resolved.reason) or ACTION_TARGET_AMBIGUOUS,
                conversation_id=conversation_id,
                candidates=list(resolved.candidates or []),
            )
        if resolved.status == NOT_FOUND:
            return self._reject(
                parts,
                ACTION_TARGET_NOT_FOUND,
                _text(resolved.reason) or ACTION_TARGET_NOT_FOUND,
                conversation_id=conversation_id,
            )
        if resolved.status == UNSUPPORTED_REFERENCE:
            return self._reject(parts, UNSUPPORTED_REFERENCE, UNSUPPORTED_REFERENCE, conversation_id=conversation_id)
        if resolved.status == RESOLUTION_CORRUPT:
            return self._reject(
                parts,
                CORRUPT,
                _text(resolved.reason) or CORRUPT,
                conversation_id=conversation_id,
            )
        return self._reject(parts, INVALID_SELECTOR, INVALID_SELECTOR, conversation_id=conversation_id)

    def _reject(self, parts, status, reason, **extra) -> ActionResult:
        candidates = extra.get("candidates")
        self._audit(
            event=EVENT_REJECTED,
            result=status,
            reason=reason,
            action_type=parts.get("action_type", ""),
            conversation_id=extra.get("conversation_id") or parts.get("conversation_id", ""),
            message_id=parts.get("message_id", ""),
            actor_ref=parts.get("actor_ref", ""),
            target_id=extra.get("target_id", ""),
            before_status=extra.get("before_status", ""),
            after_status=extra.get("after_status", ""),
        )
        return ActionResult(
            status,
            reason=reason,
            action_type=parts.get("action_type", ""),
            conversation_id=extra.get("conversation_id") or parts.get("conversation_id", ""),
            message_id=parts.get("message_id", ""),
            actor_ref=parts.get("actor_ref", ""),
            target_task_id=extra.get("target_id", ""),
            target_title=extra.get("target_title", ""),
            current_status=extra.get("current_status", ""),
            target_status=extra.get("target_status", ""),
            candidates=candidates,
        )

    def _reject_empty_actor(self, action_id: str) -> ActionResult:
        record = None
        try:
            record = self.action_store.get_action(action_id)
        except BusinessActionStoreError:
            self._audit(event=EVENT_REJECTED, result=CORRUPT, reason=ACTIONS_CORRUPT, action_id=action_id)
            return ActionResult(CORRUPT, reason=ACTIONS_CORRUPT, action_id=action_id)
        self._audit(
            event=EVENT_REJECTED,
            result=ACTOR_REQUIRED,
            reason=ACTOR_REQUIRED,
            action_id=action_id,
            action_type="" if record is None else str(record.get("action_type") or ""),
            conversation_id="" if record is None else str(record.get("conversation_id") or ""),
            message_id="" if record is None else str(record.get("message_id") or ""),
            target_id="" if record is None else str(record.get("target_task_id") or ""),
        )
        if record is None:
            return ActionResult(ACTOR_REQUIRED, reason=ACTOR_REQUIRED, action_id=action_id)
        result = _from_record(record, status=ACTOR_REQUIRED, reason=ACTOR_REQUIRED)
        result.requires_confirmation = False
        result.preview = None
        return result

    def _from_commit(self, commit, action_id: str, actor: str) -> ActionResult:
        record = commit.record
        if commit.outcome == OUTCOME_NOT_FOUND:
            self._audit(
                event=EVENT_REJECTED,
                result=ACTION_NOT_FOUND,
                reason=ACTION_NOT_FOUND,
                action_id=action_id,
                actor_ref=actor,
            )
            return ActionResult(ACTION_NOT_FOUND, reason=ACTION_NOT_FOUND, action_id=action_id, actor_ref=actor)
        if commit.outcome == OUTCOME_ACTOR_MISMATCH:
            self._audit_record(EVENT_REJECTED, record, ACTOR_MISMATCH, ACTOR_MISMATCH, actor)
            result = _from_record(record, status=ACTOR_MISMATCH, reason=ACTOR_MISMATCH)
            result.actor_ref = actor
            result.requires_confirmation = False
            result.preview = None
            return result
        if commit.outcome == OUTCOME_UNCHANGED:
            state = str(record.get("state") or "")
            if state in (STATE_EXECUTED, STATE_SUCCEEDED_NOOP):
                self._audit_record(EVENT_CONFIRM_REQUESTED, record, ALREADY_EXECUTED, ALREADY_EXECUTED, actor)
                result = _from_record(record, status=ALREADY_EXECUTED, reason=ALREADY_EXECUTED)
                result.actor_ref = actor
                return result
            reason = str(record.get("result_reason") or state or FAILED)
            self._audit_record(EVENT_CONFIRM_REQUESTED, record, state or FAILED, reason, actor)
            result = _from_record(record, status=state or FAILED, reason=reason)
            result.actor_ref = actor
            return result
        transition = (commit.applied or {}).get("_transition")
        lifecycle_status = "" if transition is None else str(transition.status or "")
        before_status, after_status = _status_pair(record, transition)
        if commit.outcome == OUTCOME_RECORD_PERSIST_FAILED:
            self._audit_record(
                EVENT_FAILED,
                record,
                RECORD_PERSIST_FAILED,
                RECORD_PERSIST_FAILED,
                actor,
                before_status=before_status,
                after_status=after_status,
            )
            logger.warning(
                "Business action record persist failed action_id=%s lifecycle_status=%s",
                action_id,
                lifecycle_status,
            )
            result = _from_record(
                record,
                status=RECORD_PERSIST_FAILED,
                reason=RECORD_PERSIST_FAILED,
                lifecycle_status=lifecycle_status,
            )
            result.actor_ref = actor
            result.requires_confirmation = False
            result.preview = None
            return result
        state = str(record.get("state") or "")
        reason = str(record.get("result_reason") or "")
        self._audit_record(EVENT_CONFIRM_REQUESTED, record, "REQUESTED", "", actor, before_status=before_status)
        if state == STATE_EXECUTED:
            self._audit_record(
                EVENT_EXECUTED,
                record,
                EXECUTED,
                reason,
                actor,
                before_status=before_status,
                after_status=after_status,
            )
            logger.info(
                "Business action executed action_id=%s conversation_id=%s task_id=%s actor_ref=%s",
                record.get("action_id", ""),
                record.get("conversation_id", ""),
                record.get("target_task_id", ""),
                actor,
            )
        elif state == STATE_SUCCEEDED_NOOP:
            self._audit_record(
                EVENT_NOOP,
                record,
                SUCCEEDED_NOOP,
                reason,
                actor,
                before_status=before_status,
                after_status=after_status,
            )
        else:
            self._audit_record(
                EVENT_FAILED,
                record,
                FAILED,
                reason or FAILED,
                actor,
                before_status=before_status,
                after_status=after_status,
            )
            logger.warning(
                "Business action failed action_id=%s reason=%s",
                record.get("action_id", ""),
                reason or FAILED,
            )
        result = _from_record(record, reason=reason, lifecycle_status=lifecycle_status)
        result.actor_ref = actor
        return result

    def _audit_record(self, event, record, result, reason, actor, before_status="", after_status=""):
        self._audit(
            event=event,
            result=result,
            reason=reason,
            action_id=str(record.get("action_id") or ""),
            action_type=str(record.get("action_type") or ""),
            conversation_id=str(record.get("conversation_id") or ""),
            message_id=str(record.get("message_id") or ""),
            actor_ref=actor,
            target_id=str(record.get("target_task_id") or ""),
            before_status=before_status,
            after_status=after_status,
        )

    def _audit(self, **fields):
        fields.setdefault("target_type", TARGET_TYPE_TASK)
        try:
            append_business_action_audit(self.root_dir, fields)
        except Exception as exc:
            logger.warning(
                "Business action audit append failed action_id=%s event=%s error=%s",
                fields.get("action_id", ""),
                fields.get("event", ""),
                exc,
            )


def make_action_id(conversation_id: str, message_id: str, action_type: str, target_task_id: str) -> str:
    parts = (
        str(conversation_id or ""),
        str(message_id or ""),
        str(action_type or ""),
        str(target_task_id or ""),
    )
    seed = "|".join("%d:%s" % (len(part), part) for part in parts)
    return "act_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _parts(request):
    if not isinstance(request, ActionRequest):
        return None
    return {
        "action_type": _text(request.action_type),
        "conversation_id": _text(request.conversation_id),
        "message_id": _text(request.message_id),
        "actor_ref": _text(request.actor_ref),
        "selector": request.target_selector,
    }


def _prepared_record(action_id, parts, conversation_id, task_id, title, created_at) -> dict:
    return {
        "action_id": action_id,
        "action_type": parts["action_type"],
        "conversation_id": conversation_id,
        "message_id": parts["message_id"],
        "actor_ref": parts["actor_ref"],
        "target_task_id": task_id,
        "target_title": title,
        "expected_status": TASK_STATUS_OPEN,
        "target_status": TASK_STATUS_DONE,
        "state": STATE_PREPARED,
        "created_at": created_at,
        "confirmed_at": "",
        "completed_at": "",
        "result_status": "",
        "result_reason": "",
    }


def _from_record(record, status="", reason="", lifecycle_status="") -> ActionResult:
    state = str(record.get("state") or "")
    public = status or state
    preview = None
    requires = public == STATE_PREPARED and state == STATE_PREPARED
    if requires and str(record.get("action_type") or "") == ACTION_COMPLETE_TASK:
        preview = _preview_from_record(record)
    return ActionResult(
        public,
        reason=reason,
        action_id=str(record.get("action_id") or ""),
        action_type=str(record.get("action_type") or ""),
        conversation_id=str(record.get("conversation_id") or ""),
        message_id=str(record.get("message_id") or ""),
        actor_ref=str(record.get("actor_ref") or ""),
        target_task_id=str(record.get("target_task_id") or ""),
        target_title=str(record.get("target_title") or ""),
        current_status=str(record.get("expected_status") or ""),
        target_status=str(record.get("target_status") or ""),
        requires_confirmation=requires,
        state=state,
        created_at=str(record.get("created_at") or ""),
        preview=preview,
        record=dict(record),
        lifecycle_status=lifecycle_status,
    )


def _preview_from_record(record) -> ActionPreview:
    return ActionPreview(
        str(record.get("action_id") or ""),
        str(record.get("action_type") or ""),
        str(record.get("conversation_id") or ""),
        str(record.get("message_id") or ""),
        str(record.get("actor_ref") or ""),
        str(record.get("target_task_id") or ""),
        str(record.get("target_title") or ""),
        str(record.get("expected_status") or ""),
        str(record.get("target_status") or ""),
        True,
        STATE_PREPARED,
        str(record.get("created_at") or ""),
    )


def _outcome_from_transition(status: str):
    if status == TRANSITION_TRANSITIONED:
        return STATE_EXECUTED, ""
    if status == TRANSITION_ALREADY_IN_STATE:
        return STATE_SUCCEEDED_NOOP, TRANSITION_ALREADY_IN_STATE
    if status == TRANSITION_STALE_STATE:
        return STATE_FAILED, TRANSITION_STALE_STATE
    if status == TRANSITION_WRITE_FAILED:
        return STATE_FAILED, TRANSITION_WRITE_FAILED
    if status == TRANSITION_TASK_NOT_FOUND:
        return STATE_FAILED, TRANSITION_TASK_NOT_FOUND
    return STATE_FAILED, str(status or STATE_FAILED)


def _status_pair(record, transition):
    expected = str(record.get("expected_status") or "")
    if transition is None:
        return expected, ""
    before = str(transition.from_status or "")
    if transition.status == TRANSITION_TRANSITIONED:
        return before, str(transition.to_status or "")
    if transition.status == TRANSITION_ALREADY_IN_STATE:
        return before, before
    return before, before


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()
