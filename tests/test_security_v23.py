# -*- coding: utf-8 -*-
"""v2.3 Phase 2：送模型前個資遮罩、SQLite 欄位加密、雜湊鏈稽核。虛構資料，不連網。"""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from config import Config
from engine import crypto_store, dialogue_ai
from engine.dialogue_ai import generate_youth_response, prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.privacy_scrubber import pii_findings, scrub_pii
from engine.triage import perform_triage
from models import database

PII_TURN = "我叫林小明，住南投縣草屯鎮中正路500號，手機0912-345-678，身分證M123456789，這兩週都失眠。"
SECRETS = ("林小明", "草屯鎮中正路500號", "0912-345-678", "M123456789")


def gemini(text):
    response = Mock(status_code=200)
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return response


class PrivacyScrubberTests(unittest.TestCase):
    def test_masks_each_identifier_kind(self):
        masked = scrub_pii(PII_TURN)
        for secret in SECRETS:
            self.assertNotIn(secret, masked)
        for label in ("[姓名已隱碼]", "[地址已隱碼]", "[電話已隱碼]", "[身分證/學號已隱碼]"):
            self.assertIn(label, masked)
        self.assertIn("失眠", masked)
        self.assertEqual(scrub_pii("我的 IG 是 anla_cat99，信箱 a.b@example.com"), "我的 IG [帳號已隱碼]，信箱 [帳號已隱碼]")

    def test_ordinary_text_is_untouched(self):
        for text in ("我是學生", "我叫他不要再傳了", "1925 跟 119 都可以打", "段考考了 85 分，排名第 12",
                     "我閨蜜剛剛傳 LINE 跟我說她吞了很多顆安眠藥", "我住在埔里鎮"):
            with self.subTest(text=text):
                self.assertEqual(scrub_pii(text), text)
                self.assertEqual(pii_findings(text), [])

    def test_nothing_identifying_reaches_the_model(self):
        dialogue_ai.reset_model_health()
        with patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"), \
             patch("engine.dialogue_ai.requests.post", return_value=gemini("失眠兩週真的很辛苦，我先聽你說。")) as post:
            triage, state = prepare_dialogue(PII_TURN, perform_triage(PII_TURN))
            first = generate_youth_response(PII_TURN, triage, dialogue_state=state)
            state = remember_turn(state, PII_TURN, first["reply"])
            follow = "還有，我同學也會半夜傳訊息吵我"
            triage, state = prepare_dialogue(follow, perform_triage(follow), state)
            generate_youth_response(follow, triage, dialogue_state=state)
        self.assertGreaterEqual(post.call_count, 2)
        for call in post.call_args_list:
            payload = json.dumps(call.kwargs["json"], ensure_ascii=False)
            for secret in SECRETS:
                self.assertNotIn(secret, payload)
        # The server-side memory keeps the original words; only the outbound copy is masked.
        self.assertEqual(state["history"][0]["text"], PII_TURN)


class EncryptionAtRestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "enc.db")
        self.enterContext(patch.object(database, "DB_PATH", self.db))
        crypto_store.reset_key_cache()
        database.init_db()

    def tearDown(self):
        crypto_store.reset_key_cache()
        self.tmp.cleanup()

    def raw_bytes(self):
        return Path(self.db).read_bytes()

    def test_case_fields_are_ciphertext_on_disk_and_readable_in_app(self):
        case_id = database.save_case({
            "student_alias": "小明", "student_email": "student@example.edu.tw", "risk_level": "orange",
            "dialogue_snippet": "我最近真的很想消失", "life_impact": "上課一直分心",
            "summary": {"self_harm_signals": ["好想消失"]}, "triage": {"reasons": ["好想消失"]}})
        raw = self.raw_bytes()
        for plain in ("我最近真的很想消失", "student@example.edu.tw", "上課一直分心", "好想消失"):
            self.assertNotIn(plain.encode("utf-8"), raw)
        case = database.get_case_by_id(case_id)
        self.assertEqual(case["dialogue_snippet"], "我最近真的很想消失")
        self.assertEqual(case["summary"]["self_harm_signals"], ["好想消失"])
        self.assertEqual(database.get_all_cases(risk_filter="orange")[0]["student_email"], "student@example.edu.tw")

    def test_student_context_blob_is_ciphertext(self):
        from engine.referral import get_student_context, save_dialogue_state, set_student_profile
        set_student_profile("ctx", "hash", {"student_email": "x@example.com", "student_alias": "阿哲", "township": "南投市"})
        save_dialogue_state("ctx", "hash", {"risk_level": "green", "turn_count": 1,
                                             "history": [{"role": "user", "text": "這兩個禮拜都睡不好"}]}, 0)
        self.assertNotIn("這兩個禮拜都睡不好".encode("utf-8"), self.raw_bytes())
        self.assertNotIn(b"x@example.com", self.raw_bytes())
        self.assertEqual(get_student_context("ctx", "hash")["dialogue_state"]["history"][0]["text"], "這兩個禮拜都睡不好")

    def test_legacy_plaintext_rows_remain_readable(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO cases (case_id, student_alias, township, risk_level, status, dialogue_snippet,"
                         " bsrs5_json, triage_json, summary_json, created_at, updated_at)"
                         " VALUES ('OLD', '舊資料', '南投市', 'yellow', 'pending', '舊的明文', '{}', '{}', '{}', 'x', 'x')")
        self.assertEqual(database.get_case_by_id("OLD")["dialogue_snippet"], "舊的明文")

    def test_tampered_ciphertext_is_rejected(self):
        sealed = crypto_store.encrypt_text("秘密", self.db)
        broken = sealed[:-4] + ("AAAA" if not sealed.endswith("AAAA") else "BBBB")
        with self.assertRaises(crypto_store.DecryptionError):
            crypto_store.decrypt_text(broken, self.db)

    def test_stdlib_fallback_round_trip(self):
        sealed = crypto_store.encrypt_text("備援加密", self.db, force_fallback=True)
        self.assertTrue(sealed.startswith("enc:v0:"))
        self.assertEqual(crypto_store.decrypt_text(sealed, self.db), "備援加密")

    def test_passphrase_key_from_environment(self):
        with patch.dict(os.environ, {"ANLA_DB_KEY": "a long test passphrase"}):
            crypto_store.reset_key_cache()
            sealed = crypto_store.encrypt_text("用環境金鑰", self.db)
            self.assertEqual(crypto_store.decrypt_text(sealed, self.db), "用環境金鑰")
        crypto_store.reset_key_cache()
        with self.assertRaises(crypto_store.DecryptionError):
            crypto_store.decrypt_text(sealed, self.db)  # file key differs from the passphrase key


class AuditChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "audit.db")
        self.enterContext(patch.object(database, "DB_PATH", self.db))
        crypto_store.reset_key_cache()
        database.init_db()

    def tearDown(self):
        crypto_store.reset_key_cache()
        self.tmp.cleanup()

    def test_chain_verifies_and_detects_tampering(self):
        for i in range(4):
            database.log_audit("staff", "view_case", f"CASE-{i}", "查閱個案摘要")
        self.assertEqual(database.verify_audit_chain(), (True, None))
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE audit_logs SET details='竄改' WHERE id=2")
        self.assertEqual(database.verify_audit_chain(), (False, 2))

    def test_deleting_a_middle_entry_breaks_the_chain(self):
        for i in range(3):
            database.log_audit("staff", "view_case", f"CASE-{i}")
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM audit_logs WHERE id=2")
        self.assertFalse(database.verify_audit_chain()[0])

    def test_viewing_a_case_is_audited(self):
        from app import app
        case_id = database.save_case({"student_alias": "測試", "risk_level": "yellow"})
        with patch.object(Config, "WORKBENCH_PASSWORD", "local-test-password-long-enough"):
            client = app.test_client()
            client.get("/login")
            with client.session_transaction() as sess:
                token = sess["csrf_token"]
            client.post("/login", data={"password": "local-test-password-long-enough", "csrf_token": token})
            self.assertEqual(client.get(f"/api/cases/{case_id}").status_code, 200)
        with closing(sqlite3.connect(self.db)) as conn:
            actions = [r[0] for r in conn.execute("SELECT action FROM audit_logs WHERE case_id=?", (case_id,))]
        self.assertIn("view_case", actions)
        self.assertTrue(database.verify_audit_chain()[0])


if __name__ == "__main__":
    unittest.main()
