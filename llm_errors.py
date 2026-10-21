# -*- coding: utf-8 -*-
"""LLM / OpenAI 兼容 API 错误分类。禁止把所有失败都说成余额不足。"""

from __future__ import annotations

from typing import Optional

AUTH_ERROR = "AUTH_ERROR"
RATE_LIMIT = "RATE_LIMIT"
TIMEOUT = "TIMEOUT"
NETWORK_ERROR = "NETWORK_ERROR"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
SERVICE_ERROR = "SERVICE_ERROR"
INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
CONTENT_FILTER = "CONTENT_FILTER"
UNTRUSTED_PROVIDER = "UNTRUSTED_PROVIDER"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

USER_MESSAGES = {
    AUTH_ERROR: "AI 服务认证失败，请检查 API Key 是否有效",
    RATE_LIMIT: "AI 服务调用过于频繁，请稍后重试",
    TIMEOUT: "AI 服务响应超时，请稍后重试",
    NETWORK_ERROR: "无法连接 AI 服务，请检查网络后重试",
    MODEL_NOT_FOUND: "指定的模型不可用，请检查模型名称",
    SERVICE_ERROR: "AI 服务暂时不可用，请稍后重试",
    INSUFFICIENT_BALANCE: "AI 服务余额不足或需要充值",
    CONTENT_FILTER: "内容未通过安全检查，已跳过本次回复",
    UNTRUSTED_PROVIDER: "当前 API 服务商不受信任，已拒绝请求",
    UNKNOWN_ERROR: "AI 服务暂时不可用，请稍后重试",
}

RETRYABLE = {RATE_LIMIT, TIMEOUT, NETWORK_ERROR, SERVICE_ERROR}


class LlmApiError(RuntimeError):
    def __init__(self, code: str, user_message: str, log_detail: str = "", status_code=None):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.log_detail = log_detail
        self.status_code = status_code


def _status_code(exc) -> Optional[int]:
    for attr in ("status_code", "status", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def classify_api_error(exc, default_code: str = UNKNOWN_ERROR) -> LlmApiError:
    if isinstance(exc, LlmApiError):
        return exc
    text = str(exc or "")
    lowered = text.lower()
    code = default_code
    status = _status_code(exc)

    if "untrusted" in lowered or "不受信任" in text:
        code = UNTRUSTED_PROVIDER
    elif status == 401 or "api key is invalid" in lowered or "unauthorized" in lowered or "authentication" in lowered or "invalid api key" in lowered:
        code = AUTH_ERROR
    elif status == 402 or "payment required" in lowered or "user quota" in lowered or "is not enough" in lowered or "unlimitedquota" in lowered or ("insufficient" in lowered and "quota" in lowered):
        code = INSUFFICIENT_BALANCE
    elif status == 429 or "rate limit" in lowered or "too many requests" in lowered:
        code = RATE_LIMIT
    elif status == 404 or "model_not_found" in lowered or ("does not exist" in lowered and "model" in lowered):
        code = MODEL_NOT_FOUND
    elif "timeout" in lowered or "timed out" in lowered:
        code = TIMEOUT
    elif "connection" in lowered or "network" in lowered or "name or service not known" in lowered:
        code = NETWORK_ERROR
    elif "sensitive words detected" in lowered or "content_filter" in lowered or ("sensitive" in lowered and "content" in lowered):
        code = CONTENT_FILTER
    elif status in (500, 502, 503, 504) or "service unavailable" in lowered or "internal server error" in lowered:
        code = SERVICE_ERROR
    elif "real name verification" in lowered:
        code = AUTH_ERROR

    return LlmApiError(
        code=code,
        user_message=USER_MESSAGES.get(code, USER_MESSAGES[UNKNOWN_ERROR]),
        log_detail=text[:500],
        status_code=status,
    )


def is_retryable(error: LlmApiError) -> bool:
    return error.code in RETRYABLE
