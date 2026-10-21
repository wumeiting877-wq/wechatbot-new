# -*- coding: utf-8 -*-
"""P5 Decision Extractor Client：独立 LLM 调用与独立 parser。

不得复用 topic_extractor_client.parse_extractor_json（会剥离 decisions）。
不得复用 task_extractor_client 的 parser。
必须 store_context=false。不得走 Chat Prompt / chat_contexts。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

ALLOWED_DECISIONS = ("NEW_DECISION", "UNRELATED")
FORBIDDEN_DECISIONS = (
    "DECISION_UPDATE",
    "SUPERSEDED",
    "CANCELLED",
    "INVALID",
    "NEW_TOPIC",
    "EXISTING_TOPIC",
    "TOPIC_UPDATE",
    "NEW_TASK",
    "TASK_UPDATE",
    "NEW_RISK",
    "RISK_UPDATE",
)
ALLOWED_CONFIDENCE = ("HIGH", "MEDIUM", "LOW")
ALLOWED_DECISION_KEYS = {
    "decision",
    "decision_id",
    "supersedes_decision_id",
    "title",
    "decision_text",
    "confidence",
    "evidence_message_ids",
    "reason",
}
STRIP_KEYS = {
    "status",
    "task_id",
    "severity",
    "risk_id",
    "risk_ids",
    "owner",
    "assignee",
    "assignee_text",
    "due",
    "due_text",
    "due_at",
    "tasks",
    "topics",
    "risks",
    "summary",
}
LIFECYCLE_DECISIONS = {"DECISION_UPDATE", "SUPERSEDED", "CANCELLED", "INVALID"}

EXTRACTOR_TEMPERATURE = 0.2
EXTRACTOR_MAX_TOKENS = 1400
EXTRACTOR_TIMEOUT_SEC = 20
_TIMEOUT_FLAG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime_control",
    "DECISION_EXTRACTOR_TIMEOUT_SEC",
)

_CONFIRM_MARKERS = (
    "那就这么定",
    "这么定",
    "就按照",
    "按照这个方案",
    "方案确定",
    "这个方案确定",
    "方案改了",
)
_TASK_ASSIGN = re.compile(
    r"[\u4e00-\u9fff]{2,4}(?:今天|明天).{0,16}(?:\d{1,2}\s*点前|之前).{0,16}(?:处理|做完|修好|准备)"
)
_PROBLEM_MARKERS = ("失败了", "超时了", "报错了")
_SUGGEST_START = re.compile(r"^(?:我)?建议")


class DecisionExtractorError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


def _extractor_timeout_sec() -> float:
    try:
        if os.path.isfile(_TIMEOUT_FLAG):
            with open(_TIMEOUT_FLAG, "r", encoding="utf-8") as handle:
                return max(0.01, float(handle.read().strip() or EXTRACTOR_TIMEOUT_SEC))
    except (OSError, ValueError):
        pass
    raw = str(os.environ.get("DECISION_EXTRACTOR_TIMEOUT_SEC", "") or "").strip()
    if raw:
        try:
            return max(0.01, float(raw))
        except ValueError:
            pass
    return float(EXTRACTOR_TIMEOUT_SEC)


def parse_decision_extractor_json(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text:
        raise DecisionExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise DecisionExtractorError("JSON_PARSE_ERROR", "Extractor 输出不是 JSON 对象", text[:200])
        text = text[start : end + 1]
    text = (
        text.replace(": None", ": null")
        .replace(":None", ": null")
        .replace(": True", ": true")
        .replace(":True", ": true")
        .replace(": False", ": false")
        .replace(":False", ": false")
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecisionExtractorError("JSON_PARSE_ERROR", "Extractor JSON 解析失败", str(exc))
    if not isinstance(data, dict):
        raise DecisionExtractorError("JSON_PARSE_ERROR", "Extractor JSON 必须是对象")
    return normalize_decision_extractor_output(data)


def normalize_decision_extractor_output(data: dict) -> dict:
    payload = data if isinstance(data, dict) else {}
    if "decisions" not in payload:
        raise DecisionExtractorError("INVALID_OUTPUT", "缺少 decisions")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise DecisionExtractorError("INVALID_OUTPUT", "decisions 必须是数组")
    if len(raw_decisions) < 1 or len(raw_decisions) > 5:
        raise DecisionExtractorError("INVALID_OUTPUT", "decisions 必须是 1..5 条", str(len(raw_decisions)))
    decisions = [normalize_decision(item) for item in raw_decisions]
    return {"decisions": decisions}


def normalize_decision(item: Any) -> dict:
    if not isinstance(item, dict):
        raise DecisionExtractorError("INVALID_OUTPUT", "decision 必须是对象")
    data = dict(item)
    for key in list(data.keys()):
        if key in STRIP_KEYS or key not in ALLOWED_DECISION_KEYS:
            data.pop(key, None)
    decision = str(data.get("decision") or "").strip().upper()
    if decision in LIFECYCLE_DECISIONS or decision in FORBIDDEN_DECISIONS:
        raise DecisionExtractorError("INVALID_DECISION", "禁止改变 Decision 生命周期的 decision", decision)
    decision_id = data.get("decision_id")
    if decision_id == "" or decision_id is False:
        decision_id = None
    supersedes = data.get("supersedes_decision_id")
    if supersedes == "" or supersedes is False:
        supersedes = None
    evidence = data.get("evidence_message_ids") or []
    if not isinstance(evidence, list):
        evidence = []
    confidence = str(data.get("confidence") or "").strip().upper()
    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "LOW"
    return {
        "decision": decision,
        "decision_id": decision_id,
        "supersedes_decision_id": supersedes,
        "title": str(data.get("title") or "").strip(),
        "decision_text": str(data.get("decision_text") or "").strip(),
        "confidence": confidence,
        "evidence_message_ids": [str(value) for value in evidence if value],
        "reason": str(data.get("reason") or "").strip(),
    }


class DecisionExtractorClient:
    """Engine Input + DECISION_EXTRACTOR Prompt + LLM → {decisions: [...]}。

    必须 store_context=false。不得调用 resolve_chat_prompt / get_user_prompt。
    """

    def __init__(self, llm_call: Optional[Callable] = None, model: str = ""):
        self.llm_call = llm_call
        self.model = model or "INHERIT"
        self.last_latency_ms = 0
        self.last_model = self.model

    def extract(self, engine_input: dict, prompt_content: str) -> dict:
        llm_call = self.llm_call if self.llm_call is not None else _default_extractor_llm_call
        payload = json.dumps(engine_input, ensure_ascii=False)
        messages = [
            {"role": "system", "content": prompt_content},
            {"role": "user", "content": payload},
        ]
        last_error = None
        for attempt in range(2):
            try:
                raw = llm_call(
                    messages,
                    temperature=EXTRACTOR_TEMPERATURE,
                    max_tokens=EXTRACTOR_MAX_TOKENS,
                    timeout=_extractor_timeout_sec(),
                    store_context=False,
                    model=self.model,
                )
                if isinstance(raw, str):
                    stripped = raw.strip()
                    if not stripped:
                        raise DecisionExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空")
                    if "{" not in stripped:
                        raise DecisionExtractorError(
                            "JSON_PARSE_ERROR",
                            "Extractor 输出不是 JSON 对象",
                            stripped[:200],
                        )
                if isinstance(raw, dict):
                    return normalize_decision_extractor_output(raw)
                return parse_decision_extractor_json(raw)
            except TimeoutError as exc:
                raise DecisionExtractorError("EXTRACTOR_TIMEOUT", "Extractor LLM timeout", str(exc))
            except DecisionExtractorError as exc:
                last_error = exc
                if exc.code not in ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY") or attempt == 1:
                    raise
            except Exception as exc:
                text = str(exc)
                if "EXTRACTOR_EMPTY" in text and attempt == 0:
                    last_error = DecisionExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空", text[:200])
                    continue
                raise DecisionExtractorError("EXTRACTOR_EXCEPTION", "Extractor LLM 调用失败", text[:300])
        raise last_error


def _default_extractor_llm_call(messages, **kwargs):
    from llm_client import get_extractor_response
    kwargs.setdefault("purpose", "decision_extractor")
    return get_extractor_response(messages, **kwargs)


def _unrelated(message_id: str, reason: str) -> dict:
    return {
        "decisions": [
            {
                "decision": "UNRELATED",
                "decision_id": None,
                "supersedes_decision_id": None,
                "title": "",
                "decision_text": "",
                "confidence": "HIGH",
                "evidence_message_ids": [message_id] if message_id else [],
                "reason": reason,
            }
        ]
    }


def _new_decision(
    *,
    message_id: str,
    title: str,
    decision_text: str,
    evidence_message_ids=None,
    supersedes_decision_id=None,
    reason: str = "heuristic",
) -> dict:
    evidence = list(evidence_message_ids or [])
    if message_id and message_id not in evidence:
        evidence.insert(0, message_id)
    return {
        "decision": "NEW_DECISION",
        "decision_id": None,
        "supersedes_decision_id": supersedes_decision_id,
        "title": title[:40],
        "decision_text": decision_text[:500],
        "confidence": "HIGH",
        "evidence_message_ids": evidence,
        "reason": reason,
    }


def is_confirmation(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _CONFIRM_MARKERS):
        if "就按照" in text and "执行" not in text and "这么定" not in text:
            return False
        return True
    if re.search(r"就按.{0,20}执行", text):
        return True
    if "按照" in text and "方案" in text and "执行" in text:
        return True
    if "改成" in text and ("同步" in text or "方案" in text):
        return True
    if re.search(r"决定(?:采用|使用|先用)", text):
        return True
    return False


def _is_suggestion_only(content: str) -> bool:
    text = str(content or "").strip()
    if _SUGGEST_START.match(text) and not is_confirmation(text):
        return True
    return False


def _is_task_assignment_only(content: str) -> bool:
    text = str(content or "").strip()
    if is_confirmation(text):
        return False
    return bool(_TASK_ASSIGN.search(text))


def _is_problem_fact(content: str) -> bool:
    text = str(content or "").strip()
    if is_confirmation(text):
        return False
    return any(marker in text for marker in _PROBLEM_MARKERS)


def _title_for(current: str, recent_blob: str) -> str:
    blob = "%s\n%s" % (current, recent_blob)
    if "异常池" in blob:
        return "采用异常池方案"
    if "demo-viewer" in blob:
        return "现场演示使用 demo-viewer 账号"
    if "全量同步" in current:
        return "改用全量同步"
    if "增量同步" in current:
        return "采用增量同步"
    trimmed = re.sub(r"[。.?？!！]+$", "", current).strip()
    return (trimmed or "确认方案")[:40]


def _decision_text_for(current: str, recent: list) -> str:
    text = str(current or "").strip()
    scheme_tokens = ("异常池", "demo-viewer", "全量同步", "增量同步")
    if any(token in text for token in scheme_tokens):
        return text[:500]
    for item in recent:
        content = str((item or {}).get("content") or "")
        if any(token in content for token in scheme_tokens) or "建议" in content or "方案" in content:
            combined = ("%s %s" % (content.strip(), text)).strip()
            return combined[:500]
    return text[:500]


def _evidence_ids(current_id: str, recent: list, current_content: str) -> list:
    ids = [current_id] if current_id else []
    for item in recent:
        msg_id = str((item or {}).get("id") or "")
        content = str((item or {}).get("content") or "")
        if not msg_id or msg_id in ids:
            continue
        if "建议" in content or "方案" in content or "决定" in content:
            ids.append(msg_id)
    return ids


class HeuristicDecisionExtractor:
    """离线确定性 Extractor，供 fixture 红线。生产默认走 DecisionExtractorClient。禁止接入微信。"""

    def extract(self, engine_input: dict, prompt_content: str) -> dict:
        current = (engine_input or {}).get("current_message") or {}
        content = str(current.get("content") or "")
        current_id = str(current.get("id") or "")
        recent = list((engine_input or {}).get("recent_topic_messages") or [])
        existing = list((engine_input or {}).get("existing_decisions") or [])
        stripped = content.strip()

        if _is_suggestion_only(stripped):
            return _unrelated(current_id, "建议不是 Decision")
        if _is_problem_fact(stripped):
            return _unrelated(current_id, "问题事实不是 Decision")
        if _is_task_assignment_only(stripped):
            return _unrelated(current_id, "Task 指派不是 Decision")
        if not is_confirmation(stripped):
            return _unrelated(current_id, "无明确确认结构")

        recent_blob = "\n".join(str(item.get("content") or "") for item in recent)
        title = _title_for(stripped, recent_blob)
        decision_text = _decision_text_for(stripped, recent)
        supersedes = None
        if existing and ("方案改了" in stripped or "改成" in stripped or "改为" in stripped):
            supersedes = existing[0].get("id")
        return {
            "decisions": [
                _new_decision(
                    message_id=current_id,
                    title=title,
                    decision_text=decision_text,
                    evidence_message_ids=_evidence_ids(current_id, recent, stripped),
                    supersedes_decision_id=supersedes,
                    reason="heuristic NEW_DECISION",
                )
            ]
        }
