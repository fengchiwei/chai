# -*- coding: utf-8 -*-
"""Run locally: python -m unittest discover -s tests -p test_dialogue_v12.py -v

Only fixed fictional sentences. No network, database or real students' data.
"""
import unittest
from unittest.mock import patch

from engine.triage import perform_triage
from engine.dialogue_policy import POLICY_VERSION, initial_state, build_state, remember_turn, wants_practical_help
from engine.dialogue_ai import prepare_dialogue, generate_youth_response
from engine.dialogue_reply import response_violations, local_reply
from engine.support import choose_support_offer

C14 = [
    '我想走設計，但家裡一直要我選他們覺得穩的科系。我一開口就被說太理想化。',
    '我只是希望他們先聽我講完啊，不要每次都直接說設計沒前途，好像我的想法根本不重要。',
    '對啊，我又不是要他們馬上同意。我只是希望他們認真聽我講一次，不要什麼都還沒聽就覺得我不懂現實。',
    '對啊，我就是希望他們把我當成一個有自己想法、可以自己做決定的人，而不是永遠把我當小孩。可是我也不知道怎麼跟他們講，才不會又吵起來。',
]


def run_four_turns():
    state = {}
    outputs = []
    for i, msg in enumerate(C14):
        triage = perform_triage(msg, previous_level=state.get('risk_level','green'))
        triage, state = prepare_dialogue(msg, triage, previous=state, use_model=False)
        outputs.append((triage, state))
        reply = '我有聽見你。' if i < 3 else local_reply(msg, state)
        state = remember_turn(state, msg, reply)
    return outputs


class DialoguePolicyTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(POLICY_VERSION, 'satir-2026-10-19.2')

    def test_c14_fourth_turn_goes_to_action(self):
        outcomes = run_four_turns()
        fourth_triage, fourth = outcomes[-1]
        self.assertEqual(fourth_triage['level'], 'green')
        self.assertEqual(fourth['current_goal'], 'support_choice')
        self.assertEqual(fourth['response_strategy'], 'support_next_step')
        self.assertEqual(fourth['advice_request'], True)
        self.assertTrue(fourth['known_expectation'])
        self.assertTrue(fourth['known_yearning'])
        self.assertFalse(fourth['safety_check_required'])
        self.assertFalse(fourth['safety_override'])
        self.assertIn('可以先', local_reply(C14[-1], fourth))

    def test_step_requires_real_intent(self):
        for message in ['我不知道', '我不知道怎麼說', '我不知道怎麼說自己的心情',
                        '我只想先聊一聊，不要給我建議', '你先聽我講就好',
                        '我知道怎麼跟他們講了']:
            with self.subTest(message=message):
                self.assertFalse(wants_practical_help(message))
        self.assertTrue(wants_practical_help('可是我也不知道怎麼跟他們講，才不會又吵起來。'))
        self.assertTrue(wants_practical_help('我想問一下要如何跟老師說這件事？'))
        self.assertTrue(wants_practical_help('現在我該怎麼辦'))

    def test_high_emotion_blocks_advice(self):
        msg = '我哭到停不下來，我不知道怎麼跟爸媽說。'
        triage, state = prepare_dialogue(msg, perform_triage(msg), use_model=False)
        self.assertEqual(state['current_goal'], 'stabilize')
        self.assertIn('give_advice', state['forbidden_actions'])

    def test_boundary_blocks_advice(self):
        msg = '我不想再講了，也不要一直問我怎麼跟他們溝通。'
        triage, state = prepare_dialogue(msg, perform_triage(msg), use_model=False)
        self.assertEqual(state['current_goal'], 'respect_boundary')
        self.assertIn('give_advice', state['forbidden_actions'])

    def test_confirmed_self_harm_still_protected(self):
        msg = '我想死，卻不知道怎麼跟家裡講。'
        triage, state = prepare_dialogue(msg, perform_triage(msg), use_model=False)
        self.assertIn(state['risk_level'], ('orange','red'))
        self.assertTrue(state['safety_override'])
        self.assertTrue(state['safety_check_required'])
        self.assertEqual(state['current_goal'], 'safety_support')
        self.assertIn('give_advice', state['forbidden_actions'])
        response = generate_youth_response(msg, triage, dialogue_state=state)
        self.assertIn('安全', response['model_used'])

    def test_highest_risk_still_not_lowered(self):
        msg = C14[3]
        triage = perform_triage(msg, previous_level='orange')
        triage, state = prepare_dialogue(msg, triage, previous={'risk_level':'orange','risk_type':'suicide'}, use_model=False)
        self.assertEqual(state['risk_level'], 'orange')
        self.assertTrue(state['safety_override'])
        self.assertNotEqual(state['current_goal'],'support_choice')

    def test_no_proactive_resources_in_action_turn(self):
        triage, state = run_four_turns()[-1]
        offer, support_state = choose_support_offer(C14[-1], triage['level'], {'turns':3,'has_concern':True}, state)
        self.assertIsNone(offer)
        self.assertEqual(support_state['turns'], 4)

    def test_explicit_resources_still_available(self):
        msg = '我想看學校輔導室的資源'
        triage, state = prepare_dialogue(msg, perform_triage(msg), use_model=False)
        offer, _ = choose_support_offer(msg, triage['level'], {}, state)
        self.assertIsNotNone(offer)
        self.assertEqual(offer['kind'], 'resources')

    def test_reject_nonaction_when_action_requested(self):
        _, state = run_four_turns()[-1]
        warm = '你只是希望自己被尊重和被認真聽見，想溝通卻擔心吵架，確實很不容易。'
        self.assertIn('missing_next_step', response_violations(warm, state, C14[-1]))
        concrete = '我知道你不想再吵。可以先挑平靜的時候，用一句話說明你希望先被聽完。'
        self.assertNotIn('missing_next_step', response_violations(concrete, state, C14[-1]))

    def test_model_empathy_only_is_flagged_but_sent(self):
        # v2.5.9: missing a concrete step is a style slip: logged, the model's reply is still sent.
        _, state = run_four_turns()[-1]
        empathy = {'reply': '你只是希望能被聽見，卻常常感到不被尊重，這真的很不容易。', 'model_used': 'mock-model'}
        with patch('engine.dialogue_ai._call_model', return_value=(empathy,'ok')):
            reply = generate_youth_response(C14[-1], perform_triage(C14[-1]), dialogue_state=state)
        self.assertEqual(reply['model_used'], 'mock-model')

    def test_classmates_not_mistaken_for_family(self):
        msg = '我不知道怎麼跟他們講分組的事，才不會吵起來。'
        triage, state = prepare_dialogue(msg, perform_triage(msg), use_model=False)
        self.assertEqual(state['current_goal'], 'support_choice')
        self.assertNotIn('你們會擔心我的未來', local_reply(msg, state))

    def test_other_topics_do_not_invent_parents(self):
        msg = '我不知道怎麼跟老師講我想換座位，怕他生氣。'
        triage, state = prepare_dialogue(msg, perform_triage(msg), use_model=False)
        self.assertEqual(state['current_goal'], 'support_choice')
        self.assertNotIn('你們會擔心我的未來', local_reply(msg, state))


if __name__ == '__main__':
    unittest.main()
