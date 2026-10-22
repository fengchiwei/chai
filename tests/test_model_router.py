# -*- coding: utf-8 -*-
"""自動選模型與故障切換：依金鑰列出可用模型、排名、逐一備援；模型名稱只在後台。假 API，不連網。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from config import Config
from engine import dialogue_ai, model_router
from engine.dialogue_ai import _call_model, generate_youth_response, model_status
from engine.triage import perform_triage
from models import database

KEY_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-preview-tts", "gemini-flash-latest", "gemini-2.5-flash-image",
              "gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.5-flash-lite",
              "gemini-3.5-pro", "gemini-omni-1.1-flash", "text-embedding-004"]


def listing(names=KEY_MODELS):
    return Mock(status_code=200, json=Mock(return_value={"models": [
        {"name": "models/" + n, "supportedGenerationMethods": ["generateContent"]} for n in names]}))


def reply(text="考完試真的會累，我先聽你說。"):
    return Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [{"text": text}]}}]}))


def status(code, text=""):
    return Mock(status_code=code, text=text, headers={}, json=Mock(return_value={}))


def model_of(call):
    return call.args[0].split("/models/")[1].split(":")[0]


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


class RouterTests(unittest.TestCase):
    def setUp(self):
        dialogue_ai.reset_model_health()
        self.clock = Clock()
        for p in (patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"),
                  patch.object(Config, "LLM_CALL_MODE", "single"), patch.object(dialogue_ai, "_clock", self.clock),
                  patch.object(model_router, "_clock", self.clock), patch.dict(os.environ, {}, clear=False)):
            self.enterContext(p)
        os.environ.pop("GEMINI_MODEL", None)
        with patch("engine.model_router.requests.get", return_value=listing()):
            model_router.discover("gemini")

    def tearDown(self):
        dialogue_ai.reset_model_health()

    def call(self, post):
        with patch("engine.dialogue_ai.requests.post", **post) as mock:
            result = _call_model("系統提示", "<student_message>\n今天好累\n</student_message>", [])
        return result, mock

    def test_discovery_keeps_chat_models_and_ranks_them(self):
        self.assertEqual(model_router.ranked("gemini"), [
            "gemini-3.5-pro", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
            "gemini-2.5-flash", "gemini-flash-latest", "gemini-3-flash-preview"])

    def test_best_model_is_used_first(self):
        (result, status_), post = self.call({"return_value": reply()})
        self.assertEqual(status_, "ok")
        self.assertEqual(model_of(post.call_args), "gemini-3.5-pro")
        self.assertIn("gemini-3.5-pro", result["model_used"])

    def test_quota_on_best_model_fails_over_within_the_same_turn(self):
        (result, status_), post = self.call({"side_effect": [status(429), reply()]})
        self.assertEqual(status_, "ok")
        self.assertEqual([model_of(c) for c in post.call_args_list], ["gemini-3.5-pro", "gemini-3.5-flash"])
        _, post = self.call({"return_value": reply()})
        self.assertEqual(model_of(post.call_args), "gemini-3.5-flash")  # the exhausted model stays paused
        self.clock.now += 61
        _, post = self.call({"return_value": reply()})
        self.assertEqual(model_of(post.call_args), "gemini-3.5-pro")  # and comes back after its pause

    def test_retired_and_overloaded_models_are_skipped(self):
        (_, status_), post = self.call({"side_effect": [status(404), status(503), reply()]})
        self.assertEqual(status_, "ok")
        self.assertEqual(len(post.call_args_list), 3)
        self.assertNotIn("gemini-3.5-pro", model_router.candidates("gemini"))      # 404: paused for a day
        self.assertIn("gemini-3.5-flash", model_router.candidates("gemini"))       # one 503: not paused yet

    def test_failover_is_capped_and_reports_the_last_failure(self):
        (_, status_), post = self.call({"return_value": status(503)})
        self.assertEqual(status_, "unavailable")
        self.assertEqual(post.call_count, model_router.MAX_FAILOVER)

    def test_key_network_and_content_problems_do_not_cycle_models(self):
        for effect in ({"return_value": status(400, "API key not valid")}, {"side_effect": requests.ConnectionError()},
                       {"return_value": Mock(status_code=200, json=Mock(return_value={"promptFeedback": {"blockReason": "SAFETY"}}))}):
            with self.subTest(effect=effect):
                dialogue_ai.reset_model_health()
                with patch("engine.model_router.requests.get", return_value=listing()):
                    model_router.discover("gemini")
                _, post = self.call(effect)
                self.assertEqual(post.call_count, 1)

    def test_turn_budget_limits_failover(self):
        def slow_failure(*args, **kwargs):
            self.clock.now += 24
            raise requests.Timeout()
        with patch("engine.dialogue_ai.requests.post", side_effect=slow_failure) as post:
            _call_model("系統提示", "今天好累", [], timeout=25)
        self.assertEqual(post.call_count, 1)  # 1 second left: not enough for another model

    def test_admin_pinned_model_goes_first(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-3.1-flash-lite"}):
            self.assertEqual(model_router.ranked("gemini")[0], "gemini-3.1-flash-lite")

    def test_slow_models_move_to_the_back(self):
        model_router.record("gemini", "gemini-3.5-pro", "ok", latency=22)
        self.assertEqual(model_router.ranked("gemini")[-1], "gemini-3.5-pro")

    def test_when_every_model_is_paused_the_reply_is_local_and_status_says_why(self):
        for model in model_router.ranked("gemini"):
            model_router.record("gemini", model, "rate_limited")
        with patch("engine.dialogue_ai.requests.post") as post:
            result = generate_youth_response("今天考試很累", perform_triage("今天考試很累"))
        post.assert_not_called()
        self.assertEqual(result["fallback_reason"], "cooldown")
        self.assertEqual((model_status()["state"], model_status()["reason"]), ("degraded", "rate_limited"))

    def test_without_discovery_the_configured_default_is_used(self):
        model_router.reset()
        self.assertEqual(model_router.ranked("gemini"), [Config.GEMINI_MODEL])


class BackendOnlyTests(unittest.TestCase):
    PASSWORD = "local-test-password-long-enough"

    def setUp(self):
        from app import app, limiter
        limiter.reset()
        dialogue_ai.reset_model_health()
        self.tmp = tempfile.TemporaryDirectory()
        for p in (patch.object(database, "DB_PATH", str(Path(self.tmp.name) / "m.db")),
                  patch.object(Config, "WORKBENCH_PASSWORD", self.PASSWORD),
                  patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"),
                  patch.object(Config, "LLM_CALL_MODE", "single"),
                  # one module object: the same mock answers the model list and the probe
                  patch("engine.model_router.requests.get", return_value=listing())):
            self.enterContext(p)
        database.init_db()
        self.app = app

    def tearDown(self):
        dialogue_ai.reset_model_health()
        self.tmp.cleanup()

    def student(self):
        client = self.app.test_client()
        client.get("/")
        with client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
        return client, headers

    def test_student_side_never_sees_model_names(self):
        client, headers = self.student()
        state = client.get("/api/status?probe=1").get_json()
        self.assertEqual(state["ai"]["state"], "ok")
        self.assertNotIn("gemini", str(state).lower())
        with patch("engine.dialogue_ai.requests.post", return_value=reply('{"analysis": {}, "reply": "考完試真的會累。"}')):
            chat = client.post("/api/chat", headers=headers, json={"message": "今天考試很累"}).get_json()
        self.assertEqual(chat["reply_source"], "ai")
        self.assertEqual(chat["model_used"], "雲端 AI")
        self.assertNotIn("gemini", str(chat).lower())

    def test_staff_panel_lists_ranked_models_and_can_refresh(self):
        self.assertEqual(self.app.test_client().get("/api/config/llm").status_code, 401)
        staff = self.app.test_client()
        staff.get("/login")
        with staff.session_transaction() as sess:
            token = sess["csrf_token"]
        staff.post("/login", data={"password": self.PASSWORD, "csrf_token": token})
        panel = staff.get("/api/config/llm").get_json()
        rows = panel["router"]["models"]
        self.assertEqual(rows[0]["model"], "gemini-3.5-pro")
        self.assertTrue(rows[0]["active"])
        self.assertNotIn("test-key", str(panel))
        self.assertEqual(staff.post("/api/config/llm", json={"action": "refresh"}).status_code, 403)  # CSRF
        refreshed = staff.post("/api/config/llm", headers={"X-CSRF-Token": token}, json={"action": "refresh"})
        self.assertEqual(refreshed.status_code, 200)
        self.assertTrue(refreshed.get_json()["router"]["discovered"])


if __name__ == "__main__":
    unittest.main()
