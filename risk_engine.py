# -*- coding: utf-8 -*-
"""P5 Risk Engine 离线流水线。

给定已形成的 Topic 与已入库的 Message Evidence，抽取明确的未来不利结果。
G4 由 Topic 成功后的 Risk Side-path 非阻塞投递；仍不改 listener / Topic / Task / Decision decision。
失败隔离在本模块边界内，不影响 Topic / Task / Decision / Chat。
禁止 send_reply / wx.SendMsg。
TaskStore 读取失败不得升级为 Risk FAILED。
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from agent_store import PromptResolveError, resolve_extractor_prompt
from conversation_store import utc_now_iso
from risk_extractor_client import (
    ALLOWED_DECISIONS,
    HeuristicRiskExtractor,
    RiskExtractorError,
    normalize_risk_extractor_output,
    parse_risk_extractor_json,
)
from risk_store import (
    DECISION_FAILED,
    DECISION_NEW_RISK,
    DECISION_RISK_UPDATE,
    DECISION_SKIPPED,
    DECISION_UNRELATED,
    DEFAULT_PROCESSING_VERSION,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    RELATION_UPDATED_BY,
    RISK_STATUS_OPEN,
    RiskStore,
    RiskStoreError,
    content_preview,
    make_risk_id,
    make_rlink_id,
)
from topic_store import DIRECTION_OUTBOUND, TopicStore, TopicStoreError

RISK_ENGINE_ENABLED = False
RISK_EXTRACTOR_PROMPT_NAME = "RISK_EXTRACTOR"
MAX_RECENT_TOPIC_MESSAGES = 12
MAX_EXISTING_RISKS = 10
MAX_CANDIDATE_TASKS = 10
MAX_CONTENT_CHARS = 800
MAX_TITLE_CHARS = 40
MAX_TEXT_CHARS = 500

ACKNOWLEDGEMENTS = {"收到", "好的", "嗯", "ok", "OK", "谢谢", "行", "好", "收到收到"}
EMOJI_ONLY = re.compile(
    r"^(?:\[[^\]]{1,8}\]|\s|[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F])+$"
)


@dataclass
class EngineResult:
    skipped: bool = False
    decision: str = ""
    decision_summary: str = ""
    topic_id: Optional[str] = None
    message_id: str = ""
    conversation_id: str = ""
    risk_ids: list = field(default_factory=list)
    error: str = ""
    error_code: str = ""
    evidence_message_ids: list = field(default_factory=list)
    confidence: str = ""
    isolated: bool = True
    replayed: bool = False
    new_risk_count: int = 0
    update_count: int = 0
    candidate_tasks_error: str = ""

    def as_dict(self) -> dict:
        return {
            "skipped": self.skipped,
            "decision": self.decision,
            "decision_summary": self.decision_summary,
            "topic_id": self.topic_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "risk_ids": list(self.risk_ids),
            "error": self.error,
            "error_code": self.error_code,
            "evidence_message_ids": list(self.evidence_message_ids),
            "confidence": self.confidence,
            "isolated": self.isolated,
            "replayed": self.replayed,
            "new_risk_count": self.new_risk_count,
            "update_count": self.update_count,
            "candidate_tasks_error": self.candidate_tasks_error,
        }


def _strip_ack(text: str) -> str:
    value = str(text or "").strip()
    return re.sub(r"[。.?？!！,，\s]+$", "", value).strip()


def rule_prefilter(content: str) -> Optional[str]:
    text = str(content or "")
    stripped = text.strip()
    if not stripped:
        return DECISION_SKIPPED
    ack = _strip_ack(stripped)
    if ack in ACKNOWLEDGEMENTS:
        return DECISION_UNRELATED
    if stripped in ("[图片]",) or (stripped.startswith("[图片]") and len(stripped) <= 8):
        return DECISION_UNRELATED
    if EMOJI_ONLY.match(stripped) and not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", re.sub(r"\[[^\]]+\]", "", stripped)):
        return DECISION_UNRELATED
    return None


def known_message_ids(engine_input: dict) -> set:
    ids = set()
    current = (engine_input.get("current_message") or {}).get("id")
    if current:
        ids.add(current)
    for item in engine_input.get("recent_topic_messages") or []:
        if item.get("id"):
            ids.add(item["id"])
    return ids


def _clip_task_id(value) -> Optional[str]:
    text = str(value or "").strip()
    if not text or text.lower() in ("none", "null"):
        return None
    return text


def build_extractor_input(
    conversation: dict,
    topic: dict,
    current: dict,
    recent: list,
    existing_risks: list,
    candidate_tasks: list,
) -> dict:
    def clip_msg(item: dict) -> dict:
        return {
            "id": item.get("id") or "",
            "sender_name": item.get("sender_name") or "",
            "sender_wxid": item.get("sender_wxid") or "",
            "content": str(item.get("content") or "")[:MAX_CONTENT_CHARS],
            "created_at": item.get("created_at") or "",
        }

    return {
        "conversation": {
            "id": conversation.get("id") or "",
            "conversation_type": conversation.get("conversation_type") or "",
            "display_name": conversation.get("display_name") or "",
        },
        "topic": {
            "id": topic.get("id") or "",
            "title": topic.get("title") or "",
            "summary": topic.get("summary") or "",
            "status": topic.get("status") or "",
        },
        "current_message": clip_msg(current),
        "recent_topic_messages": [clip_msg(item) for item in recent[-MAX_RECENT_TOPIC_MESSAGES:]],
        "existing_risks": [
            {
                "id": item.get("id"),
                "title": item.get("title") or "",
                "condition_text": item.get("condition_text") or "",
                "impact_text": item.get("impact_text") or "",
                "status": item.get("status") or RISK_STATUS_OPEN,
                "confidence": item.get("confidence") or "",
                "task_id": item.get("task_id") or "",
                "created_msg_id": item.get("created_msg_id") or "",
            }
            for item in existing_risks[:MAX_EXISTING_RISKS]
        ],
        "candidate_tasks": [
            {
                "id": item.get("id"),
                "title": item.get("title") or "",
                "assignee_text": item.get("assignee_text") or "",
                "due_text": item.get("due_text") or "",
                "status": item.get("status") or "OPEN",
                "created_msg_id": item.get("created_msg_id") or "",
            }
            for item in candidate_tasks[:MAX_CANDIDATE_TASKS]
        ],
    }


def validate_risk_decisions(output: dict, engine_input: dict) -> list:
    payload = output if isinstance(output, dict) else {}
    if "risks" not in payload:
        payload = normalize_risk_extractor_output(payload) if isinstance(payload, dict) else payload
    risks = list(payload.get("risks") or [])
    if len(risks) < 1 or len(risks) > 5:
        raise RiskExtractorError("INVALID_OUTPUT", "risks 必须是 1..5 条", str(len(risks)))
    existing_ids = {item.get("id") for item in (engine_input.get("existing_risks") or [])}
    candidate_ids = {item.get("id") for item in (engine_input.get("candidate_tasks") or []) if item.get("id")}
    current_id = (engine_input.get("current_message") or {}).get("id")
    allowed_msgs = known_message_ids(engine_input)
    validated = []
    for item in risks:
        decision = str((item or {}).get("decision") or "")
        if decision not in ALLOWED_DECISIONS:
            raise RiskExtractorError("INVALID_DECISION", "非法 decision", decision)
        risk_id = item.get("risk_id")
        evidence = list(item.get("evidence_message_ids") or [])
        for msg_id in evidence:
            if msg_id not in allowed_msgs:
                raise RiskExtractorError("INVALID_EVIDENCE_ID", "evidence 引用了未知 message id", msg_id)
        if current_id and current_id not in evidence:
            raise RiskExtractorError("INVALID_EVIDENCE_ID", "evidence 必须包含当前消息", str(current_id))
        task_id = _clip_task_id(item.get("task_id"))
        if task_id and task_id not in candidate_ids:
            task_id = None
        item["task_id"] = task_id
        if decision == DECISION_NEW_RISK:
            if risk_id:
                raise RiskExtractorError("INVALID_RISK_ID", "NEW_RISK 不得携带 risk_id", str(risk_id))
            if not str(item.get("title") or "").strip():
                raise RiskExtractorError("INVALID_RISK_DECISION", "NEW_RISK 需要 title")
            if not str(item.get("condition_text") or "").strip() or not str(item.get("impact_text") or "").strip():
                raise RiskExtractorError(
                    "INVALID_RISK_DECISION",
                    "NEW_RISK 必须同时有 condition_text 与 impact_text",
                )
            item["risk_id"] = None
        elif decision == DECISION_RISK_UPDATE:
            if not risk_id or risk_id not in existing_ids:
                raise RiskExtractorError("INVALID_RISK_ID", "risk_id 不在本次 existing_risks 中", str(risk_id))
        elif decision == DECISION_UNRELATED:
            if risk_id:
                raise RiskExtractorError("INVALID_RISK_ID", "UNRELATED 不得携带 risk_id", str(risk_id))
            item["risk_id"] = None
            item["task_id"] = None
        validated.append(item)
    return validated


def recent_topic_messages(
    topic_store: TopicStore,
    conversation_id: str,
    topic_id: str,
    exclude_id: str = "",
    limit: int = MAX_RECENT_TOPIC_MESSAGES,
) -> list:
    linked_ids = {
        item.get("message_id")
        for item in topic_store.links_for_topic(conversation_id, topic_id)
        if item.get("message_id")
    }
    messages = [
        item
        for item in topic_store.list_messages(conversation_id)
        if item.get("id") in linked_ids and item.get("id") != exclude_id
    ]
    messages.sort(key=lambda item: str(item.get("created_at") or ""))
    if limit <= 0:
        return messages
    return messages[-limit:]


def message_belongs_to_topic(topic_store: TopicStore, conversation_id: str, topic_id: str, message_id: str) -> bool:
    for item in topic_store.links_for_topic(conversation_id, topic_id):
        if item.get("message_id") == message_id:
            return True
    return False


class RiskEngine:
    def __init__(
        self,
        store: RiskStore,
        topic_store: TopicStore,
        *,
        task_store=None,
        extractor=None,
        root_dir: str = "",
        enabled: Optional[bool] = None,
        extractor_prompt_name: str = RISK_EXTRACTOR_PROMPT_NAME,
        model: str = "INHERIT",
    ):
        self.store = store
        self.topic_store = topic_store
        self.task_store = task_store
        self.extractor = extractor if extractor is not None else HeuristicRiskExtractor()
        self.root_dir = root_dir
        self.enabled = RISK_ENGINE_ENABLED if enabled is None else bool(enabled)
        self.extractor_prompt_name = extractor_prompt_name or RISK_EXTRACTOR_PROMPT_NAME
        self.model = model or "INHERIT"
        self.last_candidate_tasks_error = ""

    def process_record(self, conversation: dict, topic: dict, message: dict) -> EngineResult:
        if not self.enabled:
            return EngineResult(skipped=True, decision="DISABLED", isolated=True)
        started = time.perf_counter()
        conversation_id = str((conversation or {}).get("id") or (message or {}).get("conversation_id") or "")
        message_id = str((message or {}).get("id") or "")
        try:
            return self._process_record(conversation, topic, message, started)
        except Exception as exc:
            return self._isolate(
                exc,
                conversation_id=conversation_id,
                message_id=message_id,
                topic_id=str((topic or {}).get("id") or ""),
                started=started,
            )

    def _process_record(self, conversation: dict, topic: dict, message: dict, started: float) -> EngineResult:
        cid = str((conversation or {}).get("id") or "")
        topic_id = str((topic or {}).get("id") or "")
        if not cid:
            raise RiskStoreError("INVALID_CONVERSATION_ID", "缺少 conversation.id")
        if not topic_id:
            raise RiskStoreError("INVALID_TOPIC_ID", "缺少 topic.id")
        stored_topic = self.store.require_topic(cid, topic_id)
        saved = self.topic_store.get_message(cid, str((message or {}).get("id") or ""))
        if saved is None:
            raise RiskStoreError("MESSAGE_NOT_FOUND", "MessageRecord 不存在，禁止猜 Topic / 写 Risk")
        message_id = saved["id"]
        if str(saved.get("conversation_id") or "") != cid:
            raise RiskStoreError("MESSAGE_CONVERSATION_MISMATCH", "Message 不属于当前 Conversation")
        if str(stored_topic.get("conversation_id") or "") != cid:
            raise RiskStoreError("TOPIC_CONVERSATION_MISMATCH", "Topic 不属于当前 Conversation")
        if not message_belongs_to_topic(self.topic_store, cid, topic_id, message_id):
            raise RiskStoreError("TOPIC_EVIDENCE_MISSING", "当前 Message 没有 Topic Evidence，禁止抽 Risk")

        if self.store.has_successful_processing(cid, message_id):
            prev = self.store.get_processing(cid, message_id) or {}
            return EngineResult(
                skipped=True,
                replayed=True,
                decision=str(prev.get("decision_summary") or ""),
                decision_summary=str(prev.get("decision_summary") or ""),
                topic_id=prev.get("topic_id") or topic_id,
                message_id=message_id,
                conversation_id=cid,
                risk_ids=list(prev.get("risk_ids") or []),
            )
        if str(saved.get("direction") or "").upper() == DIRECTION_OUTBOUND:
            return self._finalize(
                cid,
                saved,
                stored_topic,
                [DECISION_SKIPPED],
                risk_ids=[],
                reason="outbound_not_extracted",
                started=started,
            )
        pre = rule_prefilter(saved.get("content") or "")
        if pre:
            return self._finalize(
                cid,
                saved,
                stored_topic,
                [pre],
                risk_ids=[],
                reason="rule_prefilter",
                started=started,
            )

        existing = self.store.list_open_risks(cid, topic_id, limit=MAX_EXISTING_RISKS)
        recent = recent_topic_messages(
            self.topic_store,
            cid,
            topic_id,
            exclude_id=message_id,
            limit=MAX_RECENT_TOPIC_MESSAGES,
        )
        candidate_tasks, candidate_error = self._read_candidate_tasks(
            cid, topic_id, str(saved.get("content") or "")
        )
        engine_input = build_extractor_input(
            conversation, stored_topic, saved, recent, existing, candidate_tasks
        )
        prompt = resolve_extractor_prompt(self.extractor_prompt_name, root_dir=self.root_dir)
        raw = self.extractor.extract(engine_input, prompt.content)
        if isinstance(raw, dict) and "risks" in raw:
            parsed = normalize_risk_extractor_output(raw)
        else:
            parsed = parse_risk_extractor_json(raw if isinstance(raw, str) else json_dumps_safe(raw))
        validated = validate_risk_decisions(parsed, engine_input)
        applied = self._apply_risks(cid, stored_topic, saved, validated, existing)
        return self._finalize(
            cid,
            saved,
            stored_topic,
            [item["decision"] for item in validated],
            risk_ids=applied["risk_ids"],
            evidence=_all_evidence(validated),
            confidence=_primary_confidence(validated),
            prompt=prompt,
            started=started,
            reason=";".join(item.get("reason") or "" for item in validated),
            new_risk_count=applied["new_risk_count"],
            update_count=applied["update_count"],
            candidate_tasks_error=candidate_error,
        )

    def _read_candidate_tasks(self, conversation_id: str, topic_id: str, content: str):
        self.last_candidate_tasks_error = ""
        if self.task_store is None:
            return [], ""
        try:
            items = self.task_store.list_open_tasks(
                conversation_id,
                topic_id,
                limit=MAX_CANDIDATE_TASKS,
                content=content,
            ) or []
            return list(items)[:MAX_CANDIDATE_TASKS], ""
        except Exception as exc:
            detail = "%s: %s" % (exc.__class__.__name__, str(exc)[:200])
            self.last_candidate_tasks_error = detail
            try:
                self._audit(
                    {
                        "conversation_id": conversation_id,
                        "topic_id": topic_id,
                        "risk_decision": "CANDIDATE_TASKS_UNAVAILABLE",
                        "error": detail,
                        "reason": "task_store_read_failed_continue",
                    }
                )
            except Exception:
                pass
            return [], detail

    def _apply_risks(self, conversation_id: str, topic: dict, message: dict, decisions: list, existing: list) -> dict:
        now = utc_now_iso()
        created_at_seed = str(message.get("created_at") or now)
        new_risks = []
        updates = []
        new_links = []
        risk_ids = []
        new_count = 0
        update_count = 0
        ordinal = 0
        known_msgs = {item.get("id") for item in self.topic_store.list_messages(conversation_id)}
        current_id = message["id"]
        existing_by_id = {item.get("id"): item for item in existing}
        for item in decisions:
            decision = item["decision"]
            confidence = item.get("confidence") or "MEDIUM"
            task_id = item.get("task_id") or ""
            if decision == DECISION_UNRELATED:
                continue
            if decision == DECISION_NEW_RISK:
                risk_id = make_risk_id(
                    conversation_id,
                    topic["id"],
                    current_id,
                    ordinal,
                    created_at_seed,
                )
                record = {
                    "id": risk_id,
                    "conversation_id": conversation_id,
                    "topic_id": topic["id"],
                    "task_id": task_id or "",
                    "title": str(item.get("title") or "")[:MAX_TITLE_CHARS],
                    "description": "",
                    "condition_text": str(item.get("condition_text") or "")[:MAX_TEXT_CHARS],
                    "impact_text": str(item.get("impact_text") or "")[:MAX_TEXT_CHARS],
                    "status": RISK_STATUS_OPEN,
                    "confidence": confidence,
                    "created_msg_id": current_id,
                    "created_at": now,
                    "updated_at": now,
                    "schema_version": 1,
                }
                new_risks.append(record)
                new_links.append(
                    {
                        "id": make_rlink_id(risk_id, current_id, RELATION_CREATED_BY),
                        "risk_id": risk_id,
                        "message_id": current_id,
                        "relation": RELATION_CREATED_BY,
                        "confidence": confidence,
                        "created_at": now,
                    }
                )
                for evidence_id in item.get("evidence_message_ids") or []:
                    if evidence_id == current_id or evidence_id not in known_msgs:
                        continue
                    new_links.append(
                        {
                            "id": make_rlink_id(risk_id, evidence_id, RELATION_RELATED),
                            "risk_id": risk_id,
                            "message_id": evidence_id,
                            "relation": RELATION_RELATED,
                            "confidence": confidence,
                            "created_at": now,
                        }
                    )
                risk_ids.append(risk_id)
                new_count += 1
                ordinal += 1
                continue
            if decision == DECISION_RISK_UPDATE:
                target_id = item.get("risk_id")
                current = existing_by_id.get(target_id) or self.store.get_risk(conversation_id, target_id) or {}
                fields = {"confidence": confidence}
                title = str(item.get("title") or "").strip()
                condition = str(item.get("condition_text") or "").strip()
                impact = str(item.get("impact_text") or "").strip()
                if title:
                    fields["title"] = title[:MAX_TITLE_CHARS]
                if condition:
                    fields["condition_text"] = condition[:MAX_TEXT_CHARS]
                if impact:
                    fields["impact_text"] = impact[:MAX_TEXT_CHARS]
                if task_id and not str(current.get("task_id") or ""):
                    fields["task_id"] = task_id
                updates.append({"id": target_id, "fields": fields, "updated_at": now})
                new_links.append(
                    {
                        "id": make_rlink_id(target_id, current_id, RELATION_UPDATED_BY),
                        "risk_id": target_id,
                        "message_id": current_id,
                        "relation": RELATION_UPDATED_BY,
                        "confidence": confidence,
                        "created_at": now,
                    }
                )
                risk_ids.append(target_id)
                update_count += 1
        if new_risks or updates or new_links:
            applied_commit = self.store.commit_apply(
                conversation_id,
                new_risks=new_risks,
                updates=updates,
                new_links=new_links,
            )
            risk_ids = list(applied_commit.get("risk_ids") or [])
        return {
            "risk_ids": risk_ids,
            "new_risk_count": new_count,
            "update_count": update_count,
        }

    def _finalize(
        self,
        conversation_id: str,
        message: dict,
        topic: dict,
        decisions: list,
        *,
        risk_ids=None,
        evidence=None,
        confidence="",
        prompt=None,
        started=None,
        reason="",
        error="",
        new_risk_count=0,
        update_count=0,
        candidate_tasks_error="",
    ) -> EngineResult:
        prompt_name = getattr(prompt, "prompt_name", "") if prompt is not None else self.extractor_prompt_name
        prompt_hash = getattr(prompt, "prompt_hash", "") if prompt is not None else ""
        summary = ",".join(decisions) if decisions else DECISION_UNRELATED
        self.store.write_processing(
            {
                "message_id": message["id"],
                "conversation_id": conversation_id,
                "topic_id": topic.get("id"),
                "risk_processing_version": DEFAULT_PROCESSING_VERSION,
                "extractor_prompt_name": prompt_name,
                "extractor_prompt_hash": prompt_hash,
                "decision_summary": summary,
                "risk_ids": list(risk_ids or []),
                "error": error,
            }
        )
        latency_ms = int((time.perf_counter() - started) * 1000) if started is not None else 0
        self._audit(
            {
                "conversation_id": conversation_id,
                "message_id": message["id"],
                "risk_decision": summary,
                "topic_id": topic.get("id"),
                "risk_ids": list(risk_ids or []),
                "confidence": confidence,
                "evidence_message_ids": list(evidence or []),
                "extractor_prompt_name": prompt_name,
                "extractor_prompt_hash": prompt_hash,
                "model": self.model,
                "latency_ms": latency_ms,
                "error": error,
                "reason": reason,
                "content_preview": content_preview(message.get("content") or ""),
                "candidate_tasks_error": candidate_tasks_error,
            }
        )
        primary = decisions[0] if decisions else DECISION_UNRELATED
        return EngineResult(
            decision=primary,
            decision_summary=summary,
            topic_id=topic.get("id"),
            message_id=message["id"],
            conversation_id=conversation_id,
            risk_ids=list(risk_ids or []),
            evidence_message_ids=list(evidence or []),
            confidence=confidence,
            error=error,
            new_risk_count=new_risk_count,
            update_count=update_count,
            candidate_tasks_error=candidate_tasks_error,
        )

    def _isolate(
        self,
        exc: Exception,
        *,
        conversation_id: str,
        message_id: str,
        topic_id: str = "",
        started=None,
    ) -> EngineResult:
        code = getattr(exc, "code", None) or exc.__class__.__name__
        if isinstance(exc, PromptResolveError):
            code = exc.code
        if isinstance(exc, RiskExtractorError):
            code = exc.code
        if isinstance(exc, RiskStoreError):
            code = exc.code
        if isinstance(exc, TopicStoreError):
            code = exc.code
        if isinstance(exc, TimeoutError):
            code = "EXTRACTOR_TIMEOUT"
        detail = str(getattr(exc, "detail", None) or exc)
        if message_id and conversation_id:
            try:
                self.store.write_processing(
                    {
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                        "topic_id": topic_id or None,
                        "decision_summary": DECISION_FAILED,
                        "error": "%s: %s" % (code, detail)[:300],
                    }
                )
            except Exception:
                pass
        try:
            self._audit(
                {
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "topic_id": topic_id,
                    "risk_decision": DECISION_FAILED,
                    "error": "%s: %s" % (code, detail)[:300],
                    "model": self.model,
                    "latency_ms": int((time.perf_counter() - started) * 1000) if started else 0,
                    "extractor_prompt_name": self.extractor_prompt_name,
                }
            )
        except Exception:
            pass
        return EngineResult(
            decision=DECISION_FAILED,
            decision_summary=DECISION_FAILED,
            message_id=message_id,
            conversation_id=conversation_id,
            topic_id=topic_id or None,
            error=detail,
            error_code=code,
            isolated=True,
        )

    def _audit(self, event: dict) -> None:
        self.store.write_audit(event)


def _all_evidence(decisions: list) -> list:
    ids = []
    seen = set()
    for item in decisions:
        for msg_id in item.get("evidence_message_ids") or []:
            if msg_id in seen:
                continue
            seen.add(msg_id)
            ids.append(msg_id)
    return ids


def _primary_confidence(decisions: list) -> str:
    for item in decisions:
        if item.get("confidence"):
            return item.get("confidence")
    return ""


def json_dumps_safe(value) -> str:
    import json
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return "{}"


def engine_source_forbids_wechat_sidepath() -> bool:
    import risk_extractor_client
    import risk_sidepath
    import risk_store

    source = inspect.getsource(RiskEngine)
    source += inspect.getsource(build_extractor_input)
    source += inspect.getsource(risk_extractor_client)
    source += inspect.getsource(risk_sidepath)
    source += inspect.getsource(risk_store)
    encoded = (
        "send_reply" + "(",
        "wx.SendMsg" + "(",
        "SendMsg" + "(",
        "from message" + ".listener",
    )
    return all(token not in source for token in encoded)
