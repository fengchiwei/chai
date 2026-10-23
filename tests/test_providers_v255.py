# -*- coding: utf-8 -*-
"""v2.5.5：不限 Gemini——依金鑰判斷服務（Gemini、Claude、OpenAI 與 OpenAI 相容服務），以及模型切換的可靠性修正。
假 API、假金鑰，不連網。"""
import json
import os
import unittest
from unittest.mock import Mock, patch

import requests

from app import reply_source
from config import Config
from engine import dialogue_ai, model_router, providers
from engine.dialogue_ai import _call_model, model_status


def configure(**values):
    """Patch the model settings to exactly these values (everything else empty)."""
    base = {"LLM_PROVIDER": "auto", "LLM_API_KEY": "", "LLM_BASE_URL": "", "LLM_MODEL": "",
            "GEMINI_API_KEY": "", "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
            "OPENAI_BASE_URL": "https://api.openai.com/v1", "MODEL_AUTO_SELECT": False, "LLM_CALL_MODE": "single"}
    base.update(values)
    return [patch.object(Config, k, v) for k, v in base.items()]


def anthropic_reply(text, stop="end_turn"):
    return Mock(status_code=200, json=Mock(return_value={"content": [{"type": "text", "text": text}], "stop_reason": stop}))


class Base(unittest.TestCase):
    settings = {}

    def setUp(self):
        dialogue_ai.reset_model_health()
        env = {k: v for k, v in os.environ.items() if k not in ("LLM_MODEL", "GEMINI_MODEL", "OPENAI_MODEL", "ANTHROPIC_MODEL")}
        self.enterContext(patch.dict(os.environ, env, clear=True))
        for p in configure(**self.settings):
            self.enterContext(p)

    def tearDown(self):
        dialogue_ai.reset_model_health()


class DetectionTests(Base):
    def test_key_prefixes(self):
        for key, name in (("sk-ant-api03-x", "anthropic"), ("AIzaSyX", "gemini"), ("AQ.test", "gemini"),
                          ("gsk_x", "groq"), ("sk-or-v1-x", "openrouter"), ("xai-x", "xai"), ("sk-proj-x", "openai")):
            with self.subTest(key=key):
                self.assertEqual(providers.detect(key), name)
        self.assertIsNone(providers.detect("sk-0123456789abcdef"))  # OpenAI or DeepSeek: the operator chooses

    def test_generic_key_selects_the_service(self):
        with patch.object(Config, "LLM_API_KEY", "sk-ant-api03-test"):
            info = providers.active()
        self.assertEqual((info["name"], info["api"], info["base_url"]), ("anthropic", "anthropic", "https://api.anthropic.com/v1"))
        self.assertEqual(providers.auth_headers(info)["anthropic-version"], "2023-06-01")

    def test_operator_choice_and_custom_endpoint(self):
        with patch.object(Config, "LLM_API_KEY", "sk-0123"), patch.object(Config, "LLM_PROVIDER", "deepseek"):
            self.assertEqual(providers.active()["base_url"], "https://api.deepseek.com/v1")
        with patch.object(Config, "LLM_API_KEY", "local-key"), patch.object(Config, "LLM_PROVIDER", "custom"):
            self.assertFalse(providers.configured())  # custom needs an address
            with patch.object(Config, "LLM_BASE_URL", "http://127.0.0.1:11434/v1/"):
                self.assertEqual(providers.active()["base_url"], "http://127.0.0.1:11434/v1")
                self.assertTrue(providers.configured())

    def test_older_settings_still_work(self):
        with patch.object(Config, "GEMINI_API_KEY", "legacy"):
            self.assertEqual(providers.name(), "gemini")
        with patch.object(Config, "ANTHROPIC_API_KEY", "legacy"):
            self.assertEqual(providers.name(), "anthropic")
        self.assertEqual(providers.name(), "builtin")


class AnthropicTests(Base):
    settings = {"LLM_API_KEY": "sk-ant-api03-test", "LLM_MODEL": "claude-sonnet-5-5"}

    def test_request_shape_and_reply(self):
        with patch("engine.dialogue_ai.requests.post", return_value=anthropic_reply("考完試真的會累。")) as post:
            result, status = _call_model("系統提示", "今天好累", [{"role": "user", "text": "嗨"}, {"role": "assistant", "text": "嗨"}])
        self.assertEqual(status, "ok")
        self.assertEqual(result["reply"], "考完試真的會累。")
        self.assertTrue(result["model_used"].startswith("Anthropic Claude"))
        self.assertEqual(reply_source(result["model_used"]), "ai")
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(kwargs["headers"]["x-api-key"], "sk-ant-api03-test")
        body = kwargs["json"]
        self.assertEqual(body["system"], "系統提示")
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])
        self.assertIn("max_tokens", body)

    def test_truncated_or_refused_is_incomplete_and_does_not_change_everyones_status(self):
        with patch("engine.dialogue_ai.requests.post", return_value=anthropic_reply("…", stop="max_tokens")):
            _, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual(status, "incomplete")
        self.assertNotEqual(model_status()["state"], "degraded")

    def test_overloaded_model_fails_over(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_MODEL", None)
            with patch.object(Config, "LLM_MODEL", ""), patch.object(Config, "MODEL_AUTO_SELECT", True), \
                 patch("engine.model_router.requests.get", return_value=Mock(status_code=200, json=Mock(return_value={"data": [
                     {"id": "claude-haiku-5-5"}, {"id": "claude-opus-5-5"}, {"id": "claude-sonnet-5-5"},
                     {"id": "claude-sonnet-4-5-20250929"}]}))):
                model_router.discover("anthropic", force=True)
                self.assertEqual(model_router.ranked("anthropic")[:3],
                                 ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
                with patch("engine.dialogue_ai.requests.post",
                           side_effect=[Mock(status_code=529, headers={}, text=""), anthropic_reply("我在。")]) as post:
                    _, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual(status, "ok")
        self.assertEqual([c.kwargs["json"]["model"] for c in post.call_args_list], ["claude-opus-5-5", "claude-sonnet-5-5"])


class CompatibleServiceTests(Base):
    settings = {"LLM_API_KEY": "sk-0123", "LLM_PROVIDER": "deepseek"}

    def test_model_list_keeps_chat_models(self):
        listing = Mock(status_code=200, json=Mock(return_value={"data": [
            {"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}, {"id": "text-embedding-3"}, {"id": "whisper-1"}]}))
        with patch("engine.model_router.requests.get", return_value=listing) as get:
            model_router.discover("deepseek", force=True)
        self.assertEqual(get.call_args.args[0], "https://api.deepseek.com/v1/models")
        self.assertEqual(set(model_router.ranked("deepseek")), {"deepseek-chat", "deepseek-reasoner"})

    def test_chat_completions_on_the_service_address(self):
        reply = Mock(status_code=200, json=Mock(return_value={"choices": [{"message": {"content": "我在。"}, "finish_reason": "stop"}]}))
        with patch("engine.dialogue_ai.requests.post", return_value=reply) as post:
            result, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual(status, "ok")
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-0123")
        self.assertTrue(result["model_used"].startswith("DeepSeek"))

    def test_failed_model_list_is_retried_after_a_minute(self):
        clock = [1000.0]
        with patch.object(model_router, "_clock", lambda: clock[0]), \
             patch("engine.model_router.requests.get", return_value=Mock(status_code=500, json=Mock(return_value={}))) as get:
            model_router.discover("deepseek")
            model_router.discover("deepseek")
            self.assertEqual(get.call_count, 1)
            clock[0] += model_router.DISCOVERY_RETRY + 1
            model_router.discover("deepseek")
            self.assertEqual(get.call_count, 2)


class ReliabilityTests(Base):
    settings = {"LLM_API_KEY": "AIzaTest"}

    def test_first_model_timeout_leaves_time_for_the_next(self):
        catalogue = Mock(status_code=200, json=Mock(return_value={"models": [
            {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}]}))
        clock = [0.0]
        reads = []

        def post(*args, **kwargs):
            reads.append(kwargs["timeout"][1])
            if len(reads) == 1:
                clock[0] += kwargs["timeout"][1]
                raise requests.Timeout()
            return Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [{"text": "我在。"}]}}]}))

        with patch.object(dialogue_ai, "_clock", lambda: clock[0]), patch.object(model_router, "_clock", lambda: clock[0]), \
             patch("engine.model_router.requests.get", return_value=catalogue), \
             patch("engine.dialogue_ai.requests.post", side_effect=post):
            model_router.discover("gemini", force=True)
            _, status = _call_model("系統提示", "今天好累", [], timeout=25)
            self.assertNotIn("gemini-3.5-flash", model_router.candidates("gemini"))  # paused after one timeout
        self.assertEqual(status, "ok")
        self.assertLess(reads[0], 25 * 0.7)        # the first model could not use the whole turn

    def test_broken_json_counts_against_the_model(self):
        from engine.dialogue_ai import prepare_dialogue
        from engine.triage import perform_triage
        broken = Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [{"text": '{"reply": "斷'}]}}]}))
        with patch("engine.dialogue_ai.requests.post", return_value=broken):
            for _ in range(2):
                prepare_dialogue("今天好累", perform_triage("今天好累"))
        self.assertEqual(model_router.snapshot("gemini")["models"][0]["state"], "paused")


if __name__ == "__main__":
    unittest.main()
