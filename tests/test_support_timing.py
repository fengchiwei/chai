"""資源邀請的時機、學生選擇、回覆文字及案件邊界；不使用真實 API。"""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import app
from config import Config
from engine.ai_agent import generate_youth_response
from engine.support import choose_support_offer
from models import database
from tests.helpers import consented_cases


class SupportTimingTests(unittest.TestCase):
    def test_offer_waits_for_fourth_turn_and_does_not_repeat(self):
        state = {}
        for message in ['我最近心情不好', '段考還有很多沒讀', '想到進度有點心慌']:
            offer, state = choose_support_offer(message, 'green', state)
            self.assertIsNone(offer)
        offer, state = choose_support_offer('說出來好像有比較輕鬆一點', 'green', state)
        self.assertTrue(offer['proactive'])
        for _ in range(8):
            offer, state = choose_support_offer('我想繼續說今天發生的事', 'green', state)
            self.assertIsNone(offer)

    def test_decline_is_respected_but_later_explicit_request_still_works(self):
        for message in ['我先不要輔導資源，只想聊聊', '先不要', '資源先不要']:
            offer, state = choose_support_offer(message, 'yellow', {'turns': 3, 'has_concern': True})
            self.assertIsNone(offer)
            for _ in range(5):
                offer, state = choose_support_offer('心情還是有點低落', 'yellow', state)
                self.assertIsNone(offer)
            offer, state = choose_support_offer('現在想了解附近有哪些輔導資源', 'yellow', state)
            self.assertEqual(offer['kind'], 'resources')
            self.assertFalse(offer['proactive'])
        offer, _ = choose_support_offer('不想轉介，只想看資源', 'green')
        self.assertEqual(offer['kind'], 'resources')

    def test_brief_reply_and_no_concern_do_not_trigger_automatic_offer(self):
        for message in ['嗯', '不是', '1', '沒有']:
            offer, _ = choose_support_offer(message, 'green', {'turns': 3, 'has_concern': True})
            self.assertIsNone(offer)
        offer, _ = choose_support_offer('今天和朋友出門玩得很開心', 'green', {'turns': 3})
        self.assertIsNone(offer)
        offer, _ = choose_support_offer('你覺得活著的意義是什麼', 'green', {'turns': 3, 'has_concern': True})
        self.assertIsNone(offer)

    def test_explicit_request_works_on_first_turn(self):
        for message, kind in [('我想看附近的輔導資源', 'resources'), ('可以找誰聊聊', 'resources'),
                              ('請幫我寫一張給輔導老師的字條', 'draft')]:
            offer, _ = choose_support_offer(message, 'yellow')
            self.assertEqual(offer['kind'], kind)
            self.assertFalse(offer['proactive'])

    def test_same_offer_is_in_fallback_and_model_reply_without_extra_question(self):
        message = '說出來好像有比較輕鬆一點'
        offer, _ = choose_support_offer(message, 'green', {'turns': 3, 'has_concern': True})
        from tests.stand_in import stand_in
        with patch.object(Config, 'LLM_PROVIDER', 'builtin'), stand_in():
            local = generate_youth_response(message, {'level': 'green'}, support_offer=offer)
        self.assertEqual(local['reply'].count(offer['text']), 1)
        self.assertLessEqual(local['reply'].count('？'), 1)
        length = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', local['reply']))
        self.assertTrue(10 <= length <= 220, length)
        response = Mock(status_code=200)
        response.json.return_value = {'candidates': [{'content': {'parts': [{'text': '我有聽到你說輕鬆了一點。'}]}}]}
        with patch.object(Config, 'LLM_PROVIDER', 'gemini'), patch.object(Config, 'GEMINI_API_KEY', 'test-only'), \
             patch('engine.ai_agent.requests.post', return_value=response) as post:
            result = generate_youth_response(message, {'level': 'green'}, support_offer=offer)
        self.assertTrue(result['reply'].endswith(offer['text']))
        self.assertIn('本輪資源邀請', post.call_args.kwargs['json']['systemInstruction']['parts'][0]['text'])

    def test_crisis_always_bypasses_resource_delay(self):
        offered, _ = choose_support_offer('想看輔導資源', 'green')
        for level in ['orange', 'red']:
            offer, _ = choose_support_offer('先不要，我只想聊', level, {'turns': 1, 'declined': True})
            self.assertIsNone(offer)
            with patch('engine.ai_agent.requests.post') as post:
                response = generate_youth_response('我還在', {'level': level}, support_offer=offered)
            post.assert_not_called()
            self.assertNotIn(offered['text'], response['reply'])
            for phone in ['119', '110', '1925']:
                self.assertIn(phone, response['reply'])

    def test_api_persists_timing_across_contact_edits_and_isolates_new_session(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(database, 'DB_PATH', str(Path(tmp) / 'test.db')), \
             patch.object(Config, 'LLM_PROVIDER', 'builtin'):
            database.init_db()
            client = app.test_client()
            client.get('/')
            with client.session_transaction() as sess:
                headers = {'X-CSRF-Token': sess['csrf_token']}
            profile = {'student_email': 'timing@example.edu.tw', 'township': '埔里鎮',
                       'privacy_acknowledged': True}
            self.assertEqual(client.post('/api/onboarding', headers=headers, json=profile).status_code, 200)
            for index, message in enumerate(['我最近心情不好', '讀書有點壓力', '段考還有好多沒讀', '說出來有輕鬆一點'], 1):
                response = client.post('/api/chat', headers=headers, json={**profile, 'message': message})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(bool(response.json['support_offer']), index == 4)
                self.assertIsNone(response.json['next_steps']['consent_kind'])
            self.assertEqual(consented_cases(), [])
            client.get('/')
            response = client.post('/api/chat', headers=headers, json={**profile, 'message': '我還想繼續聊今天的事'})
            self.assertIsNone(response.json['support_offer'])
            profile['student_email'] = 'another@example.edu.tw'
            client.post('/api/onboarding', headers=headers, json=profile)
            response = client.post('/api/chat', headers=headers, json={**profile, 'message': '我最近心情不好'})
            self.assertIsNone(response.json['support_offer'])
            with client.session_transaction() as sess:
                self.assertEqual(sess['support_offer_state']['turns'], 6)
            other = app.test_client()
            other.get('/')
            with other.session_transaction() as sess:
                other_headers = {'X-CSRF-Token': sess['csrf_token']}
            other.post('/api/onboarding', headers=other_headers, json={'privacy_acknowledged': True})
            response = other.post('/api/chat', headers=other_headers, json={'message': '我最近心情不好'})
            self.assertIsNone(response.json['support_offer'])
            with other.session_transaction() as sess:
                self.assertEqual(sess['support_offer_state']['turns'], 1)


if __name__ == '__main__':
    unittest.main()
