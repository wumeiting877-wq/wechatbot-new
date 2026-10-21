# -*- coding: utf-8 -*-
"""P3-G1 Gate 3–5：Topic Engine 离线 fixture、失败注入、幂等。"""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from message.identity import InboundMessage
from topic_engine import (
    MAX_CANDIDATES,
    MAX_RECENT_MESSAGES,
    TOPIC_ENGINE_ENABLED,
    TopicEngine,
    engine_source_forbids_wechat_sidepath,
    retrieve_candidate_topics,
)
from topic_extractor_client import HeuristicTopicExtractor, TopicExtractorClient, parse_extractor_json
from topic_store import DECISION_FAILED, TopicStore


FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "topic_engine")
DEMO_PATH = os.path.join(FIXTURE_DIR, "zhiqun_demo.json")
BOUNDARY_PATH = os.path.join(FIXTURE_DIR, "boundary_cases.json")

TITLE_A = ("ERP 数据同步异常", "ERP 增量同步", "ERP 同步异常")
TITLE_B = ("权限整改", "权限页面问题", "质检权限")
TITLE_C = ("现场演示准备", "周五现场演示", "演示准备")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _conversation(payload):
    return dict(payload["conversation"])


def _record(conversation, message, index=0):
    created = message.get("created_at") or ("2026-09-20T09:%02d:00+08:00" % (index + 1))
    return {
        "id": message["id"],
        "conversation_id": conversation["id"],
        "platform_message_id": message["id"],
        "sender_name": message.get("sender_name") or "",
        "content": message.get("content") or "",
        "created_at": created,
        "direction": "INBOUND",
        "message_type": "text",
    }


def _engine(store, extractor=None, enabled=True):
    return TopicEngine(
        store,
        extractor=extractor or HeuristicTopicExtractor(),
        root_dir=ROOT,
        enabled=enabled,
    )


def _topic_key(title):
    text = title or ""
    if any(item in text or text in item for item in TITLE_A) or ("ERP" in text and "同步" in text) or "ERP" in text:
        if "权限" not in text and "演示" not in text:
            return "A"
        if "ERP" in text:
            return "A"
    if any(item in text or text in item for item in TITLE_B) or "权限" in text or "质检" in text:
        return "B"
    if any(item in text or text in item for item in TITLE_C) or "演示" in text or "现场" in text:
        return "C"
    if "接口" in text:
        return "API"
    return None


def _linked_message_ids(store, cid, topic_id):
    return {item.get("message_id") for item in store.links_for_topic(cid, topic_id)}


class CaptureExtractor:
    def __init__(self, inner=None):
        self.inner = inner or HeuristicTopicExtractor()
        self.inputs = []

    def extract(self, engine_input, prompt_content):
        self.inputs.append(engine_input)
        return self.inner.extract(engine_input, prompt_content)


class ScriptedExtractor:
    def __init__(self, payload):
        self.payload = payload

    def extract(self, engine_input, prompt_content):
        current_id = engine_input["current_message"]["id"]
        if callable(self.payload):
            return self.payload(engine_input)
        if not isinstance(self.payload, dict):
            return self.payload
        data = dict(self.payload)
        evidence = data.get("evidence_message_ids")
        if evidence is None:
            data["evidence_message_ids"] = [current_id]
        return data


class TopicExtractorClientTests(unittest.TestCase):
    def test_client_uses_store_context_false_and_parses_json(self):
        seen = {}

        def llm_call(messages, **kwargs):
            seen["store_context"] = kwargs.get("store_context")
            seen["temperature"] = kwargs.get("temperature")
            seen["max_tokens"] = kwargs.get("max_tokens")
            seen["messages"] = messages
            return (
                '```json\n{"decision":"UNRELATED","topic_id":null,"proposed_title":"",'
                '"summary_update":"","confidence":"HIGH","evidence_message_ids":["msg_1"],'
                '"reason":"x","tasks":[]}\n```'
            )

        client = TopicExtractorClient(llm_call=llm_call, model="coding-glm-4.7-free")
        out = client.extract(
            {
                "current_message": {"id": "msg_1", "content": "hi"},
                "active_topics": [],
                "recent_messages": [],
            },
            "prompt",
        )
        self.assertFalse(seen["store_context"])
        self.assertEqual(seen["messages"][0]["role"], "system")
        self.assertEqual(out["decision"], "UNRELATED")
        self.assertNotIn("tasks", out)

    def test_strips_unknown_fields(self):
        parsed = parse_extractor_json(
            '{"decision":"UNRELATED","topic_id":null,"proposed_title":"",'
            '"summary_update":"","confidence":"HIGH","evidence_message_ids":[],'
            '"reason":"","risks":[],"decisions":[],"assignee":"王强"}'
        )
        self.assertEqual(parsed["decision"], "UNRELATED")
        self.assertNotIn("risks", parsed)
        self.assertNotIn("assignee", parsed)


class CandidateRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = TopicStore(self.tmpdir.name)
        self.cid = "conv_zhiqun_demo01"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_keyword_recall_beats_recency_only_top5(self):
        demo = self.store.create_topic(
            self.cid,
            title="现场演示准备",
            summary="周五现场演示",
            created_msg_id="msg_demo",
            created_at="2026-09-20T09:10:00+08:00",
            last_message_at="2026-09-20T09:10:00+08:00",
        )
        for index in range(6):
            self.store.create_topic(
                self.cid,
                title="其它事项 %s" % (index + 1),
                summary="无关占位",
                created_msg_id="msg_other_%s" % index,
                created_at="2026-09-20T18:0%s:00+08:00" % index,
                last_message_at="2026-09-20T18:0%s:00+08:00" % index,
            )
        by_time = sorted(self.store.list_topics(self.cid), key=lambda t: t["last_message_at"], reverse=True)[:5]
        self.assertNotIn(demo["id"], [item["id"] for item in by_time])
        current = {"id": "msg_back", "content": "演示账号已经建好了", "sender_name": "李娜"}
        candidates = retrieve_candidate_topics(self.store, self.cid, current, limit=MAX_CANDIDATES)
        self.assertLessEqual(len(candidates), MAX_CANDIDATES)
        self.assertIn(demo["id"], [item["id"] for item in candidates])


class TopicEngineOfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = TopicStore(self.tmpdir.name)
        self.demo = _load_json(DEMO_PATH)
        self.boundary = _load_json(BOUNDARY_PATH)
        self.conv = _conversation(self.demo)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _replay(self, messages, extractor=None, conversation=None):
        conv = conversation or self.conv
        capture = CaptureExtractor(extractor or HeuristicTopicExtractor())
        engine = _engine(self.store, extractor=capture)
        results = []
        for index, message in enumerate(messages):
            results.append(engine.process_record(_record(conv, message, index), conv))
        return results, capture

    def test_topic_engine_enabled_defaults_false(self):
        self.assertFalse(TOPIC_ENGINE_ENABLED)
        engine = TopicEngine(self.store, root_dir=ROOT)
        result = engine.process_record(_record(self.conv, {"id": "msg_x", "content": "ERP 同步失败了"}), self.conv)
        self.assertEqual(result.decision, "DISABLED")
        self.assertEqual(self.store.list_topics(self.conv["id"]), [])

    def test_engine_does_not_touch_wechat_sidepath(self):
        self.assertTrue(engine_source_forbids_wechat_sidepath())
        source = inspect.getsource(TopicEngine)
        self.assertNotIn("send_reply" + "(", source)
        self.assertNotIn("wx.SendMsg" + "(", source)
        self.assertNotIn("from message.listener", source)

    def test_main_sample_three_topics(self):
        results, capture = self._replay(self.demo["messages"])
        cid = self.conv["id"]
        topics = self.store.list_topics(cid)
        self.assertEqual(len(topics), 3, [item.get("title") for item in topics])
        keys = sorted(filter(None, (_topic_key(item["title"]) for item in topics)))
        self.assertEqual(keys, ["A", "B", "C"])
        by_key = {_topic_key(item["title"]): item for item in topics}
        for expected in self.demo["expected_topics"]:
            topic = by_key[expected["key"]]
            self.assertTrue(
                any(item in topic["title"] or topic["title"] in item for item in expected["title_whitelist"]),
                topic["title"],
            )
            linked = _linked_message_ids(self.store, cid, topic["id"])
            for msg_id in expected["must_include_message_ids"]:
                self.assertIn(msg_id, linked)
        for item in topics:
            self.assertEqual(item["status"], "ACTIVE")
        self.assertTrue(all(len(inp["active_topics"]) <= MAX_CANDIDATES for inp in capture.inputs))
        self.assertTrue(all(len(inp["recent_messages"]) <= MAX_RECENT_MESSAGES for inp in capture.inputs))
        self.assertFalse(any("tasks" in (self.store.get_topic(cid, t["id"]) or {}) for t in topics))
        last_decisions = [item.decision for item in results[-2:]]
        self.assertTrue(all(d in ("EXISTING_TOPIC", "TOPIC_UPDATE", "UNRELATED") for d in last_decisions))
        self.assertEqual(len(topics), 3)

    def test_case_01_continuous_erp_one_topic(self):
        case = [item for item in self.boundary["cases"] if item["id"] == "CASE-01"][0]
        self._replay(case["messages"])
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 1)

    def test_case_02_lunch_unrelated(self):
        case = [item for item in self.boundary["cases"] if item["id"] == "CASE-02"][0]
        results, _ = self._replay(case["messages"])
        lunch = [item for item in results if item.message_id == "case02_x"][0]
        self.assertEqual(lunch.decision, "UNRELATED")
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 1)

    def test_case_03_returns_to_original_erp_topic(self):
        case = [item for item in self.boundary["cases"] if item["id"] == "CASE-03"][0]
        results, _ = self._replay(case["messages"])
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 2)
        first = [item for item in results if item.message_id == "case03_1"][0]
        last = [item for item in results if item.message_id == "case03_3"][0]
        self.assertIn(last.decision, ("EXISTING_TOPIC", "TOPIC_UPDATE"))
        self.assertEqual(last.topic_id, first.topic_id)
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 2)

    def test_case_04_wording_change_same_topic(self):
        case = [item for item in self.boundary["cases"] if item["id"] == "CASE-04"][0]
        results, _ = self._replay(case["messages"])
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 1)
        self.assertIn(results[1].decision, ("EXISTING_TOPIC", "TOPIC_UPDATE"))
        self.assertEqual(results[1].topic_id, results[0].topic_id)

    def test_case_05_keyword_recall_after_gap(self):
        case = [item for item in self.boundary["cases"] if item["id"] == "CASE-05"][0]
        messages = list(case["seed_messages"])
        gap = case["gap"]
        for n in range(1, gap["count"] + 1):
            if n == gap["inject_other_topic_at"]:
                messages.append(gap["inject_message"])
            messages.append(
                {
                    "id": "%s%s" % (gap["id_prefix"], n),
                    "sender_name": gap["sender_name"],
                    "content": gap["content_template"].format(n=n),
                }
            )
        messages.append(case["final_message"])
        results, _ = self._replay(messages[:-1])
        cid = self.conv["id"]
        demo_result = [item for item in results if item.message_id == "case05_demo"][0]
        for index in range(6):
            self.store.create_topic(
                cid,
                title="间隔事项 %s" % (index + 1),
                summary="为检索压力构造的较新 Topic",
                created_msg_id="msg_pressure_%s" % index,
                last_message_at="2026-09-20T22:0%s:00+08:00" % index,
            )
        recency = sorted(self.store.list_topics(cid), key=lambda t: t.get("last_message_at") or "", reverse=True)[:5]
        self.assertNotIn(demo_result.topic_id, [item["id"] for item in recency])
        engine = _engine(self.store)
        back = engine.process_record(_record(self.conv, case["final_message"], 99), self.conv)
        self.assertIn(back.decision, ("EXISTING_TOPIC", "TOPIC_UPDATE"))
        self.assertEqual(back.topic_id, demo_result.topic_id)

    def test_case_06_acknowledgements_create_zero_topics(self):
        case = [item for item in self.boundary["cases"] if item["id"] == "CASE-06"][0]
        results, _ = self._replay(case["messages"])
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 0)
        for item in results:
            self.assertIn(item.decision, ("UNRELATED", "SKIPPED"))

    def test_case_07_single_decision_no_third_topic(self):
        case = [item for item in self.boundary["cases"] if item["id"] == "CASE-07"][0]
        self._replay(case["seed_messages"])
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 2)
        results, _ = self._replay(case["messages"])
        dual = results[-1]
        self.assertIn(dual.decision, ("EXISTING_TOPIC", "TOPIC_UPDATE"))
        topic_ids = {item["id"] for item in self.store.list_topics(self.conv["id"])}
        self.assertEqual(len(topic_ids), 2)
        self.assertIn(dual.topic_id, topic_ids)
        self.assertFalse(case.get("multi_topic_supported"))

    def test_idempotent_replay_does_not_duplicate_topics(self):
        messages = self.demo["messages"]
        self._replay(messages)
        first_topics = self.store.list_topics(self.conv["id"])
        first_links = self.store.list_links(self.conv["id"])
        counts = {item["id"]: item["message_count"] for item in first_topics}
        self._replay(messages)
        second_topics = self.store.list_topics(self.conv["id"])
        self.assertEqual(len(second_topics), len(first_topics))
        self.assertEqual(len(self.store.list_links(self.conv["id"])), len(first_links))
        for item in second_topics:
            self.assertEqual(item["message_count"], counts[item["id"]])

    def test_conversation_not_resolved_does_not_create_topic(self):
        engine = _engine(self.store)
        inbound = InboundMessage(
            platform_message_id="x:1",
            chat_name="未知群",
            chat_wxid="999@chatroom",
            content="ERP 同步失败了",
            conversation_id="未知群",
        )
        result = engine.process_inbound(inbound, conversations=[self.conv])
        self.assertEqual(result.error_code, "CONVERSATION_NOT_RESOLVED")
        self.assertEqual(self.store.list_topics(self.conv["id"]), [])

    def test_lookup_uses_wxid_not_inbound_conversation_id(self):
        conv = {
            "id": "conv_6fbe0f455b94",
            "platform": "WECHAT",
            "display_name": "QIYE",
            "platform_conversation_id": "58847495172@chatroom",
            "conversation_type": "GROUP",
        }
        engine = _engine(self.store)
        inbound = InboundMessage(
            platform_message_id="room:1",
            chat_name="QIYE",
            chat_wxid="58847495172@chatroom",
            conversation_id="58847495172@chatroom",
            sender_name="陈总",
            content="ERP 增量同步的问题现在解决了吗？",
        )
        result = engine.process_inbound(inbound, conversations=[conv])
        self.assertEqual(result.conversation_id, "conv_6fbe0f455b94")
        self.assertNotEqual(result.conversation_id, inbound.conversation_id)
        topics = self.store.list_topics("conv_6fbe0f455b94")
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["conversation_id"], "conv_6fbe0f455b94")


class FailureInjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = TopicStore(self.tmpdir.name)
        self.conv = {
            "id": "conv_zhiqun_demo01",
            "platform": "WECHAT",
            "conversation_type": "GROUP",
            "display_name": "智群Demo",
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def _seed_erp(self):
        engine = _engine(self.store)
        return engine.process_record(
            _record(self.conv, {"id": "seed_erp", "content": "ERP 同步失败了"}),
            self.conv,
        )

    def _process_with(self, extractor, message=None):
        engine = _engine(self.store, extractor=extractor)
        payload = message or {"id": "fail_msg", "content": "权限页面质检员能看到采购价格"}
        return engine.process_record(_record(self.conv, payload, 9), self.conv)

    def test_extractor_timeout_isolated(self):
        self._seed_erp()
        before = len(self.store.list_topics(self.conv["id"]))

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise TimeoutError("llm timeout")

        result = self._process_with(Boom())
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(result.error_code, "EXTRACTOR_TIMEOUT")
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), before)
        rec = self.store.get_processing(self.conv["id"], "fail_msg")
        self.assertEqual(rec["decision"], DECISION_FAILED)

    def test_extractor_exception_isolated(self):
        self._seed_erp()
        before = len(self.store.list_topics(self.conv["id"]))

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("boom")

        result = self._process_with(Boom())
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), before)

    def test_invalid_json_isolated(self):
        self._seed_erp()
        before = len(self.store.list_topics(self.conv["id"]))
        result = self._process_with(ScriptedExtractor("not-json-at-all"))
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "JSON_PARSE_ERROR")
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), before)

    def test_invalid_topic_id_does_not_create_it(self):
        self._seed_erp()
        before_ids = {item["id"] for item in self.store.list_topics(self.conv["id"])}
        result = self._process_with(
            ScriptedExtractor(
                {
                    "decision": "EXISTING_TOPIC",
                    "topic_id": "topic_does_not_exist",
                    "proposed_title": "",
                    "summary_update": "",
                    "confidence": "HIGH",
                    "reason": "x",
                }
            )
        )
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertEqual(result.error_code, "INVALID_TOPIC_ID")
        after_ids = {item["id"] for item in self.store.list_topics(self.conv["id"])}
        self.assertEqual(after_ids, before_ids)
        self.assertNotIn("topic_does_not_exist", after_ids)

    def test_prompt_missing_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                return {"decision": "NEW_TOPIC", "proposed_title": "x"}

        engine = TopicEngine(
            self.store,
            extractor=Boom(),
            root_dir=self.tmpdir.name,
            enabled=True,
        )
        result = engine.process_record(
            _record(self.conv, {"id": "no_prompt", "content": "ERP 同步失败了"}),
            self.conv,
        )
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_NOT_FOUND")
        self.assertEqual(self.store.list_topics(self.conv["id"]), [])

    def test_prompt_empty_does_not_call_llm(self):
        called = {"n": 0}

        class Boom:
            def extract(self, engine_input, prompt_content):
                called["n"] += 1
                raise AssertionError("should not run")

        prompt_dir = os.path.join(self.tmpdir.name, "prompts", "extractors")
        os.makedirs(prompt_dir)
        with open(os.path.join(prompt_dir, "TOPIC_EXTRACTOR.md"), "w", encoding="utf-8") as f:
            f.write("\n")
        engine = TopicEngine(self.store, extractor=Boom(), root_dir=self.tmpdir.name, enabled=True)
        result = engine.process_record(
            _record(self.conv, {"id": "empty_prompt", "content": "ERP 同步失败了"}),
            self.conv,
        )
        self.assertEqual(called["n"], 0)
        self.assertEqual(result.error_code, "EXTRACTOR_PROMPT_EMPTY")
        self.assertEqual(self.store.list_topics(self.conv["id"]), [])

    def test_failed_then_retry_can_succeed(self):
        self._seed_erp()

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("first fail")

        first = self._process_with(Boom(), {"id": "retry_msg", "content": "权限页面质检员能看到采购价格"})
        self.assertEqual(first.decision, DECISION_FAILED)
        second = self._process_with(
            HeuristicTopicExtractor(),
            {"id": "retry_msg", "content": "权限页面质检员能看到采购价格"},
        )
        self.assertIn(second.decision, ("NEW_TOPIC", "EXISTING_TOPIC", "TOPIC_UPDATE"))
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 2)

    def test_process_does_not_raise_to_caller(self):
        class Boom:
            def extract(self, engine_input, prompt_content):
                raise RuntimeError("explode")

        engine = _engine(self.store, extractor=Boom())
        result = engine.process_record(
            _record(self.conv, {"id": "no_crash", "content": "ERP 同步失败了"}),
            self.conv,
        )
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)


if __name__ == "__main__":
    unittest.main()
