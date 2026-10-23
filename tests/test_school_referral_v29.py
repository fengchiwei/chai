# -*- coding: utf-8 -*-
"""v2.9：性平／霸凌不分燈號都提醒可以找學校輔導室，提供轉介單；學生願意說學校時，用核對過的輔導室信箱開草稿。
只用暫存 SQLite 與暫存學校名單，不連網、不寄信。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from engine import school_referral
from engine.dialogue_reply import safety_reply
from models import database
from tests.test_ai_only_v259 import Base, single
from tests.test_finals_v29 import ROOT, RouteBase

SCHOOLS = {"schools": [
    {"name": "測試縣立安啦國民中學", "aliases": ["安啦國中"], "office": "輔導室", "email": "anla.counsel@gmail.com",
     "phone": "049-0000000", "source_url": "https://example.edu.tw/counsel", "verified_on": "2026-10-23"},
    {"name": "沒有來源的高中", "email": "x@gmail.com", "verified_on": "2026-10-23"},
    {"name": "不是 https 的高中", "email": "y@gmail.com", "source_url": "http://example.edu.tw", "verified_on": "2026-10-23"},
    {"name": "信箱寫錯的高中", "email": "not-an-email", "source_url": "https://example.edu.tw", "verified_on": "2026-10-23"},
]}


class DetectionTests(unittest.TestCase):
    def test_gender_equity_and_bullying_are_recognised(self):
        cases = {
            "班上同學一直排擠我": ["bullying"], "我在網路上被肉搜還被造謠": ["bullying"], "我被霸凌了": ["bullying"],
            "有人在廁所偷拍我": ["gender_equity"], "學長一直摸我大腿": ["gender_equity"],
            "他們都叫我娘炮": ["gender_equity"], "補習班老師對我性騷擾": ["gender_equity"],
            "因為我是gay，同學都排擠我": ["bullying"],
            "他們笑我太娘還把我書包丟掉": ["gender_equity", "bullying"],
        }
        for text, expected in cases.items():
            self.assertEqual(school_referral.detect_topics(text), expected, text)

    def test_denials_jokes_and_ordinary_talk_are_not(self):
        for text in ("我沒有被霸凌，只是有點累", "今天被數學霸凌了", "今天放學想去打球", "媽媽摸我的頭說加油",
                     "不是性騷擾啦，是我想太多", "考試好難"):
            self.assertEqual(school_referral.detect_topics(text), [], text)

    def test_the_note_names_only_the_topic_never_the_students_words(self):
        note = school_referral.referral_note(["bullying"])
        self.assertIn("校園霸凌", note)
        self.assertIn("輔導室老師您好", note)
        self.assertNotIn("排擠我", note)
        self.assertIn("要不要交出去由我自己決定", note)


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "schools.json"
        path.write_text(json.dumps(SCHOOLS, ensure_ascii=False), encoding="utf-8")
        self.enterContext(patch.object(school_referral, "DATA", str(path)))

    def test_only_verified_entries_with_an_https_source_are_used(self):
        self.assertEqual([s["name"] for s in school_referral.directory()], ["測試縣立安啦國民中學"])
        self.assertIsNone(school_referral.find_school("沒有來源的高中"))

    def test_names_and_aliases_match_but_vague_names_do_not(self):
        for name in ("安啦國中", "測試縣立 安啦國民中學", "我讀安啦國中二年級"):
            self.assertEqual(school_referral.find_school(name)["email"], "anla.counsel@gmail.com", name)
        for name in ("國中", "", "南投高中"):
            self.assertIsNone(school_referral.find_school(name), name)

    def test_the_mail_draft_carries_the_note_and_sends_nothing(self):
        data = school_referral.payload(["gender_equity"], "安啦國中")
        link = data["school"]["mailto"]
        self.assertTrue(link.startswith("mailto:anla.counsel@gmail.com?subject="))
        self.assertIn("測試縣立安啦國民中學輔導室老師您好", unquote(link))
        self.assertEqual(data["notices"][0]["source"]["url"], "https://edu.law.moe.gov.tw/LawContent.aspx?id=FL030508")
        self.assertIn("113", data["notices"][0]["text"])

    def test_the_shipped_directory_has_no_unusable_entries(self):
        shipped = json.loads((ROOT / "data" / "school_counseling.json").read_text(encoding="utf-8"))["schools"]
        with patch.object(school_referral, "DATA", str(ROOT / "data" / "school_counseling.json")):
            self.assertEqual(len(school_referral.directory()), len(shipped))


class RouteTests(RouteBase):
    def setUp(self):
        super().setUp()
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "schools.json"
        path.write_text(json.dumps(SCHOOLS, ensure_ascii=False), encoding="utf-8")
        self.enterContext(patch.object(school_referral, "DATA", str(path)))

    def chat(self, client, headers, message):
        return client.post("/api/chat", headers=headers, json={"message": message}).json

    def test_any_risk_level_gets_the_card_with_every_mention(self):
        client, headers = self.student()
        first = self.chat(client, headers, "班上同學一直排擠我，下課都沒人理我")
        self.assertFalse(first["show_support_help"])                     # an everyday (not urgent) message
        self.assertEqual(first["school_referral"]["topics"], ["霸凌"])
        self.assertIn("1953", first["school_referral"]["notices"][0]["text"])
        self.assertIsNone(first["school_referral"]["school"])
        # Sent again with every mention (the page shows each topic once): a first reply lost to a network error
        # left the student without the card (2026-10-23 live test 「被同學霸凌」).
        again = self.chat(client, headers, "今天又被排擠了")
        self.assertEqual(again["school_referral"]["topics"], ["霸凌"])
        self.assertIsNone(self.chat(client, headers, "今天午餐吃咖哩")["school_referral"])
        self.assertTrue(again["school_referral_available"])               # the header button stays
        both = self.chat(client, headers, "還有學長在走廊摸我屁股")
        self.assertEqual(both["school_referral"]["topics"], ["霸凌", "性平事件"])
        self.assertTrue(client.get("/api/chat/state").json["school_referral_available"])

    def test_urgent_messages_get_the_card_too(self):
        client, headers = self.student()
        data = self.chat(client, headers, "我被性侵了，我不想活了")
        self.assertTrue(data["show_support_help"])
        self.assertEqual(data["school_referral"]["topics"], ["性平事件"])

    def test_ordinary_chat_gets_no_card(self):
        client, headers = self.student()
        data = self.chat(client, headers, "今天放學想去打球")
        self.assertIsNone(data["school_referral"])
        self.assertFalse(data["school_referral_available"])

    def test_naming_a_school_finds_its_office_without_saving_the_name(self):
        client, headers = self.student()
        self.chat(client, headers, "我被霸凌了")
        found = client.post("/api/school-referral", headers=headers, json={"school": "安啦國中"}).json["school_referral"]
        self.assertEqual(found["school"]["email"], "anla.counsel@gmail.com")
        self.assertIn("測試縣立安啦國民中學輔導室老師您好", found["note"])
        missing = client.post("/api/school-referral", headers=headers, json={"school": "火星高中"}).json["school_referral"]
        self.assertTrue(missing["school_asked"])
        self.assertIsNone(missing["school"])
        self.assertEqual(client.get("/api/chat/state").json["student_profile"]["student_school"], "")
        self.assertEqual(database.get_all_cases(), [])                     # nothing is sent or recorded
        self.assertEqual(client.post("/api/school-referral", headers=headers, json={"school": "x" * 101}).status_code, 400)
        self.assertEqual(client.post("/api/school-referral", json={"school": "安啦國中"}).status_code, 403)

    def test_a_new_conversation_forgets_the_topics(self):
        client, headers = self.student()
        self.chat(client, headers, "我被霸凌了")
        client.post("/api/chat/reset", headers=headers, json={})
        self.assertFalse(client.get("/api/chat/state").json["school_referral_available"])
        self.assertEqual(self.chat(client, headers, "又被霸凌了")["school_referral"]["topics"], ["霸凌"])


class BullyingIsNotASuicideQuestionTests(Base):
    """2026-10-23 live test: 「被同學霸凌」 → the model labelled it a suicide signal → 「你最近有沒有不想活了」."""

    def hint(self, kind, evidence):
        return {"risk": {"signal": "ambiguous", "type": kind, "danger": "possible", "subject": "self",
                         "affirmed": True, "evidence": evidence}}

    def test_a_suicide_hint_quoting_only_the_bullying_is_ignored(self):
        reply = "被同學霸凌真的很難受，這不是你的錯。願意說說發生了什麼事嗎？"
        result, _, state = self.turn("被同學霸凌", {"return_value": single(reply, self.hint("suicide", "被同學霸凌"))})
        self.assertFalse(state["safety_check_required"])
        self.assertEqual(result["reply"], reply)

    def test_death_words_next_to_the_bullying_still_count(self):
        text = "被同學霸凌，我真的不想活了"
        _, _, state = self.turn(text, {"return_value": single("我在。", self.hint("suicide", text))})
        self.assertTrue(state["safety_check_required"])

    def test_a_bullying_safety_check_asks_about_safety_not_dying(self):
        _, _, state = self.turn("被同學霸凌", {"return_value": single("我在。", self.hint("abuse", "被同學霸凌"))})
        text = safety_reply("被同學霸凌", {**state, "safety_action": "brief_safety_check"})
        self.assertIn("現在安全嗎", text)
        self.assertNotIn("不想活", text)


if __name__ == "__main__":
    unittest.main()
