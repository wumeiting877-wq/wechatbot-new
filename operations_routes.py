# -*- coding: utf-8 -*-
"""P7-G0 只读运维 JSON 与最小页面。P7-G2 增加只读调查详情。"""

from __future__ import annotations

import os

from flask import jsonify, render_template, request

from operations_diagnostic_service import OperationsDiagnosticService
from operations_read_model import OperationsReadModel

_ROOT = os.path.dirname(os.path.abspath(__file__))


def register_operations_routes(app, login_required, root_dir: str = ""):
    root = os.path.abspath(root_dir or _ROOT)

    def _model() -> OperationsReadModel:
        return OperationsReadModel(root)

    def _diagnostics() -> OperationsDiagnosticService:
        return OperationsDiagnosticService(root)

    @app.route("/api/operations/status", methods=["GET"])
    @login_required
    def operations_status():
        return jsonify(_model().status())

    @app.route("/api/operations/messages", methods=["GET"])
    @login_required
    def operations_messages():
        limit = request.args.get("limit", 100, type=int)
        attention = str(request.args.get("attention") or "").strip().lower() in ("1", "true", "yes")
        rows = _model().list_messages()
        if attention:
            rows = [row for row in rows if row.get("attention_required")]
        if limit is not None and limit > 0:
            rows = rows[:limit]
        return jsonify({"messages": rows})

    @app.route("/api/operations/messages/<message_id>", methods=["GET"])
    @login_required
    def operations_message(message_id):
        row = _model().get_message(message_id, request.args.get("conversation_id") or "")
        if row is None:
            return jsonify({
                "error": "message not found",
                "message_id": message_id,
            }), 404
        return jsonify(row)

    @app.route("/api/operations/messages/<message_id>/diagnostics", methods=["GET"])
    @login_required
    def operations_message_diagnostics(message_id):
        view = _diagnostics().get_message_diagnostics(
            message_id,
            request.args.get("conversation_id") or "",
        )
        if view is None:
            return jsonify({
                "error": "message not found",
                "message_id": message_id,
            }), 404
        return jsonify(view)

    @app.route("/operations/messages/<message_id>", methods=["GET"])
    @login_required
    def operations_message_detail(message_id):
        view = _diagnostics().get_message_diagnostics(
            message_id,
            request.args.get("conversation_id") or "",
        )
        if view is None:
            return render_template(
                "operations_message.html",
                missing=True,
                message_id=message_id,
                detail=None,
            ), 404
        return render_template(
            "operations_message.html",
            missing=False,
            message_id=message_id,
            detail=view,
        )

    @app.route("/api/operations/issues", methods=["GET"])
    @login_required
    def operations_issues():
        limit = request.args.get("limit", 50, type=int)
        return jsonify({"issues": _model().issues(limit=limit)})

    @app.route("/operations", methods=["GET"])
    @login_required
    def operations_home():
        model = _model()
        status = model.status()
        attention = request.args.get("attention", "1")
        show_all = str(attention).strip() == "0"
        rows = model.list_messages()
        if not show_all:
            rows = [row for row in rows if row.get("attention_required")]
        rows = rows[:50]
        return render_template(
            "operations.html",
            status=status,
            rows=rows,
            show_all=show_all,
        )
