# -*- coding: utf-8 -*-
"""P3-G1 Gate 1：Topic Store 数据层。不调用 LLM。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from conversation_store import find_by_platform_conversation_id, find_conversation_by_display_name
from message.identity import InboundMessage
from topic_store import (
    DECISION_FAILED,
    DECISION_NEW_TOPIC,
    DECISION_UNRELATED,
    RELATION_CREATED_BY,
    RELATION_RELATED,
    TopicStore,
    make_message_id,
    project_inbound_to_message_record,
)


class ConversationLookupTests(unittest.TestCase):
    def test_find_by_platform_conversation_id_is_readonly_lookup(self):
        convs = [
            {
                "id": "conv_b35d9b7aaba2",
                "display_name": "ceshi",
                "platform": "WECHAT",
                "platform_conversation_id": "wxid_rvzydi2xoif022",
            },
            {
                "id": "conv_6fbe0f455b94",
                "display_name": "QIYE",
                "platform": "WECHAT",
                "platform_conversation_id": "58847495172@chatroom",
            },
        ]
        hit = find_by_platform_conversation_id(convs, "58847495172@chatroom")
        self.assertEqual(hit["id"], "conv_6fbe0f455b94")
        self.assertIsNone(find_by_platform_conversation_id(convs, "wxid_missing"))
        self.assertIsNone(find_by_platform_conversation_id(convs, ""))
        by_name = find_conversation_by_display_name(convs, "ceshi")
        self.assertEqual(by_name["id"], "conv_b35d9b7aaba2")


class TopicStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = TopicStore(self.tmpdir.name)
        self.cid_a = "conv_aaaaaaaaaaaa"
        self.cid_b = "conv_bbbbbbbbbbbb"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_message_same_platform_id_replay_does_not_duplicate(self):
        first = self.store.upsert_message(
            {
                "conversation_id": self.cid_a,
                "platform_message_id": "wxid:101",
                "sender_name": "陈总",
                "content": "ERP 同步失败了",
            }
        )
        second = self.store.upsert_message(
            {
                "conversation_id": self.cid_a,
                "platform_message_id": "wxid:101",
                "sender_name": "陈总",
                "content": "ERP 同步失败了",
            }
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["id"], make_message_id(self.cid_a, "wxid:101"))
        self.assertEqual(len(self.store.list_messages(self.cid_a)), 1)

    def test_message_id_uses_fingerprint_only_when_platform_id_missing(self):
        rec = self.store.upsert_message(
            {
                "conversation_id": self.cid_a,
                "sender_wxid": "wxid_user",
                "message_type": "text",
                "created_at": "2026-09-20T09:05:00+08:00",
                "content": "hello",
            }
        )
        self.assertTrue(rec["id"].startswith("msg_"))
        again = self.store.upsert_message(
            {
                "conversation_id": self.cid_a,
                "sender_wxid": "wxid_user",
                "message_type": "text",
                "created_at": "2026-09-20T09:05:00+08:00",
                "content": "hello",
            }
        )
        self.assertEqual(rec["id"], again["id"])
        self.assertEqual(len(self.store.list_messages(self.cid_a)), 1)

    def test_inbound_projection_uses_conversation_id_not_nickname(self):
        inbound = InboundMessage(
            platform_message_id="room:9",
            sender_name="陈总",
            conversation_id="QIYE",
            chat_name="QIYE",
            chat_wxid="58847495172@chatroom",
            content="ERP 增量同步的问题现在解决了吗？",
        )
        projected = project_inbound_to_message_record(inbound, "conv_6fbe0f455b94")
        self.assertEqual(projected["conversation_id"], "conv_6fbe0f455b94")
        self.assertNotEqual(projected["conversation_id"], inbound.conversation_id)
        self.assertTrue(projected["id"].startswith("msg_"))

    def test_topic_write_status_is_active(self):
        topic = self.store.create_topic(
            self.cid_a,
            title="ERP 数据同步异常",
            summary="增量同步失败",
            created_msg_id="msg_demo_0905",
        )
        self.assertTrue(topic["id"].startswith("topic_"))
        self.assertEqual(topic["conversation_id"], self.cid_a)
        self.assertEqual(topic["status"], "ACTIVE")
        self.assertEqual(self.store.list_topics(self.cid_a)[0]["id"], topic["id"])

    def test_link_uniqueness_and_message_count_not_doubled_on_replay(self):
        msg = self.store.upsert_message(
            {
                "conversation_id": self.cid_a,
                "platform_message_id": "m1",
                "content": "ERP 同步失败了",
            }
        )
        topic = self.store.create_topic(
            self.cid_a,
            title="ERP 数据同步异常",
            created_msg_id=msg["id"],
        )
        first = self.store.add_link(self.cid_a, topic["id"], msg["id"], RELATION_CREATED_BY)
        second = self.store.add_link(self.cid_a, topic["id"], msg["id"], RELATION_CREATED_BY)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_links(self.cid_a)), 1)
        stored = self.store.get_topic(self.cid_a, topic["id"])
        self.assertEqual(stored["message_count"], 1)
        self.store.add_link(self.cid_a, topic["id"], msg["id"], RELATION_RELATED)
        self.assertEqual(len(self.store.list_links(self.cid_a)), 2)
        stored = self.store.get_topic(self.cid_a, topic["id"])
        self.assertEqual(stored["message_count"], 1)

    def test_processing_success_replay_skips_and_failed_can_retry(self):
        msg_id = "msg_proc_000001"
        success = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision": DECISION_NEW_TOPIC,
                "topic_id": "topic_abc",
            }
        )
        replay = self.store.write_processing(
            {
                "message_id": msg_id,
                "conversation_id": self.cid_a,
                "decision": DECISION_UNRELATED,
            }
        )
        self.assertEqual(replay["decision"], DECISION_NEW_TOPIC)
        self.assertEqual(replay["topic_id"], success["topic_id"])
        self.assertTrue(self.store.has_successful_processing(self.cid_a, msg_id))

        fail_id = "msg_proc_failed01"
        self.store.write_processing(
            {
                "message_id": fail_id,
                "conversation_id": self.cid_a,
                "decision": DECISION_FAILED,
                "error": "timeout",
            }
        )
        self.assertFalse(self.store.has_successful_processing(self.cid_a, fail_id))
        retried = self.store.write_processing(
            {
                "message_id": fail_id,
                "conversation_id": self.cid_a,
                "decision": DECISION_UNRELATED,
            }
        )
        self.assertEqual(retried["decision"], DECISION_UNRELATED)
        self.assertTrue(self.store.has_successful_processing(self.cid_a, fail_id))

    def test_conversations_are_isolated(self):
        self.store.upsert_message(
            {"conversation_id": self.cid_a, "platform_message_id": "a1", "content": "A"}
        )
        self.store.upsert_message(
            {"conversation_id": self.cid_b, "platform_message_id": "b1", "content": "B"}
        )
        topic_a = self.store.create_topic(self.cid_a, title="A 主题", created_msg_id="msg_a")
        topic_b = self.store.create_topic(self.cid_b, title="B 主题", created_msg_id="msg_b")
        self.assertEqual(len(self.store.list_messages(self.cid_a)), 1)
        self.assertEqual(len(self.store.list_messages(self.cid_b)), 1)
        self.assertEqual(self.store.list_topics(self.cid_a)[0]["id"], topic_a["id"])
        self.assertEqual(self.store.list_topics(self.cid_b)[0]["id"], topic_b["id"])
        self.assertNotEqual(topic_a["id"], topic_b["id"])

    def test_delete_conversation_topic_data_removes_all(self):
        msg = self.store.upsert_message(
            {"conversation_id": self.cid_a, "platform_message_id": "del1", "content": "x"}
        )
        topic = self.store.create_topic(self.cid_a, title="待删", created_msg_id=msg["id"])
        self.store.add_link(self.cid_a, topic["id"], msg["id"], RELATION_CREATED_BY)
        self.store.write_processing(
            {
                "message_id": msg["id"],
                "conversation_id": self.cid_a,
                "decision": DECISION_NEW_TOPIC,
                "topic_id": topic["id"],
            }
        )
        self.store.upsert_message(
            {"conversation_id": self.cid_b, "platform_message_id": "keep", "content": "keep"}
        )
        self.assertTrue(self.store.delete_conversation_topic_data(self.cid_a))
        self.assertEqual(self.store.list_messages(self.cid_a), [])
        self.assertEqual(self.store.list_topics(self.cid_a), [])
        self.assertEqual(self.store.list_links(self.cid_a), [])
        self.assertIsNone(self.store.get_processing(self.cid_a, msg["id"]))
        self.assertEqual(len(self.store.list_messages(self.cid_b)), 1)


if __name__ == "__main__":
    unittest.main()
