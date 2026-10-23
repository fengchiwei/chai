# -*- coding: utf-8 -*-
"""v2.5.8：Claude 目前的模型不接受 temperature（HTTP 400），而且會先思考；後台顯示服務的錯誤原文，
「重新偵測」會讓暫停中的模型立刻重試。假 API，不連網。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import app, limiter
from config import Config
from engine import dialogue_ai, model_router
from engine.dialogue_ai import _anthropic_options, _call_model
from models import database
from tests.test_providers_v255 import anthropic_reply, configure

PASSWORD = "local-test-password-long-enough"


class OptionsTests(unittest.TestCase):
    def test_current_models_get_no_sampling_and_low_effort(self):
        for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1",
                      "claude-mythos-5-1", "claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-5"):
            with self.subTest(model=model):
                options = _anthropic_options(model, 1600, 0.8)
                self.assertNotIn("temperature", options)
                self.assertEqual(options["output_config"], {"effort": "low"})
                self.assertGreaterEqual(options["max_tokens"], 4000)  # thinking counts toward the cap

    def test_older_models_keep_temperature(self):
        for model in ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6", "claude-sonnet-4-5-20250929",
                      "claude-3-5-haiku-20241022", "claude-opus-4-20250514"):
            with self.subTest(model=model):
                options = _anthropic_options(model, 1600, 0.8)
                self.assertEqual(options, {"max_tokens": 1600, "temperature": 0.8})

    def test_effort_setting(self):
        with patch.object(Config, "LLM_EFFORT", "default"):
            self.assertNotIn("output_config", _anthropic_options("claude-haiku-5-5", 1600, 0.8))
        with patch.object(Config, "LLM_EFFORT", "medium"):
            self.assertEqual(_anthropic_options("claude-haiku-5-5", 1600, 0.8)["output_config"], {"effort": "medium"})


class PanelTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        dialogue_ai.reset_model_health()
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in ("LLM_MODEL", "ANTHROPIC_MODEL")}
        for p in [patch.dict(os.environ, env, clear=True),
                  patch.object(database, "DB_PATH", str(Path(self.tmp.name) / "o.db")),
                  patch.object(Config, "WORKBENCH_PASSWORD", PASSWORD),
                  *configure(LLM_API_KEY="sk-ant-api03-test", MODEL_AUTO_SELECT=True),
                  patch("engine.model_router.requests.get", return_value=Mock(status_code=200, json=Mock(return_value={
                      "data": [{"id": "claude-haiku-5-5"}, {"id": "claude-sonnet-5-5"}]})))]:
            self.enterContext(p)
        database.init_db()
        model_router.discover("anthropic", force=True)

    def tearDown(self):
        dialogue_ai.reset_model_health()
        limiter.reset()
        self.tmp.cleanup()

    def test_request_body_has_no_temperature(self):
        with patch("engine.dialogue_ai.requests.post", return_value=anthropic_reply("我在。")) as post:
            _, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual(status, "ok")
        body = post.call_args.kwargs["json"]
        self.assertNotIn("temperature", body)
        self.assertEqual(body["output_config"], {"effort": "low"})

    def test_provider_error_reaches_the_panel_and_refresh_retries(self):
        rejected = Mock(status_code=400, headers={}, text="", json=Mock(return_value={
            "type": "error", "error": {"type": "invalid_request_error", "message": "temperature: not supported"}}))
        with patch("engine.dialogue_ai.requests.post", return_value=rejected):
            _, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual(status, "rejected")
        rows = {r["model"]: r for r in model_router.snapshot("anthropic")["models"]}
        self.assertEqual(rows["claude-sonnet-5-5"]["state"], "paused")
        self.assertIn("temperature: not supported", rows["claude-sonnet-5-5"]["detail"])
        self.assertEqual(model_router.candidates("anthropic"), [])
        staff = app.test_client()
        staff.get("/login")
        with staff.session_transaction() as sess:
            token = sess["csrf_token"]
        staff.post("/login", data={"password": PASSWORD, "csrf_token": token})
        staff.post("/api/config/llm", headers={"X-CSRF-Token": token}, json={"action": "refresh"})
        self.assertEqual(len(model_router.candidates("anthropic")), 2)  # tried again at once


if __name__ == "__main__":
    unittest.main()
