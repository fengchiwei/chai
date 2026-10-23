# -*- coding: utf-8 -*-
"""v2.8.9：工作臺管理員專用「下載備份」。備份含個案、帳號、操作紀錄（敏感欄位仍加密），
不含未分享的對話暫存與金鑰；每次下載都留操作紀錄。只用暫存 SQLite，不連網。"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from models import database
from tests.test_safety_flow_v254 import Daytime


class BackupTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for p in (patch.object(database, "DB_PATH", str(self.tmp / "b.db")), patch.object(Config, "LLM_PROVIDER", "builtin"),
                  patch.object(Config, "WORKBENCH_PASSWORD", "builtin-pass-123"), patch("app.datetime", Daytime)):
            self.enterContext(p)
        database.init_db()
        database.create_staff_user("lin", "林老師", "counselor", "counselor-pass-1")
        # A student who asked for help (a case) and one who only chatted (an unshared conversation).
        for message, ask in (("最近跟家人一直吵架", True), ("今天放學想去打球", False)):
            student = app.test_client()
            student.get("/")
            with student.session_transaction() as sess:
                headers = {"X-CSRF-Token": sess["csrf_token"]}
            student.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
            steps = student.post("/api/chat", headers=headers, json={"message": message}).json["next_steps"]
            if ask:
                student.post("/api/referral/consent", headers=headers,
                             json={"consent": True, "revision": steps["revision"], "consent_kind": "request"})

    def login(self, username="", password="builtin-pass-123"):
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        client.post("/login", data={"username": username, "password": password, "csrf_token": token})
        return client, {"X-CSRF-Token": token}

    def test_admin_downloads_a_backup_without_unshared_conversations(self):
        client, headers = self.login()
        response = client.post("/api/admin/backup", headers=headers, json={})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"SQLite format 3"))
        self.assertIn("attachment; filename=\"anla_backup_", response.headers["Content-Disposition"])
        copy = self.tmp / "copy.db"
        copy.write_bytes(response.data)
        with closing(sqlite3.connect(copy)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM staff_users").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM student_contexts").fetchone()[0], 0)
            alias = conn.execute("SELECT student_alias FROM cases").fetchone()[0]
        self.assertNotIn("匿名同學", alias)  # still encrypted; the key is not in the file
        with closing(sqlite3.connect(database.DB_PATH)) as conn:  # the live database keeps its conversations
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM student_contexts").fetchone()[0], 2)
            actions = [row[0] for row in conn.execute("SELECT action FROM audit_logs")]
        self.assertIn("admin_backup_downloaded", actions)

    def test_a_backup_restores_with_the_same_key(self):
        import shutil
        client, headers = self.login()
        restored = self.tmp / "restored" / "anla_youth.db"
        restored.parent.mkdir()
        restored.write_bytes(client.post("/api/admin/backup", headers=headers, json={}).data)
        shutil.copy(database.DB_PATH + ".key", str(restored) + ".key")  # the key travels separately
        with patch.object(database, "DB_PATH", str(restored)):
            [case] = database.get_all_cases()
            self.assertEqual(case["status"], "student_requested_help")
            self.assertEqual(case["student_alias"], "匿名同學")  # decrypted with the same key
            self.assertTrue(database.authenticate_staff("lin", "counselor-pass-1"))

    def test_only_admins_with_the_csrf_token(self):
        counsellor, headers = self.login("lin", "counselor-pass-1")
        self.assertEqual(counsellor.post("/api/admin/backup", headers=headers, json={}).status_code, 403)
        admin, _ = self.login()
        self.assertEqual(admin.post("/api/admin/backup", headers={}, json={}).status_code, 403)
        self.assertEqual(app.test_client().post("/api/admin/backup", json={}).status_code, 401)

    def test_the_panel_is_for_admins_only(self):
        admin, _ = self.login()
        self.assertIn('id="backupPanel"', admin.get("/counselor").get_data(as_text=True))
        counsellor, _ = self.login("lin", "counselor-pass-1")
        self.assertNotIn('id="backupPanel"', counsellor.get("/counselor").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
