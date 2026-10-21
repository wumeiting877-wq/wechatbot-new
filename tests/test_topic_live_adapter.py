# -*- coding: utf-8 -*-
"""P3-G2 Gate 2：真实 Topic Extractor 适配与离线联调。"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_store import resolve_extractor_prompt
from llm_client import get_deepseek_response, get_extractor_response
from topic_engine import TopicEngine
from topic_extractor_client import TopicExtractorClient, parse_extractor_json
from topic_sidepath import sidepath_source_forbids_wechat_send
from topic_store import DECISION_FAILED, TopicStore


FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "topic_engine")
BOUNDARY_PATH = os.path.join(FIXTURE_DIR, "boundary_cases.json")
PROMPT_PATH = os.path.join(ROOT, "prompts", "extractors", "TOPIC_EXTRACTOR.md")

TITLE_A = ("ERP", "同步")
TITLE_B = ("权限", "质检")
TITLE_C = ("演示", "现场")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _prompt_hash():
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return hashlib.sha256(f.read().encode("utf-8")).hexdigest()


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


def _real_llm_ready():
    try:
        from app_config import is_configured_secret, load_config
        cfg = load_config()
        return bool(is_configured_secret(cfg.get("DEEPSEEK_API_KEY")) and cfg.get("MODEL"))
    except Exception:
        return False


def _topic_bucket(title: str) -> str:
    text = title or ""
    if "权限" in text or "质检" in text:
        return "B"
    if "演示" in text or "现场" in text:
        return "C"
    if "ERP" in text or "同步" in text or "接口" in text:
        return "A"
    return "OTHER"


class ExtractorIsolationTests(unittest.TestCase):
    def test_extractor_entry_is_not_chat_wrapper(self):
        source = inspect.getsource(get_extractor_response)
        self.assertNotIn("get_user_prompt", source)
        self.assertNotIn("chat_contexts", source)
        self.assertNotIn("load_chat_contexts", source)
        self.assertNotIn("save_chat_contexts", source)
        self.assertNotIn("resolve_chat_prompt", source)
        self.assertNotIn("get_deepseek_response", source)
        self.assertNotIn("send_reply" + "(", source)
        self.assertNotIn("wx.SendMsg", source)
        self.assertIn("store_context", source)

    def test_extractor_helpers_exported_for_bot_install(self):
        from llm_client import EXPORTS
        for name in (
            "get_extractor_response",
            "_resolver_extractor_client",
            "_invoke_extractor",
            "_extractor_choice_text",
            "_finish_extractor_text",
            "_looks_like_extractor_json",
        ):
            self.assertIn(name, EXPORTS)

    def test_chat_function_unchanged_still_has_prompt_binding(self):
        source = inspect.getsource(get_deepseek_response)
        self.assertIn("PromptResolveError", source)
        self.assertIn("get_user_prompt", source)
        self.assertNotIn("topic_extractor", source)

    def test_sidepath_and_extractor_forbid_send(self):
        self.assertTrue(sidepath_source_forbids_wechat_send())
        import topic_engine
        import topic_extractor_client
        import topic_sidepath
        for module in (topic_engine, topic_extractor_client, topic_sidepath):
            text = inspect.getsource(module)
            self.assertNotIn("send_reply" + "(", text)
            self.assertNotIn("wx.SendMsg" + "(", text)

    def test_markdown_json_and_empty_and_http_error(self):
        parsed = parse_extractor_json('```json\n{"decision":"UNRELATED","topic_id":null,"proposed_title":"","summary_update":"","confidence":"HIGH","evidence_message_ids":["msg_1"],"reason":"闲聊"}\n```')
        self.assertEqual(parsed["decision"], "UNRELATED")
        with self.assertRaises(Exception) as empty_ctx:
            parse_extractor_json("")
        self.assertEqual(empty_ctx.exception.code, "JSON_PARSE_ERROR")
        with self.assertRaises(Exception) as bad_ctx:
            parse_extractor_json("not json")
        self.assertEqual(bad_ctx.exception.code, "JSON_PARSE_ERROR")

        def boom(*_a, **_k):
            raise RuntimeError("HTTP 500")

        client = TopicExtractorClient(llm_call=boom)
        with self.assertRaises(Exception) as http_ctx:
            client.extract({"current_message": {"id": "m1", "content": "x"}}, "prompt")
        self.assertEqual(http_ctx.exception.code, "EXTRACTOR_EXCEPTION")

        def timeout(*_a, **_k):
            raise TimeoutError("deadline")

        client_t = TopicExtractorClient(llm_call=timeout)
        with self.assertRaises(Exception) as t_ctx:
            client_t.extract({"current_message": {"id": "m1"}}, "prompt")
        self.assertEqual(t_ctx.exception.code, "EXTRACTOR_TIMEOUT")

    def test_extractor_reads_reasoning_when_content_empty(self):
        from llm_client import _extractor_choice_text

        class Msg:
            content = ""
            reasoning_content = '{"decision":"UNRELATED","topic_id":null}'

        class Choice:
            message = Msg()

        class Resp:
            choices = [Choice()]

        self.assertIn("UNRELATED", _extractor_choice_text(Resp()))

        class ThinkOnly:
            content = ""
            reasoning_content = "The current message mentions two topics but has no JSON yet."

        class Choice2:
            message = ThinkOnly()

        class Resp2:
            choices = [Choice2()]

        self.assertEqual(_extractor_choice_text(Resp2()), "")

    def test_engine_failed_does_not_create_topic(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = TopicStore(tmp.name)
        conv = {"id": "conv_live_fail", "platform": "WECHAT", "display_name": "x"}

        class Boom:
            def extract(self, engine_input, prompt_content):
                raise TimeoutError("20s")

        engine = TopicEngine(store, extractor=Boom(), root_dir=ROOT, enabled=True)
        result = engine.process_record(
            _record(conv, {"id": "msg_live_fail", "content": "ERP 同步失败了"}),
            conv,
        )
        self.assertEqual(result.decision, DECISION_FAILED)
        self.assertTrue(result.isolated)
        self.assertEqual(store.list_topics(conv["id"]), [])


@unittest.skipUnless(_real_llm_ready(), "主模型 API Key 未配置，真实 Extractor 联调 NOT RUN")
class RealTopicExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = TopicStore(self.tmpdir.name)
        self.boundary = _load_json(BOUNDARY_PATH)
        self.conv = dict(self.boundary["conversation"])
        self.prompt = resolve_extractor_prompt("TOPIC_EXTRACTOR", root_dir=ROOT)
        from app_config import load_config
        cfg = load_config()
        self.model = cfg.get("MODEL") or "INHERIT"
        self.client = TopicExtractorClient(llm_call=get_extractor_response, model=self.model)
        self.engine = TopicEngine(
            self.store,
            extractor=self.client,
            root_dir=ROOT,
            enabled=True,
            extractor_prompt_name="TOPIC_EXTRACTOR",
            model=self.model,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _replay(self, messages):
        results = []
        for index, message in enumerate(messages):
            results.append(self.engine.process_record(_record(self.conv, message, index), self.conv))
        return results

    def _case(self, case_id):
        return [item for item in self.boundary["cases"] if item["id"] == case_id][0]

    def test_prompt_and_model_are_recorded(self):
        self.assertEqual(self.prompt.prompt_name, "TOPIC_EXTRACTOR")
        self.assertEqual(self.prompt.prompt_hash, _prompt_hash())
        self.assertTrue(self.model)
        self.assertNotIn("sk-", str(self.model))

    def test_case_01_continuous_erp(self):
        case = self._case("CASE-01")
        results = self._replay(case["messages"])
        self.assertFalse(any(item.decision == DECISION_FAILED for item in results), [item.as_dict() for item in results])
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 1)

    def test_case_02_chitchat_unrelated(self):
        case = self._case("CASE-02")
        results = self._replay(case["messages"])
        lunch_result = results[2]
        self.assertIn(lunch_result.decision, ("UNRELATED", "SKIPPED"))
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 1)

    def test_case_03_erp_perm_erp_reuse(self):
        case = self._case("CASE-03")
        results = self._replay(case["messages"])
        topics = self.store.list_topics(self.conv["id"])
        self.assertEqual(len(topics), 2, [item.get("title") for item in topics])
        self.assertEqual(results[-1].topic_id, results[0].topic_id)

    def test_case_04_synonym_one_topic(self):
        case = self._case("CASE-04")
        self._replay(case["messages"])
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 1)

    def test_case_05_keyword_recall(self):
        case = self._case("CASE-05")
        seed = self._replay(case["seed_messages"])[0]
        self.assertTrue(seed.topic_id)
        cid = self.conv["id"]
        for index in range(6):
            self.store.create_topic(
                cid,
                title="间隔事项 %s" % (index + 1),
                summary="为检索压力构造的较新 Topic",
                created_msg_id="msg_pressure_%s" % index,
                last_message_at="2026-09-20T22:0%s:00+08:00" % index,
            )
        recency = sorted(self.store.list_topics(cid), key=lambda t: t.get("last_message_at") or "", reverse=True)[:5]
        self.assertNotIn(seed.topic_id, [item["id"] for item in recency])
        back = self.engine.process_record(_record(self.conv, case["final_message"], 99), self.conv)
        self.assertIn(back.decision, ("EXISTING_TOPIC", "TOPIC_UPDATE"))
        self.assertEqual(back.topic_id, seed.topic_id)

    def test_case_06_ack_no_topic(self):
        case = self._case("CASE-06")
        results = self._replay(case["messages"])
        self.assertTrue(all(item.decision in ("UNRELATED", "SKIPPED") for item in results))
        self.assertEqual(len(self.store.list_topics(self.conv["id"])), 0)

    def test_case_07_no_third_composite(self):
        case = self._case("CASE-07")
        self._replay(case["seed_messages"])
        results = self._replay(case["messages"])
        topics = self.store.list_topics(self.conv["id"])
        self.assertEqual(len(topics), 2, [item.get("title") for item in topics])
        self.assertIn(results[-1].decision, ("EXISTING_TOPIC", "TOPIC_UPDATE", "UNRELATED"))
        if results[-1].topic_id:
            self.assertIn(results[-1].topic_id, {item["id"] for item in topics})


if __name__ == "__main__":
    unittest.main()
