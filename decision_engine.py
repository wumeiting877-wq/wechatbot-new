# -*- coding: utf-8 -*-
"""P5 Decision Engine 离线流水线。

给定已形成的 Topic 与已入库的 Message Evidence，抽取已确认的企业决策。
G2 由 Topic 成功后的 Decision Side-path 非阻塞投递；仍不改 listener / Topic decision / Task。
失败隔离在本模块边界内，不影响 Topic / Task / Chat。
禁止 send_reply / wx.SendMsg。
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from agent_store import PromptResolveError, resolve_extractor_prompt
from conversation_store import utc_now_iso
from decision_extractor_client import (
    ALLOWED_DECISIONS,
    DecisionExtractorClient,
    DecisionExtractorError,
    normalize_decision_extractor_output,
    parse_decision_extractor_json,
)
from decision_store import (
    DECISION_FAILED,
    DECISION_NEW_DECISION,
    DECISION_SKIPPED,
    DECISION_STATUS_RECORDED,
    DECISION_UNRELATED,
    DEFAULT_PROCESSING_VERSION,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    DecisionStore,
    DecisionStoreError,
    content_preview,
    make_decision_id,
    make_dlink_id,
)
from topic_store import DIRECTION_OUTBOUND, TopicStore, TopicStoreError

DECISION_ENGINE_ENABLED = False
DECISION_EXTRACTOR_PROMPT_NAME = "DECISION_EXTRACTOR"
MAX_RECENT_TOPIC_MESSAGES = 12
MAX_EXISTING_DECISIONS = 10
MAX_CONTENT_CHARS = 800
MAX_TITLE_CHARS = 40
MAX_DECISION_TEXT_CHARS = 500

ACKNOWLEDGEMENTS = {"收到", "好的", "嗯", "ok", "OK", "谢谢", "行", "可以", "好", "收到收到"}
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
    decision_ids: list = field(default_factory=list)
    error: str = ""
    error_code: str = ""
    evidence_message_ids: list = field(default_factory=list)
    confidence: str = ""
    isolated: bool = True
    replayed: bool = False
    new_decision_count: int = 0

    def as_dict(self) -> dict:
        return {
            "skipped": self.skipped,
            "decision": self.decision,
            "decision_summary": self.decision_summary,
            "topic_id": self.topic_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "decision_ids": list(self.decision_ids),
            "error": self.error,
            "error_code": self.error_code,
            "evidence_message_ids": list(self.evidence_message_ids),
            "confidence": self.confidence,
            "isolated": self.isolated,
            "replayed": self.replayed,
            "new_decision_count": self.new_decision_count,
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


def build_extractor_input(
    conversation: dict,
    topic: dict,
    current: dict,
    recent: list,
    existing_decisions: list,
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
        "existing_decisions": [
            {
                "id": item.get("id"),
                "title": item.get("title") or "",
                "decision_text": item.get("decision_text") or "",
                "status": item.get("status") or DECISION_STATUS_RECORDED,
                "confidence": item.get("confidence") or "",
                "supersedes_decision_id": item.get("supersedes_decision_id"),
                "created_msg_id": item.get("created_msg_id") or "",
            }
            for item in existing_decisions[:MAX_EXISTING_DECISIONS]
        ],
    }


def validate_decision_decisions(output: dict, engine_input: dict) -> list:
    payload = output if isinstance(output, dict) else {}
    if "decisions" not in payload:
        payload = normalize_decision_extractor_output(payload) if isinstance(payload, dict) else payload
    decisions = list(payload.get("decisions") or [])
    if len(decisions) < 1 or len(decisions) > 5:
        raise DecisionExtractorError("INVALID_OUTPUT", "decisions 必须是 1..5 条", str(len(decisions)))
    existing_ids = {item.get("id") for item in (engine_input.get("existing_decisions") or [])}
    current_id = (engine_input.get("current_message") or {}).get("id")
    allowed_msgs = known_message_ids(engine_input)
    validated = []
    for item in decisions:
        decision = str((item or {}).get("decision") or "")
        if decision not in ALLOWED_DECISIONS:
            raise DecisionExtractorError("INVALID_DECISION", "非法 decision", decision)
        decision_id = item.get("decision_id")
        supersedes = item.get("supersedes_decision_id")
        if supersedes == "" or supersedes is False:
            supersedes = None
            item["supersedes_decision_id"] = None
        evidence = list(item.get("evidence_message_ids") or [])
        for msg_id in evidence:
            if msg_id not in allowed_msgs:
                raise DecisionExtractorError("INVALID_EVIDENCE_ID", "evidence 引用了未知 message id", msg_id)
        if current_id and current_id not in evidence:
            raise DecisionExtractorError("INVALID_EVIDENCE_ID", "evidence 必须包含当前消息", str(current_id))
        if supersedes is not None:
            if supersedes not in existing_ids:
                raise DecisionExtractorError(
                    "INVALID_SUPERSEDES_DECISION_ID",
                    "supersedes_decision_id 不在本次 existing_decisions 中",
                    str(supersedes),
                )
        if decision == DECISION_NEW_DECISION:
            if decision_id:
                raise DecisionExtractorError("INVALID_DECISION_ID", "NEW_DECISION 不得携带 decision_id", str(decision_id))
            if not str(item.get("title") or "").strip():
                raise DecisionExtractorError("INVALID_OUTPUT", "NEW_DECISION 需要 title")
            if not str(item.get("decision_text") or "").strip():
                raise DecisionExtractorError("INVALID_OUTPUT", "NEW_DECISION 需要 decision_text")
            item["decision_id"] = None
        elif decision == DECISION_UNRELATED:
            if decision_id:
                raise DecisionExtractorError("INVALID_DECISION_ID", "UNRELATED 不得携带 decision_id", str(decision_id))
            item["decision_id"] = None
            item["supersedes_decision_id"] = None
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


class DecisionEngine:
    def __init__(
        self,
        store: DecisionStore,
        topic_store: TopicStore,
        *,
        extractor=None,
        root_dir: str = "",
        enabled: Optional[bool] = None,
        extractor_prompt_name: str = DECISION_EXTRACTOR_PROMPT_NAME,
        model: str = "INHERIT",
    ):
        self.store = store
        self.topic_store = topic_store
        self.extractor = extractor if extractor is not None else DecisionExtractorClient()
        self.root_dir = root_dir
        self.enabled = DECISION_ENGINE_ENABLED if enabled is None else bool(enabled)
        self.extractor_prompt_name = extractor_prompt_name or DECISION_EXTRACTOR_PROMPT_NAME
        self.model = model or "INHERIT"

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
            raise DecisionStoreError("INVALID_CONVERSATION_ID", "缺少 conversation.id")
        if not topic_id:
            raise DecisionStoreError("INVALID_TOPIC_ID", "缺少 topic.id")
        stored_topic = self.store.require_topic(cid, topic_id)
        saved = self.topic_store.get_message(cid, str((message or {}).get("id") or ""))
        if saved is None:
            raise DecisionStoreError("MESSAGE_NOT_FOUND", "MessageRecord 不存在，禁止猜 Topic / 写 Decision")
        message_id = saved["id"]
        if str(saved.get("conversation_id") or "") != cid:
            raise DecisionStoreError("MESSAGE_CONVERSATION_MISMATCH", "Message 不属于当前 Conversation")
        if str(stored_topic.get("conversation_id") or "") != cid:
            raise DecisionStoreError("TOPIC_CONVERSATION_MISMATCH", "Topic 不属于当前 Conversation")
        if not message_belongs_to_topic(self.topic_store, cid, topic_id, message_id):
            raise DecisionStoreError("TOPIC_EVIDENCE_MISSING", "当前 Message 没有 Topic Evidence，禁止抽 Decision")

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
                decision_ids=list(prev.get("decision_ids") or []),
            )
        if str(saved.get("direction") or "").upper() == DIRECTION_OUTBOUND:
            return self._finalize(
                cid,
                saved,
                stored_topic,
                [DECISION_SKIPPED],
                decision_ids=[],
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
                decision_ids=[],
                reason="rule_prefilter",
                started=started,
            )

        existing = self.store.list_recorded_decisions(
            cid,
            topic_id,
            limit=MAX_EXISTING_DECISIONS,
            current_effective=True,
        )
        recent = recent_topic_messages(
            self.topic_store,
            cid,
            topic_id,
            exclude_id=message_id,
            limit=MAX_RECENT_TOPIC_MESSAGES,
        )
        engine_input = build_extractor_input(conversation, stored_topic, saved, recent, existing)
        prompt = resolve_extractor_prompt(self.extractor_prompt_name, root_dir=self.root_dir)
        raw = self.extractor.extract(engine_input, prompt.content)
        if isinstance(raw, dict) and "decisions" in raw:
            parsed = normalize_decision_extractor_output(raw)
        else:
            parsed = parse_decision_extractor_json(raw if isinstance(raw, str) else json_dumps_safe(raw))
        validated = validate_decision_decisions(parsed, engine_input)
        applied = self._apply_decisions(cid, stored_topic, saved, validated)
        return self._finalize(
            cid,
            saved,
            stored_topic,
            [item["decision"] for item in validated],
            decision_ids=applied["decision_ids"],
            evidence=_all_evidence(validated),
            confidence=_primary_confidence(validated),
            prompt=prompt,
            started=started,
            reason=";".join(item.get("reason") or "" for item in validated),
            new_decision_count=applied["new_decision_count"],
        )

    def _apply_decisions(self, conversation_id: str, topic: dict, message: dict, decisions: list) -> dict:
        now = utc_now_iso()
        created_at_seed = str(message.get("created_at") or now)
        new_decisions = []
        new_links = []
        decision_ids = []
        new_count = 0
        ordinal = 0
        known_msgs = {item.get("id") for item in self.topic_store.list_messages(conversation_id)}
        current_id = message["id"]
        for item in decisions:
            decision = item["decision"]
            confidence = item.get("confidence") or "MEDIUM"
            if decision == DECISION_UNRELATED:
                continue
            if decision != DECISION_NEW_DECISION:
                raise DecisionExtractorError("INVALID_DECISION", "非法 decision", decision)
            decision_id = make_decision_id(
                conversation_id,
                topic["id"],
                current_id,
                ordinal,
                created_at_seed,
            )
            decision_text = str(item.get("decision_text") or "")[:MAX_DECISION_TEXT_CHARS]
            record = {
                "id": decision_id,
                "conversation_id": conversation_id,
                "topic_id": topic["id"],
                "title": str(item.get("title") or "")[:MAX_TITLE_CHARS],
                "decision_text": decision_text,
                "summary": decision_text,
                "status": DECISION_STATUS_RECORDED,
                "confidence": confidence,
                "created_msg_id": current_id,
                "supersedes_decision_id": item.get("supersedes_decision_id"),
                "created_at": now,
                "updated_at": now,
                "schema_version": 1,
            }
            new_decisions.append(record)
            new_links.append(
                {
                    "id": make_dlink_id(decision_id, current_id, RELATION_CREATED_BY),
                    "decision_id": decision_id,
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
                        "id": make_dlink_id(decision_id, evidence_id, RELATION_RELATED),
                        "decision_id": decision_id,
                        "message_id": evidence_id,
                        "relation": RELATION_RELATED,
                        "confidence": confidence,
                        "created_at": now,
                    }
                )
            decision_ids.append(decision_id)
            new_count += 1
            ordinal += 1
        if new_decisions:
            applied_commit = self.store.commit_apply(
                conversation_id,
                new_decisions=new_decisions,
                new_links=new_links,
            )
            decision_ids = list(applied_commit.get("decision_ids") or [])
        return {
            "decision_ids": decision_ids,
            "new_decision_count": new_count,
        }

    def _finalize(
        self,
        conversation_id: str,
        message: dict,
        topic: dict,
        decisions: list,
        *,
        decision_ids=None,
        evidence=None,
        confidence="",
        prompt=None,
        started=None,
        reason="",
        error="",
        new_decision_count=0,
    ) -> EngineResult:
        prompt_name = getattr(prompt, "prompt_name", "") if prompt is not None else self.extractor_prompt_name
        prompt_hash = getattr(prompt, "prompt_hash", "") if prompt is not None else ""
        summary = ",".join(decisions) if decisions else DECISION_UNRELATED
        self.store.write_processing(
            {
                "message_id": message["id"],
                "conversation_id": conversation_id,
                "topic_id": topic.get("id"),
                "decision_processing_version": DEFAULT_PROCESSING_VERSION,
                "extractor_prompt_name": prompt_name,
                "extractor_prompt_hash": prompt_hash,
                "decision_summary": summary,
                "decision_ids": list(decision_ids or []),
                "error": error,
            }
        )
        latency_ms = int((time.perf_counter() - started) * 1000) if started is not None else 0
        self._audit(
            {
                "conversation_id": conversation_id,
                "message_id": message["id"],
                "decision_decision": summary,
                "topic_id": topic.get("id"),
                "decision_ids": list(decision_ids or []),
                "confidence": confidence,
                "evidence_message_ids": list(evidence or []),
                "extractor_prompt_name": prompt_name,
                "extractor_prompt_hash": prompt_hash,
                "model": self.model,
                "latency_ms": latency_ms,
                "error": error,
                "reason": reason,
                "content_preview": content_preview(message.get("content") or ""),
            }
        )
        primary = decisions[0] if decisions else DECISION_UNRELATED
        return EngineResult(
            decision=primary,
            decision_summary=summary,
            topic_id=topic.get("id"),
            message_id=message["id"],
            conversation_id=conversation_id,
            decision_ids=list(decision_ids or []),
            evidence_message_ids=list(evidence or []),
            confidence=confidence,
            error=error,
            new_decision_count=new_decision_count,
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
        if isinstance(exc, DecisionExtractorError):
            code = exc.code
        if isinstance(exc, DecisionStoreError):
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
                    "decision_decision": DECISION_FAILED,
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
    import decision_extractor_client
    import decision_sidepath
    import decision_store

    source = inspect.getsource(DecisionEngine)
    source += inspect.getsource(build_extractor_input)
    source += inspect.getsource(decision_extractor_client)
    source += inspect.getsource(decision_sidepath)
    source += inspect.getsource(decision_store)
    encoded = (
        "send_reply" + "(",
        "wx.SendMsg" + "(",
        "SendMsg" + "(",
        "from message" + ".listener",
    )
    return all(token not in source for token in encoded)
