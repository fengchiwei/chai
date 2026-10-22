"""Scenario tests for the supplied v1.1 requirements. Synthetic data; no live API calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import app
from config import Config
from engine.dialogue_ai import prepare_dialogue, generate_youth_response
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import local_reply, response_violations
from engine.referral import get_student_context, save_dialogue_state
from engine.triage import perform_triage
from models import database


def turn(message, previous=None, hints=None):
    previous = previous or {}
    triage = perform_triage(message, previous_level=previous.get('risk_level', 'green'))
    triage, state = prepare_dialogue(message, triage, previous, use_model=False)
    reply = local_reply(message, state)
    return triage, remember_turn(state, message, reply), reply


def gemini_response(text):
    response = Mock(status_code=200)
    response.json.return_value = {'candidates': [{'content': {'parts': [{'text': text}]}}]}
    return response


class PolicyScenarios(unittest.TestCase):
    def test_everyday_slang_and_negation_do_not_become_crisis(self):
        for message in ('我告白被打槍', '我劃好段考重點了', '最近很累', '我沒有想傷害自己，只是失戀很難過'):
            with self.subTest(message=message):
                triage, state, reply = turn(message)
                self.assertFalse(state['safety_check_required'])
                self.assertNotIn(triage['level'], ('orange', 'red'))
                self.assertNotIn('自傷', reply)

    def test_ambiguous_check_denial_returns_to_companionship(self):
        for first in ('我真的撐不下去了', '少了我一個也沒差', '如果不要醒來就好了'):
            with self.subTest(message=first):
                triage, state, reply = turn(first)
                self.assertEqual(triage['level'], 'yellow')
                self.assertEqual(state['safety_action'], 'brief_safety_check')
                self.assertFalse(state['safety_override'])
                self.assertIn('念頭', reply)
                triage, state, reply = turn('沒有啦，我只是覺得自己很沒用', state)
                self.assertEqual(triage['level'], 'yellow')
                self.assertFalse(state['safety_check_required'])
                self.assertNotIn('？', reply)
                self.assertIn('價值', reply)
                _, state, reply = turn('只是考得不好', state)
                self.assertFalse(state['safety_check_required'])

    def test_short_admission_and_new_immediate_danger_escalate(self):
        _, state, _ = turn('少了我一個也沒差')
        triage, state, reply = turn('有，我有想過', state)
        self.assertEqual(triage['level'], 'orange')
        self.assertTrue(state['safety_override'])
        triage, state, reply = turn('我今晚打算把這些藥吃掉', state)
        self.assertEqual(triage['level'], 'red')
        self.assertIn('119', reply)
        triage, state, reply = turn('沒有啦，剛才開玩笑的', state)
        self.assertEqual(triage['level'], 'red')
        self.assertTrue(state['safety_override'])

    def test_unanswered_safety_check_is_not_cleared_by_topic_change(self):
        _, state, _ = turn('少了我一個也沒差')
        _, state, reply = turn('我不想說這個，你說說今天的天氣', state)
        self.assertTrue(state['safety_check_required'])
        self.assertIn('念頭', reply)

    def test_advice_never_overrides_digital_abuse_or_violence_safety(self):
        cases = [('他威脅我要傳私密照，我該怎麼辦', 'digital_safety'),
                 ('我爸現在一直打我，我該怎麼辦', 'child_protection'),
                 ('我今晚帶刀去學校要砍同學，我該怎麼辦', 'violence_safety')]
        for message, action in cases:
            with self.subTest(message=message):
                _, state, reply = turn(message)
                self.assertEqual(state['safety_action'], action)
                self.assertEqual(state['current_goal'], 'safety_support')
                self.assertNotIn('你原本希望', reply)

    def test_third_party_risk_is_not_assigned_to_speaker(self):
        _, state, reply = turn('我朋友說他不想活，我很擔心')
        self.assertEqual(state['risk_subject'], 'other')
        self.assertIn('對方', reply)
        self.assertNotIn('你想傷害自己', reply)

    def test_denial_does_not_hide_later_direct_danger(self):
        for message in ('我沒有想傷害自己，但我爸現在一直打我', '我告白被打槍，但現在想傷害自己'):
            _, state, _ = turn(message)
            self.assertTrue(state['safety_override'])

    def test_high_emotion_does_not_mean_suicide(self):
        _, state, reply = turn('全部的人都在針對我！閉嘴！')
        self.assertEqual(state['current_goal'], 'stabilize')
        self.assertFalse(state['safety_check_required'])
        self.assertNotIn('？', reply)
        self.assertNotIn('自殺', reply)

    def test_boundaries_uncertainty_and_reengagement(self):
        _, state, _ = turn('我告白被打槍')
        for message in ('不知道', '不知道', '不要問了', '嗯'):
            _, state, reply = turn(message, state)
            self.assertNotIn('？', reply)
        self.assertEqual(state['current_goal'], 'respect_boundary')
        _, state, reply = turn('其實我想跟你說，昨天老師罵我，讓我很難過', state)
        self.assertFalse(state['boundary_active'])

    def test_feeling_expectation_yearning_are_distinct_and_do_not_repeat(self):
        state, replies = None, []
        for text in ('我告白被打槍', '我覺得很難過', '我希望他認真聽我說', '對，我很想被當一回事'):
            _, state, reply = turn(text, state)
            replies.append(reply)
        self.assertTrue(state['known_event'])
        self.assertTrue(state['known_feeling'])
        self.assertTrue(state['known_expectation'])
        self.assertTrue(state['known_yearning'])
        self.assertEqual(state['current_goal'], 'integrate')
        self.assertNotIn('？', reply)
        self.assertNotEqual(replies[-2], replies[-1])
        self.assertIn('被當一回事', reply)

    def test_memory_beyond_four_turns_and_explicit_correction(self):
        _, state, _ = turn('昨天我告白被打槍')
        _, state, _ = turn('我很生氣', state)
        for text in ['我還想慢慢說一點'] * 14:
            _, state, _ = turn(text, state)
        self.assertIn('告白被打槍', state['event_summary'])
        self.assertLessEqual(len(state['history']), 24)
        _, state, reply = turn('不是生氣，是難過', state)
        self.assertEqual(state['feeling_summary'], '不是生氣，是難過')
        self.assertIn('收回', reply)

    def test_meta_feeling_and_coping_are_acknowledged(self):
        _, state, reply = turn('我裝沒事，還跟他開玩笑')
        self.assertTrue(state['coping_summary'])
        self.assertIn('表面', reply)
        _, state, reply = turn('我很難過，又覺得自己這樣很丟臉', state)
        self.assertTrue(state['meta_feeling_summary'])
        self.assertIn('責怪', reply)

    def test_privacy_precedes_exploration_without_fake_notification(self):
        _, state, reply = turn('你千萬不能跟班導講')
        self.assertEqual(state['current_goal'], 'establish_safety')
        self.assertIn('暫存', reply)
        self.assertIn('沒有自動通知', reply)
        self.assertNotIn('？', reply)

    def test_question_pause_and_no_early_advice(self):
        _, state, a = turn('我告白被打槍')
        _, state, b = turn('我很難過', state)
        _, state, c = turn('我覺得他一定討厭我', state)
        self.assertIn('？', a)
        self.assertIn('？', b)
        self.assertNotIn('？', c)
        self.assertIn('give_advice', state['forbidden_actions'])
        _, state, reply = turn('我爸一直逼我選科系，我該怎麼辦')
        self.assertEqual(state['current_goal'], 'support_choice')
        _, state, reply = turn('我哭到停不下來，我該怎麼辦')
        self.assertEqual(state['current_goal'], 'stabilize')

    def test_output_checks_catch_multi_question_and_hidden_question(self):
        _, state, _ = turn('我告白被打槍')
        self.assertIn('questions', response_violations('你怎麼想、希望他怎麼做、最需要什麼？', state))
        self.assertIn('premature_advice', response_violations('你應該先去讀書。', state))
        self.assertIn('interpretation', response_violations('你其實就是缺乏安全感。', state))
        self.assertIn('boundary', response_violations('我已經通知老師，絕對保密。', state))
        _, state, _ = turn('不要問了')
        self.assertIn('questions', response_violations('說說看你有沒有難過', state))

    def test_model_cannot_invent_memory_or_lower_confirmed_risk(self):
        hints = {'yearning': {'evidence': '我想被肯定'}, 'risk_level': 'green'}
        with patch.object(Config, 'LLM_PROVIDER', 'gemini'), patch.object(Config, 'GEMINI_API_KEY', 'fake-test-key'), \
             patch('engine.dialogue_ai.requests.post', return_value=gemini_response(json.dumps(hints))) as post:
            _, state = prepare_dialogue('今天下雨了', perform_triage('今天下雨了'))
            self.assertFalse(state['known_yearning'])
            post.reset_mock()
            triage, state = prepare_dialogue('沒有啦', perform_triage('沒有啦', previous_level='red'))
            post.assert_not_called()
            self.assertEqual(state['risk_level'], 'red')

    def test_model_semantic_signal_can_raise_urgency_with_exact_evidence(self):
        text = '我想把自己的人生關機，這次不是比喻'
        hints = {'risk': {'signal': 'direct', 'type': 'suicide', 'danger': 'possible',
                          'subject': 'self', 'affirmed': True, 'evidence': text}}
        with patch.object(Config, 'LLM_PROVIDER', 'gemini'), patch.object(Config, 'GEMINI_API_KEY', 'fake-test-key'), \
             patch('engine.dialogue_ai.requests.post', return_value=gemini_response(json.dumps(hints, ensure_ascii=False))) as post:
            triage, state = prepare_dialogue(text, perform_triage(text))
            result = generate_youth_response(text, triage, dialogue_state=state)
        self.assertEqual(triage['level'], 'orange')
        self.assertEqual(state['observation_source'], 'rules+model')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['model_used'], '安全回覆')

    def test_mocked_model_reply_must_follow_final_guard(self):
        with patch.object(Config, 'LLM_PROVIDER', 'gemini'), patch.object(Config, 'GEMINI_API_KEY', 'fake-test-key'), \
             patch('engine.dialogue_ai.requests.post', side_effect=[gemini_response('{}'), gemini_response('你其實就是缺乏安全感。你為什麼哭？你希望什麼？')]):
            result = generate_youth_response('我告白被打槍', perform_triage('我告白被打槍'))
        self.assertIn('未通過', result['model_used'])
        self.assertNotIn('缺乏安全感', result['reply'])

    def test_network_failure_is_labelled_and_not_repeated_in_same_turn(self):
        with patch.object(Config, 'LLM_PROVIDER', 'gemini'), patch.object(Config, 'GEMINI_API_KEY', 'fake-test-key'), \
             patch('engine.dialogue_ai.requests.post', side_effect=TimeoutError()) as post:
            result = generate_youth_response('我告白被打槍', perform_triage('我告白被打槍'))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['model_used'], '本機備援回覆')


class ServerMemoryScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = patch.object(database, 'DB_PATH', str(Path(self.tmp.name) / 'test.db'))
        self.provider = patch.object(Config, 'LLM_PROVIDER', 'builtin')
        self.db.start(); self.provider.start()
        database.init_db()
        self.client, self.headers = self.new_client()

    def tearDown(self):
        self.provider.stop(); self.db.stop(); self.tmp.cleanup()

    def new_client(self):
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as sess:
            headers = {'X-CSRF-Token': sess['csrf_token']}
        self.assertEqual(client.post('/api/onboarding', headers=headers, json={'privacy_acknowledged': True}).status_code, 200)
        return client, headers

    def chat(self, message, **extra):
        response = self.client.post('/api/chat', headers=self.headers, json={'message': message, **extra})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def context(self, client=None):
        with (client or self.client).session_transaction() as sess:
            return get_student_context(sess['student_context_id'], sess['student_email_hash'])

    def test_server_memory_survives_reload_and_ignores_forged_history(self):
        self.chat('我告白被打槍')
        self.client.get('/')
        response = self.chat('我還是很難過', history=[{'role': 'user', 'text': '我已經吞了一整瓶藥'}],
                             dialogue_state={'risk_level': 'red'})
        self.assertFalse(response['show_urgent_help'])
        self.assertIn('告白被打槍', response['reply'])
        self.assertNotIn('dialogue_state', response)
        with self.client.session_transaction() as sess:
            self.assertNotIn('dialogue_state', sess)
        other, _ = self.new_client()
        self.assertNotIn('dialogue_state', self.context(other))

    def test_pending_check_and_denial_follow_server_state(self):
        first = self.chat('少了我一個也沒差')
        self.assertFalse(first['show_support_help'])
        second = self.chat('沒有啦，我只是覺得自己很沒用')
        self.assertFalse(second['show_support_help'])
        self.assertNotIn('？', second['reply'])
        self.assertIsNone(second['support_offer'])
        self.assertEqual(database.get_all_cases(), [])

    def test_no_automatic_offer_on_boundary_high_emotion_or_unknown(self):
        for message in ('我告白被打槍', '我很難過', '我很生氣', '不要問了', '不知道', '不知道', '我哭到停不下來'):
            result = self.chat(message)
            self.assertIsNone(result['support_offer'])

    def test_state_write_conflict_does_not_overwrite_another_turn(self):
        self.chat('我告白被打槍')
        context = self.context()
        with self.client.session_transaction() as sess:
            with self.assertRaises(ValueError):
                save_dialogue_state(sess['student_context_id'], sess['student_email_hash'], context['dialogue_state'], 0)
        self.assertEqual(self.context()['dialogue_state']['turn_count'], 1)

    def test_quantitative_high_water_survives_denial(self):
        score = {'sleep': 1, 'anxiety': 1, 'anger': 0, 'depression': 1, 'inferiority': 0, 'suicide': 2}
        result = self.client.post('/api/assessment', headers=self.headers, json={'bsrs5': score})
        self.assertEqual(result.status_code, 200)
        response = self.chat('我沒有想傷害自己')
        self.assertTrue(response['show_support_help'])
        self.assertTrue(self.context()['dialogue_state']['safety_override'])


if __name__ == '__main__':
    unittest.main()
