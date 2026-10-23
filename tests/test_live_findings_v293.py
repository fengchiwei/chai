# -*- coding: utf-8 -*-
"""v2.9.3：2026-10-23 在 Render 上手動測試發現的問題（安全問題重複、霸凌、字條、工作臺）。不連網。"""
import unittest
from pathlib import Path

from engine.ai_agent import generate_help_seeking_draft
from engine.knowledge import prompt_block, select
from engine.referral import DEFAULT_CATEGORY, summary_category
from engine.support import choose_support_offer, support_turn_instruction
from engine.triage import perform_triage
from tests.test_finals_v29 import RouteBase

ROOT = Path(__file__).resolve().parents[1]


class NoteWordingTests(unittest.TestCase):
    def test_self_check_labels_read_as_sentences(self):
        for impact, expected in (("有一點", "生活上也受到一點影響。"),
                                 ("明顯影響（例如不想上學、常請假、吃不下）", "已經明顯影響到上學或日常生活。"),
                                 ("沒有", ""), ("說不上來", "")):
            note = generate_help_seeking_draft({"category": "家裡", "life_impact": impact, "duration": "說不上來"})
            self.assertNotIn("例如有一點", note)
            self.assertNotIn("說不上來", note)
            if expected:
                self.assertIn(expected, note)

    def test_no_doubled_words_and_no_workbench_labels(self):
        plain = generate_help_seeking_draft({})
        self.assertIn("我最近因為心情和生活的事情", plain)
        self.assertIn("＿年＿班", plain)
        auto = generate_help_seeking_draft({"category": "自傷、家庭衝突", "category_auto": True})
        self.assertNotIn("自傷", auto)

    def test_the_note_offer_does_not_invite_a_second_note(self):
        offer, _ = choose_support_offer("請幫我寫給輔導老師的字條", "green", {}, {})
        self.assertEqual(offer["kind"], "draft")
        self.assertIn("點「寫一張給老師的小字條」", offer["text"])
        self.assertNotIn("可以一起", offer["text"])
        self.assertIn("不要自己在回覆裡寫字條內容", support_turn_instruction(offer))

    def test_the_header_button_makes_the_note_directly(self):
        page = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('onclick="window.AnlaNextSteps.openNote()">寫求助字條', page)


class CitationPromptTests(unittest.TestCase):
    def test_citations_only_for_facts_with_short_names(self):
        state = {"current_goal": "answer_question", "info_request": True, "township": "埔里鎮"}
        block = prompt_block(select("我住埔里，附近有衛生所嗎", state))
        self.assertIn("一般的鼓勵或做法", block)
        self.assertIn("不要拿法規來支持", block)
        self.assertNotIn("政府資料開放平臺", block)


class CaseCategoryTests(unittest.TestCase):
    def test_the_workbench_list_names_the_concern(self):
        snippet = "最近心情很差\n我現在沒有想傷害自己，但昨天真的有想過\n因為跟爸媽吵架"
        category = summary_category(snippet, perform_triage("我現在沒有想傷害自己，但昨天真的有想過"))
        self.assertTrue(category.startswith(("自傷", "自殺")), category)
        self.assertIn("家庭衝突", category)
        self.assertEqual(summary_category("今天天氣不錯", perform_triage("今天天氣不錯")), DEFAULT_CATEGORY)


class DiagnosticsTimingTests(RouteBase):
    def test_the_turn_time_includes_the_whole_turn(self):
        from unittest.mock import patch
        import app as app_module
        client, headers = self.student()
        real = app_module.prepare_dialogue

        def slow(*args, **kwargs):
            import time
            time.sleep(0.05)
            return real(*args, **kwargs)

        with patch.object(app_module, "prepare_dialogue", slow):
            client.post("/api/chat", headers=headers, json={"message": "今天好累"})
        turns = self.admin().get("/api/admin/diagnostics").json["turns"]
        self.assertGreaterEqual(turns[0]["latency_ms"], 50)


if __name__ == "__main__":
    unittest.main()
