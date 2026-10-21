# -*- coding: utf-8 -*-
"""P1 Conversation Store：迁移幂等、ID 稳定、enabled 投影、wxid 回写。"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from conversation_store import (
    apply_listen_rows,
    apply_platform_identity,
    conversation_type_from_wxid,
    make_initial_conversation_id,
    migrate_from_listen_list,
    project_listen_list,
    validate_conversations,
    ConversationValidationError,
)


REAL_LISTEN_LIST = [
    ["ceshi", "企业_1"],
    ["哈", "企业_1"],
    ["QIYE", "QIYE"],
]


class ConversationMigrationTests(unittest.TestCase):
    def test_01_listen_list_migrates_three_conversations(self):
        result = migrate_from_listen_list({"LISTEN_LIST": REAL_LISTEN_LIST, "CONVERSATIONS": []})
        convs = result["conversations"]
        self.assertTrue(result["migrated"])
        self.assertEqual(len(convs), 3)
        names = [item["display_name"] for item in convs]
        self.assertEqual(names, ["ceshi", "哈", "QIYE"])
        for item in convs:
            self.assertTrue(item["id"].startswith("conv_"))
            self.assertEqual(item["platform"], "WECHAT")
            self.assertEqual(item["conversation_type"], "UNKNOWN")
            self.assertTrue(item["enabled"])

    def test_02_migration_is_idempotent_ten_times(self):
        cfg = {"LISTEN_LIST": REAL_LISTEN_LIST, "CONVERSATIONS": []}
        first = migrate_from_listen_list(cfg)
        ids = [item["id"] for item in first["conversations"]]
        cfg["CONVERSATIONS"] = first["conversations"]
        for _ in range(9):
            again = migrate_from_listen_list(cfg)
            self.assertFalse(again["migrated"])
            self.assertEqual([item["id"] for item in again["conversations"]], ids)
            self.assertEqual(len(again["conversations"]), 3)
            cfg["CONVERSATIONS"] = again["conversations"]
        self.assertEqual(len(set(ids)), 3)

    def test_03_conversation_id_stable_after_display_name_change(self):
        first = migrate_from_listen_list({"LISTEN_LIST": REAL_LISTEN_LIST, "CONVERSATIONS": []})
        ceshi = [item for item in first["conversations"] if item["display_name"] == "ceshi"][0]
        original_id = ceshi["id"]
        rows = [
            {
                "id": original_id,
                "display_name": "ceshi测试",
                "prompt_name": "企业_1",
                "enabled": True,
            },
            {
                "id": [item["id"] for item in first["conversations"] if item["display_name"] == "哈"][0],
                "display_name": "哈",
                "prompt_name": "企业_1",
                "enabled": True,
            },
            {
                "id": [item["id"] for item in first["conversations"] if item["display_name"] == "QIYE"][0],
                "display_name": "QIYE",
                "prompt_name": "QIYE",
                "enabled": True,
            },
        ]
        updated = apply_listen_rows({"CONVERSATIONS": first["conversations"]}, rows)
        renamed = [item for item in updated if item["display_name"] == "ceshi测试"][0]
        self.assertEqual(renamed["id"], original_id)
        self.assertNotEqual(original_id, make_initial_conversation_id("WECHAT", "ceshi测试"))

    def test_04_duplicate_display_name_rejected(self):
        convs = migrate_from_listen_list({"LISTEN_LIST": REAL_LISTEN_LIST})["conversations"]
        convs[1]["display_name"] = "ceshi"
        with self.assertRaises(ConversationValidationError) as ctx:
            validate_conversations(convs)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertIn("存在重复监听对象名称", ctx.exception.message)

    def test_05_disabled_not_projected(self):
        convs = migrate_from_listen_list({"LISTEN_LIST": REAL_LISTEN_LIST})["conversations"]
        for item in convs:
            if item["display_name"] == "哈":
                item["enabled"] = False
        projected = project_listen_list(convs)
        names = [row[0] for row in projected]
        self.assertEqual(names, ["ceshi", "QIYE"])
        self.assertNotIn("哈", names)

    def test_06_private_group_writeback_from_wxid(self):
        convs = migrate_from_listen_list({"LISTEN_LIST": REAL_LISTEN_LIST})["conversations"]
        self.assertTrue(apply_platform_identity(convs, "ceshi", "wxid_ceshi_abc"))
        ceshi = [item for item in convs if item["display_name"] == "ceshi"][0]
        self.assertEqual(ceshi["platform_conversation_id"], "wxid_ceshi_abc")
        self.assertEqual(ceshi["conversation_type"], "PRIVATE")
        self.assertEqual(conversation_type_from_wxid("123@chatroom"), "GROUP")
        self.assertTrue(apply_platform_identity(convs, "QIYE", "123456@chatroom"))
        qiye = [item for item in convs if item["display_name"] == "QIYE"][0]
        self.assertEqual(qiye["platform_conversation_id"], "123456@chatroom")
        self.assertEqual(qiye["conversation_type"], "GROUP")
        before = dict(ceshi)
        self.assertFalse(apply_platform_identity(convs, "ceshi", ""))
        self.assertEqual(ceshi["platform_conversation_id"], before["platform_conversation_id"])


if __name__ == "__main__":
    unittest.main()
