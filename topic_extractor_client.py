# -*- coding: utf-8 -*-
"""P3 Topic Extractor Client：独立 LLM 调用，不读写 chat_contexts，不走 Chat Prompt。"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

ALLOWED_DECISIONS = ("NEW_TOPIC", "EXISTING_TOPIC", "TOPIC_UPDATE", "UNRELATED")
ALLOWED_CONFIDENCE = ("HIGH", "MEDIUM", "LOW")
ALLOWED_OUTPUT_KEYS = {
    "decision",
    "topic_id",
    "proposed_title",
    "summary_update",
    "confidence",
    "evidence_message_ids",
    "reason",
}
STRIP_KEYS = {
    "tasks",
    "risks",
    "decisions",
    "assignee",
    "owner",
    "due",
    "due_at",
    "progress",
    "progress_percent",
    "daily_report",
    "daily_report_flag",
}

EXTRACTOR_TEMPERATURE = 0.2
EXTRACTOR_MAX_TOKENS = 1200
EXTRACTOR_TIMEOUT_SEC = 20
_TIMEOUT_FLAG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime_control",
    "TOPIC_EXTRACTOR_TIMEOUT_SEC",
)


def _extractor_timeout_sec() -> float:
    """真机 R12 可写 runtime_control/TOPIC_EXTRACTOR_TIMEOUT_SEC 注入超时，不改 Chat timeout。"""
    try:
        if os.path.isfile(_TIMEOUT_FLAG):
            with open(_TIMEOUT_FLAG, "r", encoding="utf-8") as handle:
                return max(0.01, float(handle.read().strip() or EXTRACTOR_TIMEOUT_SEC))
    except (OSError, ValueError):
        pass
    raw = str(os.environ.get("TOPIC_EXTRACTOR_TIMEOUT_SEC", "") or "").strip()
    if raw:
        try:
            return max(0.01, float(raw))
        except ValueError:
            pass
    return float(EXTRACTOR_TIMEOUT_SEC)


class TopicExtractorError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


def parse_extractor_json(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text:
        raise TopicExtractorError("JSON_PARSE_ERROR", "Extractor 输出为空")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise TopicExtractorError("JSON_PARSE_ERROR", "Extractor 输出不是 JSON 对象", text[:200])
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
        raise TopicExtractorError("JSON_PARSE_ERROR", "Extractor JSON 解析失败", str(exc))
    if not isinstance(data, dict):
        raise TopicExtractorError("JSON_PARSE_ERROR", "Extractor JSON 必须是对象")
    for key in list(data.keys()):
        if key in STRIP_KEYS or key not in ALLOWED_OUTPUT_KEYS:
            data.pop(key, None)
    topic_id = data.get("topic_id")
    if topic_id == "" or topic_id is False:
        topic_id = None
    evidence = data.get("evidence_message_ids") or []
    if not isinstance(evidence, list):
        evidence = []
    confidence = str(data.get("confidence") or "").strip().upper()
    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "LOW"
    decision = str(data.get("decision") or "").strip().upper()
    return {
        "decision": decision,
        "topic_id": topic_id,
        "proposed_title": str(data.get("proposed_title") or "").strip(),
        "summary_update": str(data.get("summary_update") or "").strip(),
        "confidence": confidence,
        "evidence_message_ids": [str(item) for item in evidence if item],
        "reason": str(data.get("reason") or "").strip(),
    }


class TopicExtractorClient:
    """Engine Input + Extractor Prompt + LLM → Raw Extractor JSON。

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
                        raise TopicExtractorError(
                            "EXTRACTOR_EXCEPTION",
                            "Extractor 输出不是 JSON 对象",
                            stripped[:200],
                        )
                return parse_extractor_json(raw)
            except TimeoutError as exc:
                raise TopicExtractorError("EXTRACTOR_TIMEOUT", "Extractor LLM timeout", str(exc))
            except TopicExtractorError as exc:
                last_error = exc
                if exc.code not in ("JSON_PARSE_ERROR", "EXTRACTOR_EMPTY", "EXTRACTOR_EXCEPTION") or attempt == 1:
                    raise
            except Exception as exc:
                text = str(exc)
                if "EXTRACTOR_EMPTY" in text and attempt == 0:
                    last_error = TopicExtractorError("EXTRACTOR_EMPTY", "Extractor 输出为空", text[:200])
                    continue
                raise TopicExtractorError("EXTRACTOR_EXCEPTION", "Extractor LLM 调用失败", text[:300])
        raise last_error


def _default_extractor_llm_call(messages, **kwargs):
    from llm_client import get_extractor_response
    kwargs.setdefault("purpose", "topic_extractor")
    return get_extractor_response(messages, **kwargs)


_ERP_KEYS = ("ERP", "同步", "增量", "供应商", "编码", "异常池", "空值", "回归", "超时", "主数据", "日志")
_PERM_KEYS = ("权限", "质检", "采购价格", "采购")
_DEMO_KEYS = ("演示", "现场", "Wi-Fi", "WIFI", "wifi", "WiFi", "离线", "demo", "Demo")
_API_KEYS = ("接口",)
_UPDATE_KEYS = (
    "方案",
    "异常池",
    "建议",
    "必须",
    "15:30",
    "Wi-Fi",
    "WIFI",
    "wifi",
    "跑通",
    "修复",
    "建好",
    "离线",
    "超时",
    "500",
    "重启",
    "规则",
)
_CHITCHAT_KEYS = ("吃什么", "喝什么", "天气怎么样", "天气")


def domain_tags(text: str) -> set:
    value = text or ""
    tags = set()
    if any(key in value for key in _ERP_KEYS):
        tags.add("erp")
    if any(key in value for key in _PERM_KEYS):
        tags.add("perm")
    if any(key in value for key in _DEMO_KEYS):
        tags.add("demo")
    if any(key in value for key in _API_KEYS):
        tags.add("api")
    lowered = value.lower()
    if "demo" in lowered or "账号" in value:
        if "erp" not in tags:
            tags.add("demo")
        if "权限" in value or "质检" in value:
            tags.add("perm")
    return tags


def canonical_title(tags: set, content: str) -> str:
    if "erp" in tags:
        return "ERP 数据同步异常"
    if "perm" in tags:
        return "权限整改"
    if "demo" in tags:
        return "现场演示准备"
    if "api" in tags:
        return "接口问题"
    trimmed = re.sub(r"[。.?？!！]+$", "", (content or "").strip())
    return trimmed[:20]


class HeuristicTopicExtractor:
    """离线确定性 Extractor，供 fixture 验收使用。生产默认走 TopicExtractorClient。"""

    def extract(self, engine_input: dict, prompt_content: str) -> dict:
        current = (engine_input or {}).get("current_message") or {}
        content = str(current.get("content") or "")
        current_id = str(current.get("id") or "")
        active = list((engine_input or {}).get("active_topics") or [])
        msg_tags = domain_tags(content)
        scored = []
        for topic in active:
            blob = "%s %s" % (topic.get("title") or "", topic.get("summary") or "")
            topic_tags = domain_tags(blob)
            overlap = len(msg_tags & topic_tags)
            if overlap:
                scored.append((overlap, topic))
        scored.sort(key=lambda item: -item[0])
        reason = "heuristic"
        if scored:
            _score, topic = scored[0]
            extra = ""
            if len(scored) > 1:
                extra = "；省略其它候选主题"
                reason = "v1 单主 Topic" + extra
            decision = "TOPIC_UPDATE" if any(key in content for key in _UPDATE_KEYS) else "EXISTING_TOPIC"
            return {
                "decision": decision,
                "topic_id": topic.get("id"),
                "proposed_title": "",
                "summary_update": content[:400] if decision == "TOPIC_UPDATE" else "",
                "confidence": "HIGH" if _score >= 2 else "MEDIUM",
                "evidence_message_ids": [current_id] if current_id else [],
                "reason": reason,
            }
        if any(key in content for key in _CHITCHAT_KEYS):
            return _unrelated(current_id, "闲聊")
        if not msg_tags:
            return _unrelated(current_id, "无可命名业务对象")
        title = canonical_title(msg_tags, content)
        if title in ("项目综合", "综合问题"):
            return _unrelated(current_id, "禁止综合主题")
        return {
            "decision": "NEW_TOPIC",
            "topic_id": None,
            "proposed_title": title,
            "summary_update": content[:400],
            "confidence": "HIGH",
            "evidence_message_ids": [current_id] if current_id else [],
            "reason": "新业务对象",
        }


def _unrelated(message_id: str, reason: str) -> dict:
    return {
        "decision": "UNRELATED",
        "topic_id": None,
        "proposed_title": "",
        "summary_update": "",
        "confidence": "HIGH",
        "evidence_message_ids": [message_id] if message_id else [],
        "reason": reason,
    }
