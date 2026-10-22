# -*- coding: utf-8 -*-
"""學生頁的 AI 連線狀態：/api/status 與每輪回覆的狀態資訊。假 API，不連網。"""
import unittest
from unittest.mock import Mock, patch

from config import Config
from engine import dialogue_ai
from engine.dialogue_ai import generate_youth_response, model_status
from engine.triage import perform_triage


def status_response(code, text=""):
    return Mock(status_code=code, text=text)


class ModelStatusTests(unittest.TestCase):
    def setUp(self):
        dialogue_ai.reset_model_health()

    def tearDown(self):
        dialogue_ai.reset_model_health()

    def gemini(self):
        return (patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"))

    def test_not_configured_without_a_key(self):
        with patch.object(Config, "LLM_PROVIDER", "builtin"):
            self.assertEqual(model_status(probe=True)["state"], "not_configured")
        with patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", ""):
            self.assertEqual(model_status(probe=True)["state"], "not_configured")

    def test_probe_states_and_cache(self):
        cases = [(status_response(200), "ok", None), (status_response(403), "degraded", "auth_error"),
                 (status_response(400, '{"error": {"details": [{"reason": "API_KEY_INVALID"}]}}'), "degraded", "auth_error"),
                 (status_response(404), "degraded", "model_not_found")]
        for response, state, reason in cases:
            with self.subTest(code=response.status_code, reason=reason):
                dialogue_ai.reset_model_health()
                p1, p2 = self.gemini()
                with p1, p2, patch("engine.dialogue_ai.requests.get", return_value=response) as get:
                    first = model_status(probe=True)
                    model_status(probe=True)
                self.assertEqual(first["state"], state)
                self.assertEqual(first["reason"] if reason else None, reason)
                self.assertEqual(get.call_count, 1)  # cached for PROBE_TTL

    def test_probe_never_generates_or_leaks_the_key(self):
        p1, p2 = self.gemini()
        with p1, p2, patch("engine.dialogue_ai.requests.get", return_value=status_response(200)) as get, \
             patch("engine.dialogue_ai.requests.post") as post:
            result = model_status(probe=True)
        post.assert_not_called()
        self.assertNotIn("test-key", str(result))
        self.assertTrue(get.call_args.args[0].endswith("/models/" + Config.GEMINI_MODEL))

    def test_a_later_chat_failure_overrides_a_cached_ok_probe(self):
        p1, p2 = self.gemini()
        with p1, p2, patch("engine.dialogue_ai.requests.get", return_value=status_response(200)):
            self.assertEqual(model_status(probe=True)["state"], "ok")
            with patch("engine.dialogue_ai.requests.post", side_effect=TimeoutError()):
                generate_youth_response("今天考試很累", perform_triage("今天考試很累"))
            status = model_status(probe=True)
        self.assertEqual((status["state"], status["reason"]), ("degraded", "timeout"))

    def test_invalid_key_in_chat_is_reported_as_auth_error(self):
        p1, p2 = self.gemini()
        with p1, p2, patch("engine.dialogue_ai.requests.post",
                           return_value=status_response(400, "API key not valid. Please pass a valid API key.")):
            result = generate_youth_response("今天考試很累", perform_triage("今天考試很累"))
        self.assertEqual(result["fallback_reason"], "auth_error")


class StatusRouteTests(unittest.TestCase):
    def test_status_route_is_public_and_secret_free(self):
        from app import app
        dialogue_ai.reset_model_health()
        with patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "secret-key-xyz"), \
             patch("engine.dialogue_ai.requests.get", return_value=status_response(200)):
            response = app.test_client().get("/api/status?probe=1")
        dialogue_ai.reset_model_health()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["ai"]["state"], "ok")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(b"secret-key-xyz", response.data)


class StaleAssetTests(unittest.TestCase):
    """Regression: an unchanged ?v= query let the offline service worker keep serving an old app.js,
    so the status light never left 「檢查 AI 連線中…」 after an update."""

    def test_page_links_scripts_by_content_hash(self):
        import hashlib
        import re
        from pathlib import Path
        from app import app
        html = app.test_client().get("/").get_data(as_text=True)
        version = re.search(r"/static/js/app\.js\?v=([0-9a-f]{10})", html)
        self.assertIsNotNone(version, "app.js must carry a content-hash version")
        source = Path(app.static_folder, "js", "app.js").read_bytes()
        self.assertEqual(version.group(1), hashlib.sha256(source).hexdigest()[:10])

    def test_no_template_uses_a_hand_written_static_url(self):
        import re
        from pathlib import Path
        for template in Path(__file__).resolve().parents[1].joinpath("templates").glob("*.html"):
            with self.subTest(template=template.name):
                self.assertIsNone(re.search(r"[\"']/static/(?:css|js)/", template.read_text(encoding="utf-8")))

    def test_service_worker_fetches_static_files_network_first(self):
        from pathlib import Path
        worker = Path(__file__).resolve().parents[1].joinpath("static", "sw.js").read_text(encoding="utf-8")
        body = worker[worker.index("async function handleStatic"):worker.index('self.addEventListener("fetch"')]
        self.assertLess(body.index("await fetch(request)"), body.index("cache.match(request)"))


if __name__ == "__main__":
    unittest.main()
