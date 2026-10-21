# -*- coding: utf-8 -*-
"""P6-G5 Gate 1 探针：不改生产代码，证明 Topic FAILED → 同 MessageRecord 再 process 可 SUCCESS。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decision_extractor_client import HeuristicDecisionExtractor
from decision_sidepath import DecisionSidepath
from risk_extractor_client import HeuristicRiskExtractor
from risk_sidepath import RiskSidepath
from task_extractor_client import HeuristicTaskExtractor
from task_sidepath import TaskSidepath
from topic_engine import TopicEngine
from topic_extractor_client import HeuristicTopicExtractor
from topic_sidepath import TopicSidepath
from topic_store import DECISION_FAILED, TopicStore

CONV = {
    "id": "conv_p6g5probe01",
    "platform": "WECHAT",
    "platform_conversation_id": "room_p6g5@chatroom",
    "conversation_type": "GROUP",
    "display_name": "测试群",
    "enabled": True,
}

NEW_TOPIC_TEXT = "ERP 同步今天还是有问题。"
EXISTING_TEXT = "ERP 同步供应商编码还是空。"
UPDATE_TEXT = "ERP 同步规则需要修复。"


class CountingExtractor:
    def __init__(self, inner=None, *, boom=False):
        self.inner = inner
        self.boom = boom
        self.calls = 0

    def extract(self, engine_input, prompt_content):
        self.calls += 1
        if self.boom:
            raise TimeoutError("p6g5 probe boom")
        return self.inner.extract(engine_input, prompt_content)


class P6G5TopicFailedRetryProbe(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmpdir.name
        self.store = TopicStore(self.root)
        self.topic_ext = CountingExtractor(HeuristicTopicExtractor(), boom=True)

    def tearDown(self):
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass

    def _record(self, msg_id, content, pid=None):
        return {
            "id": msg_id,
            "conversation_id": CONV["id"],
            "platform_message_id": pid or msg_id,
            "sender_name": "张三",
            "content": content,
            "created_at": "2026-09-22T21:00:00+08:00",
            "direction": "INBOUND",
            "message_type": "text",
        }

    def _engine(self, extractor):
        return TopicEngine(
            self.store,
            extractor=extractor,
            root_dir=ROOT,
            enabled=True,
        )

    def test_probe_failed_then_new_topic_overwrites_processing(self):
        record = self._record("msg_p6g5_new", NEW_TOPIC_TEXT)
        first = self._engine(self.topic_ext).process_record(record, CONV)
        self.assertEqual(first.decision, DECISION_FAILED)
        self.assertFalse(first.replayed)
        self.assertEqual(self.topic_ext.calls, 1)
        rec = self.store.get_processing(CONV["id"], record["id"])
        self.assertEqual(rec["decision"], DECISION_FAILED)
        self.assertFalse(self.store.has_successful_processing(CONV["id"], record["id"]))
        self.assertEqual(self.store.list_topics(CONV["id"]), [])

        self.topic_ext.boom = False
        second = self._engine(self.topic_ext).process_record(record, CONV)
        self.assertEqual(second.decision, "NEW_TOPIC")
        self.assertFalse(second.replayed)
        self.assertTrue(second.topic_id)
        self.assertEqual(self.topic_ext.calls, 2)
        rec2 = self.store.get_processing(CONV["id"], record["id"])
        self.assertEqual(rec2["decision"], "NEW_TOPIC")
        self.assertEqual(rec2["topic_id"], second.topic_id)
        self.assertTrue(self.store.has_successful_processing(CONV["id"], record["id"]))

        third = self._engine(self.topic_ext).process_record(record, CONV)
        self.assertTrue(third.replayed)
        self.assertEqual(self.topic_ext.calls, 2)

    def test_probe_failed_then_existing_and_update(self):
        seed = self._record("msg_p6g5_seed", NEW_TOPIC_TEXT, pid="seed")
        self.topic_ext.boom = False
        seeded = self._engine(self.topic_ext).process_record(seed, CONV)
        self.assertEqual(seeded.decision, "NEW_TOPIC")

        fail_ext = CountingExtractor(HeuristicTopicExtractor(), boom=True)
        existing_rec = self._record("msg_p6g5_exist", EXISTING_TEXT, pid="exist")
        failed_existing = self._engine(fail_ext).process_record(existing_rec, CONV)
        self.assertEqual(failed_existing.decision, DECISION_FAILED)
        self.assertFalse(self.store.has_successful_processing(CONV["id"], existing_rec["id"]))

        fail_ext.boom = False
        recovered_existing = self._engine(fail_ext).process_record(existing_rec, CONV)
        self.assertEqual(recovered_existing.decision, "EXISTING_TOPIC")
        self.assertFalse(recovered_existing.replayed)
        self.assertEqual(fail_ext.calls, 2)

        update_ext = CountingExtractor(HeuristicTopicExtractor(), boom=True)
        update_rec = self._record("msg_p6g5_upd", UPDATE_TEXT, pid="upd")
        failed_update = self._engine(update_ext).process_record(update_rec, CONV)
        self.assertEqual(failed_update.decision, DECISION_FAILED)
        update_ext.boom = False
        recovered_update = self._engine(update_ext).process_record(update_rec, CONV)
        self.assertEqual(recovered_update.decision, "TOPIC_UPDATE")
        self.assertFalse(recovered_update.replayed)
        self.assertEqual(update_ext.calls, 2)

    def test_probe_sidepath_failed_zero_fanout(self):
        boom = CountingExtractor(HeuristicTopicExtractor(), boom=True)
        task_path = TaskSidepath(
            root_dir=self.root, extractor=HeuristicTaskExtractor(), enabled=True, maxsize=4, prompt_root=ROOT
        )
        decision_path = DecisionSidepath(
            root_dir=self.root, extractor=HeuristicDecisionExtractor(), enabled=True, maxsize=4, prompt_root=ROOT
        )
        risk_path = RiskSidepath(
            root_dir=self.root, extractor=HeuristicRiskExtractor(), enabled=True, maxsize=4, prompt_root=ROOT
        )
        sidepath = TopicSidepath(
            root_dir=self.root,
            conversations=[dict(CONV)],
            extractor=boom,
            enabled=True,
            maxsize=4,
            prompt_root=ROOT,
            store=self.store,
            task_sidepath=task_path,
            decision_sidepath=decision_path,
            risk_sidepath=risk_path,
        )
        from message.identity import InboundMessage

        msg = InboundMessage(
            platform_message_id="probe-fail-1",
            conversation_id="room_p6g5@chatroom",
            chat_name="测试群",
            chat_wxid="room_p6g5@chatroom",
            sender_id=1,
            sender_wxid="wxid_zhangsan",
            sender_name="张三",
            content=NEW_TOPIC_TEXT,
            raw_type="text",
            direction="INBOUND",
            create_time=1710000000,
            attr="friend",
        )
        try:
            sidepath._process({"inbound": msg, "conversation": dict(CONV), "enqueued_at": 0})
            self.assertEqual(sidepath.last_result.decision, DECISION_FAILED)
            self.assertEqual(task_path.enqueued_count, 0)
            self.assertEqual(decision_path.enqueued_count, 0)
            self.assertEqual(risk_path.enqueued_count, 0)
            self.assertEqual(boom.calls, 1)
        finally:
            sidepath.shutdown()
            task_path.shutdown()
            decision_path.shutdown()
            risk_path.shutdown()


if __name__ == "__main__":
    unittest.main()
