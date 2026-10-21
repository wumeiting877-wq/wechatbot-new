# -*- coding: utf-8 -*-
"""P3 Topic Engine 离线流水线。

不接入 message/listener.py，不调用 send_reply / wx.SendMsg。
失败隔离在本模块边界内，不影响 Chat。
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from agent_store import (
    DEFAULT_EXTRACTOR_PROMPT_NAME,
    PromptResolveError,
    resolve_extractor_prompt,
)
from conversation_store import (
    PLATFORM_WECHAT,
    find_by_platform_conversation_id,
    find_conversation_by_display_name,
    utc_now_iso,
)
from topic_extractor_client import (
    ALLOWED_DECISIONS,
    TopicExtractorClient,
    TopicExtractorError,
    domain_tags,
    parse_extractor_json,
)
from topic_store import (
    CANDIDATE_STATUSES,
    DECISION_EXISTING_TOPIC,
    DECISION_FAILED,
    DECISION_NEW_TOPIC,
    DECISION_SKIPPED,
    DECISION_TOPIC_UPDATE,
    DECISION_UNRELATED,
    DEFAULT_PROCESSING_VERSION,
    DIRECTION_OUTBOUND,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    RELATION_UPDATED_BY,
    TOPIC_STATUS_RESOLVED,
    TopicStore,
    TopicStoreError,
    content_preview,
    project_inbound_to_message_record,
)

TOPIC_ENGINE_ENABLED = False
MAX_CANDIDATES = 5
MAX_RECENT_MESSAGES = 12
MAX_CONTENT_CHARS = 800
MAX_SUMMARY_CHARS = 400
MAX_TITLE_CHARS = 40

CONVERSATION_NOT_RESOLVED = "CONVERSATION_NOT_RESOLVED"
ACKNOWLEDGEMENTS = {"收到", "好的", "嗯", "1", "ok", "OK", "谢谢", "收到收到"}
CHITCHAT_MARKERS = ("吃什么", "喝什么", "天气怎么样")
EMOJI_ONLY = re.compile(
    r"^(?:\[[^\]]{1,8}\]|\s|[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F])+$"
)


@dataclass
class EngineResult:
    skipped: bool = False
    decision: str = ""
    topic_id: Optional[str] = None
    message_id: str = ""
    conversation_id: str = ""
    error: str = ""
    error_code: str = ""
    candidate_topic_ids: list = field(default_factory=list)
    evidence_message_ids: list = field(default_factory=list)
    confidence: str = ""
    isolated: bool = True
    replayed: bool = False

    def as_dict(self) -> dict:
        return {
            "skipped": self.skipped,
            "decision": self.decision,
            "topic_id": self.topic_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "error": self.error,
            "error_code": self.error_code,
            "candidate_topic_ids": list(self.candidate_topic_ids),
            "evidence_message_ids": list(self.evidence_message_ids),
            "confidence": self.confidence,
            "isolated": self.isolated,
            "replayed": self.replayed,
        }


def resolve_topic_conversation(source: Any, conversations: list) -> Optional[dict]:
    """严禁把 InboundMessage.conversation_id 当作 Topic.conversation_id。"""
    chat_wxid = _field(source, "chat_wxid")
    chat_name = _field(source, "chat_name")
    if chat_wxid:
        hit = find_by_platform_conversation_id(conversations, chat_wxid)
        if hit:
            return hit
    if chat_name:
        hit = find_conversation_by_display_name(conversations, chat_name)
        if hit and str(hit.get("platform") or PLATFORM_WECHAT).upper() == PLATFORM_WECHAT:
            return hit
    return None


def _field(source: Any, name: str) -> str:
    if isinstance(source, dict):
        return str(source.get(name) or "").strip()
    return str(getattr(source, name, "") or "").strip()


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
    if any(marker in stripped for marker in CHITCHAT_MARKERS):
        return DECISION_UNRELATED
    compact = re.sub(r"\s+", "", stripped)
    if len(compact) <= 2 and not domain_tags(stripped):
        return DECISION_UNRELATED
    return None


def _keyword_tokens(text: str) -> set:
    value = str(text or "")
    tokens = set()
    for word in re.findall(r"[A-Za-z0-9]+", value):
        if len(word) >= 2:
            tokens.add(word.lower())
    for chunk in re.findall(r"[\u4e00-\u9fff]+", value):
        if len(chunk) == 1:
            tokens.add(chunk)
        for index in range(len(chunk) - 1):
            tokens.add(chunk[index : index + 2])
    return tokens


def retrieve_candidate_topics(
    store: TopicStore,
    conversation_id: str,
    current_message: dict,
    limit: int = MAX_CANDIDATES,
) -> list:
    """同会话 ACTIVE/WAITING/OPEN，最多 5 个。关键词重叠优先于 last_message_at。"""
    topics = [
        topic
        for topic in store.list_topics(conversation_id)
        if str(topic.get("status") or "") in CANDIDATE_STATUSES
    ]
    reply_to = str(current_message.get("reply_to_message_id") or "").strip()
    reply_topic_ids = set()
    if reply_to:
        for link in store.links_for_message(conversation_id, reply_to):
            reply_topic_ids.add(link.get("topic_id"))
        for topic in store.list_topics(conversation_id):
            if topic.get("id") in reply_topic_ids and topic.get("status") == TOPIC_STATUS_RESOLVED:
                topics.append(topic)
    content = str(current_message.get("content") or "")
    msg_tokens = _keyword_tokens(content)
    msg_tags = domain_tags(content)
    sender = str(current_message.get("sender_name") or "")
    scored = []
    for topic in topics:
        blob = "%s %s" % (topic.get("title") or "", topic.get("summary") or "")
        score = 0.0
        if topic.get("id") in reply_topic_ids:
            score += 10000
        overlap = len(msg_tokens & _keyword_tokens(blob))
        score += overlap * 100
        score += len(msg_tags & domain_tags(blob)) * 80
        last_at = str(topic.get("last_message_at") or topic.get("updated_at") or "")
        if sender and sender in blob:
            score += 5
        scored.append((score, last_at, topic))
    # 关键词分优先；同分才用 last_message_at。禁止只按时间取最近 5 个。
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    unique = []
    seen = set()
    for _score, _ts, topic in scored:
        topic_id = topic.get("id")
        if topic_id in seen:
            continue
        seen.add(topic_id)
        unique.append(topic)
        if len(unique) >= limit:
            break
    return unique


def build_extractor_input(conversation: dict, current: dict, recent: list, topics: list) -> dict:
    def clip_msg(item: dict) -> dict:
        return {
            "id": item.get("id") or "",
            "sender_name": item.get("sender_name") or "",
            "sender_wxid": item.get("sender_wxid") or "",
            "content": str(item.get("content") or "")[:MAX_CONTENT_CHARS],
            "created_at": item.get("created_at") or "",
            "reply_to_message_id": item.get("reply_to_message_id") or "",
            "message_type": item.get("message_type") or "text",
        }

    return {
        "conversation": {
            "id": conversation.get("id") or "",
            "conversation_type": conversation.get("conversation_type") or "",
            "display_name": conversation.get("display_name") or "",
        },
        "current_message": clip_msg(current),
        "recent_messages": [clip_msg(item) for item in recent[-MAX_RECENT_MESSAGES:]],
        "active_topics": [
            {
                "id": topic.get("id"),
                "title": topic.get("title") or "",
                "summary": str(topic.get("summary") or "")[:MAX_SUMMARY_CHARS],
                "status": topic.get("status") or "",
                "last_message_at": topic.get("last_message_at") or "",
                "message_count": int(topic.get("message_count") or 0),
            }
            for topic in topics[:MAX_CANDIDATES]
        ],
    }


def known_message_ids(engine_input: dict) -> set:
    ids = set()
    current = (engine_input.get("current_message") or {}).get("id")
    if current:
        ids.add(current)
    for item in engine_input.get("recent_messages") or []:
        if item.get("id"):
            ids.add(item["id"])
    return ids


def validate_extractor_output(output: dict, engine_input: dict) -> dict:
    decision = str((output or {}).get("decision") or "")
    if decision not in ALLOWED_DECISIONS:
        raise TopicExtractorError("INVALID_DECISION", "非法 decision", decision)
    topic_id = output.get("topic_id")
    active_ids = {item.get("id") for item in (engine_input.get("active_topics") or [])}
    current_id = (engine_input.get("current_message") or {}).get("id")
    allowed_msgs = known_message_ids(engine_input)
    evidence = list(output.get("evidence_message_ids") or [])
    for item in evidence:
        if item not in allowed_msgs:
            raise TopicExtractorError("INVALID_EVIDENCE_ID", "evidence 引用了未知 message id", item)
    if current_id and current_id not in evidence:
        raise TopicExtractorError("INVALID_EVIDENCE_ID", "evidence 必须包含当前消息", current_id)
    if decision == DECISION_NEW_TOPIC:
        if topic_id:
            raise TopicExtractorError("INVALID_TOPIC_ID", "NEW_TOPIC 不得携带 topic_id", str(topic_id))
        if not str(output.get("proposed_title") or "").strip():
            raise TopicExtractorError("INVALID_OUTPUT", "NEW_TOPIC 需要 proposed_title")
        output["topic_id"] = None
    elif decision in (DECISION_EXISTING_TOPIC, DECISION_TOPIC_UPDATE):
        if not topic_id or topic_id not in active_ids:
            raise TopicExtractorError("INVALID_TOPIC_ID", "topic_id 不在本次 active_topics 中", str(topic_id))
    elif decision == DECISION_UNRELATED:
        if topic_id:
            raise TopicExtractorError("INVALID_TOPIC_ID", "UNRELATED 不得携带 topic_id", str(topic_id))
        output["topic_id"] = None
    return output


class TopicEngine:
    def __init__(
        self,
        store: TopicStore,
        *,
        extractor=None,
        root_dir: str = "",
        conversations: Optional[list] = None,
        enabled: Optional[bool] = None,
        extractor_prompt_name: str = DEFAULT_EXTRACTOR_PROMPT_NAME,
        model: str = "INHERIT",
    ):
        self.store = store
        self.extractor = extractor if extractor is not None else TopicExtractorClient()
        self.root_dir = root_dir
        self.conversations = list(conversations or [])
        self.enabled = TOPIC_ENGINE_ENABLED if enabled is None else bool(enabled)
        self.extractor_prompt_name = extractor_prompt_name or DEFAULT_EXTRACTOR_PROMPT_NAME
        self.model = model or "INHERIT"

    def process_inbound(self, inbound: Any, conversations: Optional[list] = None) -> EngineResult:
        convs = list(conversations if conversations is not None else self.conversations)
        try:
            conversation = resolve_topic_conversation(inbound, convs)
            if conversation is None:
                self._audit(
                    {
                        "conversation_id": "",
                        "message_id": "",
                        "topic_decision": "",
                        "error": CONVERSATION_NOT_RESOLVED,
                        "content_preview": content_preview(_field(inbound, "content")),
                    }
                )
                return EngineResult(skipped=True, error_code=CONVERSATION_NOT_RESOLVED, error=CONVERSATION_NOT_RESOLVED)
            record = project_inbound_to_message_record(inbound, conversation["id"])
            return self.process_record(record, conversation)
        except Exception as exc:
            return self._isolate(exc, conversation_id="", message_id="")

    def process_record(self, record: dict, conversation: dict) -> EngineResult:
        if not self.enabled:
            return EngineResult(skipped=True, decision="DISABLED", isolated=True)
        started = time.perf_counter()
        message_id = str((record or {}).get("id") or "")
        conversation_id = str((conversation or {}).get("id") or (record or {}).get("conversation_id") or "")
        try:
            return self._process_record(record, conversation, started)
        except Exception as exc:
            return self._isolate(exc, conversation_id=conversation_id, message_id=message_id, started=started)

    def _process_record(self, record: dict, conversation: dict, started: float) -> EngineResult:
        cid = conversation["id"]
        saved = self.store.upsert_message(dict(record, conversation_id=cid))
        message_id = saved["id"]
        if self.store.has_successful_processing(cid, message_id):
            prev = self.store.get_processing(cid, message_id) or {}
            return EngineResult(
                skipped=True,
                replayed=True,
                decision=str(prev.get("decision") or ""),
                topic_id=prev.get("topic_id"),
                message_id=message_id,
                conversation_id=cid,
            )
        if str(saved.get("direction") or "").upper() == DIRECTION_OUTBOUND:
            return self._finalize(
                cid,
                saved,
                DECISION_SKIPPED,
                topic_id=None,
                reason="outbound_not_extracted",
                started=started,
            )
        pre = rule_prefilter(saved.get("content") or "")
        if pre:
            return self._finalize(cid, saved, pre, topic_id=None, reason="rule_prefilter", started=started)

        candidates = retrieve_candidate_topics(self.store, cid, saved, limit=MAX_CANDIDATES)
        recent = self.store.recent_messages(cid, limit=MAX_RECENT_MESSAGES, exclude_id=message_id)
        engine_input = build_extractor_input(conversation, saved, recent, candidates)
        prompt = resolve_extractor_prompt(self.extractor_prompt_name, root_dir=self.root_dir)
        raw = self.extractor.extract(engine_input, prompt.content)
        if not isinstance(raw, dict) or "decision" not in raw:
            raw = parse_extractor_json(raw if isinstance(raw, str) else json_dumps_safe(raw))
        validated = validate_extractor_output(raw, engine_input)
        topic_id = self._apply_decision(cid, saved, validated, candidates)
        return self._finalize(
            cid,
            saved,
            validated["decision"],
            topic_id=topic_id,
            evidence=validated.get("evidence_message_ids") or [],
            confidence=validated.get("confidence") or "",
            candidates=candidates,
            prompt=prompt,
            started=started,
            reason=validated.get("reason") or "",
        )

    def _apply_decision(self, conversation_id: str, message: dict, output: dict, candidates: list) -> Optional[str]:
        decision = output["decision"]
        now = message.get("created_at") or utc_now_iso()
        confidence = output.get("confidence") or "MEDIUM"
        if decision == DECISION_UNRELATED:
            return None
        if decision == DECISION_NEW_TOPIC:
            topic = self.store.create_topic(
                conversation_id,
                title=str(output.get("proposed_title") or "")[:MAX_TITLE_CHARS],
                summary=str(output.get("summary_update") or output.get("proposed_title") or "")[:500],
                created_msg_id=message["id"],
                confidence=confidence,
                created_at=now,
                last_message_at=now,
            )
            self.store.add_link(
                conversation_id,
                topic["id"],
                message["id"],
                RELATION_CREATED_BY,
                confidence=confidence,
                created_at=now,
            )
            known = {item.get("id") for item in self.store.list_messages(conversation_id)}
            for evidence_id in output.get("evidence_message_ids") or []:
                if evidence_id == message["id"] or evidence_id not in known:
                    continue
                self.store.add_link(
                    conversation_id,
                    topic["id"],
                    evidence_id,
                    RELATION_RELATED,
                    confidence=confidence,
                    created_at=now,
                )
            return topic["id"]
        topic_id = output.get("topic_id")
        relation = RELATION_UPDATED_BY if decision == DECISION_TOPIC_UPDATE else RELATION_RELATED
        self.store.add_link(
            conversation_id,
            topic_id,
            message["id"],
            relation,
            confidence=confidence,
            created_at=now,
        )
        fields = {"confidence": confidence, "last_message_at": now}
        if decision == DECISION_TOPIC_UPDATE:
            summary = str(output.get("summary_update") or "").strip()
            if summary:
                fields["summary"] = summary[:500]
        self.store.update_topic(conversation_id, topic_id, **fields)
        self.store.refresh_topic_message_count(conversation_id, topic_id, last_message_at=now)
        return topic_id

    def _finalize(
        self,
        conversation_id: str,
        message: dict,
        decision: str,
        *,
        topic_id=None,
        evidence=None,
        confidence="",
        candidates=None,
        prompt=None,
        started=None,
        reason="",
        error="",
    ) -> EngineResult:
        prompt_name = getattr(prompt, "prompt_name", "") if prompt is not None else self.extractor_prompt_name
        prompt_hash = getattr(prompt, "prompt_hash", "") if prompt is not None else ""
        self.store.write_processing(
            {
                "message_id": message["id"],
                "conversation_id": conversation_id,
                "topic_processing_version": DEFAULT_PROCESSING_VERSION,
                "extractor_prompt_name": prompt_name,
                "extractor_prompt_hash": prompt_hash,
                "decision": decision,
                "topic_id": topic_id,
                "error": error,
            }
        )
        latency_ms = int((time.perf_counter() - started) * 1000) if started is not None else 0
        self._audit(
            {
                "conversation_id": conversation_id,
                "message_id": message["id"],
                "topic_decision": decision,
                "topic_id": topic_id,
                "candidate_topic_ids": [item.get("id") for item in (candidates or [])],
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
        return EngineResult(
            decision=decision,
            topic_id=topic_id,
            message_id=message["id"],
            conversation_id=conversation_id,
            candidate_topic_ids=[item.get("id") for item in (candidates or [])],
            evidence_message_ids=list(evidence or []),
            confidence=confidence,
            error=error,
        )

    def _isolate(self, exc: Exception, *, conversation_id: str, message_id: str, started=None) -> EngineResult:
        code = getattr(exc, "code", None) or exc.__class__.__name__
        if isinstance(exc, PromptResolveError):
            code = exc.code
        if isinstance(exc, TopicExtractorError):
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
                        "decision": DECISION_FAILED,
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
                    "topic_decision": DECISION_FAILED,
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
            message_id=message_id,
            conversation_id=conversation_id,
            error=detail,
            error_code=code,
            isolated=True,
        )

    def _audit(self, event: dict) -> None:
        self.store.write_audit(event)


def json_dumps_safe(value) -> str:
    import json
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return "{}"


def engine_source_forbids_wechat_sidepath() -> bool:
    source = inspect.getsource(TopicEngine)
    source += inspect.getsource(resolve_topic_conversation)
    source += inspect.getsource(build_extractor_input)
    encoded = ("send_reply" + "(", "wx.SendMsg" + "(", "get_user_prompt" + "(", "resolve_chat_prompt" + "(")
    return all(token not in source for token in encoded)
