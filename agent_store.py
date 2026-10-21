# -*- coding: utf-8 -*-
"""P2 AgentConfig 与 Chat Prompt 绑定。

Conversation → AgentConfig → Chat Prompt
Extractor Prompt 本轮只预留字段，不实现 Topic Extractor。

禁止把微信回复 Prompt 与 Topic JSON Prompt 写进同一个 md。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

from conversation_store import utc_now_iso

AGENT_TYPE_PROJECT_COLLABORATION = "PROJECT_COLLABORATION"
AGENT_UNAVAILABLE_USER_MESSAGE = "当前智能体配置不可用，请检查 Prompt 配置。"

AGENT_CONFIG_NOT_FOUND = "AGENT_CONFIG_NOT_FOUND"
CHAT_PROMPT_NOT_BOUND = "CHAT_PROMPT_NOT_BOUND"
PROMPT_FILE_NOT_FOUND = "PROMPT_FILE_NOT_FOUND"
PROMPT_EMPTY = "PROMPT_EMPTY"
EXTRACTOR_PROMPT_NOT_FOUND = "EXTRACTOR_PROMPT_NOT_FOUND"
EXTRACTOR_PROMPT_EMPTY = "EXTRACTOR_PROMPT_EMPTY"
DEFAULT_EXTRACTOR_PROMPT_NAME = "TOPIC_EXTRACTOR"

PROMPT_IN_USE = "PROMPT_IN_USE"
PROMPT_RENAME_FORBIDDEN = "PROMPT_RENAME_FORBIDDEN"


class PromptResolveError(Exception):
    def __init__(self, code: str, message: str, detail: str = "", **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message
        self.extra = extra


@dataclass
class PromptBinding:
    content: str
    conversation_id: str = ""
    agent_config_id: str = ""
    prompt_name: str = ""
    prompt_hash: str = ""
    display_name: str = ""


@dataclass
class ExtractorPromptBinding:
    content: str
    prompt_name: str = ""
    prompt_hash: str = ""
    path: str = ""


def sha256_text(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def make_agent_id(prompt_name: str) -> str:
    seed = "%s|%s" % (AGENT_TYPE_PROJECT_COLLABORATION, prompt_name or "")
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return "agt_%s" % digest


def empty_agent_config(prompt_name: str, *, name: str = "", agent_id: str = "") -> dict:
    prompt = str(prompt_name or "").strip()
    now = utc_now_iso()
    display = str(name or "").strip() or ("智群 · 项目协同 Agent · %s" % prompt if prompt else "智群 · 项目协同 Agent")
    return {
        "id": agent_id or make_agent_id(prompt),
        "name": display,
        "agent_type": AGENT_TYPE_PROJECT_COLLABORATION,
        "enabled": True,
        "chat_prompt_name": prompt,
        "chat_prompt_hash": "",
        "extractor_prompt_name": None,
        "reply_policy": "INHERIT",
        "model_config": "INHERIT",
        "context_policy": "INHERIT",
        "created_at": now,
        "updated_at": now,
    }


def normalize_agent(raw: dict) -> dict:
    data = raw if isinstance(raw, dict) else {}
    prompt_name = str(data.get("chat_prompt_name") or "").strip()
    now = utc_now_iso()
    extractor = data.get("extractor_prompt_name", None)
    if extractor is not None:
        extractor = str(extractor).strip() or None
    return {
        "id": str(data.get("id") or "").strip() or make_agent_id(prompt_name),
        "name": str(data.get("name") or "").strip() or ("智群 · 项目协同 Agent · %s" % prompt_name),
        "agent_type": str(data.get("agent_type") or AGENT_TYPE_PROJECT_COLLABORATION),
        "enabled": bool(data.get("enabled", True)),
        "chat_prompt_name": prompt_name,
        "chat_prompt_hash": str(data.get("chat_prompt_hash") or ""),
        "extractor_prompt_name": extractor,
        "reply_policy": str(data.get("reply_policy") or "INHERIT"),
        "model_config": str(data.get("model_config") or "INHERIT"),
        "context_policy": str(data.get("context_policy") or "INHERIT"),
        "created_at": str(data.get("created_at") or now),
        "updated_at": str(data.get("updated_at") or now),
    }


def ensure_agents_for_conversations(
    conversations: list,
    agents: Optional[list] = None,
    *,
    prompt_root: Optional[str] = None,
) -> list:
    """多个 Conversation 共享同一 Prompt 时只生成一个 AgentConfig。幂等。"""
    existing = [normalize_agent(item) for item in (agents or []) if isinstance(item, dict)]
    by_id = {item["id"]: item for item in existing}
    by_prompt = {}
    for item in existing:
        prompt = item.get("chat_prompt_name") or ""
        if prompt and prompt not in by_prompt:
            by_prompt[prompt] = item

    result = list(existing)
    now = utc_now_iso()
    for conv in conversations or []:
        metadata = conv.get("metadata") if isinstance(conv.get("metadata"), dict) else {}
        prompt_name = str(metadata.get("prompt_name") or "").strip()
        agent_id = str(conv.get("agent_config_id") or "").strip()
        agent = None
        created = False
        if agent_id and agent_id in by_id:
            agent = by_id[agent_id]
        elif prompt_name and prompt_name in by_prompt:
            agent = by_prompt[prompt_name]
        elif prompt_name:
            agent = empty_agent_config(prompt_name)
            created = True
            result.append(agent)
            by_id[agent["id"]] = agent
            by_prompt[prompt_name] = agent
        if not agent:
            continue
        if prompt_name and agent.get("chat_prompt_name") != prompt_name:
            agent["chat_prompt_name"] = prompt_name
            agent["updated_at"] = now
            by_prompt[prompt_name] = agent
        if prompt_root and prompt_name:
            digest = hash_prompt_file(prompt_root, prompt_name)
            if digest and agent.get("chat_prompt_hash") != digest:
                agent["chat_prompt_hash"] = digest
                if not created:
                    agent["updated_at"] = now
        if conv.get("agent_config_id") != agent["id"]:
            conv["agent_config_id"] = agent["id"]
            conv["updated_at"] = now
        if prompt_name:
            metadata["prompt_name"] = prompt_name
            conv["metadata"] = metadata
    return result


def hash_prompt_file(prompt_root: str, prompt_name: str) -> str:
    path = os.path.join(prompt_root, "prompts", "%s.md" % prompt_name)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sha256_text(f.read())
    except OSError:
        return ""


def agents_using_prompt(agents: Iterable[dict], prompt_name: str) -> list:
    name = str(prompt_name or "").strip()
    if name.endswith(".md"):
        name = name[:-3]
    hits = []
    for agent in agents or []:
        if str(agent.get("chat_prompt_name") or "").strip() == name:
            hits.append(agent)
        extractor = agent.get("extractor_prompt_name")
        if extractor and str(extractor).strip() == name:
            hits.append(agent)
    return hits


def listen_list_using_prompt(listen_list: Iterable, prompt_name: str) -> list:
    name = str(prompt_name or "").strip()
    if name.endswith(".md"):
        name = name[:-3]
    hits = []
    for row in listen_list or []:
        if isinstance(row, (list, tuple)) and len(row) > 1 and str(row[1] or "").strip() == name:
            hits.append(row)
    return hits


def update_agents_prompt_hash(agents: list, prompt_name: str, content: str) -> list:
    name = str(prompt_name or "").strip()
    if name.endswith(".md"):
        name = name[:-3]
    digest = sha256_text(content or "")
    now = utc_now_iso()
    for agent in agents or []:
        if str(agent.get("chat_prompt_name") or "").strip() == name:
            agent["chat_prompt_hash"] = digest
            agent["updated_at"] = now
    return agents


def find_agent(agents: Iterable[dict], agent_id: str) -> Optional[dict]:
    target = str(agent_id or "").strip()
    if not target:
        return None
    for agent in agents or []:
        if str(agent.get("id") or "") == target:
            return agent
    return None


def resolve_chat_prompt(
    user_id: str,
    *,
    conversations: Optional[list] = None,
    agents: Optional[list] = None,
    prompt_mapping: Optional[dict] = None,
    root_dir: str = "",
) -> PromptBinding:
    """解析 Chat Prompt。未命中或文件异常时明确失败，禁止用 nickname 当文件名，禁止默认助手。"""
    display_name = str(user_id or "").strip()
    conversations = list(conversations or [])
    agents = list(agents or [])
    mapping = dict(prompt_mapping or {})

    conversation = None
    for conv in conversations:
        if str(conv.get("display_name") or "").strip() == display_name:
            conversation = conv
            break

    agent = None
    prompt_name = ""
    conversation_id = ""
    agent_id = ""

    if conversation:
        conversation_id = str(conversation.get("id") or "")
        agent_id = str(conversation.get("agent_config_id") or "").strip()
        if not agent_id:
            raise PromptResolveError(
                AGENT_CONFIG_NOT_FOUND,
                "Conversation 未绑定 AgentConfig",
                "display_name=%s conversation_id=%s" % (display_name, conversation_id),
                conversation_id=conversation_id,
            )
        agent = find_agent(agents, agent_id)
        if agent is None:
            raise PromptResolveError(
                AGENT_CONFIG_NOT_FOUND,
                "找不到 AgentConfig",
                "agent_config_id=%s display_name=%s" % (agent_id, display_name),
                conversation_id=conversation_id,
                agent_config_id=agent_id,
            )
        prompt_name = str(agent.get("chat_prompt_name") or "").strip()
        if not prompt_name:
            raise PromptResolveError(
                CHAT_PROMPT_NOT_BOUND,
                "AgentConfig 未绑定 Chat Prompt",
                "agent_config_id=%s" % agent_id,
                conversation_id=conversation_id,
                agent_config_id=agent_id,
            )
    elif display_name in mapping:
        prompt_name = str(mapping.get(display_name) or "").strip()
        if not prompt_name:
            raise PromptResolveError(
                CHAT_PROMPT_NOT_BOUND,
                "未绑定 Chat Prompt",
                "display_name=%s" % display_name,
            )
    else:
        raise PromptResolveError(
            AGENT_CONFIG_NOT_FOUND,
            "找不到对应的 AgentConfig / Prompt 绑定",
            "display_name=%s" % display_name,
        )

    prompt_path = os.path.join(root_dir or "", "prompts", "%s.md" % prompt_name)
    if not os.path.isfile(prompt_path):
        raise PromptResolveError(
            PROMPT_FILE_NOT_FOUND,
            "Prompt 文件不存在",
            "prompt=%s path=%s" % (prompt_name, prompt_path),
            conversation_id=conversation_id,
            agent_config_id=agent_id,
            prompt_name=prompt_name,
        )

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        content = None
        for encoding in ("gbk", "gb2312", "latin-1", "cp1252"):
            try:
                with open(prompt_path, "r", encoding=encoding) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, OSError):
                continue
        if content is None:
            raise PromptResolveError(
                PROMPT_FILE_NOT_FOUND,
                "无法读取 Prompt 文件",
                prompt_path,
                prompt_name=prompt_name,
            )
    except OSError as exc:
        raise PromptResolveError(
            PROMPT_FILE_NOT_FOUND,
            "无法读取 Prompt 文件",
            str(exc),
            prompt_name=prompt_name,
        )

    if not str(content or "").strip():
        raise PromptResolveError(
            PROMPT_EMPTY,
            "Prompt 文件为空",
            "prompt=%s" % prompt_name,
            conversation_id=conversation_id,
            agent_config_id=agent_id,
            prompt_name=prompt_name,
        )

    digest = sha256_text(content)
    return PromptBinding(
        content=content,
        conversation_id=conversation_id,
        agent_config_id=agent_id,
        prompt_name=prompt_name,
        prompt_hash=digest,
        display_name=display_name,
    )


def _safe_extractor_prompt_name(prompt_name: str) -> str:
    name = str(prompt_name or "").strip()
    if name.endswith(".md"):
        name = name[:-3]
    name = name.replace("\\", "/").split("/")[-1]
    if not name or ".." in name:
        return ""
    return name


def resolve_extractor_prompt(
    prompt_name: str = DEFAULT_EXTRACTOR_PROMPT_NAME,
    *,
    root_dir: str = "",
) -> ExtractorPromptBinding:
    """读取 Topic Extractor Prompt。禁止走 Chat loader，禁止 fallback 到 Chat Prompt。"""
    name = _safe_extractor_prompt_name(prompt_name) or DEFAULT_EXTRACTOR_PROMPT_NAME
    prompt_path = os.path.join(root_dir or "", "prompts", "extractors", "%s.md" % name)
    if not os.path.isfile(prompt_path):
        raise PromptResolveError(
            EXTRACTOR_PROMPT_NOT_FOUND,
            "Extractor Prompt 文件不存在",
            "prompt=%s path=%s" % (name, prompt_path),
            prompt_name=name,
        )
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        raise PromptResolveError(
            EXTRACTOR_PROMPT_NOT_FOUND,
            "无法读取 Extractor Prompt 文件",
            str(exc),
            prompt_name=name,
        )
    if not str(content or "").strip():
        raise PromptResolveError(
            EXTRACTOR_PROMPT_EMPTY,
            "Extractor Prompt 文件为空",
            "prompt=%s" % name,
            prompt_name=name,
        )
    return ExtractorPromptBinding(
        content=content,
        prompt_name=name,
        prompt_hash=sha256_text(content),
        path=prompt_path,
    )
