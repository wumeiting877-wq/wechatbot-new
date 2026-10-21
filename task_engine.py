# -*- coding: utf-8 -*-
"""P4 Task Engine 离线流水线。

给定已形成的 Topic 与已入库的 Message Evidence，抽取工作事项。
不接入 message/listener.py，不修改 topic_engine。
P4-G2 由 topic_sidepath 在 Topic 成功后非阻塞投递；本模块仍不调用 send_reply / wx.SendMsg。
失败隔离在本模块边界内，不影响 Topic / Chat。
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from agent_store import PromptResolveError, resolve_extractor_prompt
from conversation_store import utc_now_iso
from task_extractor_client import (
    ALLOWED_DECISIONS,
    TaskExtractorClient,
    TaskExtractorError,
    has_self_action,
    normalize_task_extractor_output,
    parse_task_extractor_json,
)
from task_store import (
    DECISION_FAILED,
    DECISION_NEW_TASK,
    DECISION_SKIPPED,
    DECISION_TASK_UPDATE,
    DECISION_UNRELATED,
    DEFAULT_PROCESSING_VERSION,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    RELATION_UPDATED_BY,
    TASK_STATUS_OPEN,
    TaskStore,
    TaskStoreError,
    content_preview,
    make_task_id,
    make_tlink_id,
)
from topic_store import DIRECTION_OUTBOUND, TopicStore, TopicStoreError

TASK_ENGINE_ENABLED = False
TASK_EXTRACTOR_PROMPT_NAME = "TASK_EXTRACTOR"
MAX_RECENT_TOPIC_MESSAGES = 12
MAX_EXISTING_TASKS = 10
MAX_CONTENT_CHARS = 800
MAX_TITLE_CHARS = 40
MAX_DESCRIPTION_CHARS = 500

ACKNOWLEDGEMENTS = {"收到", "好的", "嗯", "1", "ok", "OK", "谢谢", "收到收到"}
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
    task_ids: list = field(default_factory=list)
    error: str = ""
    error_code: str = ""
    evidence_message_ids: list = field(default_factory=list)
    confidence: str = ""
    isolated: bool = True
    replayed: bool = False
    new_task_count: int = 0
    update_count: int = 0

    def as_dict(self) -> dict:
        return {
            "skipped": self.skipped,
            "decision": self.decision,
            "decision_summary": self.decision_summary,
            "topic_id": self.topic_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "task_ids": list(self.task_ids),
            "error": self.error,
            "error_code": self.error_code,
            "evidence_message_ids": list(self.evidence_message_ids),
            "confidence": self.confidence,
            "isolated": self.isolated,
            "replayed": self.replayed,
            "new_task_count": self.new_task_count,
            "update_count": self.update_count,
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


def input_content_blob(engine_input: dict) -> str:
    parts = []
    current = engine_input.get("current_message") or {}
    parts.append(str(current.get("content") or ""))
    for item in engine_input.get("recent_topic_messages") or []:
        parts.append(str(item.get("content") or ""))
    return "\n".join(parts)


def assignee_is_valid(assignee_text: str, engine_input: dict) -> bool:
    value = str(assignee_text or "").strip()
    if not value:
        return True
    blob = input_content_blob(engine_input)
    if value in blob:
        return True
    current = engine_input.get("current_message") or {}
    sender = str(current.get("sender_name") or "")
    if value == sender and has_self_action(str(current.get("content") or "")):
        return True
    return False


def build_extractor_input(
    conversation: dict,
    topic: dict,
    current: dict,
    recent: list,
    existing_tasks: list,
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
        "existing_tasks": [
            {
                "id": item.get("id"),
                "title": item.get("title") or "",
                "description": item.get("description") or "",
                "assignee_text": item.get("assignee_text") or "",
                "due_text": item.get("due_text") or "",
                "status": item.get("status") or TASK_STATUS_OPEN,
                "confidence": item.get("confidence") or "",
            }
            for item in existing_tasks[:MAX_EXISTING_TASKS]
        ],
    }


def validate_task_decisions(output: dict, engine_input: dict) -> list:
    payload = output if isinstance(output, dict) else {}
    if "decisions" not in payload:
        payload = normalize_task_extractor_output(payload) if isinstance(payload, dict) else payload
    decisions = list(payload.get("decisions") or [])
    if len(decisions) < 1 or len(decisions) > 5:
        raise TaskExtractorError("INVALID_OUTPUT", "decisions 必须是 1..5 条", str(len(decisions)))
    existing_ids = {item.get("id") for item in (engine_input.get("existing_tasks") or [])}
    current_id = (engine_input.get("current_message") or {}).get("id")
    allowed_msgs = known_message_ids(engine_input)
    validated = []
    for item in decisions:
        decision = str((item or {}).get("decision") or "")
        if decision not in ALLOWED_DECISIONS:
            raise TaskExtractorError("INVALID_DECISION", "非法 decision", decision)
        task_id = item.get("task_id")
        evidence = list(item.get("evidence_message_ids") or [])
        for msg_id in evidence:
            if msg_id not in allowed_msgs:
                raise TaskExtractorError("INVALID_EVIDENCE_ID", "evidence 引用了未知 message id", msg_id)
        if current_id and current_id not in evidence:
            raise TaskExtractorError("INVALID_EVIDENCE_ID", "evidence 必须包含当前消息", str(current_id))
        assignee = str(item.get("assignee_text") or "").strip()
        if not assignee_is_valid(assignee, engine_input):
            raise TaskExtractorError("INVALID_ASSIGNEE", "assignee_text 必须来自原文或自称发送者", assignee)
        if decision == DECISION_NEW_TASK:
            if task_id:
                raise TaskExtractorError("INVALID_TASK_ID", "NEW_TASK 不得携带 task_id", str(task_id))
            if not str(item.get("title") or "").strip():
                raise TaskExtractorError("INVALID_OUTPUT", "NEW_TASK 需要 title")
            if not assignee:
                raise TaskExtractorError("INVALID_ASSIGNEE", "NEW_TASK 必须有负责人", "")
            item["task_id"] = None
        elif decision == DECISION_TASK_UPDATE:
            if not task_id or task_id not in existing_ids:
                raise TaskExtractorError("INVALID_TASK_ID", "task_id 不在本次 existing_tasks 中", str(task_id))
        elif decision == DECISION_UNRELATED:
            if task_id:
                raise TaskExtractorError("INVALID_TASK_ID", "UNRELATED 不得携带 task_id", str(task_id))
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


class TaskEngine:
    def __init__(
        self,
        store: TaskStore,
        topic_store: TopicStore,
        *,
        extractor=None,
        root_dir: str = "",
        enabled: Optional[bool] = None,
        extractor_prompt_name: str = TASK_EXTRACTOR_PROMPT_NAME,
        model: str = "INHERIT",
    ):
        self.store = store
        self.topic_store = topic_store
        self.extractor = extractor if extractor is not None else TaskExtractorClient()
        self.root_dir = root_dir
        self.enabled = TASK_ENGINE_ENABLED if enabled is None else bool(enabled)
        self.extractor_prompt_name = extractor_prompt_name or TASK_EXTRACTOR_PROMPT_NAME
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
            raise TaskStoreError("INVALID_CONVERSATION_ID", "缺少 conversation.id")
        stored_topic = self.store.require_topic(cid, topic_id)
        saved = self.topic_store.get_message(cid, str((message or {}).get("id") or ""))
        if saved is None:
            raise TaskStoreError("MESSAGE_NOT_FOUND", "MessageRecord 不存在，禁止猜 Topic / 写 Task")
        message_id = saved["id"]
        if str(saved.get("conversation_id") or "") != cid:
            raise TaskStoreError("MESSAGE_CONVERSATION_MISMATCH", "Message 不属于当前 Conversation")
        if str(stored_topic.get("conversation_id") or "") != cid:
            raise TaskStoreError("TOPIC_CONVERSATION_MISMATCH", "Topic 不属于当前 Conversation")
        if not message_belongs_to_topic(self.topic_store, cid, topic_id, message_id):
            raise TaskStoreError("TOPIC_EVIDENCE_MISSING", "当前 Message 没有 Topic Evidence，禁止抽 Task")

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
                task_ids=list(prev.get("task_ids") or []),
            )
        if str(saved.get("direction") or "").upper() == DIRECTION_OUTBOUND:
            return self._finalize(
                cid,
                saved,
                stored_topic,
                [DECISION_SKIPPED],
                task_ids=[],
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
                task_ids=[],
                reason="rule_prefilter",
                started=started,
            )

        existing = self.store.list_open_tasks(
            cid,
            topic_id,
            limit=MAX_EXISTING_TASKS,
            content=str(saved.get("content") or ""),
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
            parsed = normalize_task_extractor_output(raw)
        else:
            parsed = parse_task_extractor_json(raw if isinstance(raw, str) else json_dumps_safe(raw))
        validated = validate_task_decisions(parsed, engine_input)
        applied = self._apply_decisions(cid, stored_topic, saved, validated, existing)
        result = self._finalize(
            cid,
            saved,
            stored_topic,
            [item["decision"] for item in validated],
            task_ids=applied["task_ids"],
            evidence=_all_evidence(validated),
            confidence=_primary_confidence(validated),
            prompt=prompt,
            started=started,
            reason=";".join(item.get("reason") or "" for item in validated),
            new_task_count=applied["new_task_count"],
            update_count=applied["update_count"],
        )
        self._attach_identity_links(cid, applied)
        return result

    def _attach_identity_links(self, conversation_id: str, applied: dict) -> None:
        """Task 成功语义已经写完。链接失败留在这里，不回滚 Task。"""
        try:
            from task_identity_link import attach_exact_links_for_created_tasks, note_assignee_text_drift

            note_assignee_text_drift(self.store, conversation_id, applied.get("assignee_drifts") or [])
            attach_exact_links_for_created_tasks(
                self.store,
                conversation_id,
                applied.get("created_task_ids") or [],
            )
        except Exception:
            return

    def _apply_decisions(self, conversation_id: str, topic: dict, message: dict, decisions: list, existing: list) -> dict:
        now = utc_now_iso()
        created_at_seed = str(message.get("created_at") or now)
        new_tasks = []
        updates = []
        new_links = []
        assignee_drifts = []
        new_count = 0
        update_count = 0
        ordinal = 0
        before_ids = {item.get("id") for item in self.store.list_tasks(conversation_id)}
        existing_by_id = {item.get("id"): item for item in existing}
        known_msgs = {item.get("id") for item in self.topic_store.list_messages(conversation_id)}
        for item in decisions:
            decision = item["decision"]
            confidence = item.get("confidence") or "MEDIUM"
            if decision == DECISION_UNRELATED:
                continue
            if decision == DECISION_NEW_TASK:
                task_id = make_task_id(
                    conversation_id,
                    topic["id"],
                    message["id"],
                    ordinal,
                    created_at_seed,
                )
                task = {
                    "id": task_id,
                    "conversation_id": conversation_id,
                    "topic_id": topic["id"],
                    "title": str(item.get("title") or "")[:MAX_TITLE_CHARS],
                    "description": str(item.get("description") or "")[:MAX_DESCRIPTION_CHARS],
                    "status": TASK_STATUS_OPEN,
                    "assignee_text": str(item.get("assignee_text") or "").strip(),
                    "due_text": str(item.get("due_text") or "").strip(),
                    "due_at": "",
                    "created_msg_id": message["id"],
                    "confidence": confidence,
                    "created_at": now,
                    "updated_at": now,
                    "schema_version": 1,
                }
                new_tasks.append(task)
                new_links.append(
                    {
                        "id": make_tlink_id(task_id, message["id"], RELATION_CREATED_BY),
                        "task_id": task_id,
                        "message_id": message["id"],
                        "relation": RELATION_CREATED_BY,
                        "confidence": confidence,
                        "created_at": now,
                    }
                )
                for evidence_id in item.get("evidence_message_ids") or []:
                    if evidence_id == message["id"] or evidence_id not in known_msgs:
                        continue
                    new_links.append(
                        {
                            "id": make_tlink_id(task_id, evidence_id, RELATION_RELATED),
                            "task_id": task_id,
                            "message_id": evidence_id,
                            "relation": RELATION_RELATED,
                            "confidence": confidence,
                            "created_at": now,
                        }
                    )
                new_count += 1
                ordinal += 1
                continue
            if decision == DECISION_TASK_UPDATE:
                target_id = item.get("task_id")
                current = existing_by_id.get(target_id) or self.store.get_task(conversation_id, target_id) or {}
                fields = {"confidence": confidence}
                title = str(item.get("title") or "").strip()
                description = str(item.get("description") or "").strip()
                assignee = str(item.get("assignee_text") or "").strip()
                due_text = str(item.get("due_text") or "").strip()
                if title:
                    fields["title"] = title[:MAX_TITLE_CHARS]
                if description:
                    fields["description"] = description[:MAX_DESCRIPTION_CHARS]
                if assignee:
                    fields["assignee_text"] = assignee
                    previous = str(current.get("assignee_text") or "").strip()
                    if assignee != previous:
                        assignee_drifts.append({"task_id": target_id})
                if due_text:
                    fields["due_text"] = due_text
                updates.append({"id": target_id, "fields": fields, "updated_at": now})
                new_links.append(
                    {
                        "id": make_tlink_id(target_id, message["id"], RELATION_UPDATED_BY),
                        "task_id": target_id,
                        "message_id": message["id"],
                        "relation": RELATION_UPDATED_BY,
                        "confidence": confidence,
                        "created_at": now,
                    }
                    )
                update_count += 1
                _ = current
        applied_commit = self.store.commit_apply(
            conversation_id,
            new_tasks=new_tasks,
            updates=updates,
            new_links=new_links,
        )
        created_task_ids = []
        seen_created = set()
        for task_id in applied_commit.get("task_ids") or []:
            if task_id in before_ids or task_id in seen_created:
                continue
            seen_created.add(task_id)
            created_task_ids.append(task_id)
        return {
            "task_ids": list(applied_commit.get("task_ids") or []),
            "new_task_count": new_count,
            "update_count": update_count,
            "created_task_ids": created_task_ids,
            "assignee_drifts": assignee_drifts,
        }

    def _finalize(
        self,
        conversation_id: str,
        message: dict,
        topic: dict,
        decisions: list,
        *,
        task_ids=None,
        evidence=None,
        confidence="",
        prompt=None,
        started=None,
        reason="",
        error="",
        new_task_count=0,
        update_count=0,
    ) -> EngineResult:
        prompt_name = getattr(prompt, "prompt_name", "") if prompt is not None else self.extractor_prompt_name
        prompt_hash = getattr(prompt, "prompt_hash", "") if prompt is not None else ""
        summary = ",".join(decisions) if decisions else DECISION_UNRELATED
        self.store.write_processing(
            {
                "message_id": message["id"],
                "conversation_id": conversation_id,
                "topic_id": topic.get("id"),
                "task_processing_version": DEFAULT_PROCESSING_VERSION,
                "extractor_prompt_name": prompt_name,
                "extractor_prompt_hash": prompt_hash,
                "decision_summary": summary,
                "task_ids": list(task_ids or []),
                "error": error,
            }
        )
        latency_ms = int((time.perf_counter() - started) * 1000) if started is not None else 0
        self._audit(
            {
                "conversation_id": conversation_id,
                "message_id": message["id"],
                "task_decision": summary,
                "topic_id": topic.get("id"),
                "task_ids": list(task_ids or []),
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
            task_ids=list(task_ids or []),
            evidence_message_ids=list(evidence or []),
            confidence=confidence,
            error=error,
            new_task_count=new_task_count,
            update_count=update_count,
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
        if isinstance(exc, TaskExtractorError):
            code = exc.code
        if isinstance(exc, TaskStoreError):
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
                    "task_decision": DECISION_FAILED,
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
    import task_extractor_client
    import task_store

    source = inspect.getsource(TaskEngine)
    source += inspect.getsource(build_extractor_input)
    source += inspect.getsource(task_extractor_client)
    source += inspect.getsource(task_store)
    encoded = ("send_reply" + "(", "wx.SendMsg" + "(", "SendMsg" + "(", "get_user_prompt" + "(", "resolve_chat_prompt" + "(")
    return all(token not in source for token in encoded)
