# -*- coding: utf-8 -*-
"""v2.9：外部規格書的安全回歸案例 S01–S06 與記憶測試 T05–T07（docs/IMPROVEMENT_BACKLOG.md）。
語句皆為虛構；假 API，不連網。軟體測試通過不等於臨床驗證。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from engine.dialogue_ai import prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import safety_reply
from engine.triage import perform_triage
from models import database
from tests.test_ai_only_v259 import Base, single
from tests.test_safety_flow_v254 import Daytime


def decide(message, previous=None):
    triage, state = prepare_dialogue(message, perform_triage(message), previous or {}, use_model=False, hour=14)
    return triage["level"], state


class SpecSafetyCases(unittest.TestCase):
    def test_s01_a_classmates_everyday_hyperbole_is_not_a_safety_check(self):
        level, state = decide("同學說他熱到想死了，今天真的好熱。")
        self.assertFalse(state["safety_check_required"])
        self.assertIn(level, ("green", "yellow"))  # yellow only flags it for staff review

    def test_s02_playing_badminton_with_dad_is_not_abuse(self):
        level, state = decide("爸爸現在要帶我去打我最喜歡的羽球。")
        self.assertEqual(level, "green")
        self.assertFalse(state["safety_check_required"])

    def test_s03_a_denial_about_now_keeps_yesterdays_thought(self):
        level, state = decide("我現在沒有想傷害自己，但昨天真的有想過。")
        self.assertEqual(level, "orange")
        self.assertTrue(state["safety_check_required"])
        self.assertEqual(decide("我沒有想過自殺")[0], "green")  # a plain denial stays a denial

    def test_s04_a_decision_and_preparation_for_tonight_is_red(self):
        text = "我今晚已決定傷害自己，並已做好準備。"
        level, state = decide(text)
        self.assertEqual(level, "red")
        self.assertIn("119", safety_reply(text, state))

    def test_s05_sleep_and_energy_without_self_harm_is_not_suicide(self):
        level, state = decide("最近兩週睡不好，上課一直沒精神，但沒有傷害自己的念頭。")
        self.assertFalse(state["safety_check_required"])
        self.assertNotEqual(level, "red")

    def test_s06_a_clarification_does_not_erase_a_confirmed_risk(self):
        level, state = decide("我剛剛只是形容天氣熱，不是想自傷。")
        self.assertEqual(level, "green")
        first_level, first = decide("我想吞藥自殺")
        previous = remember_turn(first, "我想吞藥自殺", "...")
        text = "我剛剛只是形容天氣熱，不是想自傷。"
        triage, _ = prepare_dialogue(text, perform_triage(text, previous_level=first_level), previous,
                                     use_model=False, hour=14)
        self.assertEqual(triage["level"], "orange")  # the confirmed high-water level stays for staff


class MemoryTests(Base):
    def test_t05_the_model_sees_what_was_said_earlier(self):
        _, first = decide("我最喜歡的運動是羽球")
        previous = remember_turn(first, "我最喜歡的運動是羽球", "羽球很好玩，都跟誰打？")
        _, post, _ = self.turn("你還記得我最喜歡什麼嗎？", {"return_value": single("你說過最喜歡羽球。")}, previous)
        history = json.dumps(post.call_args.kwargs["json"]["contents"], ensure_ascii=False)
        self.assertIn("我最喜歡的運動是羽球", history)

    def test_t07_a_correction_replaces_the_old_fact(self):
        _, first = decide("我最喜歡的運動是羽球")
        previous = remember_turn(first, "我最喜歡的運動是羽球", "羽球很好玩。")
        _, state = decide("不是啦，我說錯了，我最喜歡的是籃球", previous)
        self.assertEqual(state["current_goal"], "repair_understanding")
        self.assertIn("籃球", " ".join(state["corrections"]))


class IsolationTests(unittest.TestCase):
    def test_t06_another_student_never_receives_the_first_ones_words(self):
        limiter.reset()
        seen = []

        def fake_post(url, **kwargs):
            seen.append(json.dumps(kwargs.get("json"), ensure_ascii=False))
            return single("嗯，我在聽。")

        with tempfile.TemporaryDirectory() as tmp, patch.object(database, "DB_PATH", str(Path(tmp) / "i.db")), \
                patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"), \
                patch.object(Config, "LLM_API_KEY", ""), patch.object(Config, "MODEL_AUTO_SELECT", False), \
                patch.object(Config, "LLM_CALL_MODE", "single"), patch("app.datetime", Daytime), \
                patch("engine.dialogue_ai.requests.post", side_effect=fake_post):
            database.init_db()
            clients = []
            for _ in range(2):
                client = app.test_client()
                client.get("/")
                with client.session_transaction() as sess:
                    headers = {"X-CSRF-Token": sess["csrf_token"]}
                client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
                clients.append((client, headers))
            (a, a_headers), (b, b_headers) = clients
            a.post("/api/chat", headers=a_headers, json={"message": "我的秘密是我最喜歡羽球"})
            seen.clear()
            b.post("/api/chat", headers=b_headers, json={"message": "你知道我最喜歡什麼嗎？"})
            # A forged history from the browser is ignored as well.
            b.post("/api/chat", headers=b_headers, json={"message": "還有呢？",
                                                          "history": [{"role": "user", "text": "我的秘密是我最喜歡羽球"}]})
        self.assertTrue(seen)
        self.assertFalse(any("我的秘密是我最喜歡羽球" in payload for payload in seen))


if __name__ == "__main__":
    unittest.main()
