"""v1.3-B: explainable replay of FICTIONAL dialogues for authorised staff review.

Runs the real rule pipeline offline (no model, no network, no database) so every
displayed signal can be traced to a verbatim quote and the rule that produced it.
It never creates cases, consents or notifications, and never reads real conversations.
"""
import json
import os

from engine.dialogue_ai import prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import local_reply
from engine.triage import RISK_LEVEL_WEIGHTS, RISK_METADATA, perform_triage
from engine.wellbeing_signals import DOMAINS, UNKNOWN, VERSION as WELLBEING_VERSION, update_wellbeing_signals

VERSION = "v1.3-B-explain-1"
SCENARIO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "explain_scenarios.json")
MAX_TURNS = 12

DOMAIN_LABELS = {
    "duration": "持續時間", "sleep": "睡眠", "daily_function": "生活／上學功能",
    "stress_relationships": "人際與壓力", "safety": "安全線索", "support_system": "支持系統",
}
STATUS_LABELS = {
    UNKNOWN: "未提及（不代表正常）",
    "time_mentioned": "提到時間", "reported_difficulty": "自述困難", "reported_ok_or_improving": "自述尚可或改善",
    "reported_impact": "自述受影響", "reported_maintained": "自述仍能維持", "topic_mentioned": "提到相關主題",
    "support_mentioned": "提到可求助對象", "difficulty_seeking_support": "自述難以求助",
    "requires_human_review": "需真人覆核", "clarification_needed": "待安全確認",
    "self_reported_denial": "自述否認（不等於已確認安全）",
}
GOAL_LABELS = {
    "clarify_event": "了解事件", "explore_feeling": "探索感受", "explore_perception": "探索想法",
    "explore_expectation": "探索期待", "explore_yearning": "探索渴望", "integrate": "整合收束",
    "support_choice": "提供可選的小步驟", "respect_boundary": "尊重界線", "stabilize": "先穩定情緒",
    "establish_safety": "說明隱私界線", "safety_support": "安全確認優先",
    "configure_role": "設定陪伴角色", "clarify_identity": "說明 AI 身分",
}


def load_scenarios(path=SCENARIO_PATH):
    """Only fictional scenarios marked as such are accepted."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    scenarios = []
    for item in data.get("scenarios", []):
        turns = item.get("turns")
        if (item.get("fictional") is True and isinstance(item.get("id"), str)
                and isinstance(turns, list) and 0 < len(turns) <= MAX_TURNS
                and all(isinstance(t, str) and 0 < len(t) <= 500 for t in turns)):
            scenarios.append(item)
    return scenarios


def _rule_sources(rules):
    return [{"tier": tier, "matched": flag} for tier in ("red", "orange", "yellow")
            for flag in rules.get(tier + "_flags", [])]


def replay(turns):
    """Replay user turns exactly like the chat route, minus the model and the database."""
    state, wellbeing, highest = {}, None, "green"
    records = []
    for index, message in enumerate(turns, 1):
        triage = perform_triage(message, previous_level=highest)
        rules = triage["rule_details"]
        triage, dialogue_state = prepare_dialogue(message, triage, state, use_model=False)
        wellbeing = update_wellbeing_signals(wellbeing, message, dialogue_state)
        dialogue_state["wellbeing_signals"] = wellbeing
        reply = local_reply(message, dialogue_state)
        highest = max((highest, triage["level"], dialogue_state["risk_level"]), key=RISK_LEVEL_WEIGHTS.get)
        records.append({
            "turn": index,
            "message": message,
            "rule_level": rules["triggered_level"],
            "level": triage["level"],
            "highest_level": highest,
            "rule_sources": _rule_sources(rules),
            "dialogue_safety": {key: dialogue_state.get(key) for key in (
                "risk_signal", "risk_type", "risk_subject", "risk_evidence",
                "immediate_danger", "safety_denied", "pending_safety_check")},
            "reasons": triage.get("reasons", []),
            "current_goal": dialogue_state["current_goal"],
            "goal_label": GOAL_LABELS.get(dialogue_state["current_goal"], dialogue_state["current_goal"]),
            "reply": reply,
        })
        state = remember_turn(dialogue_state, message, reply)
    return records, wellbeing, highest


def explain(scenario):
    turns = scenario["turns"]
    records, wellbeing, highest = replay(turns)
    domains = []
    for key in DOMAINS:
        note = (wellbeing or {}).get("domains", {}).get(key, {"status": UNKNOWN, "evidence": "", "turn": 0})
        turn = note.get("turn", 0)
        evidence = note.get("evidence", "")
        domains.append({
            "key": key, "label": DOMAIN_LABELS[key], "status": note["status"],
            "status_label": STATUS_LABELS.get(note["status"], note["status"]),
            "known": note["status"] != UNKNOWN, "evidence": evidence, "turn": turn,
            "source": note.get("source", "not_assessed"),
            # Evidence must be a verbatim substring of the cited turn, never a paraphrase.
            "evidence_verified": bool(evidence) and 0 < turn <= len(turns) and evidence in turns[turn - 1],
        })
    meta = RISK_METADATA[highest]
    return {
        "version": VERSION, "wellbeing_version": WELLBEING_VERSION,
        "id": scenario["id"], "title": scenario.get("title", scenario["id"]),
        "purpose": scenario.get("purpose", ""), "fictional": True,
        "expected_highest": scenario.get("expected_highest"),
        "highest_level": highest, "highest_label": meta["label"],
        "matches_expected": scenario.get("expected_highest") in (None, highest),
        "action": {"system_action": meta["system_action"], "human_role": meta["human_role"],
                   "counselor_required": meta["counselor_required"]},
        "domains": domains,
        "known_count": sum(d["known"] for d in domains),
        "turns": records,
        "reply_source": "本機規則回覆（展示重播，未呼叫雲端模型）",
        "notice": "虛構案例重播；不寫入資料庫、不建立個案、不通知任何人。線索與燈號供真人覆核，不是診斷或量表分數。",
    }
