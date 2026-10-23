# -*- coding: utf-8 -*-
"""v2.8.7：回覆有錯字、讀起來自以為是；學生沒回時加上 1 分鐘與 5 分鐘的等待提醒。假 API，不連網。"""
from pathlib import Path

from engine.dialogue_ai import SYSTEM_PROMPT
from engine.dialogue_reply import presumptuous, tidy_surface
from tests.test_ai_only_v259 import Base, single
from tests.test_listening_v28 import plain

LOW = "最近心情好低落，做什麼事都提不起勁"
BOSSY = "其實你只是太累了，這樣的日子一定很不好過。"
HUMBLE = "提不起勁的時候，連小事都變得好重。會不會最近累積了一些事？不知道我有沒有猜對。"


class ToneTests(Base):
    def test_prompt_asks_for_humility_and_correct_characters(self):
        for phrase in ("不要自以為是", "解釋權在他", "只用正確的臺灣繁體中文", "著不是着"):
            self.assertIn(phrase, SYSTEM_PROMPT)

    def test_presumptuous_wording_is_detected(self):
        for text in (BOSSY, "我完全懂你的感受", "你需要的是好好休息", "說穿了就是壓力"):
            self.assertTrue(presumptuous(text), text)
        for text in (HUMBLE, "這聽起來很累。", "「其實你只是太累」是誰說的？"):
            self.assertFalse(presumptuous(text), text)

    def test_a_presumptuous_reply_is_rewritten_once(self):
        result, post, _ = self.turn(LOW, {"side_effect": [single(BOSSY), plain(HUMBLE)]})
        self.assertEqual(result["reply"], HUMBLE)
        self.assertEqual(post.call_count, 2)
        note = post.call_args_list[1].kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("自以為是", note)


class TypoTests(Base):
    def test_simplified_characters_are_converted(self):
        result, _, _ = self.turn(LOW, {"return_value": single("我们这样说吧，你还好吗？最近有发生什么事吗？")})
        self.assertNotRegex(result["reply"], "[们这说还么吗发]")
        self.assertIn("我們這樣說吧", result["reply"])

    def test_emoji_cleanup_does_not_create_odd_full_stops_or_eat_real_words(self):
        self.assertEqual(tidy_surface("這樣🎉真的很棒", "今天跟朋友吵架"), "這樣，真的很棒")
        self.assertEqual(tidy_surface("我買了一個包🥰", "今天跟朋友吵架"), "我買了一個包")


class IdleReminderTests(Base):
    def test_student_page_schedules_reminders_at_one_and_five_minutes(self):
        script = Path(__file__).resolve().parents[1].joinpath("static", "js", "app.js").read_text(encoding="utf-8")
        self.assertIn("after: 60 * 1000", script)
        self.assertIn("after: 5 * 60 * 1000", script)
        self.assertIn("scheduleIdleReminders(", script)
        self.assertIn('addEventListener("input", clearIdleReminders)', script)


if __name__ == "__main__":
    import unittest
    unittest.main()
