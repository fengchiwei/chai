"""陪伴回覆、前文與危機界線；假 API 僅驗證串接，不代表雲端語氣驗收。"""
import re
import unittest
from unittest.mock import Mock, patch

from config import Config
from engine.ai_agent import generate_youth_response, get_auto_warm_response
from engine.triage import perform_triage


def chinese_length(value):
    return len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', value))


class CompanionDialogueTests(unittest.TestCase):
    def test_normal_replies_are_short_and_keep_student_words(self):
        scenarios = [
            ('我最近心情不好', ['心情不好']),
            ('你覺得活著的意義是甚麼', ['活著的意義']),
            ('下週段考好多還沒讀，有點心慌但還讀得進去。', ['段考', '心慌', '還讀得進去']),
            ('不敢去輔導室，怕被同學笑有病。', ['不敢去輔導室', '同學']),
            ('胃痛', ['胃痛']),
            ('今天真的很開心', ['開心']),
        ]
        for message, words in scenarios:
            with self.subTest(message=message):
                reply = get_auto_warm_response(message)
                self.assertTrue(15 <= chinese_length(reply) <= 220, chinese_length(reply))
                self.assertLessEqual(reply.count('？') + reply.count('?'), 1)
                for word in words:
                    self.assertIn(word, reply)
                for banned in ('你很珍貴', '你超棒', '加油你做得到', '根據你的描述'):
                    self.assertNotIn(banned, reply)

    def test_two_turn_fallback_answers_meaning_and_remembers_low_mood(self):
        with patch.object(Config, 'LLM_PROVIDER', 'builtin'), \
             patch('engine.ai_agent.requests.post') as post:
            first = generate_youth_response('我最近心情不好', {'level': 'green'})
            history = [{'role': 'user', 'text': '我最近心情不好'},
                       {'role': 'assistant', 'text': first['reply']},
                       {'role': 'user', 'text': '你覺得活著的意義是甚麼'}]
            second = generate_youth_response('你覺得活著的意義是甚麼', {'level': 'green'}, history)
        post.assert_not_called()
        self.assertNotEqual(first['reply'], second['reply'])
        self.assertIn('活著的意義未必', second['reply'])
        self.assertLessEqual(second['reply'].count('？'), 1)
        self.assertNotIn('你提到想傷害自己', second['reply'])
        self.assertEqual(second['model_used'], '本機備援回覆')

    def test_pure_reactions_are_short_and_numeric_choices_follow_context(self):
        for word in ['嗯', '不是', '1', '沒有', '好喔']:
            reply = get_auto_warm_response(word)
            self.assertTrue(10 <= chinese_length(reply) <= 100, (word, chinese_length(reply)))
        selected = get_auto_warm_response('1', conversation_history=[
            {'role': 'assistant', 'text': '1. 先繼續聊。2. 寫字條。'}])
        self.assertIn('先繼續聊', selected)
        self.assertNotIn('哪個選擇', selected)
        self.assertTrue(10 <= chinese_length(selected) <= 100)
        declined = get_auto_warm_response('沒有', conversation_history=[
            {'role': 'assistant', 'text': '你現在有沒有想到傷害自己？'}])
        self.assertNotIn('我剛才可能聽偏', declined)
        self.assertTrue(10 <= chinese_length(declined) <= 100)

    def test_followup_keeps_topic_and_does_not_repeat_last_question(self):
        first = get_auto_warm_response('我最近心情不好')
        second = get_auto_warm_response('不知道', conversation_history=[
            {'role': 'user', 'text': '我最近心情不好'}, {'role': 'assistant', 'text': first}])
        self.assertIn('不用', second)
        self.assertNotEqual(first.split('\n\n')[-1], second.split('\n\n')[-1])
        self.assertTrue(10 <= chinese_length(second) <= 220)

    def test_gemini_history_parts_and_output_budget(self):
        response = Mock(status_code=200)
        response.json.return_value = {'candidates': [{'content': {'parts': [
            {'thought': True, 'text': '內部思考'}, {'text': '第一段。'}, {'text': '第二段。'}]}}]}
        history = [{'role': 'user', 'text': '我最近心情不好'},
                   {'role': 'assistant', 'text': '想從哪一點說起？'},
                   {'role': 'user', 'text': '不知道'}]
        with patch.object(Config, 'LLM_PROVIDER', 'gemini'), \
             patch.object(Config, 'GEMINI_API_KEY', 'test-only'), \
             patch.object(Config, 'GEMINI_MODEL', 'gemini-2.5-flash'), \
             patch('engine.ai_agent.requests.post', return_value=response) as post:
            result = generate_youth_response('不知道', {'level': 'green'}, history)
        self.assertEqual(result['reply'], '第一段。第二段。')
        payload = post.call_args.kwargs['json']
        self.assertEqual([c['role'] for c in payload['contents']], ['user', 'model', 'user'])
        self.assertEqual(payload['contents'][-1]['parts'][0]['text'], '不知道')
        self.assertEqual(payload['generationConfig']['temperature'], 0.8)
        self.assertEqual(payload['generationConfig']['thinkingConfig']['thinkingBudget'], 0)
        self.assertGreaterEqual(payload['generationConfig']['maxOutputTokens'], 500)

    def test_empty_model_response_falls_back_instead_of_blank_bubble(self):
        response = Mock(status_code=200)
        response.json.return_value = {'candidates': [{'content': {'parts': [{'text': '  '}]}}]}
        with patch.object(Config, 'LLM_PROVIDER', 'gemini'), \
             patch.object(Config, 'GEMINI_API_KEY', 'test-only'), \
             patch.object(Config, 'OPENAI_API_KEY', ''), \
             patch('engine.ai_agent.requests.post', return_value=response):
            result = generate_youth_response('我最近心情不好', {'level': 'green'})
        self.assertEqual(result['model_used'], '本機備援回覆')
        self.assertTrue(10 <= chinese_length(result['reply']) <= 220)

    def test_crisis_replies_keep_hotlines_and_never_call_cloud(self):
        for level in ['orange', 'red']:
            with self.subTest(level=level), patch('engine.ai_agent.requests.post') as post:
                result = generate_youth_response('我還在', {'level': level})
            post.assert_not_called()
            self.assertEqual(result['model_used'], '安全回覆')
            for phone in ['119', '110', '1925']:
                self.assertIn(phone, result['reply'])
            self.assertIn('可以繼續說', result['reply'])

    def test_previous_risk_is_never_lowered_by_a_short_reply(self):
        for previous in ['green', 'yellow', 'orange', 'red']:
            self.assertEqual(perform_triage('嗯', previous_level=previous)['level'], previous)


if __name__ == '__main__':
    unittest.main()
