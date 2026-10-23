# -*- coding: utf-8 -*-
"""v2.9.3：2026-10-23 在 Render 上手動測試發現的問題（安全問題重複、霸凌、字條、工作臺）。不連網。"""
import unittest
from pathlib import Path

from engine.ai_agent import generate_help_seeking_draft
from engine.knowledge import prompt_block, select
from engine.referral import DEFAULT_CATEGORY, summary_category
from engine.support import choose_support_offer, support_turn_instruction
from engine.triage import perform_triage
from unittest.mock import Mock

from tests.test_ai_only_v259 import Base, single
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
            time.sleep(0.2)
            return real(*args, **kwargs)

        with patch.object(app_module, "prepare_dialogue", slow):
            client.post("/api/chat", headers=headers, json={"message": "今天好累"})
        turns = self.admin().get("/api/admin/diagnostics").json["turns"]
        self.assertGreaterEqual(turns[0]["latency_ms"], 150)


class SecondRoundLiveTests(unittest.TestCase):
    """2026-10-23 second live round on Render (v2.9.3)."""

    def test_the_abuse_check_moves_on_instead_of_repeating(self):
        from engine.dialogue_reply import safety_reply
        state = {"safety_action": "brief_safety_check", "risk_type": "abuse", "risk_subject": "self",
                 "history": [{"role": "user", "text": "補習班老師一直私訊我，說我身材很好"},
                             {"role": "assistant", "text": "這不是你的錯，願意說出來很不容易。想先確認一下：你現在安全嗎？這件事現在還在發生嗎？"}],
                 "last_reply": ""}
        reply = safety_reply("他還在傳，昨天還約我下課單獨去找他", state)
        self.assertNotIn("現在安全嗎", reply)
        self.assertIn("先不要單獨去見對方", reply)
        self.assertIn("截圖", reply)
        self.assertIn("113", reply)

    def test_no_hotline_added_when_the_reference_has_none(self):
        from engine.dialogue_ai import prepare_dialogue, turn_task
        from engine.dialogue_policy import remember_turn
        from engine.dialogue_reply import safety_reply
        state = {}
        for message in ("我現在沒有想傷害自己，但昨天真的有想過", "有", "因為跟爸媽吵架"):
            _, state = prepare_dialogue(message, perform_triage(message), state, use_model=False, hour=14)
            task = turn_task(message, state)
            state = remember_turn(state, message, safety_reply(message, state))
        self.assertIn("這一輪不要自己再加求助電話", task)


class CarriedLevelTests(RouteBase):
    """2026-10-23 third live round: after a redeploy the cookie still remembered an orange level, and a report
    about a tutor's messages got the suicide-safety script plus a new workbench alert with no evidence."""

    def test_a_remembered_level_does_not_restart_the_safety_script(self):
        from models import database
        client, headers = self.student()
        with client.session_transaction() as sess:
            sess["highest_risk"] = "orange"
            sess["student_context_id"] = "expired-context-id"      # the stored conversation is gone
        client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
        data = client.post("/api/chat", headers=headers,
                           json={"message": "補習班老師一直私訊我，說我身材很好"}).json
        self.assertFalse(data["style_overridden_by_safety"])
        self.assertNotIn("結束自己的生命", data["reply"])
        self.assertIsNone(data["safety_alert"])
        self.assertEqual(database.get_all_cases(), [])
        danger = client.post("/api/chat", headers=headers, json={"message": "我今晚已決定傷害自己，並已做好準備"}).json
        self.assertTrue(danger["show_urgent_help"])
        self.assertIsNotNone(danger["safety_alert"])               # new evidence still reaches the workbench


class EmptyAnswerRetryTests(Base):
    """2026-10-23 live test: the structured answer came back with an empty reply and the student was told the AI
    could not be reached. One plain retry is made when time allows; safety turns keep the reviewed text."""

    def test_an_empty_answer_is_retried_once(self):
        plain = Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [
            {"text": "睡不著真的很磨人。今晚可以先把手機放遠一點，躺不住就起來做點安靜的事。"}]}}]}))
        result, post, _ = self.turn("睡不著怎麼辦", {"side_effect": [single(""), plain]})
        self.assertEqual(post.call_count, 2)
        self.assertIn("手機放遠", result["reply"])

    def test_a_safety_turn_is_not_retried(self):
        result, post, _ = self.turn("我不想活了", {"side_effect": [single("")] * 3})
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["model_used"], "安全回覆")


if __name__ == "__main__":
    unittest.main()
