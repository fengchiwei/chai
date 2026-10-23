# -*- coding: utf-8 -*-
"""v2.8：紓壓知識 Harness（docs/HARNESS_PLAN.md P0–P2）。學生問方法時引用已核對來源的知識卡；
安全回合不使用；回覆不能編造來源；學生頁顯示資料來源。假 API，不連網。"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from engine import knowledge
from engine.dialogue_ai import UNAVAILABLE_LABEL, generate_youth_response, prepare_dialogue
from engine.dialogue_reply import MEDICAL_ADVICE
from engine.triage import perform_triage
from models import database
from tests.test_ai_only_v259 import Base, single
from tests.test_safety_flow_v254 import Daytime

SLEEP = {"id": "sleep-routine", "topic": "sleep", "title": "睡前一小時的放鬆習慣", "status": "pilot",
         "keywords": ["睡不著", "失眠", "熬夜"], "summary": "固定的睡前習慣能幫助入睡。",
         "steps": ["睡前一小時把手機放到房間外", "每天差不多同一時間上床"], "cautions": [],
         "when_to_seek_help": "睡不好超過兩週、影響上學，就找輔導老師或醫師聊聊。", "evidence": "official_guideline",
         "sources": [{"publisher": "衛生福利部國民健康署", "name": "青少年睡眠", "url": "https://www.hpa.gov.tw/x"}]}
BREATH = {"id": "slow-breath", "topic": "breathing", "title": "放慢呼吸", "status": "pilot",
          "keywords": ["壓力好大", "喘不過氣", "緊張"], "summary": "慢慢吐氣能讓身體放鬆。",
          "steps": ["用鼻子吸氣數到四", "嘴巴慢慢吐氣數到六"], "cautions": ["頭暈就停下來正常呼吸"],
          "when_to_seek_help": "常常喘不過氣、影響生活，請找輔導老師或醫師。", "evidence": "official_guideline",
          "sources": [{"publisher": "英國國民保健署 NHS", "name": "Breathing exercises", "url": "https://www.nhs.uk/y"}]}
POOL = [SLEEP, BREATH]
ASK = "最近壓力好大，有什麼方法可以放鬆嗎"


class CardRulesTests(unittest.TestCase):
    def test_only_reviewed_unexpired_allowlisted_cards_are_used(self):
        domains = knowledge.allowed_domains()
        self.assertTrue(knowledge.usable(SLEEP, domains))
        self.assertFalse(knowledge.usable({**SLEEP, "status": "draft"}, domains))
        self.assertFalse(knowledge.usable({**SLEEP, "expires_at": "2020-01-01"}, domains))
        for url in ("https://example.com/blog", "http://www.hpa.gov.tw/x", "https://hpa.gov.tw.evil.com/x"):
            card = {**SLEEP, "sources": [{"publisher": "x", "url": url}]}
            self.assertFalse(knowledge.usable(card, domains), url)

    def test_search_finds_the_topic_and_ignores_unrelated_messages(self):
        self.assertEqual(knowledge.search("考前一直睡不著怎麼辦", pool=POOL)[0]["id"], "sleep-routine")
        self.assertEqual(knowledge.search(ASK, pool=POOL)[0]["id"], "slow-breath")
        self.assertEqual(knowledge.search("今天午餐吃咖哩飯", pool=POOL), [])

    def test_invented_sources_are_detected(self):
        self.assertFalse(knowledge.invented_source("試試慢慢吐氣（資料來源：NHS）", [BREATH]))
        self.assertTrue(knowledge.invented_source("試試慢慢吐氣（資料來源：哈佛大學）", [BREATH]))
        self.assertTrue(knowledge.invented_source("WHO 建議你慢慢吐氣", [BREATH]))
        self.assertFalse(knowledge.invented_source("難過時也可以打衛福部 1925 安心專線", [BREATH]))
        self.assertEqual(knowledge.cited("（資料來源：國健署）", [SLEEP, BREATH]), [SLEEP])


class ReplyTests(Base):
    def setUp(self):
        super().setUp()
        self.enterContext(patch("engine.knowledge.cards", return_value=POOL))

    def test_coping_question_gets_cards_and_shows_the_cited_source(self):
        reply = "壓力大的時候可以先試著放慢呼吸：吸氣數到四、吐氣數到六。（資料來源：NHS）"
        result, post, _ = self.turn(ASK, {"return_value": single(reply)})
        prompt = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("本輪參考資料卡", prompt)
        self.assertIn("放慢呼吸", prompt)
        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["sources"], [{"title": "放慢呼吸", "publisher": "英國國民保健署 NHS",
                                              "url": "https://www.nhs.uk/y"}])

    def test_a_made_up_source_is_not_sent(self):
        result, _, _ = self.turn(ASK, {"return_value": single("哈佛研究說每天冥想十分鐘就好。")})
        self.assertEqual(result["model_used"], UNAVAILABLE_LABEL)

    def test_safety_turns_and_plain_chat_get_no_cards(self):
        for message in ("我不想活了，有什麼方法可以讓我不痛", "今天考試好累"):
            with self.subTest(message=message):
                _, post, _ = self.turn(message, {"return_value": single("我在這裡。請打 119 或 110，想談可以打 1925。")})
                prompt = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
                self.assertNotIn("本輪參考資料卡", prompt)

    def test_listen_only_style_gets_no_cards(self):
        _, state = prepare_dialogue(ASK, perform_triage(ASK), {}, use_model=False, hour=14, reply_style="listen_only")
        self.assertEqual(knowledge.select(ASK, state), [])


class RouteTests(unittest.TestCase):
    def test_chat_returns_sources_and_the_transcript_keeps_them(self):
        limiter.reset()
        reply = "可以先試著放慢呼吸，吐氣比吸氣長一點。（資料來源：NHS）"
        with tempfile.TemporaryDirectory() as tmp, patch.object(database, "DB_PATH", str(Path(tmp) / "k.db")), \
                patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"), \
                patch.object(Config, "LLM_API_KEY", ""), patch.object(Config, "MODEL_AUTO_SELECT", False), \
                patch.object(Config, "LLM_CALL_MODE", "single"), patch("app.datetime", Daytime), \
                patch("engine.knowledge.cards", return_value=POOL), \
                patch("engine.dialogue_ai.requests.post", return_value=single(reply)):
            database.init_db()
            client = app.test_client()
            client.get("/")
            with client.session_transaction() as sess:
                headers = {"X-CSRF-Token": sess["csrf_token"]}
            client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
            data = client.post("/api/chat", headers=headers, json={"message": ASK}).json
            from app import current_student_context  # noqa: F401  (context read below through the DB)
            with client.session_transaction() as sess:
                ctx = (sess["student_context_id"], sess["student_email_hash"])
            from engine.referral import get_student_context
            transcript = get_student_context(*ctx)["transcript"]
        self.assertEqual(data["sources"][0]["publisher"], "英國國民保健署 NHS")
        self.assertEqual(transcript[-1]["cards"], ["放慢呼吸"])
        page = app.test_client().get("/static/js/app.js").get_data(as_text=True)
        self.assertIn("appendSources", page)


class CardDataTests(unittest.TestCase):
    """The shipped cards (data/knowledge/cards.json): P1 asked for 30+, every one sourced from the allowlist,
    and every topic of the five areas in topics.json has at least one card."""

    def setUp(self):
        self.raw = json.loads(Path(knowledge.BASE, "cards.json").read_text(encoding="utf-8"))
        self.topics = {t["id"] for t in json.loads(Path(knowledge.BASE, "topics.json").read_text(encoding="utf-8"))["topics"]}

    def test_at_least_thirty_usable_cards_covering_every_topic(self):
        usable = knowledge.cards()
        self.assertGreaterEqual(len(usable), 30)
        self.assertEqual(len(usable), len(self.raw))  # nothing silently dropped
        self.assertEqual(len({c["id"] for c in self.raw}), len(self.raw))
        self.assertEqual({c["topic"] for c in self.raw}, self.topics)

    def test_card_content_rules(self):
        for card in self.raw:
            with self.subTest(card=card["id"]):
                self.assertTrue(2 <= len(card["steps"]) <= 4)
                self.assertTrue(card["when_to_seek_help"])
                self.assertTrue(card["keywords"])
                text = " ".join([card["title"], card["summary"], *card["steps"], *card.get("cautions", [])])
                self.assertIsNone(re.search(MEDICAL_ADVICE, text))
                for source in card["sources"]:
                    self.assertTrue(source.get("publisher") and source.get("checked_at"))

    def test_a_question_per_topic_finds_a_card(self):
        questions = {"sleep": "最近都睡不著怎麼辦", "exam": "考前好緊張怎麼辦", "anger": "我好生氣要怎麼冷靜",
                     "loneliness": "覺得很孤單沒有朋友怎麼辦", "screen": "一直滑手機停不下來怎麼辦",
                     "breathing": "緊張到喘不過氣有什麼方法", "worry": "一直擔心停不下來怎麼辦",
                     "substances": "電子煙對身體有什麼影響", "part_time_work": "15歲可以打工嗎",
                     "bullying": "被霸凌可以找誰", "counseling_access": "公費心理諮商怎麼申請",
                     "online_safety": "私密照被威脅要散布怎麼辦", "study_skills": "讀書都讀不進去怎麼辦",
                     "admissions": "學測和申請入學的資訊去哪裡查"}
        for topic, question in questions.items():
            with self.subTest(topic=topic):
                found = knowledge.search(question)
                self.assertTrue(found, question)
                self.assertIn(topic, {c["topic"] for c in found} | {found[0]["topic"]})


if __name__ == "__main__":
    unittest.main()
