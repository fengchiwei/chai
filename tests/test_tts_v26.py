# -*- coding: utf-8 -*-
"""v2.6：朗讀可選雲端自然語音（Azure／OpenAI／Gemini）。金鑰只在伺服器；只傳 AI 回覆文字；
失敗時頁面改用裝置內建聲音。假 API，不連網。"""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import CONTENT_SECURITY_POLICY, app, limiter
from config import Config
from engine import tts
from models import database


def keys(**values):
    base = {"TTS_ENABLED": True, "AZURE_SPEECH_KEY": "", "AZURE_SPEECH_REGION": "", "OPENAI_API_KEY": "",
            "GEMINI_API_KEY": "", "LLM_API_KEY": "", "LLM_PROVIDER": "auto", "TTS_GEMINI_MODEL": ""}
    base.update(values)
    return [patch.object(Config, name, value) for name, value in base.items()]


class Base(unittest.TestCase):
    def use(self, **values):
        for p in keys(**values):
            self.enterContext(p)
        tts.reset_cache()
        self.addCleanup(tts.reset_cache)


class VoiceListTests(Base):
    def test_no_key_means_no_cloud_voices(self):
        self.use()
        self.assertEqual(tts.voices(), [])

    def test_only_configured_services_are_offered_azure_first(self):
        self.use(AZURE_SPEECH_KEY="az-test", AZURE_SPEECH_REGION="eastasia", GEMINI_API_KEY="g-test")
        ids = [v["id"] for v in tts.voices()]
        self.assertEqual(ids[0], "azure:zh-TW-HsiaoChenNeural")
        self.assertTrue(any(i.startswith("gemini:") for i in ids))
        self.assertFalse(any(i.startswith("openai:") for i in ids))

    def test_the_main_gemini_key_also_enables_gemini_voices(self):
        self.use(LLM_API_KEY="AIzaTestKey", LLM_PROVIDER="gemini")
        self.assertTrue(tts.voices() and all(v["id"].startswith("gemini:") for v in tts.voices()))

    def test_switched_off(self):
        self.use(TTS_ENABLED=False, AZURE_SPEECH_KEY="az-test", AZURE_SPEECH_REGION="eastasia")
        self.assertEqual(tts.voices(), [])


class SynthesisTests(Base):
    def test_azure_ssml_is_escaped_and_cached(self):
        self.use(AZURE_SPEECH_KEY="az-test", AZURE_SPEECH_REGION="eastasia")
        with patch("engine.tts.requests.post", return_value=Mock(status_code=200, content=b"mp3")) as post:
            audio = tts.synthesize("azure:zh-TW-YunJheNeural", "我在這裡 <陪你> 🌱", 0.85)
            tts.synthesize("azure:zh-TW-YunJheNeural", "我在這裡 <陪你> 🌱", 0.85)
        self.assertEqual(audio, (b"mp3", "audio/mpeg"))
        self.assertEqual(post.call_count, 1)  # the second request is served from the cache
        ssml = post.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("zh-TW-YunJheNeural", ssml)
        self.assertIn("&lt;陪你&gt;", ssml)
        self.assertIn("rate='-15%'", ssml)
        self.assertNotIn("🌱", ssml)
        self.assertIn("eastasia.tts.speech.microsoft.com", post.call_args.args[0])

    def test_openai_request(self):
        self.use(OPENAI_API_KEY="sk-test")
        with patch("engine.tts.requests.post", return_value=Mock(status_code=200, content=b"mp3")) as post:
            tts.synthesize("openai:coral", "你好", 1.0)
        body = post.call_args.kwargs["json"]
        self.assertEqual((body["voice"], body["input"], body["model"]), ("coral", "你好", Config.TTS_OPENAI_MODEL))
        self.assertTrue(post.call_args.args[0].endswith("/audio/speech"))

    def test_gemini_pcm_is_wrapped_as_wav_and_the_speech_model_is_discovered(self):
        self.use(GEMINI_API_KEY="g-test")
        models = Mock(ok=True, json=Mock(return_value={"models": [{"name": "models/gemini-2.5-flash"},
                                                                  {"name": "models/gemini-2.5-pro-preview-tts"},
                                                                  {"name": "models/gemini-2.5-flash-preview-tts"}]}))
        pcm = base64.b64encode(b"\x00\x01" * 100).decode()
        reply = Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000", "data": pcm}}]}}]}))
        with patch("engine.tts.requests.get", return_value=models), \
                patch("engine.tts.requests.post", return_value=reply) as post:
            audio, mime = tts.synthesize("gemini:Sulafat", "慢慢來", 1.0)
        self.assertEqual(mime, "audio/wav")
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertIn("gemini-2.5-flash-preview-tts:generateContent", post.call_args.args[0])
        voice = post.call_args.kwargs["json"]["generationConfig"]["speechConfig"]["voiceConfig"]
        self.assertEqual(voice["prebuiltVoiceConfig"]["voiceName"], "Sulafat")

    def test_unknown_voice_and_service_errors(self):
        self.use(AZURE_SPEECH_KEY="az-test", AZURE_SPEECH_REGION="eastasia")
        with self.assertRaises(tts.TtsError):
            tts.synthesize("openai:coral", "你好")  # service not configured
        with self.assertRaises(tts.TtsError):
            tts.synthesize("azure:someone-else", "你好")
        with patch("engine.tts.requests.post", return_value=Mock(status_code=401)):
            with self.assertRaisesRegex(tts.TtsError, "auth_error"):
                tts.synthesize("azure:zh-TW-HsiaoChenNeural", "你好")


class RouteTests(Base):
    def setUp(self):
        self.use(AZURE_SPEECH_KEY="az-test", AZURE_SPEECH_REGION="eastasia")
        limiter.reset()
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, "DB_PATH", str(Path(tmp) / "t.db")))
        database.init_db()
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.headers = {"X-CSRF-Token": sess["csrf_token"]}

    def speak(self, **body):
        payload = {"text": "我在這裡陪你。", "voice": "azure:zh-TW-HsiaoChenNeural", **body}
        return self.client.post("/api/tts", headers=self.headers, data=json.dumps(payload), content_type="application/json")

    def test_students_only_after_the_privacy_notice(self):
        self.assertEqual(self.speak().status_code, 403)

    def test_audio_is_returned_and_failures_ask_for_the_device_voice(self):
        self.client.post("/api/onboarding", headers=self.headers, json={"privacy_acknowledged": True})
        self.assertEqual(self.client.get("/api/tts/voices").json["voices"][0]["id"], "azure:zh-TW-HsiaoChenNeural")
        with patch("engine.tts.requests.post", return_value=Mock(status_code=200, content=b"mp3")):
            response = self.speak()
        self.assertEqual((response.status_code, response.mimetype, response.data), (200, "audio/mpeg", b"mp3"))
        with patch("engine.tts.requests.post", return_value=Mock(status_code=500)):
            response = self.speak(text="另一段話")
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.json["fallback"])
        self.assertEqual(self.speak(text="長" * 900).status_code, 400)

    def test_per_conversation_limit(self):
        self.client.post("/api/onboarding", headers=self.headers, json={"privacy_acknowledged": True})
        with patch("engine.tts.requests.post", return_value=Mock(status_code=200, content=b"mp3")):
            codes = [self.speak(text=f"第{i}段").status_code for i in range(41)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(set(codes[:-1]), {200})

    def test_page_may_play_generated_audio(self):
        self.assertIn("media-src 'self' blob:", CONTENT_SECURITY_POLICY)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="voiceDialog"', html)
        self.assertIn('id="voiceSettingsBtn"', html)


if __name__ == "__main__":
    unittest.main()
