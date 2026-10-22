# -*- coding: utf-8 -*-
"""v1.3-B 可解釋重播：只用虛構情境；不呼叫模型、不寫入資料庫。"""
import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from config import Config
from engine.explain import explain, load_scenarios, replay
from engine.triage import RISK_LEVEL_WEIGHTS
from models import database

PASSWORD = "local-test-password-long-enough"


class ExplainEngineTests(unittest.TestCase):
    def test_every_scenario_is_fictional_and_matches_expected_level(self):
        scenarios = load_scenarios()
        self.assertGreaterEqual(len(scenarios), 9)
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                result = explain(scenario)
                self.assertTrue(result["fictional"])
                self.assertTrue(result["matches_expected"], (result["expected_highest"], result["highest_level"]))

    def test_evidence_is_verbatim_from_the_cited_turn(self):
        for scenario in load_scenarios():
            for domain in explain(scenario)["domains"]:
                with self.subTest(scenario=scenario["id"], domain=domain["key"]):
                    if domain["evidence"]:
                        self.assertTrue(domain["evidence_verified"], domain)
                    if not domain["known"]:
                        self.assertEqual(domain["evidence"], "")
                        self.assertIn("不代表正常", domain["status_label"])

    def test_highest_level_never_drops_across_turns(self):
        for scenario in load_scenarios():
            records, _, _ = replay(scenario["turns"])
            weights = [RISK_LEVEL_WEIGHTS[r["highest_level"]] for r in records]
            self.assertEqual(weights, sorted(weights), scenario["id"])

    def test_retained_red_evidence_keeps_original_turn(self):
        result = explain({"id": "T", "fictional": True,
                          "turns": ["我已經把工具準備好，今晚等家人睡著就行動", "嗯", "嗯"]})
        safety = next(d for d in result["domains"] if d["key"] == "safety")
        self.assertEqual(safety["turn"], 1)
        self.assertTrue(safety["evidence_verified"])
        self.assertEqual(result["highest_level"], "red")

    def test_denial_is_not_recorded_as_safe(self):
        result = explain({"id": "T", "fictional": True, "turns": ["我真的撐不下去了", "沒有啦"]})
        safety = next(d for d in result["domains"] if d["key"] == "safety")
        self.assertEqual(safety["status"], "self_reported_denial")
        self.assertIn("不等於已確認安全", safety["status_label"])

    def test_third_party_crisis_is_not_support_system(self):
        result = explain({"id": "T", "fictional": True, "turns": ["我沒有說謊，朋友說他想死"]})
        support = next(d for d in result["domains"] if d["key"] == "support_system")
        self.assertFalse(support["known"])
        self.assertEqual(result["turns"][0]["dialogue_safety"]["risk_subject"], "other")

    def test_unmarked_scenarios_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text('{"scenarios": [{"id": "X", "turns": ["真實對話"]},'
                            ' {"id": "Y", "fictional": true, "turns": []}]}', encoding="utf-8")
            self.assertEqual(load_scenarios(str(path)), [])


class ExplainRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "explain.db")
        self.patches = [patch.object(database, "DB_PATH", self.db_path),
                        patch.object(Config, "WORKBENCH_PASSWORD", PASSWORD)]
        for p in self.patches:
            p.start()
        database.init_db()
        self.client = app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def login(self):
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            token = sess["csrf_token"]
        self.assertEqual(self.client.post("/login", data={"password": PASSWORD, "csrf_token": token}).status_code, 302)

    def row_counts(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}

    def test_requires_staff_login(self):
        self.assertEqual(self.client.get("/explain").status_code, 302)
        self.assertEqual(self.client.get("/api/explain/scenarios").status_code, 401)
        self.assertEqual(self.client.get("/api/explain/EX-01").status_code, 401)

    def test_replay_does_not_write_database_or_call_model(self):
        self.login()
        before = self.row_counts()
        with patch("engine.dialogue_ai.requests.post") as post:
            self.assertEqual(self.client.get("/explain").status_code, 200)
            listing = self.client.get("/api/explain/scenarios").json["scenarios"]
            for item in listing:
                response = self.client.get(f"/api/explain/{item['id']}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        post.assert_not_called()
        self.assertEqual(self.row_counts(), before)
        self.assertEqual(self.client.get("/api/explain/NOPE").status_code, 404)


if __name__ == "__main__":
    unittest.main()
