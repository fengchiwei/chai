"""v1.3-A self-contained deterministic tests; no Flask, APIs or student records."""
import unittest
from engine.wellbeing_signals import DOMAINS, VERSION, update_wellbeing_signals


def state(**kwargs):
    return {"turn_count": 1, "risk_level": "green", "pending_safety_check": False,
            "safety_check_required": False, "safety_denied": False,
            "human_escalation_required": False, **kwargs}


def observe(text, previous=None, **kwargs):
    return update_wellbeing_signals(previous, text, state(**kwargs))


class WellbeingV13ATests(unittest.TestCase):
    def test_six_unknown_domains(self):
        d = observe("嗨")
        self.assertEqual(set(d["domains"]), set(DOMAINS))
        self.assertTrue(all(d["domains"][name]["status"] == "unknown" for name in DOMAINS))
        self.assertEqual(d["version"], VERSION)

    def test_duration_is_direct_quote(self):
        d = observe("我已經兩個禮拜覺得很煩。")
        self.assertEqual(d["domains"]["duration"]["status"], "time_mentioned")
        self.assertIn(d["domains"]["duration"]["evidence"], "我已經兩個禮拜覺得很煩。")

    def test_sleep_and_daily_impact(self):
        d = observe("最近睡不好，上課一直分心。")
        self.assertEqual(d["domains"]["sleep"]["status"], "reported_difficulty")
        self.assertEqual(d["domains"]["daily_function"]["status"], "reported_impact")

    def test_sleep_negated(self):
        d = observe("其實沒有睡不好，只是考試壓力大。")
        self.assertEqual(d["domains"]["sleep"]["status"], "reported_ok_or_improving")
        self.assertEqual(d["domains"]["stress_relationships"]["status"], "topic_mentioned")

    def test_sleep_improves_on_new_turn(self):
        old = observe("前幾天一直睡不好")
        d = update_wellbeing_signals(old, "現在睡得還好。", state(turn_count=2))
        self.assertEqual(d["domains"]["sleep"]["status"], "reported_ok_or_improving")
        self.assertEqual(d["domains"]["sleep"]["turn"], 2)

    def test_missing_fields_preserved(self):
        old = observe("最近我睡不好。")
        d = update_wellbeing_signals(old, "我只想讓家人聽我說完。", state(turn_count=2))
        self.assertEqual(d["domains"]["sleep"]["status"], "reported_difficulty")
        self.assertEqual(d["domains"]["sleep"]["turn"], 1)

    def test_support_is_not_confused_with_symptom(self):
        d = observe("我不敢告訴老師。")
        self.assertEqual(d["domains"]["support_system"]["status"], "difficulty_seeking_support")
        self.assertEqual(d["domains"]["safety"]["status"], "unknown")

    def test_safety_not_inferred_from_silence(self):
        d = observe("我今天很開心。")
        self.assertEqual(d["domains"]["safety"]["status"], "unknown")

    def test_safety_needs_confirmation(self):
        d = observe("真的快撐不住了", risk_evidence="快撐不住", pending_safety_check=True)
        self.assertEqual(d["domains"]["safety"]["status"], "clarification_needed")
        self.assertIn(d["domains"]["safety"]["evidence"], "真的快撐不住了")

    def test_high_risk_is_not_lowered_by_next_turn(self):
        first = observe("我現在有想傷害自己的念頭", risk_level="orange", human_escalation_required=True,
                        risk_evidence="想傷害自己")
        next_turn = update_wellbeing_signals(first, "我現在沒事", state(turn_count=2, risk_level="orange"))
        self.assertEqual(next_turn["domains"]["safety"]["status"], "requires_human_review")
        self.assertEqual(next_turn["domains"]["safety"]["evidence"], "想傷害自己")

    def test_red_is_not_a_scoring_algorithm(self):
        d = observe("我現在可能有危險", risk_level="red", human_escalation_required=True,
                    risk_evidence="我現在可能有危險")
        self.assertEqual(d["domains"]["safety"]["status"], "requires_human_review")
        self.assertNotIn("score", repr(d).lower())
        self.assertNotIn("red", repr(d))

    def test_no_third_party_inference(self):
        d = observe("我朋友最近睡不好，我自己沒提到睡眠。")
        self.assertEqual(d["domains"]["sleep"]["status"], "unknown")

    def test_no_hypothetical_inference(self):
        d = observe("如果我兩週睡不好怎麼辦？")
        self.assertEqual(d["domains"]["sleep"]["status"], "unknown")
        self.assertEqual(d["domains"]["duration"]["status"], "unknown")

    def test_not_formal_scale(self):
        d = observe("我最近兩週失眠、一直上課分心，但沒有做過量表。")
        self.assertNotIn("bsrs5", str(d).lower())
        self.assertNotIn("phq", str(d).lower())
        self.assertNotIn("gad", str(d).lower())

    def test_no_mutations(self):
        original = state()
        copy = original.copy()
        observe("睡不好")
        self.assertEqual(original, copy)

    def test_empty_message_unknown(self):
        d = observe("")
        self.assertTrue(all(v["status"] == "unknown" for v in d["domains"].values()))

    def test_second_session_empty(self):
        first = observe("最近睡不好")
        separate = observe("我只是想走設計")
        self.assertEqual(first["domains"]["sleep"]["status"], "reported_difficulty")
        self.assertEqual(separate["domains"]["sleep"]["status"], "unknown")

    def test_denial_does_not_mean_safe(self):
        d = observe("沒有，我沒有想傷害自己。", safety_denied=True)
        self.assertEqual(d["domains"]["safety"]["status"], "self_reported_denial")


if __name__ == "__main__":
    unittest.main()
