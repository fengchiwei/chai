"""v1.3-A: evidence-bound conversational wellbeing notes (not clinical screening).

This module is purely observational. It does not produce scores, decide crisis levels,
change the existing policy, ask questions, or notify anyone. The current server-side
conversation context retains notes under its existing expiry and consent model.
"""
from __future__ import annotations

import re

VERSION = "v1.3-A-evidence-1"
DOMAINS = (
    "duration", "sleep", "daily_function", "stress_relationships",
    "safety", "support_system",
)
UNKNOWN = "unknown"

_DURATION = re.compile(r"(?:已經|持續|大概|差不多|最近|這)?\s*(?:\d+|[一二兩三四五六七八九十半]+)\s*(?:個)?(?:天|週|周|禮拜|星期|月|年)")
_SLEEP = re.compile(r"睡不好|睡不著|失眠|睡眠不好|睡眠不足|睡眠受影響|夜裡(?:常|一直)?醒|半夜(?:常|一直)?醒|睡得(?:很)?(?:好|還好|不錯)|睡眠(?:正常|還好)")
_DAILY = re.compile(r"上課.{0,8}(?:分心|沒精神|無法專心|不能專心)|(?:沒辦法|無法|不敢|不想)(?:去)?(?:上學|上課|出門)|拒學|缺課|常請假|生活.{0,8}(?:受影響|被影響)|(?:無法|很難|沒辦法).{0,6}專心|(?:還能|仍能|可以).{0,8}(?:上學|上課|生活)|吃不下")
_STRESS = re.compile(r"考試|段考|成績|課業|功課|升學|選科系|設計|爸媽|爸爸|媽媽|家人|家裡|父母|老師|同學|朋友|交往|感情|分手|被排擠|吵架|壓力|困擾")
_SUPPORT = re.compile(r"(?:沒有人|沒人|找不到人).{0,12}(?:聽|聊|說|幫|支持|相信)|(?:不敢|不願|沒辦法).{0,14}(?:告訴|跟.{0,6}說|找.{0,6}(?:聊|談|幫忙))|(?:有人|(?<!沒)有|可以找|願意找).{0,12}(?:朋友|老師|家人|爸爸|媽媽|輔導|同學).{0,10}(?:聊|談|說|幫|支持|傾訴)|(?:老師|朋友|同學|家人).{0,10}(?:可以聊|能幫|願意聽|會支持)")
_NEG_SLEEP = re.compile(r"(?:沒有|不會|並未|從未|不是|不再|已經不).{0,4}(?:睡不好|睡不著|失眠)")
_OK_SLEEP = re.compile(r"睡得(?:很)?(?:好|還好|不錯)|睡眠(?:正常|還好)|(?:睡不好|睡不著|失眠).{0,5}(?:改善|好多了)")
_NO_IMPACT = re.compile(r"(?:沒|沒有|不會).{0,7}(?:影響|分心|缺課|拒學)|(?:還能|仍能|可以).{0,8}(?:上學|上課|生活)")
_NO_SUPPORT = re.compile(r"(?:沒有人|沒人|找不到人).{0,12}(?:聽|聊|說|幫|支持|相信)|(?:不敢|不願|沒辦法).{0,14}(?:告訴|跟.{0,6}說|找.{0,6}(?:聊|談|幫忙))")


def _clause(text: str, pattern: re.Pattern[str]) -> str:
    """Keep a bounded *verbatim substring*, never invent a paraphrased quote."""
    for part in re.split(r"[。！？!?；;\n\r]", text):
        match = pattern.search(part)
        if match:
            left = max(0, match.start() - 70)
            right = min(len(part), left + 160)
            if right < match.end():
                right = min(len(part), match.end() + 10)
                left = max(0, right - 160)
            return part[left:right].strip()
    return ""


def _note(status: str, evidence: str, turn: int, source: str = "user_text") -> dict:
    return {"status": status, "evidence": evidence, "source": source, "turn": turn}


def _existing(previous) -> dict:
    domains = {}
    existing = previous.get("domains", {}) if isinstance(previous, dict) and previous.get("version") == VERSION else {}
    for key in DOMAINS:
        item = existing.get(key) if isinstance(existing, dict) else None
        if isinstance(item, dict) and isinstance(item.get("status"), str):
            domains[key] = {
                "status": item["status"][:40],
                "evidence": str(item.get("evidence", ""))[:160],
                "source": str(item.get("source", "unknown"))[:32],
                "turn": int(item.get("turn", 0)) if str(item.get("turn", 0)).isdigit() else 0,
            }
        else:
            domains[key] = _note(UNKNOWN, "", 0, "not_assessed")
    return domains


def update_wellbeing_signals(previous, message: str, dialogue_state: dict) -> dict:
    """Observe one real user turn, using the *already resolved* safety state.

    Never changes dialogue_state, triage, advice strategy or formal questionnaire results.
    A missing observation always remains unknown rather than being declared normal.
    """
    domains = _existing(previous)
    if not isinstance(message, str) or not isinstance(dialogue_state, dict):
        return {"version": VERSION, "domains": domains}
    text = message[:2000]
    turn = int(dialogue_state.get("turn_count", 0) or 0)
    # Basic quotations and hypotheticals can contain symptoms not describing the user.
    # Avoid converting them into first-person health observations.
    snippets = re.split(r"[。！？!?；;\n\r]", text)
    eligible = [p.strip() for p in snippets if p.strip() and not re.search(
        r"^(?:如果|假如|假設|例如|比方說|小說|新聞|題目|假設題)|(?:我?朋友|我?同學|他|她|有人)(?:說|表示|提到|最近|這幾天)", p.strip())]
    user_text = "。".join(eligible)
    if match := _clause(user_text, _DURATION):
        domains["duration"] = _note("time_mentioned", match, turn)
    if match := _clause(user_text, _SLEEP):
        status = "reported_ok_or_improving" if (_NEG_SLEEP.search(match) or _OK_SLEEP.search(match)) else "reported_difficulty"
        domains["sleep"] = _note(status, match, turn)
    if match := _clause(user_text, _DAILY):
        domains["daily_function"] = _note("reported_maintained" if _NO_IMPACT.search(match) else "reported_impact", match, turn)
    if match := _clause(user_text, _STRESS):
        domains["stress_relationships"] = _note("topic_mentioned", match, turn)
    if match := _clause(user_text, _SUPPORT):
        domains["support_system"] = _note("difficulty_seeking_support" if _NO_SUPPORT.search(match) else "support_mentioned", match, turn)

    # Safety notes are only annotations of the established rule/semantic safety state;
    # they are NOT a second detector, and do not automatically consider silence safe.
    risk_level = dialogue_state.get("risk_level", "green")
    if risk_level in ("orange", "red") or dialogue_state.get("human_escalation_required"):
        evidence = dialogue_state.get("risk_evidence", "")
        evidence = evidence[:160] if isinstance(evidence, str) and evidence in text else ""
        old = domains["safety"]
        # Retain the last explicit signal when this turn adds no new evidence, keeping the
        # turn it was quoted from so the evidence stays traceable to the original message.
        if not evidence and old["status"] == "requires_human_review" and old["evidence"]:
            evidence, turn = old["evidence"], old["turn"]
        domains["safety"] = _note("requires_human_review", evidence, turn, "existing_safety_state")
    elif dialogue_state.get("pending_safety_check") or dialogue_state.get("safety_check_required"):
        evidence = dialogue_state.get("risk_evidence", "")
        evidence = evidence[:160] if isinstance(evidence, str) and evidence in text else ""
        domains["safety"] = _note("clarification_needed", evidence, turn, "existing_safety_state")
    elif dialogue_state.get("safety_denied"):
        # A denial is a self-report, NOT evidence of safety.
        domains["safety"] = _note("self_reported_denial", text[:160], turn, "user_text")
    return {"version": VERSION, "domains": domains}
