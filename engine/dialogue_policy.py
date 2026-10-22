"""Satir v1.1 dialogue policy. Rules own decisions; LLM observations are evidence-bound hints.

State is a bounded, server-side conversation aid, not a diagnosis or a clinical score.
Unconfirmed signals and confirmed high-water risk are intentionally separate.
"""
from copy import deepcopy
import re
from engine.dialogue_role import asks_identity, resolve_role

POLICY_VERSION = "satir-2026-10-19.2"
WEIGHTS = {"green": 1, "yellow": 2, "orange": 3, "red": 4}
STAGES = ("event", "feeling", "perception", "expectation", "yearning", "self")
RISK_TYPES = ("none", "self_harm", "suicide", "abuse", "violence", "digital_sexual_violence", "other")
LOW_REPLIES = {"不知道", "我不知道", "不曉得", "嗯", "嗯嗯", "喔", "哦", "沒事", "還好", "差不多吧", "不知道怎麼說", "說不上來"}
BOUNDARY = r"不想(?:再)?(?:講|說|談)|不要(?:再|一直)?問|別(?:再|一直)?問|不想(?:一直)?被問|關你什麼事|只想.{0,4}(?:聽|陪)|只要.{0,4}(?:聽|陪)"
HIGH_EMOTION = r"哭到|哭不停|哭得停不下|一直哭|暴怒|氣到發抖|恐慌|腦袋一片空白|完全無法思考|快崩潰|全部的人都在針對我|閉嘴"
FEELING = r"難過|失望|委屈|生氣|超煩|很煩|焦慮|害怕|心慌|緊張|心情不好|低落|尷尬|丟臉|孤單|疲累|很累|開心|擔心|不敢|胃痛"
PATTERNS = {
    "event": r"告白|被打槍|老師罵|考很爛|考試|段考|成績|吵架|拒絕|只把我當朋友|今天|昨天|爸媽|我爸|我媽|同學|劃好.*重點|選科系",
    "feeling": FEELING,
    "perception": r"一定.*(?:討厭|覺得|不在乎)|大家.*覺得|我覺得.*(?:他|她|自己)|反正.*不夠好|所以.*(?:我|他|她)|代表.*(?:我|他|她)",
    "expectation": r"我.*希望|我只想.*(?:聽|認真|相信)|希望.*(?:聽|比較|相信|尊重)|期待|我想要.*(?:聽|相信)",
    "yearning": r"被(?:理解|在乎|喜歡|尊重|接納|肯定|當一回事|認真對待)|歸屬感|自主權|自己有價值|有人在乎我|(?:讓我|可以|能夠)自己(?:做)?決定|把我當(?:成)?(?:一個)?有自己想法",
    "self": r"我.*(?:很沒用|超廢|沒人要|不值得|不夠好|什麼都做不好|很失敗)|沒有人會喜歡我|我是不是.*(?:沒用|不好)",
}


# 將「我不知道怎麼跟他們講」這類帶有行動對象的困難，辨識成隱含求助。
# 單純「不知道怎麼說心情／我不知道」不算求方法，仍依意願傾聽。
_EXPLICIT_HELP = re.compile(
    r"怎麼辦|怎麼做|可以怎樣|該怎麼|該如何|要如何|有什麼辦法|有沒有辦法|"
    r"給我.{0,8}建議|幫我.{0,8}(?:想|寫)|想了解.{0,8}資源|可以找誰|想看.{0,8}資源|"
    r"(?:教我|幫我看看).{0,12}(?:怎麼|如何)|(?:^|[？?])(?:怎麼|如何)(?:跟|和|向|對).{0,12}(?:說|講|談|開口|溝通|表達)"
)
_IMPLICIT_HELP = re.compile(
    r"(?:不知道|不曉得|不清楚|想不到|不會|沒辦法|不確定|不太會)"
    r".{0,15}(?:怎麼|如何).{0,18}"
    r"(?:跟|和|向|對).{0,12}(?:說|講|談|開口|溝通|表達)"
    r"|(?:不知道|不曉得|想不到|不會|沒辦法).{0,12}"
    r"(?:怎麼|如何).{0,36}(?:才不會|才能|比較不會).{0,15}(?:吵|衝突|誤會|生氣)"
)


def wants_practical_help(text):
    """偵測實際行動的求助；不將不知道如何描述感受誤認為求建議。"""
    if re.search(r"只想(?:先)?(?:聊|說|被聽)|只要你聽|不要.{0,8}(?:建議|方法|教我)|不用.{0,8}(?:建議|方法)", text):
        return False
    if re.search(r"^(?:我)?(?:不知道|不曉得)(?:怎麼說|怎麼講)?[，,。!！]*$", text.strip()):
        return False
    return bool(_EXPLICIT_HELP.search(text) or _IMPLICIT_HELP.search(text))


def compact(text):
    return re.sub(r"[\s，,。.!！?？、；;]", "", text)


def history_clean(history, message=None):
    clean = [{"role": t["role"], "text": t["text"][:2000]} for t in (history or [])
             if isinstance(t, dict) and t.get("role") in ("user", "assistant") and isinstance(t.get("text"), str)]
    if message is not None and clean and clean[-1] == {"role": "user", "text": message[:2000]}:
        clean.pop()
    # Whole pairs in production; skip a dangling assistant for older callers.
    clean = clean[-24:]
    if clean and clean[0]["role"] == "assistant" and len(clean) > 1:
        clean = clean[1:]
    return clean


def initial_state():
    state = {
        "policy_version": POLICY_VERSION, "turn_count": 0,
        "risk_signal": "none", "risk_level": "green", "risk_type": "none", "risk_types": [],
        "risk_subject": "unknown", "risk_evidence": "", "immediate_danger": "none",
        "safety_check_required": False, "safety_override": False, "pending_safety_check": False,
        "human_escalation_required": False, "safety_action": "none", "safety_denied": False,
        "emotion_intensity": "low", "conversation_willingness": "medium", "privacy_concern": False,
        "confidentiality_limit_needed": False, "advice_request": False,
        "iceberg_stage": "unknown", "current_goal": "clarify_event", "response_strategy": "clarify",
        "ask_question": True, "max_questions": 1, "forbidden_actions": [],
        "uncertainty_streak": 0, "boundary_active": False, "corrections": [],
        "coping_summary": "", "meta_feeling_summary": "", "observation_source": "rules",
        "history": [], "last_reply": "",
        "companion_role": {"description": "", "preferences": []},
    }
    for name in STAGES:
        state["known_" + name] = False
        state[name + "_summary"] = ""
    return state


def _valid_observations(hints, message):
    """Only quotes from the current user message enter memory. Never store model reasoning."""
    if not isinstance(hints, dict):
        return {}
    valid = {}
    for key in (*STAGES, "coping", "meta_feeling", "emotion", "willingness", "risk"):
        item = hints.get(key)
        if not isinstance(item, dict):
            continue
        quote = item.get("evidence")
        if isinstance(quote, str) and 2 <= len(quote) <= 240 and quote in message:
            valid[key] = {k: v for k, v in item.items()
                          if k in ("evidence", "value", "signal", "type", "danger", "subject", "affirmed")}
    return valid


def _affirmative_matches(pattern, text):
    for clause in re.split(r"[。！？!?；;\n]|但是|可是|不過|但", text):
        for match in re.finditer(pattern, clause):
            before = clause[max(0, match.start() - 16):match.start()]
            # A negation before a comma does not negate an unrelated clause.
            before = re.split(r"[,，、]", before)[-1]
            if re.search(r"(?:沒有|並未|從未|不會|不打算|不是|不想|不要|並不).{0,4}$", before):
                continue
            if re.search(r"(?:沒有|不會|並未|從未|不打算).{0,6}(?:打我|揍我|性侵|拿刀|帶刀|持刀|殺|砍|捅|威脅|自殺|傷害|吃掉|吞|吃完)", match.group()):
                continue
            yield clause, match.group()


def _reaffirms_after_denial(message):
    """A denial followed by new affirmative safety information is NOT a full denial.

    Only consulted when the *server* already recorded a pending safety question.
    A broad symptom detector must not be inferred from arbitrary conversation.
    """
    transition = re.search(r"(?:但是?|可是|不過|其實)[^。！？!?；;\n]{0,70}", message)
    if not transition:
        return ""
    tail = transition.group(0)
    # Affirmative cues in a response to a safety question. No invented intent/means.
    signals = r"想死|自殺|自傷|傷害自己|不想活|割(?:手|腕)|吞藥|想過|會想"
    for hit in re.finditer(signals, tail):
        before = tail[max(0, hit.start() - 9):hit.start()]
        after = tail[hit.end():hit.end()+8]
        if re.search(r"(?:沒有|從未|並未|不會|不打算|不想|不要|沒)[^，,。！？!?]{0,5}$", before):
            continue
        if hit.group() in ("想過", "會想") and re.match(r"(?:要|著|出)?(?:功課|作業|考試|科系|辦法|問題|遊戲|如何|怎麼)", after):
            continue
        return transition.group(0)[:100]
    return ""


def observe_safety(message, triage, previous=None, hints=None):
    previous = previous or {}
    rules = triage.get("rule_details", {})
    current = rules.get("triggered_level", "green")
    risk = {"risk_signal": "none", "risk_type": "none", "risk_subject": "unknown",
            "risk_evidence": "", "immediate_danger": "none", "safety_denied": False,
            "pending_safety_check": False, "minimum_level": "green", "risk_types": []}
    candidates = []

    def add(kind, signal, danger, evidence, floor, subject="self"):
        candidates.append({"risk_signal": signal, "risk_type": kind, "risk_subject": subject,
                           "risk_evidence": evidence[:240], "immediate_danger": danger,
                           "minimum_level": floor})

    # Existing explicit rules and quantitative/high-water levels cannot be vetoed by the LLM.
    if current in ("orange", "red"):
        evidence = "；".join(rules.get("red_flags", []) or rules.get("orange_flags", []))
        kind = "abuse" if re.search(r"被打(?!槍)|家暴", evidence) else "suicide" if re.search(
            r"想死|自殺|自傷|不想活|活不下去|活著|死亡|遺書|吞藥|跳樓|跳橋|燒炭|上吊|不想醒|不要醒|結束(?:生命|自己)|工具", evidence) else "self_harm"
        add(kind, "direct", "imminent" if current == "red" else "possible", evidence, current)

    specs = [
        (r"(?:威脅|恐嚇|逼我|強迫).{0,25}(?:私密照|裸照|性影像|性愛影片)|(?:私密照|裸照|性影像).{0,25}(?:外流|威脅|散布|散佈|公開)", "digital_sexual_violence", "orange"),
        (r"(?:爸|媽|家人|大人|老師|教練|叔叔|阿姨|繼父).{0,18}(?:打我(?!(?:最)?(?:喜歡|愛)?的?(?:羽球|籃球|桌球|排球|網球|棒球|電動|遊戲|球))|揍我|摸我|逼我脫|性侵)|(?:我|同學).{0,6}(?:被虐待|被性侵|被強暴|被家暴|被打(?!槍))", "abuse", "orange"),
        (r"(?:我|他|她|有人).{0,16}(?:拿刀|帶刀|持刀).{0,18}(?:殺|砍|捅|堵|門外|門口)|(?:我|他|她).{0,14}(?:要殺|想殺|要砍|要捅).{0,6}(?:人|他|她|同學|我)", "violence", "orange"),
        (r"(?:我今晚|我現在|我等一下|我今天).{0,12}(?:打算|要).{0,12}(?:這些藥|全部.*藥|整瓶.*藥).{0,8}(?:吃掉|吞|吃完)", "suicide", "red"),
    ]
    for pattern, kind, floor in specs:
        for clause, evidence in _affirmative_matches(pattern, message):
            if kind in ("abuse", "violence") and re.search(r"現在|正在|今晚|等一下|門外|門口|拿刀|帶刀|持刀", clause):
                floor = "red"
            add(kind, "direct", "imminent" if floor == "red" else "possible", evidence, floor)

    # Third-party disclosure stays third-party; it is still a reason to pause and help connect.
    for clause, evidence in _affirmative_matches(
            r"(?:朋友|同學|他|她).{0,8}(?:說|表示|提到).{0,15}(?:不想活|想死|自殺|傷害自己|吞藥)", message):
        danger = "imminent" if re.search(r"今晚|現在|正在|已經|等一下", clause) else "possible"
        add("suicide", "direct", danger, evidence, "red" if danger == "imminent" else "orange", "other")

    ambiguous = r"撐不下去|受不了了|不想撐了|快撐不住"
    indirect = r"少了我.{0,4}也沒差|沒有我.{0,8}(?:更好|沒差)|(?:如果|希望).{0,5}(?:不要|不再)醒來|希望睡了就不醒|不想醒來"
    for pattern, signal in ((ambiguous, "ambiguous"), (indirect, "indirect")):
        for _, evidence in _affirmative_matches(pattern, message):
            add("suicide", signal, "possible", evidence, "yellow")

    # A short answer is interpreted only against a server-recorded pending safety question.
    pending = previous.get("pending_safety_check", False)
    denied = bool(re.search(r"^(?:沒有啦|沒有|沒啦|並沒有|沒有耶)(?:$|[，,。!！\s])", message) or re.search(
        r"(?:沒有|不會|不想).{0,4}(?:傷害自己|自殺)|沒有.{0,3}不想活", message))
    if pending and not candidates:
        reaffirms = _reaffirms_after_denial(message)
        if reaffirms:
            add(previous.get("risk_type") if previous.get("risk_type") in RISK_TYPES[1:] else "suicide",
                "direct", "possible", reaffirms, "orange",
                previous.get("risk_subject") if previous.get("risk_subject") in ("self", "other") else "self")
        elif denied:
            risk["safety_denied"] = True
        elif re.search(r"^(?:有|有啊|有耶|對|是|嗯|有一點|會|想過)(?:$|[，,。!！\s])", message):
            add(previous.get("risk_type", "suicide"), "direct", "possible", message, "orange",
                previous.get("risk_subject", "self"))
        else:
            add(previous.get("risk_type", "suicide"), previous.get("risk_signal", "ambiguous"),
                "possible", previous.get("risk_evidence", ""), "yellow", previous.get("risk_subject", "self"))

    observation = _valid_observations(hints, message).get("risk", {})
    # Grounding alone is insufficient: a quote can explicitly deny a harmful intention.
    if re.search(r"(?:沒有|並未|從未|不會|不打算|不是).{0,5}(?:想|要|打算)?(?:自傷|自殺|傷害自己|想死|不想活)", observation.get("evidence", "")):
        observation = {}
    if observation.get("affirmed") is True and not (pending and denied and not candidates):
        kind, signal, danger = observation.get("type"), observation.get("signal"), observation.get("danger")
        if kind in RISK_TYPES[1:] and signal in ("ambiguous", "indirect", "direct") and danger in ("none", "possible", "imminent"):
            floor = "red" if signal == "direct" and danger == "imminent" else "orange" if signal == "direct" else "yellow"
            add(kind, signal, danger, observation["evidence"], floor,
                observation.get("subject") if observation.get("subject") in ("self", "other") else "unknown")
    if candidates:
        # A direct current safety threat wins ties over a less specific signal.
        selected = max(candidates, key=lambda c: (WEIGHTS[c["minimum_level"]], c["immediate_danger"] == "imminent",
                                                    c["risk_type"] in ("violence", "abuse", "digital_sexual_violence"),
                                                    c["risk_subject"] == "self"))
        risk.update(selected)
        risk["risk_types"] = list(dict.fromkeys(c["risk_type"] for c in candidates))
        risk["pending_safety_check"] = selected["risk_signal"] in ("ambiguous", "indirect")
    return risk


def raise_triage(triage, safety):
    """Add a floor with fresh metadata. Never edit scores or lower any existing decision."""
    from engine.triage import RISK_METADATA
    result = deepcopy(triage)
    floor = safety.get("minimum_level", "green")
    if WEIGHTS[floor] > WEIGHTS[result.get("level", "green")]:
        result.update(RISK_METADATA[floor])
        result["level"] = floor
    if safety.get("risk_signal") != "none":
        result["reasons"] = list(result.get("reasons", [])) + [
            "對話安全核對：" + safety["risk_type"] + " / " + safety["risk_signal"] + "；需真人確認"]
        result["explainability"] = "；".join(result["reasons"])
    result["dialogue_safety"] = safety
    return result


def build_state(message, triage, previous=None, hints=None, history=None):
    old = previous or {}
    state = {**initial_state(), **deepcopy(old)}
    state["policy_version"] = POLICY_VERSION
    role_hint = hints.get("companion_role") if isinstance(hints, dict) else None
    state.update(resolve_role(message, old, role_hint))
    turns = history_clean(history if history is not None else old.get("history", []), message)
    state["history"] = turns
    state["turn_count"] = old.get("turn_count", len([t for t in turns if t["role"] == "user"])) + 1
    observations = _valid_observations(hints, state["dialogue_content"])
    state["observation_source"] = "rules+model" if observations else "rules"
    safety = triage.get("dialogue_safety") or observe_safety(message, triage, old, hints)
    state.update({k: v for k, v in safety.items() if k != "minimum_level"})
    state["risk_level"] = max((triage.get("level", "green"), old.get("risk_level", "green"), safety["minimum_level"]), key=WEIGHTS.get)
    # Keep the confirmed path across denials and short follow-ups, with fresh danger evidence separate.
    if old.get("risk_level") in ("orange", "red"):
        state["risk_types"] = list(dict.fromkeys(old.get("risk_types", []) + state["risk_types"]))
        if safety["minimum_level"] == "green" or WEIGHTS[old["risk_level"]] > WEIGHTS[safety["minimum_level"]]:
            state["risk_type"] = old.get("risk_type", "other")
            state["risk_subject"] = old.get("risk_subject", "unknown")
    state["safety_override"] = state["risk_level"] in ("orange", "red")
    state["safety_check_required"] = state["safety_override"] or state["pending_safety_check"]
    state["human_escalation_required"] = state["safety_override"]
    state["safety_action"] = ({"suicide": "suicide_safety", "self_harm": "self_harm_safety", "abuse": "child_protection",
                               "violence": "violence_safety", "digital_sexual_violence": "digital_safety"}.get(
                                   state["risk_type"], "general_safety") if state["safety_override"]
                              else "brief_safety_check" if state["pending_safety_check"] else "none")
    # Safety always sees the complete original text. A role request is not a life event.
    original_message = message
    message = state["dialogue_content"]
    text = compact(message)
    short = text in LOW_REPLIES
    state["uncertainty_streak"] = old.get("uncertainty_streak", 0) + 1 if short else 0
    state["emotion_intensity"] = "high" if re.search(HIGH_EMOTION, message) else "medium" if re.search(FEELING, message) else "low"
    state["conversation_willingness"] = "low" if re.search(BOUNDARY, message) else "medium" if short or len(text) < 6 else "high"
    for key, field in (("emotion", "emotion_intensity"), ("willingness", "conversation_willingness")):
        item = observations.get(key, {})
        if item.get("value") in ("low", "medium", "high"):
            # The model cannot undo an explicit boundary or a locally detected high emotion.
            if field == "conversation_willingness" and re.search(BOUNDARY, message):
                continue
            if field == "emotion_intensity" and state[field] == "high":
                continue
            state[field] = item["value"]
    state["boundary_active"] = bool(re.search(BOUNDARY, original_message)) or bool(old.get("boundary_active") and (short or len(text) < 6))
    state["privacy_concern"] = bool(re.search(r"不能.*(?:講|說)|不要.*(?:告訴|跟.*講)|保密|會.*(?:告訴|知道|看到)|不想.*(?:老師|爸媽|班導|同學).*知道", message))
    state["confidentiality_limit_needed"] = state["privacy_concern"] or state["safety_override"]
    state["advice_request"] = wants_practical_help(message)
    correction = bool(re.search(r"^(?:不是|不對)|你誤會|你聽錯|不是那個意思|我不是.{0,6}[，,].*(?:是|而是)", message)) and not state["safety_denied"]
    if re.search(r"換個話題|換件事|另一件事|先不聊這個", message):
        state["earlier_topics"] = (old.get("earlier_topics", []) + [{stage: state[stage + "_summary"] for stage in STAGES}])[-2:]
        for stage in STAGES:
            state[stage + "_summary"] = ""
            state["known_" + stage] = False
    if correction:
        state["corrections"] = (old.get("corrections", []) + [message[:240]])[-4:]
    found = []
    for stage in STAGES:
        item = observations.get(stage)
        evidence = item["evidence"] if item else message[:240] if re.search(PATTERNS[stage], message) and not short else ""
        if evidence:
            # Quotes are observations, including negations; never turn them into asserted feelings.
            previous_summary = state[stage + "_summary"]
            entries = previous_summary.split(" ｜ ") if previous_summary and not correction else []
            if evidence not in entries:
                entries.append(evidence)
            entries = entries if len(entries) <= 3 else [entries[0], *entries[-2:]]
            state[stage + "_summary"] = " ｜ ".join(entries)
            state["known_" + stage] = True
            found.append(stage)
    for key, pattern in (("coping", r"裝沒事|裝作沒事|開玩笑|忍住|假裝|躲起來"),
                         ("meta_feeling", r"(?:難過|生氣|哭).*(?:丟臉|不應該|討厭自己)|覺得自己.*(?:不該|不應該).*(?:哭|難過|生氣)")):
        if key in observations or re.search(pattern, message):
            state[key + "_summary"] = observations.get(key, {}).get("evidence", message[:240])
    state["iceberg_stage"] = found[-1] if found else old.get("iceberg_stage", "unknown")
    goal, strategy, ask = "clarify_event", "clarify", True
    if state["safety_check_required"]:
        goal, strategy, ask = "safety_support", "safety_check", True
    elif state["emotion_intensity"] == "high":
        goal, strategy, ask = "stabilize", "reflect_only", False
    elif state["boundary_active"] or state["conversation_willingness"] == "low" or state["uncertainty_streak"] >= 2:
        goal, strategy, ask = "respect_boundary", "respect_boundary", False
    elif state["privacy_concern"]:
        goal, strategy, ask = "establish_safety", "clarify_boundary", False
    elif asks_identity(original_message):
        goal, strategy, ask = "clarify_identity", "clarify_boundary", False
    elif state["role_only"]:
        goal, strategy, ask = "configure_role", "acknowledge_choice", False
    elif state["safety_denied"]:
        goal, strategy, ask = "integrate", "reflect_only", False
    elif state["advice_request"]:
        goal, strategy, ask = "support_choice", "support_next_step", False
    elif state["known_yearning"] or "self" in found or re.search(r"原來我|明白自己|比較平靜|輕鬆一點", message):
        goal, strategy, ask = "integrate", "summarize", False
    elif correction:
        goal, strategy, ask = "integrate", "reflect_only", False
    elif short:
        goal, strategy, ask = "explore_feeling", "reflect_only", False
    else:
        for known, next_goal in (("expectation", "explore_yearning"), ("perception", "explore_expectation"),
                                 ("feeling", "explore_perception"), ("event", "explore_feeling")):
            if state["known_" + known]:
                goal, strategy = next_goal, "reflect_then_ask"
                break
    recent = [t["text"] for t in turns if t["role"] == "assistant"][-2:]
    if goal != "safety_support" and len(recent) == 2 and all(re.search(r"[？?]", r) for r in recent):
        ask, strategy = False, "reflect_only"
    state.update(current_goal=goal, response_strategy=strategy, ask_question=ask, max_questions=int(ask))
    banned = ["ask_multiple_questions", "diagnose", "interpret_for_user", "force_positive", "promise_absolute_confidentiality", "minimize_risk"]
    if goal != "support_choice":
        banned.append("give_advice")
    if goal in ("safety_support", "stabilize", "respect_boundary", "establish_safety", "integrate"):
        banned.extend(("explore_yearning", "deep_reflection", "continue_drilling"))
    state["forbidden_actions"] = banned
    return state


def remember_turn(state, message, reply):
    saved = deepcopy(state)
    saved["history"] = (history_clean(state.get("history"), message) + [
        {"role": "user", "text": message[:2000]}, {"role": "assistant", "text": reply[:2000]}])[-24:]
    saved["last_reply"] = reply[:2000]
    return saved
