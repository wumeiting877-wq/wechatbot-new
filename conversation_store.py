# -*- coding: utf-8 -*-
"""P1 Conversation 存储与 LISTEN_LIST 兼容适配器。

业务权威源：CONVERSATIONS
兼容投影：LISTEN_LIST / user_names / prompt_mapping

约束：
- 第一阶段只实现 platform=WECHAT
- Conversation.id 在首次迁移时可由 WECHAT+nickname 生成
- ID 一旦持久化，不随 display_name / nickname 变化而重生
- 不删除 LISTEN_LIST
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

PLATFORM_WECHAT = "WECHAT"
CONVERSATION_TYPES = ("UNKNOWN", "PRIVATE", "GROUP")
ALLOWED_PLATFORMS = ("WECHAT",)

SOURCE_LISTEN_LIST_V1 = "listen_list_v1"


class ConversationValidationError(ValueError):
    def __init__(self, code: str, message: str, detail: str = "", **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message
        self.extra = extra


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_initial_conversation_id(platform: str, nickname: str) -> str:
    """仅用于第一次从 LISTEN_LIST 迁移。不得在 display_name 变更后再次调用以替换已有 ID。"""
    seed = "%s|%s" % (platform or PLATFORM_WECHAT, nickname or "")
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return "conv_%s" % digest


def conversation_type_from_wxid(wxid: str) -> str:
    text = str(wxid or "").strip()
    if not text:
        return "UNKNOWN"
    if text.endswith("@chatroom"):
        return "GROUP"
    return "PRIVATE"


def _as_bool(value, default=True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no", ""):
        return False
    return default


def empty_conversation(
    display_name: str,
    *,
    conversation_id: str = "",
    platform: str = PLATFORM_WECHAT,
    prompt_name: str = "",
    enabled: bool = True,
    agent_config_id: str = "",
    source: str = SOURCE_LISTEN_LIST_V1,
) -> dict:
    now = utc_now_iso()
    name = str(display_name or "").strip()
    cid = conversation_id or make_initial_conversation_id(platform, name)
    return {
        "id": cid,
        "platform": platform,
        "platform_conversation_id": "",
        "conversation_type": "UNKNOWN",
        "display_name": name,
        "enabled": bool(enabled),
        "agent_config_id": agent_config_id or "",
        "reply_policy": "INHERIT",
        "permission_scope": "DEFAULT",
        "metadata": {
            "nickname": name,
            "source": source,
            "prompt_name": prompt_name or "",
        },
        "created_at": now,
        "updated_at": now,
    }


def normalize_conversation(raw: dict) -> dict:
    data = raw if isinstance(raw, dict) else {}
    display_name = str(data.get("display_name") or "").strip()
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    nickname = str(metadata.get("nickname") or display_name).strip()
    platform = str(data.get("platform") or PLATFORM_WECHAT).strip().upper() or PLATFORM_WECHAT
    cid = str(data.get("id") or "").strip() or make_initial_conversation_id(platform, display_name or nickname)
    conv_type = str(data.get("conversation_type") or "UNKNOWN").strip().upper()
    if conv_type not in CONVERSATION_TYPES:
        conv_type = "UNKNOWN"
    now = utc_now_iso()
    return {
        "id": cid,
        "platform": platform,
        "platform_conversation_id": str(data.get("platform_conversation_id") or "").strip(),
        "conversation_type": conv_type,
        "display_name": display_name,
        "enabled": _as_bool(data.get("enabled"), True),
        "agent_config_id": str(data.get("agent_config_id") or "").strip(),
        "reply_policy": str(data.get("reply_policy") or "INHERIT"),
        "permission_scope": str(data.get("permission_scope") or "DEFAULT"),
        "metadata": {
            "nickname": nickname or display_name,
            "source": str(metadata.get("source") or SOURCE_LISTEN_LIST_V1),
            "prompt_name": str(metadata.get("prompt_name") or ""),
        },
        "created_at": str(data.get("created_at") or now),
        "updated_at": str(data.get("updated_at") or now),
    }


def conversations_present(config: Optional[dict]) -> bool:
    convs = (config or {}).get("CONVERSATIONS")
    return isinstance(convs, list) and len(convs) > 0


def migrate_from_listen_list(config: Optional[dict], agents: Optional[list] = None) -> dict:
    """若 CONVERSATIONS 为空，从 LISTEN_LIST 生成；若已存在则原样返回（幂等）。

    返回:
        {
          "conversations": [...],
          "migrated": bool,
          "listen_list": 投影后的 LISTEN_LIST,
        }
    """
    cfg = config or {}
    existing = [normalize_conversation(item) for item in (cfg.get("CONVERSATIONS") or []) if isinstance(item, dict)]
    agent_list = list(agents if agents is not None else (cfg.get("AGENT_CONFIGS") or []))
    if existing:
        return {
            "conversations": existing,
            "migrated": False,
            "listen_list": project_listen_list(existing, agent_list),
        }

    listen = cfg.get("LISTEN_LIST") or []
    conversations = []
    used_ids = set()
    for row in listen:
        if not isinstance(row, (list, tuple)) or len(row) < 1:
            continue
        nickname = str(row[0] or "").strip()
        prompt_name = str(row[1] or "").strip() if len(row) > 1 else ""
        if not nickname:
            continue
        cid = make_initial_conversation_id(PLATFORM_WECHAT, nickname)
        if cid in used_ids:
            suffix = 2
            while "%s_%s" % (cid, suffix) in used_ids:
                suffix += 1
            cid = "%s_%s" % (cid, suffix)
        used_ids.add(cid)
        conv = empty_conversation(
            nickname,
            conversation_id=cid,
            prompt_name=prompt_name,
            enabled=True,
        )
        conversations.append(conv)
    return {
        "conversations": conversations,
        "migrated": True,
        "listen_list": project_listen_list(conversations, agent_list),
    }


def prompt_name_of(conversation: dict, agents: Optional[Iterable[dict]] = None) -> str:
    agent_id = str((conversation or {}).get("agent_config_id") or "").strip()
    metadata = (conversation or {}).get("metadata") if isinstance((conversation or {}).get("metadata"), dict) else {}
    fallback = str(metadata.get("prompt_name") or "").strip()
    if not agent_id:
        return fallback
    for agent in agents or []:
        if str(agent.get("id") or "") == agent_id:
            return str(agent.get("chat_prompt_name") or fallback).strip()
    return fallback


def project_listen_list(conversations: Iterable[dict], agents: Optional[Iterable[dict]] = None) -> list:
    """只投影 enabled=true 的 Conversation。P0 仍使用 display_name。"""
    result = []
    for conv in conversations or []:
        if not isinstance(conv, dict):
            continue
        if not _as_bool(conv.get("enabled"), True):
            continue
        name = str(conv.get("display_name") or "").strip()
        if not name:
            continue
        prompt = prompt_name_of(conv, agents)
        result.append([name, prompt])
    return result


def project_runtime(conversations: Iterable[dict], agents: Optional[Iterable[dict]] = None) -> dict:
    listen = project_listen_list(conversations, agents)
    return {
        "user_names": [row[0] for row in listen],
        "prompt_mapping": {row[0]: row[1] for row in listen},
        "LISTEN_LIST": listen,
    }


def find_duplicate_display_names(conversations: Iterable[dict], enabled_only: bool = False) -> list:
    seen = {}
    duplicates = []
    for conv in conversations or []:
        if not isinstance(conv, dict):
            continue
        if enabled_only and not _as_bool(conv.get("enabled"), True):
            continue
        name = str(conv.get("display_name") or "").strip()
        if not name:
            continue
        if name in seen:
            duplicates.append(name)
        else:
            seen[name] = conv.get("id")
    return duplicates


def validate_conversations(conversations: Iterable[dict]) -> None:
    items = [normalize_conversation(item) for item in (conversations or [])]
    ids = []
    for conv in items:
        if conv["platform"] not in ALLOWED_PLATFORMS:
            raise ConversationValidationError(
                "VALIDATION_ERROR",
                "第一阶段只支持微信 Conversation",
                "platform=%s" % conv["platform"],
            )
        if not conv["display_name"]:
            raise ConversationValidationError("VALIDATION_ERROR", "监听对象名称不能为空")
        if not conv["id"]:
            raise ConversationValidationError("VALIDATION_ERROR", "Conversation 缺少内部 id")
        ids.append(conv["id"])
    if len(ids) != len(set(ids)):
        raise ConversationValidationError("VALIDATION_ERROR", "Conversation id 重复")
    duplicates = find_duplicate_display_names(items, enabled_only=False)
    if duplicates:
        raise ConversationValidationError(
            "VALIDATION_ERROR",
            "存在重复监听对象名称。",
            "display_name=%s" % duplicates[0],
            field="nickname",
        )
    enabled_dupes = find_duplicate_display_names(items, enabled_only=True)
    if enabled_dupes:
        raise ConversationValidationError(
            "VALIDATION_ERROR",
            "存在重复监听对象名称。",
            "display_name=%s" % enabled_dupes[0],
            field="nickname",
        )


def conversations_for_ui(config: Optional[dict]) -> list:
    """展示用：已有 CONVERSATIONS 则用之；否则从 LISTEN_LIST 内存迁移，不落盘。"""
    migrated = migrate_from_listen_list(config or {})
    return migrated["conversations"]


def apply_listen_rows(config: Optional[dict], rows: list) -> list:
    """用表单行更新 Conversation 列表。保留已有 id，不随改名重生。"""
    cfg = config or {}
    existing = conversations_for_ui(cfg)
    by_id = {item["id"]: item for item in existing}
    by_name = {item["display_name"]: item for item in existing}
    used_ids = set()
    result = []
    now = utc_now_iso()
    for row in rows or []:
        display_name = str(row.get("display_name") or row.get("nickname") or "").strip()
        prompt_name = str(row.get("prompt_name") or row.get("prompt_file") or "").strip()
        enabled = _as_bool(row.get("enabled"), True)
        requested_id = str(row.get("id") or row.get("conversation_id") or "").strip()
        prev = None
        if requested_id and requested_id in by_id and requested_id not in used_ids:
            prev = copy.deepcopy(by_id[requested_id])
        elif display_name in by_name and by_name[display_name]["id"] not in used_ids:
            prev = copy.deepcopy(by_name[display_name])
        if prev:
            conv = prev
            conv["display_name"] = display_name
            conv["enabled"] = enabled
            metadata = conv.get("metadata") if isinstance(conv.get("metadata"), dict) else {}
            metadata["nickname"] = display_name
            metadata["prompt_name"] = prompt_name
            conv["metadata"] = metadata
            conv["updated_at"] = now
        else:
            conv = empty_conversation(
                display_name,
                conversation_id=requested_id,
                prompt_name=prompt_name,
                enabled=enabled,
            )
        used_ids.add(conv["id"])
        result.append(conv)
    validate_conversations(result)
    return result


def apply_platform_identity(conversations: list, display_name: str, wxid: str) -> bool:
    """启动装配阶段回写 wxid / PRIVATE|GROUP。wxid 为空时不写错误值。"""
    name = str(display_name or "").strip()
    platform_id = str(wxid or "").strip()
    if not name:
        return False
    if not platform_id:
        return False
    conv_type = conversation_type_from_wxid(platform_id)
    now = utc_now_iso()
    changed = False
    for conv in conversations or []:
        if str(conv.get("display_name") or "").strip() != name:
            continue
        if conv.get("platform_conversation_id") != platform_id or conv.get("conversation_type") != conv_type:
            conv["platform_conversation_id"] = platform_id
            conv["conversation_type"] = conv_type
            conv["updated_at"] = now
            changed = True
        break
    return changed


def find_conversation_by_display_name(conversations: Iterable[dict], display_name: str) -> Optional[dict]:
    name = str(display_name or "").strip()
    for conv in conversations or []:
        if str(conv.get("display_name") or "").strip() == name:
            return conv
    return None


def find_by_platform_conversation_id(
    conversations: Iterable[dict],
    platform_conversation_id: str,
) -> Optional[dict]:
    """只读查找。按微信侧稳定 id（wxid / @chatroom）匹配，不改 Conversation.id 规则。"""
    platform_id = str(platform_conversation_id or "").strip()
    if not platform_id:
        return None
    for conv in conversations or []:
        if not isinstance(conv, dict):
            continue
        if str(conv.get("platform_conversation_id") or "").strip() == platform_id:
            return conv
    return None
