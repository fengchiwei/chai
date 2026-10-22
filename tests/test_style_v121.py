# -*- coding: utf-8 -*-
"""v1.2.1 regression: synthetic texts only, no network or database."""
import inspect
import unittest
from unittest.mock import patch
from engine.triage import perform_triage
from engine.dialogue_policy import initial_state
from engine.dialogue_ai import SYSTEM_PROMPT, generate_youth_response, prepare_dialogue
from engine.dialogue_reply import local_reply, response_violations, safety_reply

C14 = '我想走設計，但家裡一直要我選他們覺得穩的科系。我一開口就被說太理想化。'


def decision(message, previous=None):
    triage = perform_triage(message, previous_level=(previous or {}).get('risk_level', 'green'))
    return prepare_dialogue(message, triage, previous, use_model=False)


class StyleTests(unittest.TestCase):
    def test_c14_first_fallback_no_mechanical_echo(self):
        t, state = decision(C14)
        answer = local_reply(C14, state)
        self.assertEqual(t['level'], 'green')
        self.assertNotIn('你說「', answer)
        self.assertNotIn('我先照你說的聽', answer)
        self.assertTrue(any(term in answer for term in ('設計','喜歡的方向','家裡')))
        self.assertLessEqual(answer.count('？'),1)

    def test_practical_request_still_gives_step(self):
        msg = '我想走設計，可是我不知道怎麼跟爸媽講才不會又吵起來。'
        _, state = decision(msg)
        self.assertEqual(state['current_goal'],'support_choice')
        answer = local_reply(msg, state)
        self.assertIn('可以', answer)
        self.assertNotIn('都是為我好', answer)
        self.assertNotIn('你們會擔心我的未來', answer)
        self.assertNotIn('你說「', answer)

    def test_synthetic_teacher_is_not_assumed_parent(self):
        msg='我不知道怎麼跟老師講我想換座位，怕他生氣。'
        _, state=decision(msg)
        answer=local_reply(msg,state)
        self.assertNotIn('家人',answer)
        self.assertNotIn('爸媽',answer)
        self.assertNotIn('你們希望我選',answer)

    def test_noncareer_family_topic_no_invented_career(self):
        msg='我爸不讓我參加社團，我不知道怎麼跟他講才不會吵起來。'
        _, state=decision(msg)
        self.assertEqual(state['current_goal'],'support_choice')
        answer=local_reply(msg,state)
        self.assertNotIn('選比較穩定的方向',answer)
        self.assertNotIn('未來',answer)
        self.assertIn('可以',answer)

    def test_integrate_no_old_memory_quote(self):
        msg='我希望自己能被尊重。'
        old={'yearning_summary':'希望他們把我當成一個有自己想法、可以自己做決定的人',
             'known_yearning':True}
        _, state=decision(msg,old)
        self.assertEqual(state['current_goal'],'integrate')
        answer=local_reply(msg,state)
        self.assertNotIn('前面你說',answer)
        self.assertNotIn('你說「',answer)
        self.assertNotIn('可以先',answer)

    def test_boundary_is_preserved(self):
        msg='不想再講了，不要一直問我。'
        _, state=decision(msg)
        self.assertEqual(state['current_goal'],'respect_boundary')
        self.assertNotIn('?',local_reply(msg,state))
        self.assertNotIn('？',local_reply(msg,state))

    def test_high_emotion_is_preserved(self):
        msg='我哭到停不下來，也不知道怎麼跟家裡說。'
        _,state=decision(msg)
        self.assertEqual(state['current_goal'],'stabilize')
        self.assertIn('give_advice',state['forbidden_actions'])
        self.assertNotIn('可以先',local_reply(msg,state))

    def test_safety_is_rule_owned(self):
        msg='我想死，現在不知道怎麼辦。'
        triage,state=decision(msg)
        self.assertTrue(state['safety_check_required'])
        self.assertEqual(local_reply(msg,state),safety_reply(msg,state))
        result=generate_youth_response(msg, triage, dialogue_state=state)
        self.assertIn('安全', result['model_used'])

    def test_model_used_stays_actual_model(self):
        msg=C14
        triage,state=decision(msg)
        model={'reply':'你想走設計，但家裡有不同的看法。你原本希望他們怎麼回應你？',
               'model_used':'Google Gemini (test stub)'}
        with patch('engine.dialogue_ai._call_model', return_value=(model,'ok')):
            out=generate_youth_response(msg,triage,dialogue_state=state)
        self.assertEqual(out['model_used'],'Google Gemini (test stub)')

    def test_rejected_model_uses_natural_local(self):
        msg=C14
        triage,state=decision(msg)
        invalid={'reply':'你很棒，全部都會好起來。','model_used':'Mock Gemini'}
        with patch('engine.dialogue_ai._call_model',return_value=(invalid,'ok')):
            out=generate_youth_response(msg,triage,dialogue_state=state)
        self.assertIn('本機備援', out['model_used'])
        self.assertIn('想走自己喜歡的方向',out['reply'])
        self.assertNotIn('你說「',out['reply'])

    def test_prompt_respects_real_world_uncertainty(self):
        self.assertIn('不要替家人、老師',SYSTEM_PROMPT)
        self.assertIn('不需每輪以「聽起來」',SYSTEM_PROMPT)

if __name__=='__main__': unittest.main()
