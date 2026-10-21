# -*- coding: utf-8 -*-
"""P4 Task Extractor Client：独立 LLM 调用与独立 parser。

不得复用 topic_extractor_client.parse_extractor_json（会剥离 assignee/due）。
必须 store_context=false。不得走 Chat Prompt / chat_contexts。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

ALLOWED_DECISIONS = ("NEW_TASK", "TASK_UPDATE", "UNRELATED")
FORBIDDEN_DECISIONS = ("TASK_COMPLETE", "DONE", "IN_PROGRESS", "CANCELLED", "NEW_TOPIC", "EXISTING_TOPIC")
ALLOWED_CONFIDENCE = ("HIGH", "MEDIUM", "LOW")
ALLOWED_DECISION_KEYS = {
    "decision",
    "task_id",
    "title",
    "description",
    "assignee_text",
    "due_text",
    "confidence",
    "evidence_message_ids",
    "reason",
}
STRIP_KEYS = {
    "due_at",
    "assignee_id",
    "assignee_wxid",
    "assignee_type",
    "assignee",
    "status",
    "DONE",
    "TASK_COMPLETE",
    "risks",
    "progress",
    "progress_percent",
    "reminder",
    "tasks",
    "owner",
    "daily_report",
}
LIFECYCLE_KEYS = {"DONE", "TASK_COMPLETE", "status"}

EXTRACTOR_TEMPERATURE = 0.2
EXTRACTOR_MAX_TOKENS = 1600
EXTRACTOR_TIMEOUT_SEC = 20
_TIMEOUT_FLAG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime_control",
    "TASK_EXTRACTOR_TIMEOUT_SEC",
)

_SELF_ACTION = re.compile(
    r"我(?!建议|觉得|认为|想)(?:.{0,12})(?:修复|修一下|处理|准备|做完|去做|来做|负责|修好)"
)
_DUE_PATTERNS = [
    re.compile(r"今天\s*\d{1,2}\s*点前"),
    re.compile(r"明天\s*\d{1,2}\s*点前"),
    re.compile(r"\d{1,2}\s*点前"),
    re.compile(r"中午前"),
    re.compile(r"周五"),
    re.compile(r"月底前"),
    re.compile(r"尽快"),
]
_NAME_ACTIONS = re.compile(
    r"(?P<name>[\u4e00-\u9fff]{2,4})(?P<body>(?:今天|明天|周五|尽快|中午前)?[^，,；;]{0,40}"
    r"(?:把.{1,30}(?:做完|修好|处理完|处理)|处理.{1,20}|修一下|修复.{0,16}|准备.{1,30}|修权限))"
)


class TaskExtractorError(Exception):
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
    raw = str(os.environ.get("TASK_EXTRACTOR_TIMEOUT_SEC", "") or "").strip()
    if raw:
        try:
            return max(0.01, float(raw))
        except ValueError:
            pass
    return float(EXTRACTOR_TIMEOUT_SEC)


def has_self_action(content: str) -> bool:
    text = str(content or "")
    if re.search(r"我建议|我觉得|我认为", text) and not _SELF_ACTION.search(text):
        return False
    return bool(_SELF_ACTION.search(text) or re.search(r"我.{0,8}(?:修复|修一下|处理完|准备好)", text))


def extract_due_text(content: str) -> str:
    text = str(content or "")
    for pattern in _DUE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return ""


def parse_task_extractor_json(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text:
        raise TaskExtractorError("JSON_PARSE_ERROR", "Extractor 输出为空")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise TaskExtractorError("JSON_PARSE_ERROR", "Extractor 输出不是 JSON 对象", text[:200])
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
        raise TaskExtractorError("JSON_PARSE_ERROR", "Extractor JSON 解析失败", str(exc))
    if not isinstance(data, dict):
        raise TaskExtractorError("JSON_PARSE_ERROR", "Extractor JSON 必须是对象")
    return normalize_task_extractor_output(data)


def normalize_task_extractor_output(data: dict) -> dict:
    payload = data if isinstance(data, dict) else {}
    if "decisions" not in payload:
        raise TaskExtractorError("INVALID_OUTPUT", "缺少 decisions")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise TaskExtractorError("INVALID_OUTPUT", "decisions 必须是数组")
    if len(raw_decisions) < 1 or len(raw_decisions) > 5:
        raise TaskExtractorError("INVALID_OUTPUT", "decisions 必须是 1..5 条", str(len(raw_decisions)))
    decisions = [normalize_decision(item) for item in raw_decisions]
    return {"decisions": decisions}


def normalize_decision(item: Any) -> dict:
    if not isinstance(item, dict):
        raise TaskExtractorError("INVALID_OUTPUT", "decision 必须是对象")
    data = dict(item)
    for key in list(data.keys()):
        if key in LIFECYCLE_KEYS and key != "decision":
            data.pop(key, None)
        elif key in STRIP_KEYS or key not in ALLOWED_DECISION_KEYS:
            data.pop(key, None)
    decision = str(data.get("decision") or "").strip().upper()
    if decision in FORBIDDEN_DECISIONS:
        raise TaskExtractorError("INVALID_DECISION", "禁止改变 Task 生命周期的 decision", decision)
    task_id = data.get("task_id")
    if task_id == "" or task_id is False:
        task_id = None
    evidence = data.get("evidence_message_ids") or []
    if not isinstance(evidence, list):
        evidence = []
    confidence = str(data.get("confidence") or "").strip().upper()
    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "LOW"
    return {
        "decision": decision,
        "task_id": task_id,
        "title": str(data.get("title") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "assignee_text": str(data.get("assignee_text") or "").strip(),
        "due_text": str(data.get("due_text") or "").strip(),
        "confidence": confidence,
        "evidence_message_ids": [str(value) for value in evidence if value],
        "reason": str(data.get("reason") or "").strip(),
    }


class TaskExtractorClient:
    """Engine Input + TASK_EXTRACTOR Prompt + LLM → {decisions: [...]}。

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
                    if stripped and "{" not in stripped:
                        raise TaskExtractorError(
                            "EXTRACTOR_EXCEPTION",
                            "Extractor 输出不是 JSON 对象",
                            stripped[:200],
                        )
                if isinstance(raw, dict):
                    return normalize_task_extractor_output(raw)
                return parse_task_extractor_json(raw)
            except TimeoutError as exc:
                raise TaskExtractorError("EXTRACTOR_TIMEOUT", "Extractor LLM timeout", str(exc))
            except TaskExtractorError as exc:
                last_error = exc
                if exc.code not in ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "EXTRACTOR_EXCEPTION") or attempt == 1:
                    raise
            except Exception as exc:
                text = str(exc)
                if "EXTRACTOR_EMPTY" in text and attempt == 0:
                    last_error = TaskExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空", text[:200])
                    continue
                raise TaskExtractorError("EXTRACTOR_EXCEPTION", "Extractor LLM 调用失败", text[:300])
        raise last_error


def _default_extractor_llm_call(messages, **kwargs):
    from llm_client import get_extractor_response
    kwargs.setdefault("purpose", "task_extractor")
    return get_extractor_response(messages, **kwargs)


_KNOWN_NAMES = ("王强", "李娜", "赵凯", "周敏", "陈总", "张三")
_ACTION_HINTS = ("处理", "修", "修复", "做完", "准备", "跑", "把")
_COMPLETION_MARKERS = ("已经处理完", "已经修好", "已经做完", "处理完了", "修好了", "关掉吧")
_SUGGEST_MARKERS = ("我建议", "建议", "最好")
_FACT_MARKERS = ("失败了", "能看到", "超时了")
_PLAN_CONFIRM = ("按照这个方案", "先按照这个方案", "可以，先按照")
_DUE_CHANGE = re.compile(r"(改到|改成|改为).{0,8}\d{1,2}\s*点")


def _unrelated(message_id: str, reason: str) -> dict:
    return {
        "decisions": [
            {
                "decision": "UNRELATED",
                "task_id": None,
                "title": "",
                "description": "",
                "assignee_text": "",
                "due_text": "",
                "confidence": "HIGH",
                "evidence_message_ids": [message_id] if message_id else [],
                "reason": reason,
            }
        ]
    }


def _decision(
    *,
    decision: str,
    message_id: str,
    title: str = "",
    description: str = "",
    assignee_text: str = "",
    due_text: str = "",
    task_id=None,
    reason: str = "heuristic",
) -> dict:
    return {
        "decision": decision,
        "task_id": task_id,
        "title": title,
        "description": description,
        "assignee_text": assignee_text,
        "due_text": due_text,
        "confidence": "HIGH",
        "evidence_message_ids": [message_id] if message_id else [],
        "reason": reason,
    }


def _title_for(assignee: str, body: str) -> str:
    text = body or ""
    if "空值" in text:
        return "处理供应商编码空值规则"
    if "供应商" in text or "编码" in text:
        return "处理供应商编码"
    if "权限" in text:
        return "修复质检权限问题"
    if "离线" in text or "检查清单" in text:
        return "准备离线演示包和现场检查清单"
    trimmed = re.sub(r"[。.?？!！]+$", "", text).strip()
    return (trimmed or "处理工作事项")[:40]


class HeuristicTaskExtractor:
    """离线确定性 Extractor，供 fixture 红线。生产默认走 TaskExtractorClient。禁止接入微信。"""

    def extract(self, engine_input: dict, prompt_content: str) -> dict:
        current = (engine_input or {}).get("current_message") or {}
        content = str(current.get("content") or "")
        current_id = str(current.get("id") or "")
        sender = str(current.get("sender_name") or "")
        existing = list((engine_input or {}).get("existing_tasks") or [])
        stripped = content.strip()

        if any(marker in stripped for marker in _COMPLETION_MARKERS):
            return _unrelated(current_id, "完成陈述不关闭 Task")
        if stripped.startswith("我建议") or (stripped.startswith("建议") and "做" not in stripped[:6]):
            return _unrelated(current_id, "建议不是 Task")
        if _DUE_CHANGE.search(stripped) and existing:
            due = extract_due_text(stripped) or "17 点前"
            target = existing[0]
            return {
                "decisions": [
                    _decision(
                        decision="TASK_UPDATE",
                        message_id=current_id,
                        task_id=target.get("id"),
                        due_text=due,
                        reason="更新截止",
                    )
                ]
            }
        if any(marker in stripped for marker in _PLAN_CONFIRM):
            if existing:
                return {
                    "decisions": [
                        _decision(
                            decision="TASK_UPDATE",
                            message_id=current_id,
                            task_id=existing[0].get("id"),
                            description=stripped[:500],
                            reason="确认已有方案，不新建",
                        )
                    ]
                }
            return _unrelated(current_id, "无可命中 Task 的确认")
        if any(marker in stripped for marker in _FACT_MARKERS) and not any(
            name in stripped for name in _KNOWN_NAMES if name != sender
        ):
            if not has_self_action(stripped) and not any(name in stripped for name in _KNOWN_NAMES):
                return _unrelated(current_id, "问题事实不是 Task")
        if stripped.startswith("需要") and not any(name in stripped for name in _KNOWN_NAMES):
            if not has_self_action(stripped):
                return _unrelated(current_id, "无负责人不建 Task")

        extracted = _extract_assignments(stripped, sender)
        if not extracted:
            return _unrelated(current_id, "无明确指派")

        decisions = []
        for item in extracted[:5]:
            hit = _match_existing(item, existing)
            if hit:
                decisions.append(
                    _decision(
                        decision="TASK_UPDATE",
                        message_id=current_id,
                        task_id=hit.get("id"),
                        title=item.get("title") or "",
                        description=item.get("description") or "",
                        assignee_text="",
                        due_text=item.get("due_text") or "",
                        reason="命中已有 Task",
                    )
                )
                continue
            if not item.get("assignee_text"):
                continue
            decisions.append(
                _decision(
                    decision="NEW_TASK",
                    message_id=current_id,
                    title=item["title"],
                    description=item.get("description") or "",
                    assignee_text=item["assignee_text"],
                    due_text=item.get("due_text") or "",
                    reason="heuristic NEW_TASK",
                )
            )
        if not decisions:
            return _unrelated(current_id, "无负责人或无可执行对象")
        return {"decisions": decisions}


def _extract_assignments(content: str, sender_name: str) -> list:
    text = str(content or "").strip()
    if not text:
        return []
    clauses = re.split(r"[，,；;]", text)
    pending = []
    last_assignee = ""
    for clause in clauses:
        piece = clause.strip()
        if not piece:
            continue
        if piece.startswith("再") and last_assignee and pending:
            pending[-1]["description"] = ((pending[-1].get("description") or "") + "；" + piece).strip("；")
            continue
        assignee = ""
        body = piece
        named = False
        for name in _KNOWN_NAMES:
            if piece.startswith(name) or (name in piece[:8] and any(hint in piece for hint in _ACTION_HINTS)):
                assignee = name
                body = piece[piece.find(name) + len(name) :]
                named = True
                break
        if not named and has_self_action(piece):
            assignee = sender_name
            body = re.sub(r"^.*?我", "", piece)
        if not assignee:
            match = _NAME_ACTIONS.search(piece)
            if match:
                assignee = match.group("name")
                body = match.group("body")
        if not assignee:
            continue
        if not any(hint in piece for hint in _ACTION_HINTS) and "准备" not in piece:
            continue
        last_assignee = assignee
        due = extract_due_text(piece) or extract_due_text(text)
        title = _title_for(assignee, piece)
        pending.append(
            {
                "assignee_text": assignee,
                "title": title,
                "description": body.strip(" ，,。"),
                "due_text": due if named or has_self_action(piece) else due,
            }
        )
    merged = []
    for item in pending:
        if merged and merged[-1]["assignee_text"] == item["assignee_text"]:
            merged[-1]["description"] = (merged[-1].get("description") or "") + "；" + (item.get("description") or "")
            if item.get("due_text") and not merged[-1].get("due_text"):
                merged[-1]["due_text"] = item["due_text"]
            continue
        merged.append(item)
    return merged


def _match_existing(extracted: dict, existing: list) -> Optional[dict]:
    assignee = extracted.get("assignee_text") or ""
    title = extracted.get("title") or ""
    for task in existing:
        same_person = assignee and assignee == str(task.get("assignee_text") or "")
        blob = "%s %s" % (task.get("title") or "", task.get("description") or "")
        overlap = any(token and token in blob and token in title for token in ("空值", "编码", "权限", "离线"))
        if same_person and (overlap or not title):
            return task
    return None
