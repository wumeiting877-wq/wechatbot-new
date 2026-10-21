# -*- coding: utf-8 -*-
"""P1/P2 live pretest: bind ceshi/哈 to temporary A/B prompts.

Writes only config.local.json. Does not touch .env.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conversation_store import apply_listen_rows, project_listen_list
from agent_store import ensure_agents_for_conversations, sha256_text
CONFIG = ROOT / "config.local.json"


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    rows = [
        {"id": "conv_b35d9b7aaba2", "display_name": "ceshi", "prompt_name": "P1P2_TEST_A", "enabled": True},
        {"id": "conv_2f82b3dbce7e", "display_name": "哈", "prompt_name": "P1P2_TEST_B", "enabled": True},
        {"id": "conv_6fbe0f455b94", "display_name": "QIYE", "prompt_name": "QIYE", "enabled": True},
    ]
    conversations = apply_listen_rows(cfg, rows)
    for conv in conversations:
        if conv.get("display_name") in ("ceshi", "哈"):
            conv["agent_config_id"] = ""
    agents = ensure_agents_for_conversations(
        conversations,
        cfg.get("AGENT_CONFIGS") or [],
        prompt_root=str(ROOT),
    )
    listen = project_listen_list(conversations, agents)
    cfg["CONVERSATIONS"] = conversations
    cfg["AGENT_CONFIGS"] = agents
    cfg["LISTEN_LIST"] = listen
    cfg["ENABLE_EMOJI_SENDING"] = False
    cfg["UPLOAD_MEMORY_TO_AI"] = False
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("LISTEN_LIST", json.dumps(listen, ensure_ascii=False))
    for c in conversations:
        print(
            "CONV",
            c["id"],
            c["display_name"],
            "enabled=",
            c["enabled"],
            "agent=",
            c["agent_config_id"],
            "wxid=",
            c.get("platform_conversation_id"),
            "type=",
            c.get("conversation_type"),
            "prompt=",
            (c.get("metadata") or {}).get("prompt_name"),
        )
    for a in agents:
        print(
            "AGT",
            a["id"],
            a["chat_prompt_name"],
            a.get("chat_prompt_hash", "")[:12],
        )
    a_text = (ROOT / "prompts" / "P1P2_TEST_A.md").read_text(encoding="utf-8")
    b_text = (ROOT / "prompts" / "P1P2_TEST_B.md").read_text(encoding="utf-8")
    print("A_HASH", sha256_text(a_text))
    print("B_HASH", sha256_text(b_text))
    print("QIYE_MD", (ROOT / "prompts" / "QIYE.md").exists())
    print("QIYE_1_MD", (ROOT / "prompts" / "企业_1.md").exists())


if __name__ == "__main__":
    main()
