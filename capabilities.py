# -*- coding: utf-8 -*-
"""统一能力状态。未配置不得静默当成“坏了”，也不得把主聊天打成 DEGRADED。"""

from __future__ import annotations

from typing import Optional

READY = "READY"
DISABLED = "DISABLED"
NOT_CONFIGURED = "NOT_CONFIGURED"
DEGRADED = "DEGRADED"
ERROR = "ERROR"

STATUS_LABELS = {
    READY: "已就绪",
    DISABLED: "已关闭",
    NOT_CONFIGURED: "未配置",
    DEGRADED: "降级",
    ERROR: "异常",
}

CAPABILITY_DEFS = (
    ("wechat", "微信连接"),
    ("main_model", "主模型"),
    ("image_recognition", "图片识别"),
    ("emoji_recognition", "表情识别"),
    ("online_search", "联网搜索"),
    ("assistant_model", "辅助模型"),
    ("reminders", "提醒"),
    ("auto_message", "主动消息"),
    ("url_fetch", "链接抓取"),
    ("emoji_sending", "表情包发送"),
    ("voice_stt", "语音转文字"),
    ("merged_forward", "合并转发解析"),
    ("scheduled_restart", "定时重启"),
)


def _secret_ok(value) -> bool:
    from app_config import is_configured_secret
    return is_configured_secret(value)


def evaluate_capabilities(config: dict, runtime_snapshot: Optional[dict] = None) -> dict:
    cfg = config or {}
    snap = runtime_snapshot or {}
    wechat_state = str(snap.get("wechat") or "").lower()
    if wechat_state in ("connected", "ok"):
        wechat = {"status": READY, "detail": snap.get("wechat_detail") or "已连接"}
    elif wechat_state in ("error", "disconnected") and snap.get("state") in ("ERROR", "STARTING", "RUNNING", "DEGRADED"):
        wechat = {"status": ERROR, "detail": snap.get("wechat_detail") or "未连接"}
    else:
        wechat = {"status": DISABLED, "detail": "机器人未运行"}

    if _secret_ok(cfg.get("DEEPSEEK_API_KEY")):
        ai_flag = str(snap.get("ai") or "").lower()
        if ai_flag == "error":
            main_model = {"status": ERROR, "detail": snap.get("ai_detail") or "主模型异常"}
        else:
            main_model = {"status": READY, "detail": cfg.get("MODEL") or "已配置"}
    else:
        main_model = {"status": NOT_CONFIGURED, "detail": "主模型 API Key 未配置"}

    def feature(enabled: bool, key_ok: bool, ready_detail: str, missing_detail: str) -> dict:
        if not enabled:
            return {"status": DISABLED, "detail": "功能已关闭"}
        if not key_ok:
            return {"status": NOT_CONFIGURED, "detail": missing_detail}
        return {"status": READY, "detail": ready_detail}

    image_key_ok = _secret_ok(cfg.get("MOONSHOT_API_KEY"))
    assistant_ok = _secret_ok(cfg.get("ASSISTANT_API_KEY"))
    online_ok = _secret_ok(cfg.get("ONLINE_API_KEY"))

    caps = {
        "wechat": wechat,
        "main_model": main_model,
        "image_recognition": feature(
            bool(cfg.get("ENABLE_IMAGE_RECOGNITION")),
            image_key_ok,
            "图片识别已启用",
            "图片识别已开启，但 API Key 未配置",
        ),
        "emoji_recognition": feature(
            bool(cfg.get("ENABLE_EMOJI_RECOGNITION")),
            image_key_ok,
            "表情识别已启用",
            "表情识别已开启，但 API Key 未配置",
        ),
        "online_search": feature(
            bool(cfg.get("ENABLE_ONLINE_API")),
            online_ok,
            "联网搜索已启用",
            "联网搜索已开启，但 API Key 未配置",
        ),
        "assistant_model": feature(
            bool(cfg.get("ENABLE_ASSISTANT_MODEL")),
            assistant_ok,
            "辅助模型已启用",
            "辅助模型已开启，但 API Key 未配置",
        ),
        "reminders": {
            "status": READY if cfg.get("ENABLE_REMINDERS") else DISABLED,
            "detail": "提醒功能已启用" if cfg.get("ENABLE_REMINDERS") else "提醒功能已关闭",
        },
        "auto_message": {
            "status": READY if cfg.get("ENABLE_AUTO_MESSAGE") else DISABLED,
            "detail": "主动消息已启用" if cfg.get("ENABLE_AUTO_MESSAGE") else "主动消息已关闭",
        },
        "url_fetch": {
            "status": READY if cfg.get("ENABLE_URL_FETCHING") else DISABLED,
            "detail": "链接抓取已启用" if cfg.get("ENABLE_URL_FETCHING") else "链接抓取已关闭",
        },
        "emoji_sending": {
            "status": READY if cfg.get("ENABLE_EMOJI_SENDING") else DISABLED,
            "detail": "表情包发送已启用" if cfg.get("ENABLE_EMOJI_SENDING") else "表情包发送已关闭",
        },
        "voice_stt": {
            "status": DISABLED,
            "detail": "兼容层不支持语音转文字，已关闭",
        },
        "merged_forward": {
            "status": DISABLED,
            "detail": "兼容层不支持合并转发解析，已关闭",
        },
        "scheduled_restart": {
            "status": DISABLED,
            "detail": "代码中已禁用定时重启（if False），配置项无效",
        },
    }
    labeled = []
    for key, title in CAPABILITY_DEFS:
        item = dict(caps.get(key) or {"status": DISABLED, "detail": ""})
        item["key"] = key
        item["title"] = title
        item["label"] = STATUS_LABELS.get(item.get("status"), item.get("status"))
        labeled.append(item)
        caps[key] = item
    caps["_list"] = labeled
    return caps


def assistant_ready(config: dict) -> bool:
    item = evaluate_capabilities(config).get("assistant_model") or {}
    return item.get("status") == READY


def optional_enabled_flags(config: dict) -> dict:
    """根据能力状态返回运行时应真正打开的功能开关。未配置视为关闭，不阻断主聊天。"""
    caps = evaluate_capabilities(config)
    return {
        "ENABLE_IMAGE_RECOGNITION": caps["image_recognition"]["status"] == READY,
        "ENABLE_EMOJI_RECOGNITION": caps["emoji_recognition"]["status"] == READY,
        "ENABLE_ONLINE_API": caps["online_search"]["status"] == READY,
        "ENABLE_ASSISTANT_MODEL": caps["assistant_model"]["status"] == READY,
        "ENABLE_REMINDERS": caps["reminders"]["status"] == READY,
        "ENABLE_AUTO_MESSAGE": caps["auto_message"]["status"] == READY,
        "ENABLE_URL_FETCHING": caps["url_fetch"]["status"] == READY,
        "ENABLE_EMOJI_SENDING": caps["emoji_sending"]["status"] == READY,
    }
