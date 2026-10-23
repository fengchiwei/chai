# -*- coding: utf-8 -*-
"""v1.3-B.1 服務韌性：模型逾時、額度、格式錯誤時仍有回覆，且不拖垮整輪。假 API，不連網。"""
import json
import unittest
from unittest.mock import Mock, patch

import requests

from config import Config
from engine import dialogue_ai, model_router
from engine.dialogue_ai import generate_youth_response, prepare_dialogue
from engine.triage import perform_triage

MESSAGE = "今天考試很累"


def reply_ok(text="考完試真的會累，先讓自己喘口氣也沒關係。"):
    response = Mock(status_code=200)
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return response


def status(code, headers=None):
    response = Mock(status_code=code, headers=headers or {})
    response.json.return_value = {}
    return response


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        dialogue_ai.reset_model_health()
        self.clock = FakeClock()
        for p in (patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"),
                  patch.object(dialogue_ai, "_clock", self.clock),
                  patch.object(model_router, "_clock", self.clock),  # per-model pauses use the same clock
                  patch.object(Config, "LLM_CALL_MODE", "two_stage")):  # single-call budget: test_single_call_v23
            self.enterContext(p)

    def tearDown(self):
        dialogue_ai.reset_model_health()

    def turn(self, message=MESSAGE):
        triage, state = prepare_dialogue(message, perform_triage(message))
        return generate_youth_response(message, triage, dialogue_state=state)

    def test_timeout_falls_back_with_reason_and_single_call(self):
        with patch("engine.dialogue_ai.requests.post", side_effect=requests.Timeout()) as post:
            result = self.turn()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["model_used"], "AI 暫時無法回覆")
        self.assertEqual(result["fallback_reason"], "timeout")
        self.assertTrue(result["reply"].strip())

    def test_non_json_and_unexpected_shapes_fall_back(self):
        broken = Mock(status_code=200)
        broken.json.side_effect = ValueError("not json")
        for response in (broken, Mock(status_code=200, json=Mock(return_value=["list"])),
                         Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": "文字"}}]}))):
            with self.subTest(response=response), patch("engine.dialogue_ai.requests.post", return_value=response):
                result = self.turn()
            self.assertEqual(result["model_used"], "AI 暫時無法回覆")
            self.assertTrue(result["reply"].strip())
            dialogue_ai.reset_model_health()

    def test_prompt_blocked_by_provider_is_reported(self):
        blocked = Mock(status_code=200)
        blocked.json.return_value = {"promptFeedback": {"blockReason": "SAFETY"}}
        with patch("engine.dialogue_ai.requests.post", return_value=blocked):
            result = self.turn()
        self.assertEqual(result["fallback_reason"], "incomplete")

    def test_quota_error_pauses_cloud_calls_then_recovers(self):
        with patch("engine.dialogue_ai.requests.post", return_value=status(429)) as post:
            first = self.turn()
            second = self.turn("還是好累")
        self.assertEqual(first["fallback_reason"], "rate_limited")
        self.assertEqual(second["fallback_reason"], "cooldown")
        self.assertEqual(post.call_count, 1)
        self.clock.now += 61
        with patch("engine.dialogue_ai.requests.post", return_value=reply_ok()) as post:
            third = self.turn("今天好像好一點")
        self.assertIn("Gemini", third["model_used"])
        self.assertNotIn("fallback_reason", third)

    def test_retry_after_header_is_respected_with_cap(self):
        with patch("engine.dialogue_ai.requests.post", return_value=status(429, {"Retry-After": "120"})):
            self.turn()
        self.clock.now += 100
        self.assertEqual(self.turn("還在嗎")["fallback_reason"], "cooldown")
        self.clock.now += 21
        with patch("engine.dialogue_ai.requests.post", return_value=reply_ok()):
            self.assertNotIn("fallback_reason", self.turn("我回來了"))

    def test_bad_key_pauses_longer(self):
        with patch("engine.dialogue_ai.requests.post", return_value=status(401)):
            self.assertEqual(self.turn()["fallback_reason"], "auth_error")
        self.clock.now += 120
        with patch("engine.dialogue_ai.requests.post") as post:
            self.assertEqual(self.turn("還是累")["fallback_reason"], "cooldown")
        post.assert_not_called()

    def test_repeated_transport_failures_open_cooldown(self):
        with patch("engine.dialogue_ai.requests.post", side_effect=requests.ConnectionError()) as post:
            for text in ("第一次", "第二次", "第三次", "第四次"):
                self.turn("今天考試很累，" + text)
        self.assertEqual(post.call_count, dialogue_ai.FAILURE_THRESHOLD)

    def test_success_resets_failure_count(self):
        with patch("engine.dialogue_ai.requests.post", side_effect=requests.ConnectionError()):
            for _ in range(dialogue_ai.FAILURE_THRESHOLD - 1):
                self.turn()
        with patch("engine.dialogue_ai.requests.post", side_effect=[reply_ok("{}"), reply_ok()]):
            self.turn()
        with patch("engine.dialogue_ai.requests.post", side_effect=requests.ConnectionError()) as post:
            self.turn()
            self.turn()
        self.assertEqual(post.call_count, 2)

    def test_two_stage_calls_share_one_turn_budget(self):
        calls = []

        def slow_analysis_then_reply(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                self.clock.now += 12
                return reply_ok(json.dumps({}))
            return reply_ok()
        with patch.object(Config, "LLM_TURN_BUDGET", 20), \
             patch("engine.dialogue_ai.requests.post", side_effect=slow_analysis_then_reply) as post:
            self.turn()
        timeouts = [c.kwargs["timeout"][1] for c in post.call_args_list]  # (connect, read)
        self.assertLessEqual(timeouts[0], 10)
        self.assertLessEqual(sum(timeouts), 20 + 0.01)

    def test_reply_is_skipped_when_budget_is_spent(self):
        def very_slow_analysis(*args, **kwargs):
            self.clock.now += 19
            return reply_ok(json.dumps({}))
        with patch.object(Config, "LLM_TURN_BUDGET", 20), \
             patch("engine.dialogue_ai.requests.post", side_effect=very_slow_analysis) as post:
            result = self.turn()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["fallback_reason"], "budget_exceeded")
        self.assertEqual(result["model_used"], "AI 暫時無法回覆")

    def test_cooldown_never_blocks_safety_reply(self):
        with patch("engine.dialogue_ai.requests.post", return_value=status(429)):
            self.turn()
        result = self.turn("我今晚打算把這些藥吃掉")
        self.assertEqual(result["model_used"], "安全回覆")
        self.assertIn("119", result["reply"])


if __name__ == "__main__":
    unittest.main()
