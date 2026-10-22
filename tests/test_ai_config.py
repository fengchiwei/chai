"""確認模型請求與危機固定回覆的分界，不呼叫外部 API。"""
import unittest
from unittest.mock import Mock, patch
from engine.ai_agent import generate_youth_response
from engine.triage import perform_triage
from config import Config


class AiConfigTests(unittest.TestCase):
    def test_gemini_uses_configured_temperature_and_system_prompt(self):
        fake = Mock(status_code=200)
        fake.json.return_value = {"candidates": [{"content": {"parts": [{"text": "我聽見你說的困難。"}]}}]}
        with patch.object(Config, "LLM_PROVIDER", "gemini"), \
             patch.object(Config, "GEMINI_API_KEY", "test-key"), \
             patch("engine.ai_agent.requests.post", return_value=fake) as post:
            reply = generate_youth_response("今天考試很累", perform_triage("今天考試很累"))
        self.assertIn("Gemini", reply["model_used"])
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["generationConfig"]["temperature"], Config.LLM_TEMPERATURE)
        self.assertIn("1–4 個短句", payload["systemInstruction"]["parts"][0]["text"])

    def test_red_reply_does_not_call_model(self):
        with patch("engine.ai_agent.requests.post") as post:
            reply = generate_youth_response("我把工具準備好，今晚就行動", perform_triage("我把工具準備好，今晚就行動"))
        post.assert_not_called()
        self.assertIn("119", reply["reply"])


if __name__ == "__main__":
    unittest.main()
