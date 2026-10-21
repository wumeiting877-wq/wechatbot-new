# -*- coding: utf-8 -*-
"""P5 Risk Extractor Client：独立 LLM 调用与独立 parser。

不得复用 topic_extractor_client.parse_extractor_json（会剥离 risks）。
不得复用 task / decision parser。
必须 store_context=false。不得走 Chat Prompt / chat_contexts。
离线主路径：HeuristicRiskExtractor。G4 生产路径使用 RiskExtractorClient + RISK_EXTRACTOR。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

ALLOWED_DECISIONS = ("NEW_RISK", "RISK_UPDATE", "UNRELATED")
FORBIDDEN_DECISIONS = (
    "RISK_RESOLVED",
    "MITIGATED",
    "RESOLVED",
    "CLOSED",
    "RISK_CLOSED",
    "INVALID",
    "NEW_TOPIC",
    "EXISTING_TOPIC",
    "TOPIC_UPDATE",
    "NEW_TASK",
    "TASK_UPDATE",
    "NEW_DECISION",
    "DECISION_UPDATE",
)
ALLOWED_CONFIDENCE = ("HIGH", "MEDIUM", "LOW")
ALLOWED_RISK_KEYS = {
    "decision",
    "risk_id",
    "title",
    "condition_text",
    "impact_text",
    "task_id",
    "confidence",
    "evidence_message_ids",
    "reason",
}
STRIP_KEYS = {
    "status",
    "severity",
    "severity_text",
    "owner",
    "owner_id",
    "owner_text",
    "due",
    "due_at",
    "due_text",
    "decision_id",
    "decision_ids",
    "decided_by",
    "mitigation_text",
    "tasks",
    "topics",
    "decisions",
    "description",
}
LIFECYCLE_DECISIONS = {
    "RISK_RESOLVED",
    "MITIGATED",
    "RESOLVED",
    "CLOSED",
    "RISK_CLOSED",
}

EXTRACTOR_TEMPERATURE = 0.2
EXTRACTOR_MAX_TOKENS = 1400
EXTRACTOR_TIMEOUT_SEC = 20
_TIMEOUT_FLAG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime_control",
    "RISK_EXTRACTOR_TIMEOUT_SEC",
)

_RECOVERY_MARKERS = ("已经恢复", "恢复了", "已经好了", "已经修好", "修好了")
_SUGGEST_START = re.compile(r"^(?:最好|建议|我建议)")
_VAGUE = re.compile(r"感觉有点危险|有点危险|有点担心|可能有风险")
_PROBLEM_MARKERS = ("失败了", "超时了", "报错了")
_TASK_ASSIGN = re.compile(
    r"^[\u4e00-\u9fff]{2,4}(?:今天|明天).{0,16}(?:准备|处理|做完|修好)"
)
_FUTURE_SEPS = ("会导致", "将会", "就会", "导致", "会", "将")
_IMPACT_MARKERS = ("影响", "无法", "受影响")


class RiskExtractorError(Exception):
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
    raw = str(os.environ.get("RISK_EXTRACTOR_TIMEOUT_SEC", "") or "").strip()
    if raw:
        try:
            return max(0.01, float(raw))
        except ValueError:
            pass
    return float(EXTRACTOR_TIMEOUT_SEC)


def parse_risk_extractor_json(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text:
        raise RiskExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise RiskExtractorError("JSON_PARSE_ERROR", "Extractor 输出不是 JSON 对象", text[:200])
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
        raise RiskExtractorError("JSON_PARSE_ERROR", "Extractor JSON 解析失败", str(exc))
    if not isinstance(data, dict):
        raise RiskExtractorError("JSON_PARSE_ERROR", "Extractor JSON 必须是对象")
    return normalize_risk_extractor_output(data)


def normalize_risk_extractor_output(data: dict) -> dict:
    payload = data if isinstance(data, dict) else {}
    if "risks" not in payload:
        raise RiskExtractorError("INVALID_OUTPUT", "缺少 risks")
    raw_risks = payload.get("risks")
    if not isinstance(raw_risks, list):
        raise RiskExtractorError("INVALID_OUTPUT", "risks 必须是数组")
    if len(raw_risks) < 1 or len(raw_risks) > 5:
        raise RiskExtractorError("INVALID_OUTPUT", "risks 必须是 1..5 条", str(len(raw_risks)))
    risks = [normalize_risk(item) for item in raw_risks]
    return {"risks": risks}


def normalize_risk(item: Any) -> dict:
    if not isinstance(item, dict):
        raise RiskExtractorError("INVALID_OUTPUT", "risk 必须是对象")
    data = dict(item)
    for key in list(data.keys()):
        if key in STRIP_KEYS or key not in ALLOWED_RISK_KEYS:
            data.pop(key, None)
    decision = str(data.get("decision") or "").strip().upper()
    if decision in LIFECYCLE_DECISIONS or decision in FORBIDDEN_DECISIONS:
        raise RiskExtractorError("INVALID_DECISION", "禁止改变 Risk 生命周期的 decision", decision)
    risk_id = data.get("risk_id")
    if risk_id == "" or risk_id is False:
        risk_id = None
    task_id = data.get("task_id")
    if task_id == "" or task_id is False or task_id is None:
        task_id = None
    evidence = data.get("evidence_message_ids") or []
    if not isinstance(evidence, list):
        evidence = []
    confidence = str(data.get("confidence") or "").strip().upper()
    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "LOW"
    return {
        "decision": decision,
        "risk_id": risk_id,
        "title": str(data.get("title") or "").strip(),
        "condition_text": str(data.get("condition_text") or "").strip(),
        "impact_text": str(data.get("impact_text") or "").strip(),
        "task_id": task_id,
        "confidence": confidence,
        "evidence_message_ids": [str(value) for value in evidence if value],
        "reason": str(data.get("reason") or "").strip(),
    }


class RiskExtractorClient:
    """Engine Input + RISK_EXTRACTOR Prompt + LLM → {risks: [...]}。

    必须 store_context=false。不得调用 resolve_chat_prompt / get_user_prompt。
    G3 离线主路径使用 Heuristic；G4 生产 / Real LLM 使用本 Client。
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
                        raise RiskExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空")
                    if "{" not in stripped:
                        raise RiskExtractorError(
                            "JSON_PARSE_ERROR",
                            "Extractor 输出不是 JSON 对象",
                            stripped[:200],
                        )
                if isinstance(raw, dict):
                    return normalize_risk_extractor_output(raw)
                return parse_risk_extractor_json(raw)
            except TimeoutError as exc:
                raise RiskExtractorError("EXTRACTOR_TIMEOUT", "Extractor LLM timeout", str(exc))
            except RiskExtractorError as exc:
                last_error = exc
                if exc.code not in ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY") or attempt == 1:
                    raise
            except Exception as exc:
                text = str(exc)
                if "EXTRACTOR_EMPTY" in text and attempt == 0:
                    last_error = RiskExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空", text[:200])
                    continue
                raise RiskExtractorError("EXTRACTOR_EXCEPTION", "Extractor LLM 调用失败", text[:300])
        raise last_error


def _default_extractor_llm_call(messages, **kwargs):
    from llm_client import get_extractor_response
    kwargs.setdefault("purpose", "risk_extractor")
    return get_extractor_response(messages, **kwargs)


def _unrelated(message_id: str, reason: str) -> dict:
    return {
        "risks": [
            {
                "decision": "UNRELATED",
                "risk_id": None,
                "title": "",
                "condition_text": "",
                "impact_text": "",
                "task_id": None,
                "confidence": "HIGH",
                "evidence_message_ids": [message_id] if message_id else [],
                "reason": reason,
            }
        ]
    }


def _is_recovery(content: str) -> bool:
    text = str(content or "").strip()
    return any(marker in text for marker in _RECOVERY_MARKERS)


def _is_suggestion_only(content: str) -> bool:
    text = str(content or "").strip()
    if _extract_condition_impact(text):
        return False
    return bool(_SUGGEST_START.match(text))


def _is_vague(content: str) -> bool:
    text = str(content or "").strip()
    if _extract_condition_impact(text):
        return False
    return bool(_VAGUE.search(text))


def _is_current_problem(content: str) -> bool:
    text = str(content or "").strip()
    if _extract_condition_impact(text):
        return False
    return any(marker in text for marker in _PROBLEM_MARKERS)


def _is_task_assignment_only(content: str) -> bool:
    text = str(content or "").strip()
    if _extract_condition_impact(text):
        return False
    return bool(_TASK_ASSIGN.search(text))


def _extract_condition_impact(content: str):
    text = str(content or "").strip()
    if not text:
        return None
    if_idx = text.find("如果")
    if if_idx < 0:
        if_idx = text.find("若")
    if if_idx < 0:
        return None
    rest = text[if_idx:]
    comma = re.match(r"(如果|若)([^，,]{2,80})[，,](.+)$", rest)
    if comma and any(marker in comma.group(3) for marker in _IMPACT_MARKERS):
        condition = (text[:if_idx] + comma.group(1) + comma.group(2)).strip().rstrip("，,")
        impact = comma.group(3).strip()
        if condition and impact:
            return condition, impact
    for sep in _FUTURE_SEPS:
        pos = rest.find(sep)
        if pos < 0:
            continue
        left = (text[:if_idx] + rest[:pos]).strip().rstrip("，,")
        right = rest[pos:].strip()
        if not left or not any(marker in right for marker in _IMPACT_MARKERS):
            continue
        if left and right:
            return left, right
    return None


def _title_for(condition: str, impact: str) -> str:
    cond = re.sub(r"^(如果|若)", "", str(condition or "")).strip(" ，,")
    impact_text = str(impact or "").strip(" 。.？?！!")
    title = ("%s将%s" % (cond, impact_text)).replace("会会", "会")
    title = re.sub(r"\s+", "", title)
    if not title:
        return "明确未来不利结果"[:40]
    return title[:40]


def _match_existing(existing: list, condition: str, impact: str):
    blob = "%s %s" % (condition or "", impact or "")
    concern_tokens = ("修不好", "断网", "处理不完", "Wi-Fi", "wifi", "WIFI")
    impact_tokens = ("演示", "回归", "无法")
    blob_concern = [token for token in concern_tokens if token.lower() in blob.lower()]
    blob_impact = [token for token in impact_tokens if token in blob]
    if not blob_concern or not blob_impact:
        return None
    for item in existing:
        existing_blob = "%s %s %s" % (
            item.get("condition_text") or "",
            item.get("impact_text") or "",
            item.get("title") or "",
        )
        if any(token.lower() in existing_blob.lower() for token in blob_concern) and any(
            token in existing_blob for token in blob_impact
        ):
            return item
    return None


def _safe_task_id(engine_input: dict, content: str):
    candidates = list((engine_input or {}).get("candidate_tasks") or [])
    if not candidates:
        return None
    for item in candidates:
        task_id = str((item or {}).get("id") or "")
        assignee = str((item or {}).get("assignee_text") or "")
        if task_id and assignee and assignee in (content or ""):
            return task_id
    return None


class HeuristicRiskExtractor:
    """离线确定性 Extractor，供 fixture 红线。生产默认走 RiskExtractorClient（G4）。禁止接入微信。"""

    def extract(self, engine_input: dict, prompt_content: str) -> dict:
        current = (engine_input or {}).get("current_message") or {}
        content = str(current.get("content") or "")
        current_id = str(current.get("id") or "")
        existing = list((engine_input or {}).get("existing_risks") or [])
        stripped = content.strip()

        if _is_recovery(stripped):
            return _unrelated(current_id, "已恢复不是 RESOLVED")
        if _is_suggestion_only(stripped):
            return _unrelated(current_id, "建议不是 Risk")
        if _is_vague(stripped):
            return _unrelated(current_id, "模糊担忧不是 Risk")
        if _is_current_problem(stripped):
            return _unrelated(current_id, "当前问题不是 Risk")
        if _is_task_assignment_only(stripped):
            return _unrelated(current_id, "Task 指令不是 Risk")

        extracted = _extract_condition_impact(stripped)
        if not extracted:
            return _unrelated(current_id, "缺少明确 condition + impact")

        condition, impact = extracted
        matched = _match_existing(existing, condition, impact)
        task_id = _safe_task_id(engine_input, stripped)
        evidence = [current_id] if current_id else []
        if matched:
            return {
                "risks": [
                    {
                        "decision": "RISK_UPDATE",
                        "risk_id": matched.get("id"),
                        "title": _title_for(condition, impact),
                        "condition_text": condition[:500],
                        "impact_text": impact[:500],
                        "task_id": task_id,
                        "confidence": "HIGH",
                        "evidence_message_ids": evidence,
                        "reason": "heuristic RISK_UPDATE",
                    }
                ]
            }
        return {
            "risks": [
                {
                    "decision": "NEW_RISK",
                    "risk_id": None,
                    "title": _title_for(condition, impact),
                    "condition_text": condition[:500],
                    "impact_text": impact[:500],
                    "task_id": task_id,
                    "confidence": "HIGH",
                    "evidence_message_ids": evidence,
                    "reason": "heuristic NEW_RISK",
                }
            ]
        }
