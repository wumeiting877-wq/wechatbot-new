# -*- coding: utf-8 -*-
"""P7-G1 人工重试 POST。沿用 login_required，并在登录开关关闭时拒绝执行。"""

from __future__ import annotations

import os

from flask import jsonify, request, session

from operations_action_audit import EVENT_REQUESTED, EVENT_RESULT, append_action_audit
from operations_action_service import (
    ERROR_BAD_REQUEST,
    ManualRetryResult,
    OperationsActionService,
)
from operations_action_wiring import DownstreamRetryBinding, TopicRetryBinding

_ROOT = os.path.dirname(os.path.abspath(__file__))
ERROR_AUTH_REQUIRED = "AUTH_REQUIRED"
MSG_AUTH = "当前未开启登录保护，不能执行人工重试。"


def _default_write_allowed() -> bool:
    """登录开关关闭时 login_required 不验 session。此时拒绝写，避免匿名重试。"""
    try:
        from config_editor import parse_config
        config = parse_config()
    except Exception:
        return False
    return bool(config.get("ENABLE_LOGIN_PASSWORD", False))


def _body_from_result(result: ManualRetryResult) -> dict:
    return result.as_dict()


def _plain_body(engine: str, conversation_id: str, message_id: str, error_code: str, error: str) -> dict:
    return {
        "engine": engine,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "before_state": None,
        "retry_result": None,
        "after_state": None,
        "executed": False,
        "error_code": error_code,
        "error": error,
        "after_message": None,
    }


def register_operations_action_routes(
    app,
    login_required,
    root_dir: str = "",
    *,
    write_allowed=None,
    action_service: OperationsActionService = None,
):
    root = os.path.abspath(root_dir or _ROOT)

    def _allowed() -> bool:
        if write_allowed is not None:
            return bool(write_allowed())
        return _default_write_allowed()

    def _service() -> OperationsActionService:
        if action_service is not None:
            return action_service
        return OperationsActionService(
            root,
            topic_service_factory=lambda runtime: TopicRetryBinding(root, runtime),
            downstream_service_factory=lambda runtime: DownstreamRetryBinding(root, runtime),
        )

    @app.route("/api/operations/messages/<message_id>/retry", methods=["POST"])
    @login_required
    def operations_manual_retry(message_id):
        raw = request.get_json(silent=True) if request.is_json else {}
        body = raw if isinstance(raw, dict) else {}
        engine = str(body.get("engine") or "").strip().lower()
        conversation_id = str(body.get("conversation_id") or "").strip()
        session_present = bool(session.get("logged_in"))
        if not _allowed():
            payload = _plain_body(engine, conversation_id, message_id, ERROR_AUTH_REQUIRED, MSG_AUTH)
            _audit_denial(root, payload, body.get("version"), session_present)
            return jsonify(payload), 403
        if not request.is_json:
            payload = _plain_body(engine, conversation_id, message_id, ERROR_BAD_REQUEST, "需要 application/json")
            return jsonify(payload), 415
        try:
            version = int(body.get("version"))
        except (TypeError, ValueError):
            payload = _plain_body(engine, conversation_id, message_id, ERROR_BAD_REQUEST, "version 必须是正整数")
            return jsonify(payload), 400
        result = _service().manual_retry(
            engine,
            conversation_id,
            message_id,
            version,
            session_present=session_present,
        )
        return jsonify(_body_from_result(result)), result.http_status


def _audit_denial(root: str, payload: dict, version, session_present: bool) -> None:
    try:
        ver = int(version or 0)
    except (TypeError, ValueError):
        ver = 0
    common = {
        "engine": payload.get("engine") or "",
        "conversation_id": payload.get("conversation_id") or "",
        "message_id": payload.get("message_id") or "",
        "version": ver,
        "before_state": "",
        "executed": False,
        "retry_result": "",
        "after_state": "",
        "error": payload.get("error") or "",
        "error_code": payload.get("error_code") or "",
        "session_present": bool(session_present),
    }
    try:
        append_action_audit(root, dict(common, event=EVENT_REQUESTED))
        append_action_audit(root, dict(common, event=EVENT_RESULT))
    except Exception:
        return
