# -*- coding: utf-8 -*-
"""v2.9：性平／霸凌不分燈號都提醒可以找學校輔導室，提供轉介單；學生願意說學校時，從教育部學校名錄找出學校總機與網站，
核對過輔導室信箱的學校可以開郵件草稿。
只用暫存 SQLite 與暫存學校名單，不連網、不寄信。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from engine import school_referral
from engine.dialogue_ai import prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import safety_reply
from engine.triage import perform_triage
from models import database
from tests.test_ai_only_v259 import Base, single
from tests.test_finals_v29 import ROOT, RouteBase

SCHOOLS = {"schools": [
    {"name": "國立南投高中", "office": "輔導室", "email": "counsel.test@gmail.com",
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
            "他們一直在LINE群組裡笑我，還把我的照片做成梗圖": ["bullying"],
            "有人把我的醜照傳到班群": ["bullying"],
            "補習班老師一直私訊我，說我身材很好，還叫我不要跟別人說": ["gender_equity"],
            "學長傳很噁心的訊息給我": ["gender_equity"],
        }
        for text, expected in cases.items():
            self.assertEqual(school_referral.detect_topics(text), expected, text)

    def test_denials_jokes_and_ordinary_talk_are_not(self):
        for text in ("我沒有被霸凌，只是有點累", "今天被數學霸凌了", "今天放學想去打球", "媽媽摸我的頭說加油",
                     "不是性騷擾啦，是我想太多", "考試好難", "我在看梗圖笑死", "朋友私訊我問作業", "群組裡大家在聊天"):
            self.assertEqual(school_referral.detect_topics(text), [], text)

    def test_the_note_names_only_the_topic_never_the_students_words(self):
        note = school_referral.referral_note(["bullying"])
        self.assertIn("校園霸凌", note)
        self.assertIn("輔導室老師您好", note)
        self.assertNotIn("排擠我", note)
        self.assertIn("要不要交出去由我自己決定", note)


class DirectoryTests(unittest.TestCase):
    """Every school in the Ministry of Education directory can be found; the counseling email only where verified."""

    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "schools.json"
        path.write_text(json.dumps(SCHOOLS, ensure_ascii=False), encoding="utf-8")
        self.enterContext(patch.object(school_referral, "DATA", str(path)))

    def pick(self, text):
        return school_referral.pick_school(text, county="南投縣")

    def test_only_verified_entries_with_an_https_source_are_used(self):
        self.assertEqual([s["name"] for s in school_referral.directory()], ["國立南投高中"])

    def test_common_ways_of_writing_a_school_name(self):
        for text, name in (("南投高中", "國立南投高中"), ("國立南投高級中學", "國立南投高中"), ("我讀埔里國中二年級", "縣立埔里國中"),
                           ("暨大附中", "國立暨大附中"), ("均頭國中", "私立均頭國中(小)"), ("建國高中", "市立建國中學"),
                           ("臺北市立建國高級中學", "市立建國中學"), ("台中一中", "市立臺中一中")):
            self.assertEqual(self.pick(text)[0]["name"], name, text)
        for text in ("國中", "", "火星高中"):
            self.assertEqual(self.pick(text), (None, []), text)

    def test_same_names_prefer_nantou_and_offer_the_others(self):
        school, others = self.pick("中正國小")
        self.assertEqual(school["county"], "南投縣")
        self.assertTrue(others and all(o["name"].endswith("中正國小") and o["county"] != "南投縣" for o in others))
        school, choices = school_referral.pick_school("中正國小", county="臺東縣")
        self.assertTrue(school is None or school["county"] == "臺東縣")
        if school is None:
            self.assertGreater(len(choices), 1)

    def test_a_directory_school_shows_its_main_line_and_the_source(self):
        data = school_referral.payload(["bullying"], "埔里國中", county="南投縣")
        school = data["school"]
        self.assertEqual(school["phone"], "(049)2982055")
        self.assertEqual(school["phone_href"], "tel:0492982055")
        self.assertEqual(school["email"], "")                               # no guessed counseling email
        self.assertEqual(school["mailto"], "")
        self.assertTrue(school["source_url"].startswith("https://depart.moe.edu.tw/"))
        self.assertIn("縣立埔里國中輔導室老師您好", data["note"])

    def test_a_verified_school_gets_the_mail_draft(self):
        data = school_referral.payload(["gender_equity"], "南投高中", county="南投縣")
        link = data["school"]["mailto"]
        self.assertTrue(link.startswith("mailto:counsel.test@gmail.com?subject="))
        self.assertIn("國立南投高中輔導室老師您好", unquote(link))
        self.assertEqual(data["notices"][0]["source"]["url"], "https://edu.law.moe.gov.tw/LawContent.aspx?id=FL030508")
        self.assertIn("113", data["notices"][0]["text"])

    def test_the_shipped_data(self):
        shipped = json.loads((ROOT / "data" / "school_counseling.json").read_text(encoding="utf-8"))["schools"]
        with patch.object(school_referral, "DATA", str(ROOT / "data" / "school_counseling.json")):
            self.assertEqual(len(school_referral.directory()), len(shipped))
        moe = json.loads((ROOT / "data" / "schools_moe.json").read_text(encoding="utf-8"))
        self.assertGreater(len(moe["schools"]), 4000)
        self.assertEqual(len({s["code"] for s in moe["schools"]}), len(moe["schools"]))
        for school in moe["schools"]:
            self.assertTrue(school["name"] and school["county"] and school["phone"], school)
        levels = {s["level"] for s in moe["schools"]}
        self.assertEqual(levels, {"國小", "國中", "高中職", "特殊教育學校", "大專校院"})


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
        found = client.post("/api/school-referral", headers=headers, json={"school": "南投高中"}).json["school_referral"]
        self.assertEqual(found["school"]["email"], "counsel.test@gmail.com")
        self.assertIn("國立南投高中輔導室老師您好", found["note"])
        other = found["school"]["code"]
        many = client.post("/api/school-referral", headers=headers, json={"school": "中正國小"}).json["school_referral"]
        self.assertEqual(many["school"]["county"], "南投縣")
        picked = client.post("/api/school-referral", headers=headers,
                             json={"code": many["choices"][0]["code"]}).json["school_referral"]
        self.assertEqual(picked["school"]["code"], many["choices"][0]["code"])
        self.assertNotEqual(picked["school"]["code"], other)
        self.assertEqual(client.post("/api/school-referral", headers=headers, json={"code": "../x"}).status_code, 400)
        missing = client.post("/api/school-referral", headers=headers, json={"school": "火星高中"}).json["school_referral"]
        self.assertTrue(missing["school_asked"])
        self.assertIsNone(missing["school"])
        self.assertEqual(client.get("/api/chat/state").json["student_profile"]["student_school"], "")
        self.assertEqual(database.get_all_cases(), [])                     # nothing is sent or recorded
        self.assertEqual(client.post("/api/school-referral", headers=headers, json={"school": "x" * 101}).status_code, 400)
        self.assertEqual(client.post("/api/school-referral", json={"school": "南投高中"}).status_code, 403)

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

    def test_any_label_on_a_bullying_quote_starts_no_check(self):
        # 2026-10-23 live test on Render: after v2.9.1 the model labelled it 「other」 and the question came back.
        for kind in ("suicide", "self_harm", "other", "abuse"):
            reply = "被同學霸凌真的很難受，這不是你的錯。願意說說發生了什麼事嗎？"
            result, _, state = self.turn("被同學霸凌", {"return_value": single(reply, self.hint(kind, "被同學霸凌"))})
            self.assertFalse(state["safety_check_required"], kind)
            self.assertEqual(result["reply"], reply, kind)

    def test_a_gender_equity_check_asks_about_safety_not_dying(self):
        text = "補習班老師一直私訊我，說我身材很好"
        _, _, state = self.turn(text, {"return_value": single("我在。", self.hint("other", text))})
        self.assertEqual(state["risk_type"], "abuse")
        reply = safety_reply(text, {**state, "safety_action": "brief_safety_check"})
        self.assertIn("現在安全嗎", reply)
        self.assertNotIn("不想活", reply)


class SafetyRepeatTests(Base):
    """2026-10-23 live test: the same safety question on four turns, and again after it was answered."""

    def test_an_unanswered_gentle_check_is_asked_once_more_then_dropped(self):
        state = {}
        asked = []
        for message in ("今天熱到快往生，體育課還跑操場", "你還記得我最喜歡什麼運動嗎？", "不是啦我說錯了，是籃球", "那我最喜歡的運動是什麼"):
            _, state = prepare_dialogue(message, perform_triage(message), state, use_model=False, hour=14)
            asked.append(state["safety_check_required"])
            state = remember_turn(state, message, "好喔")
        self.assertEqual(asked, [True, True, False, False])
        self.assertEqual(state["risk_level"], "yellow")                   # the staff-facing level does not drop

    def test_an_answer_with_a_time_counts_as_an_answer(self):
        state = {}
        for message in ("最近心情很差", "我現在沒有想傷害自己，但昨天真的有想過"):
            _, state = prepare_dialogue(message, perform_triage(message), state, use_model=False, hour=14)
            state = remember_turn(state, message, safety_reply(message, state) if state["safety_check_required"] else "嗯")
        answer = "昨天晚上有想過，但現在還好"
        state_before = state
        _, state = prepare_dialogue(answer, perform_triage(answer), state, use_model=False, hour=14)
        self.assertTrue(state["ideation_confirmed"])
        reply = safety_reply(answer, state)
        self.assertNotIn("結束自己的生命", reply)
        for denial in ("沒有想過", "我從來沒有想過"):
            _, after = prepare_dialogue(denial, perform_triage(denial), state_before, use_model=False, hour=14)
            self.assertFalse(after.get("thoughts_confirmed"), denial)

    def test_the_hotline_reminder_is_not_repeated_every_turn(self):
        state = {}
        replies = []
        for message in ("我現在沒有想傷害自己，但昨天真的有想過", "有", "因為跟爸媽吵架", "我在房間"):
            _, state = prepare_dialogue(message, perform_triage(message), state, use_model=False, hour=14)
            reply = safety_reply(message, state)
            replies.append(reply)
            state = remember_turn(state, message, reply)
        self.assertLessEqual(sum("一直都在" in r for r in replies[1:]), 1)
        self.assertEqual(len(set(replies[1:])), len(replies[1:]))


if __name__ == "__main__":
    unittest.main()
