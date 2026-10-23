# -*- coding: utf-8 -*-
"""v2.5.6：在工作臺的 AI 模型面板手動選擇模型。只能選這把金鑰清單裡的模型；重啟後保留；
被選的模型故障時仍會暫時改用下一個；學生端仍看不到任何模型名稱。假 API，不連網。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as app_module
from app import app, limiter
from config import Config
from engine import dialogue_ai, model_router
from models import database
from tests.test_model_router import listing, reply, status

PASSWORD = "local-test-password-long-enough"


class ModelChoiceTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        dialogue_ai.reset_model_health()
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in ("LLM_MODEL", "GEMINI_MODEL")}
        for p in (patch.dict(os.environ, env, clear=True),
                  patch.object(database, "DB_PATH", str(Path(self.tmp.name) / "c.db")),
                  patch.object(Config, "WORKBENCH_PASSWORD", PASSWORD), patch.object(Config, "LLM_PROVIDER", "gemini"),
                  patch.object(Config, "GEMINI_API_KEY", "test-key"), patch.object(Config, "LLM_API_KEY", ""),
                  patch.object(Config, "LLM_MODEL", ""), patch.object(Config, "LLM_CALL_MODE", "single"),
                  patch.object(Config, "MODEL_AUTO_SELECT", True),
                  patch("engine.model_router.requests.get", return_value=listing())):
            self.enterContext(p)
        database.init_db()
        self.staff = app.test_client()
        self.staff.get("/login")
        with self.staff.session_transaction() as sess:
            self.token = sess["csrf_token"]
        self.staff.post("/login", data={"password": PASSWORD, "csrf_token": self.token, "staff_name": "資訊組"})
        self.staff.get("/api/config/llm")  # reads the model list

    def tearDown(self):
        dialogue_ai.reset_model_health()
        limiter.reset()
        self.tmp.cleanup()

    def choose(self, model, csrf=True):
        return self.staff.post("/api/config/llm", headers={"X-CSRF-Token": self.token} if csrf else {},
                               json={"action": "select_model", "model": model})

    def test_panel_lists_choices_and_a_choice_goes_first(self):
        panel = self.staff.get("/api/config/llm").json["router"]
        self.assertIn("gemini-3.1-flash-lite", panel["choices"])
        self.assertIsNone(panel["manual"])
        chosen = self.choose("gemini-3.1-flash-lite").json["router"]
        self.assertEqual((chosen["manual"], chosen["active"], chosen["pinned_source"]),
                         ("gemini-3.1-flash-lite", "gemini-3.1-flash-lite", "manual"))
        with patch("engine.dialogue_ai.requests.post", return_value=reply()) as post:
            dialogue_ai._call_model("系統提示", "今天好累", [])
        self.assertIn("/models/gemini-3.1-flash-lite:", post.call_args.args[0])

    def test_only_listed_models_and_csrf(self):
        self.assertEqual(self.choose("gemini-made-up").status_code, 400)
        self.assertEqual(self.choose("text-embedding-004").status_code, 400)  # on the raw list, but not a chat model
        self.assertEqual(self.choose("gemini-3.5-flash", csrf=False).status_code, 403)
        self.assertIsNone(model_router.manual_model("gemini"))

    def test_back_to_automatic(self):
        self.choose("gemini-3.1-flash-lite")
        panel = self.choose("").json["router"]
        self.assertIsNone(panel["manual"])
        self.assertEqual(panel["active"], "gemini-3.5-pro")  # the best-ranked model again

    def test_choice_survives_a_restart_and_is_audited(self):
        self.choose("gemini-3.5-flash")
        model_router.reset()                     # what a restart loses
        app_module.restore_model_choice()        # what start-up does
        self.assertEqual(model_router.manual_model("gemini"), "gemini-3.5-flash")
        conn = database.get_connection()
        try:
            actions = [(r["actor"], r["action"]) for r in conn.execute("SELECT actor, action FROM audit_logs")]
        finally:
            conn.close()
        self.assertIn(("資訊組（共用帳號）", "select_model"), actions)

    def test_chosen_model_down_still_fails_over(self):
        self.choose("gemini-3.1-flash-lite")
        with patch("engine.dialogue_ai.requests.post", side_effect=[status(429), reply()]) as post:
            _, result = dialogue_ai._call_model("系統提示", "今天好累", [])
        self.assertEqual(result, "ok")
        models = [c.args[0].split("/models/")[1].split(":")[0] for c in post.call_args_list]
        self.assertEqual(models[0], "gemini-3.1-flash-lite")
        self.assertNotEqual(models[1], "gemini-3.1-flash-lite")

    def test_students_still_see_no_model_names(self):
        self.choose("gemini-3.1-flash-lite")
        student = app.test_client()
        student.get("/")
        state = student.get("/api/status?probe=1").json
        self.assertNotIn("gemini", str(state).lower())


if __name__ == "__main__":
    unittest.main()
