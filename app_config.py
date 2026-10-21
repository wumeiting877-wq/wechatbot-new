# -*- coding: utf-8 -*-
"""结构化配置加载 / 保存 / 校验。

运行配置：config.local.json
密钥：.env
模板：config.example.json、.env.example

config.py 仅作为兼容 shim，不再保存真实密钥。
"""

from __future__ import annotations

import ast
import json
import os
import re
import secrets
import tempfile
import time
from copy import deepcopy
from typing import Any, Optional

from filelock import FileLock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_CONFIG_PATH = os.path.join(ROOT_DIR, "config.local.json")
EXAMPLE_CONFIG_PATH = os.path.join(ROOT_DIR, "config.example.json")
ENV_PATH = os.path.join(ROOT_DIR, ".env")
ENV_EXAMPLE_PATH = os.path.join(ROOT_DIR, ".env.example")
LEGACY_PY_BACKUP = os.path.join(ROOT_DIR, "config.py.legacy.bak")
CONFIG_PY_PATH = os.path.join(ROOT_DIR, "config.py")

SECRET_KEYS = (
    "DEEPSEEK_API_KEY",
    "MOONSHOT_API_KEY",
    "ONLINE_API_KEY",
    "ASSISTANT_API_KEY",
    "FORUM_API_KEY",
    "LOGIN_PASSWORD",
    "WEBUI_PASSWORD_HASH",
    "FLASK_SECRET_KEY",
)

PLACEHOLDER_SECRETS = {
    "",
    "YOUR_API_KEY",
    "YOUR_API_KEY_HERE",
    "YOUR_PASSWORD",
    "123456",
}

HOT_RELOAD_KEYS = {
    "ENABLE_AUTO_MESSAGE",
    "UPLOAD_MEMORY_TO_AI",
    "QUIET_TIME_START",
    "QUIET_TIME_END",
    "ENABLE_REMINDERS",
    "ALLOW_REMINDERS_IN_QUIET_TIME",
}

_cache = {
    "data": None,
    "mtime": None,
}


def get_default_config() -> dict:
    return {
        "LISTEN_LIST": [["微信名1", "角色1"]],
        "CONVERSATIONS": [],
        "AGENT_CONFIGS": [],
        "DEEPSEEK_API_KEY": "",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "MODEL": "deepseek-chat",
        "MAX_GROUPS": 5,
        "MAX_TOKEN": 2000,
        "TEMPERATURE": 0.7,
        "MOONSHOT_API_KEY": "",
        "MOONSHOT_BASE_URL": "https://vg.v1api.cc/v1",
        "MOONSHOT_MODEL": "gpt-4o",
        "MOONSHOT_TEMPERATURE": 0.5,
        "ENABLE_IMAGE_RECOGNITION": False,
        "ENABLE_EMOJI_RECOGNITION": False,
        "QUEUE_WAITING_TIME": 7,
        "EMOJI_DIR": "emojis",
        "ENABLE_EMOJI_SENDING": True,
        "EMOJI_SENDING_PROBABILITY": 25,
        "AUTO_MESSAGE": "请你模拟系统设置的角色，在微信上找对方继续刚刚的话题或者询问对方在做什么",
        "ENABLE_AUTO_MESSAGE": False,
        "MIN_COUNTDOWN_HOURS": 1.0,
        "MAX_COUNTDOWN_HOURS": 2.0,
        "QUIET_TIME_START": "22:00",
        "QUIET_TIME_END": "8:00",
        "IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE": False,
        "AVERAGE_TYPING_SPEED": 0.5,
        "RANDOM_TYPING_SPEED_MIN": 0.05,
        "RANDOM_TYPING_SPEED_MAX": 0.1,
        "SEPARATE_ROW_SYMBOLS": True,
        "ENABLE_MEMORY": True,
        "MEMORY_TEMP_DIR": "Memory_Temp",
        "MAX_MESSAGE_LOG_ENTRIES": 30,
        "MAX_MEMORY_NUMBER": 50,
        "UPLOAD_MEMORY_TO_AI": True,
        "SAVE_MEMORY_TO_SEPARATE_FILE": True,
        "CORE_MEMORY_DIR": "CoreMemory",
        "ACCEPT_ALL_GROUP_CHAT_MESSAGES": False,
        "ENABLE_GROUP_AT_REPLY": True,
        "ENABLE_GROUP_KEYWORD_REPLY": False,
        "GROUP_KEYWORD_LIST": ["你好", "机器人", "在吗"],
        "GROUP_CHAT_RESPONSE_PROBABILITY": 100,
        "GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY": True,
        "ENABLE_LOGIN_PASSWORD": False,
        "LOGIN_PASSWORD": "",
        "PORT": 5000,
        "ENABLE_TEXT_COMMANDS": True,
        "ENABLE_REMINDERS": True,
        "ALLOW_REMINDERS_IN_QUIET_TIME": True,
        "USE_VOICE_CALL_FOR_REMINDERS": False,
        "ENABLE_ONLINE_API": False,
        "ONLINE_BASE_URL": "https://vg.v1api.cc/v1",
        "ONLINE_MODEL": "deepseek-r1-searching",
        "ONLINE_API_KEY": "",
        "ONLINE_API_TEMPERATURE": 0.5,
        "ONLINE_API_MAX_TOKEN": 2000,
        "SEARCH_DETECTION_PROMPT": "是否需要查询今天的天气、最新的新闻事件、特定网站的内容、股票价格、特定人物的最新动态、歌词、小说情节、游戏内容、网络热梗、历史信息等",
        "ONLINE_FIXED_PROMPT": "",
        "ENABLE_URL_FETCHING": True,
        "REQUESTS_TIMEOUT": 10,
        "REQUESTS_USER_AGENT": "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36",
        "MAX_WEB_CONTENT_LENGTH": 2000,
        "ENABLE_SCHEDULED_RESTART": False,
        "RESTART_INTERVAL_HOURS": 2.0,
        "RESTART_INACTIVITY_MINUTES": 15,
        "REMOVE_PARENTHESES": False,
        "ENABLE_ASSISTANT_MODEL": False,
        "ASSISTANT_BASE_URL": "https://vg.v1api.cc/v1",
        "ASSISTANT_MODEL": "gpt-4o-mini",
        "ASSISTANT_API_KEY": "",
        "ASSISTANT_TEMPERATURE": 0.3,
        "ASSISTANT_MAX_TOKEN": 1000,
        "USE_ASSISTANT_FOR_MEMORY_SUMMARY": False,
        "ENABLE_SENSITIVE_CONTENT_CLEARING": True,
        "ENABLE_FORUM_CUSTOM_MODEL": False,
        "FORUM_BASE_URL": "https://vg.v1api.cc/v1",
        "FORUM_MODEL": "deepseek-ai/DeepSeek-V3",
        "FORUM_API_KEY": "",
        "FORUM_TEMPERATURE": 1.0,
        "FORUM_MAX_TOKEN": 1200,
        "WEBUI_PASSWORD_HASH": "",
        "FLASK_SECRET_KEY": "",
    }


FIELD_TYPES = {
    "LISTEN_LIST": list,
    "CONVERSATIONS": list,
    "AGENT_CONFIGS": list,
    "MAX_GROUPS": int,
    "MAX_TOKEN": int,
    "TEMPERATURE": float,
    "MOONSHOT_TEMPERATURE": float,
    "ENABLE_IMAGE_RECOGNITION": bool,
    "ENABLE_EMOJI_RECOGNITION": bool,
    "QUEUE_WAITING_TIME": int,
    "ENABLE_EMOJI_SENDING": bool,
    "EMOJI_SENDING_PROBABILITY": int,
    "ENABLE_AUTO_MESSAGE": bool,
    "MIN_COUNTDOWN_HOURS": float,
    "MAX_COUNTDOWN_HOURS": float,
    "IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE": bool,
    "AVERAGE_TYPING_SPEED": float,
    "RANDOM_TYPING_SPEED_MIN": float,
    "RANDOM_TYPING_SPEED_MAX": float,
    "SEPARATE_ROW_SYMBOLS": bool,
    "ENABLE_MEMORY": bool,
    "MAX_MESSAGE_LOG_ENTRIES": int,
    "MAX_MEMORY_NUMBER": int,
    "UPLOAD_MEMORY_TO_AI": bool,
    "SAVE_MEMORY_TO_SEPARATE_FILE": bool,
    "ACCEPT_ALL_GROUP_CHAT_MESSAGES": bool,
    "ENABLE_GROUP_AT_REPLY": bool,
    "ENABLE_GROUP_KEYWORD_REPLY": bool,
    "GROUP_KEYWORD_LIST": list,
    "GROUP_CHAT_RESPONSE_PROBABILITY": int,
    "GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY": bool,
    "ENABLE_LOGIN_PASSWORD": bool,
    "PORT": int,
    "ENABLE_TEXT_COMMANDS": bool,
    "ENABLE_REMINDERS": bool,
    "ALLOW_REMINDERS_IN_QUIET_TIME": bool,
    "USE_VOICE_CALL_FOR_REMINDERS": bool,
    "ENABLE_ONLINE_API": bool,
    "ONLINE_API_TEMPERATURE": float,
    "ONLINE_API_MAX_TOKEN": int,
    "ENABLE_URL_FETCHING": bool,
    "REQUESTS_TIMEOUT": int,
    "MAX_WEB_CONTENT_LENGTH": int,
    "ENABLE_SCHEDULED_RESTART": bool,
    "RESTART_INTERVAL_HOURS": float,
    "RESTART_INACTIVITY_MINUTES": int,
    "REMOVE_PARENTHESES": bool,
    "ENABLE_ASSISTANT_MODEL": bool,
    "ASSISTANT_TEMPERATURE": float,
    "ASSISTANT_MAX_TOKEN": int,
    "USE_ASSISTANT_FOR_MEMORY_SUMMARY": bool,
    "ENABLE_SENSITIVE_CONTENT_CLEARING": bool,
    "ENABLE_FORUM_CUSTOM_MODEL": bool,
    "FORUM_TEMPERATURE": float,
    "FORUM_MAX_TOKEN": int,
}


def is_placeholder_secret(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.upper() in {item.upper() for item in PLACEHOLDER_SECRETS if item}


def is_configured_secret(value) -> bool:
    return not is_placeholder_secret(value)


def _parse_env_file(path: str) -> dict:
    result = {}
    if not os.path.exists(path):
        return result
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            result[key] = value
    return result


def _is_replace_lock_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    return winerror == 5


def _replace_with_retry(src: str, dest: str, attempts: int = 8) -> None:
    """Windows 上 os.replace 在目标文件被短暂占用时会 WinError 5，短重试后仍失败再抛出。"""
    last_err = None
    for index in range(attempts):
        try:
            os.replace(src, dest)
            return
        except OSError as exc:
            last_err = exc
            if not _is_replace_lock_error(exc) or index == attempts - 1:
                raise
            time.sleep(0.05 * (index + 1))
    if last_err:
        raise last_err


def _atomic_write(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmpcfg_", dir=directory, text=False)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _write_env(values: dict) -> None:
    existing = _parse_env_file(ENV_PATH)
    existing.update({k: "" if v is None else str(v) for k, v in values.items()})
    lines = [
        "# 本地密钥，请勿提交到 Git",
        "# 修改后需重启 WebUI / Bot 才会完全生效",
        "",
    ]
    for key in (
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "ONLINE_API_KEY",
        "ASSISTANT_API_KEY",
        "FORUM_API_KEY",
        "WEBUI_PASSWORD_HASH",
        "FLASK_SECRET_KEY",
    ):
        lines.append(f"{key}={existing.get(key, '')}")
    extra_keys = [k for k in existing.keys() if k not in {
        "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "ONLINE_API_KEY",
        "ASSISTANT_API_KEY", "FORUM_API_KEY", "WEBUI_PASSWORD_HASH",
        "FLASK_SECRET_KEY",
    }]
    for key in extra_keys:
        lines.append(f"{key}={existing.get(key, '')}")
    _atomic_write(ENV_PATH, "\n".join(lines) + "\n")


def parse_legacy_python_config(path: str) -> dict:
    config = {}
    if not os.path.exists(path):
        return config
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            match = re.match(r"^(\w+)\s*=\s*(.+)$", stripped)
            if not match:
                continue
            name = match.group(1)
            raw = match.group(2)
            try:
                config[name] = ast.literal_eval(raw)
            except Exception:
                config[name] = raw.strip("'\"")
    return config


def _looks_like_legacy_python(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read(4000)
        return "DEEPSEEK_API_KEY" in text and "=" in text and "load_config" not in text
    except OSError:
        return False


def _hash_password(password: str) -> str:
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password)


def verify_webui_password(password: str, config: Optional[dict] = None) -> bool:
    cfg = config or load_config()
    hashed = str(cfg.get("WEBUI_PASSWORD_HASH") or "").strip()
    if hashed:
        from werkzeug.security import check_password_hash
        try:
            return check_password_hash(hashed, password or "")
        except Exception:
            return False
    stored = str(cfg.get("LOGIN_PASSWORD") or "")
    if is_placeholder_secret(stored):
        return False
    return (password or "") == stored


def _normalize_secret(value) -> str:
    if is_placeholder_secret(value):
        return ""
    return str(value).strip()


def _merge_defaults(raw: dict) -> dict:
    merged = get_default_config()
    for key, value in (raw or {}).items():
        merged[key] = value
    return merged


def migrate_legacy_if_needed() -> bool:
    """把旧 config.py 迁到 config.local.json + .env。成功返回 True。"""
    if os.path.exists(LOCAL_CONFIG_PATH):
        return False
    source = None
    if os.path.exists(LEGACY_PY_BACKUP):
        source = LEGACY_PY_BACKUP
    elif _looks_like_legacy_python(CONFIG_PY_PATH):
        source = CONFIG_PY_PATH
    legacy = parse_legacy_python_config(source) if source else {}
    if not legacy and os.path.exists(EXAMPLE_CONFIG_PATH):
        with open(EXAMPLE_CONFIG_PATH, "r", encoding="utf-8") as f:
            legacy = json.load(f)
    merged = _merge_defaults(legacy)
    secrets_to_write = {}
    for key in SECRET_KEYS:
        if key == "LOGIN_PASSWORD":
            continue
        secrets_to_write[key] = _normalize_secret(merged.get(key, ""))
        merged[key] = secrets_to_write[key]
    password = _normalize_secret(merged.get("LOGIN_PASSWORD", ""))
    merged["LOGIN_PASSWORD"] = ""
    if password:
        merged["WEBUI_PASSWORD_HASH"] = _hash_password(password)
        secrets_to_write["WEBUI_PASSWORD_HASH"] = merged["WEBUI_PASSWORD_HASH"]
    if not secrets_to_write.get("FLASK_SECRET_KEY"):
        secrets_to_write["FLASK_SECRET_KEY"] = secrets.token_hex(24)
        merged["FLASK_SECRET_KEY"] = secrets_to_write["FLASK_SECRET_KEY"]
    public = {k: v for k, v in merged.items() if k not in SECRET_KEYS}
    _atomic_write(LOCAL_CONFIG_PATH, json.dumps(public, ensure_ascii=False, indent=2) + "\n")
    _write_env(secrets_to_write)
    if source == CONFIG_PY_PATH and not os.path.exists(LEGACY_PY_BACKUP):
        try:
            with open(CONFIG_PY_PATH, "r", encoding="utf-8") as f:
                original = f.read()
            if "Compatibility shim" not in original:
                _atomic_write(LEGACY_PY_BACKUP, original)
        except OSError:
            pass
    return True


def validate_config(config: dict) -> list:
    """返回问题列表。问题不阻断主聊天，只用于能力状态和启动提示。"""
    issues = []
    cfg = config or {}
    for key, expected in FIELD_TYPES.items():
        if key not in cfg:
            issues.append({"key": key, "code": "MISSING", "message": f"缺少配置项 {key}"})
            continue
        value = cfg[key]
        if expected is bool and not isinstance(value, bool):
            issues.append({"key": key, "code": "TYPE", "message": f"{key} 应为布尔值"})
        elif expected is int and not isinstance(value, int):
            issues.append({"key": key, "code": "TYPE", "message": f"{key} 应为整数"})
        elif expected is float and not isinstance(value, (int, float)):
            issues.append({"key": key, "code": "TYPE", "message": f"{key} 应为数字"})
        elif expected is list and not isinstance(value, list):
            issues.append({"key": key, "code": "TYPE", "message": f"{key} 应为列表"})
    port = cfg.get("PORT", 5000)
    try:
        port_i = int(port)
        if port_i < 1 or port_i > 65535:
            issues.append({"key": "PORT", "code": "RANGE", "message": "PORT 超出 1-65535"})
    except (TypeError, ValueError):
        issues.append({"key": "PORT", "code": "TYPE", "message": "PORT 应为整数"})
    prob = cfg.get("GROUP_CHAT_RESPONSE_PROBABILITY", 100)
    try:
        if int(prob) < 0 or int(prob) > 100:
            issues.append({"key": "GROUP_CHAT_RESPONSE_PROBABILITY", "code": "RANGE", "message": "群聊回复频率应在 0-100"})
    except (TypeError, ValueError):
        issues.append({"key": "GROUP_CHAT_RESPONSE_PROBABILITY", "code": "TYPE", "message": "群聊回复频率应为整数"})
    listen = cfg.get("LISTEN_LIST") or []
    if not isinstance(listen, list) or not listen:
        issues.append({"key": "LISTEN_LIST", "code": "MISSING", "message": "未配置监听对象"})
    if not is_configured_secret(cfg.get("DEEPSEEK_API_KEY")):
        issues.append({"key": "DEEPSEEK_API_KEY", "code": "NOT_CONFIGURED", "message": "主模型 API Key 未配置"})
    if cfg.get("ENABLE_ONLINE_API") and not is_configured_secret(cfg.get("ONLINE_API_KEY")):
        issues.append({"key": "ONLINE_API_KEY", "code": "NOT_CONFIGURED", "message": "联网搜索已开启但 Key 未配置"})
    if (cfg.get("ENABLE_IMAGE_RECOGNITION") or cfg.get("ENABLE_EMOJI_RECOGNITION")) and not is_configured_secret(cfg.get("MOONSHOT_API_KEY")):
        issues.append({"key": "MOONSHOT_API_KEY", "code": "NOT_CONFIGURED", "message": "图片/表情识别已开启但 Key 未配置"})
    if cfg.get("ENABLE_ASSISTANT_MODEL") and not is_configured_secret(cfg.get("ASSISTANT_API_KEY")):
        issues.append({"key": "ASSISTANT_API_KEY", "code": "NOT_CONFIGURED", "message": "辅助模型已开启但 Key 未配置"})
    if cfg.get("ENABLE_LOGIN_PASSWORD") and not (
        is_configured_secret(cfg.get("WEBUI_PASSWORD_HASH")) or is_configured_secret(cfg.get("LOGIN_PASSWORD"))
    ):
        issues.append({"key": "LOGIN_PASSWORD", "code": "NOT_CONFIGURED", "message": "已启用登录保护但未设置密码"})
    return issues


def load_config(force: bool = False) -> dict:
    migrate_legacy_if_needed()
    if not os.path.exists(LOCAL_CONFIG_PATH):
        defaults = get_default_config()
        public = {k: v for k, v in defaults.items() if k not in SECRET_KEYS}
        _atomic_write(LOCAL_CONFIG_PATH, json.dumps(public, ensure_ascii=False, indent=2) + "\n")
        if not os.path.exists(ENV_PATH):
            _write_env({
                "FLASK_SECRET_KEY": secrets.token_hex(24),
            })
    mtime = None
    try:
        mtime = (os.path.getmtime(LOCAL_CONFIG_PATH), os.path.getmtime(ENV_PATH) if os.path.exists(ENV_PATH) else 0)
    except OSError:
        mtime = None
    if not force and _cache["data"] is not None and _cache["mtime"] == mtime:
        return deepcopy(_cache["data"])
    with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
        public = json.load(f)
    merged = _merge_defaults(public)
    env = _parse_env_file(ENV_PATH)
    for key in SECRET_KEYS:
        if key in env:
            merged[key] = env.get(key, "")
    if not merged.get("FLASK_SECRET_KEY"):
        flask_secret = secrets.token_hex(24)
        merged["FLASK_SECRET_KEY"] = flask_secret
        _write_env({"FLASK_SECRET_KEY": flask_secret})
    _cache["data"] = deepcopy(merged)
    _cache["mtime"] = mtime
    return deepcopy(merged)


def save_config(updates: dict, replace: bool = False) -> dict:
    current = load_config(force=True)
    incoming = deepcopy(updates or {})
    password = incoming.pop("LOGIN_PASSWORD", None)
    if password is not None and str(password).strip() and "*" not in str(password) and not is_placeholder_secret(password):
        incoming["WEBUI_PASSWORD_HASH"] = _hash_password(str(password).strip())
    if replace:
        merged = _merge_defaults(incoming)
        for key in SECRET_KEYS:
            if key not in incoming:
                merged[key] = current.get(key, "")
    else:
        merged = deepcopy(current)
        merged.update(incoming)
    env_values = {}
    for key in SECRET_KEYS:
        if key == "LOGIN_PASSWORD":
            merged["LOGIN_PASSWORD"] = ""
            continue
        value = _normalize_secret(merged.get(key, "")) if key.endswith("_KEY") or key.endswith("_PASSWORD") else merged.get(key, "")
        if key in ("WEBUI_PASSWORD_HASH", "FLASK_SECRET_KEY"):
            value = merged.get(key, "") or ""
        env_values[key] = value
        merged[key] = value
    if not env_values.get("FLASK_SECRET_KEY"):
        env_values["FLASK_SECRET_KEY"] = current.get("FLASK_SECRET_KEY") or secrets.token_hex(24)
        merged["FLASK_SECRET_KEY"] = env_values["FLASK_SECRET_KEY"]
    public = {k: v for k, v in merged.items() if k not in SECRET_KEYS}
    lock = FileLock(LOCAL_CONFIG_PATH + ".lock")
    with lock:
        _atomic_write(LOCAL_CONFIG_PATH, json.dumps(public, ensure_ascii=False, indent=2) + "\n")
        _write_env(env_values)
    _cache["data"] = deepcopy(merged)
    try:
        _cache["mtime"] = (os.path.getmtime(LOCAL_CONFIG_PATH), os.path.getmtime(ENV_PATH) if os.path.exists(ENV_PATH) else 0)
    except OSError:
        _cache["mtime"] = None
    return deepcopy(merged)


def get_value(key: str, default=None):
    cfg = load_config()
    return cfg.get(key, default)


def apply_to_module(module, config: Optional[dict] = None) -> None:
    cfg = config or load_config()
    for key, value in cfg.items():
        setattr(module, key, value)


def ensure_example_files() -> None:
    if not os.path.exists(EXAMPLE_CONFIG_PATH):
        public = {k: v for k, v in get_default_config().items() if k not in SECRET_KEYS}
        _atomic_write(EXAMPLE_CONFIG_PATH, json.dumps(public, ensure_ascii=False, indent=2) + "\n")
    if not os.path.exists(ENV_EXAMPLE_PATH):
        _atomic_write(ENV_EXAMPLE_PATH, "\n".join([
            "DEEPSEEK_API_KEY=",
            "MOONSHOT_API_KEY=",
            "ONLINE_API_KEY=",
            "ASSISTANT_API_KEY=",
            "FORUM_API_KEY=",
            "WEBUI_PASSWORD_HASH=",
            "FLASK_SECRET_KEY=",
            "",
        ]))
