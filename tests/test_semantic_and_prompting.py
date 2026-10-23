"""已知青少年語詞、對話節奏與轉介提示回歸；不代表臨床檢出率。"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from config import Config
from engine.ai_agent import generate_youth_response
from engine.triage import perform_triage
from models import database


class SemanticAndPromptingTests(unittest.TestCase):
    def test_slang_is_not_harm_but_another_harm_signal_is_still_seen(self):
        for message in ['我告白被打槍', '我劃好重點了', '今天計劃去讀書', '今天切割紙張做勞作']:
            with self.subTest(message=message):
                self.assertEqual(perform_triage(message)['level'], 'green')
        for message in ['我告白被打槍，現在想傷害自己', '我劃好重點，但還是不想再活下去了',
                        '我在家被打了', '我用美工刀劃手臂', '我現在不想再活下去了']:
            with self.subTest(message=message):
                self.assertEqual(perform_triage(message)['level'], 'orange')
        self.assertEqual(perform_triage('我告白被打槍，我已經把工具準備好，今晚等家人睡著就行動')['level'], 'red')
        self.assertEqual(perform_triage('我沒有想傷害自己')['level'], 'green')

    def test_existing_thirty_example_matrix_is_preserved(self):
        path = Path(__file__).resolve().parents[1] / 'data/mock_cases.json'
        for case in json.loads(path.read_text(encoding='utf-8')):
            with self.subTest(case=case['case_id']):
                result = perform_triage(case['dialogue_snippet'], case['bsrs5'], case['duration'],
                                        case['life_impact'], case['support_system'])
                self.assertEqual(result['level'], case['risk_level'])

    def test_rejection_then_low_mood_gets_contextual_companionship_and_question_pause(self):
        history, responses = [], []
        with patch.object(Config, 'LLM_PROVIDER', 'builtin'):
            for message in ['我告白被打槍', '我最近心情不好', '他說只把我當朋友']:
                result = generate_youth_response(message, perform_triage(message), history)
                response = result['reply']
                self.assertNotIn('119', response)
                self.assertNotIn('你提到想傷害自己', response)
                self.assertNotIn('下一步', response)
                self.assertLessEqual(response.count('？'), 1)
                self.assertTrue(10 <= len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', response)) <= 220)
                history.extend([{'role': 'user', 'text': message}, {'role': 'assistant', 'text': response}])
                responses.append(response)
        self.assertIn('告白被打槍', responses[1])
        self.assertEqual(responses[2].count('？'), 0)
        self.assertEqual(len(set(responses)), 3)

    def test_safety_response_acknowledges_answer_without_reasking_it(self):
        first = '我已經把工具準備好，今晚等家人睡著就行動'
        response = generate_youth_response(first, perform_triage(first))['reply']
        second = generate_youth_response('媽媽已經在旁邊陪我', perform_triage('媽媽已經在旁邊陪我', previous_level='red'),
            [{'role': 'user', 'text': first}, {'role': 'assistant', 'text': response}])['reply']
        # v2.5.4: acknowledged without echoing the student's words back (counselling review, 2026-10-23).
        self.assertIn('媽媽陪著你', second)
        self.assertNotIn('現在有人能到你身邊陪你嗎', second)
        for phone in ['119', '110', '1925']:
            self.assertIn(phone, second)

    def test_actual_sequence_and_only_one_automatic_referral_prompt_per_level(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(database, 'DB_PATH', str(Path(tmp)/'test.db')), \
             patch.object(Config, 'LLM_PROVIDER', 'builtin'):
            database.init_db()
            client = app.test_client()
            client.get('/')
            with client.session_transaction() as sess:
                headers = {'X-CSRF-Token': sess['csrf_token']}
            client.post('/api/onboarding', headers=headers, json={'privacy_acknowledged': True})
            history = []
            for index, message in enumerate(['我告白被打槍', '我最近心情不好', '他說只把我當朋友', '我還是有點難過'], 1):
                result = client.post('/api/chat', headers=headers, json={'message': message, 'history': history})
                self.assertEqual(result.status_code, 200)
                self.assertIsNone(result.json['next_steps']['consent_kind'])
                self.assertFalse(result.json['next_steps']['prompt_referral'])
                # Still expressing hurt is not permission to offer advice at a fixed turn.
                self.assertIsNone(result.json['support_offer'])
                self.assertNotIn('學校輔導室', result.json['reply'])
                history.extend([{'role': 'user', 'text': message}, {'role': 'assistant', 'text': result.json['reply']}])
            self.assertEqual(database.get_all_cases(), [])
            def chat(message):
                return client.post('/api/chat', headers=headers, json={'message': message}).json
            orange = chat('我想傷害自己，但還沒有計畫')
            self.assertTrue(orange['next_steps']['prompt_referral'])
            client.post('/api/referral/consent', headers=headers, json={'consent': False})
            followup = chat('我還想再說一點')
            self.assertEqual(followup['next_steps']['consent_kind'], 'referral')
            self.assertFalse(followup['next_steps']['prompt_referral'])
            self.assertFalse(client.get('/api/chat/state').json['next_steps']['prompt_referral'])
            self.assertTrue(chat('我想轉介')['next_steps']['prompt_referral'])
            red = chat('我已經把工具準備好，今晚等家人睡著就行動')
            self.assertTrue(red['show_urgent_help'])
            self.assertTrue(red['next_steps']['prompt_referral'])
            self.assertFalse(chat('我还在')['next_steps']['prompt_referral'])
            self.assertTrue(client.get('/api/chat/state').json['show_urgent_help'])
            self.assertEqual(database.get_all_cases(), [])


if __name__ == '__main__':
    unittest.main()
