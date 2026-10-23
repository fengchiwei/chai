"""Short local responses and final output checks. Local fallback is not a language model."""
import re
from difflib import SequenceMatcher
from engine.dialogue_policy import CLARIFIED, PATTERNS, STAGES
from engine.prompt_guard import detect_injection
from engine.dialogue_role import relationship_violations, role_acknowledgement, role_notice


def quote(text, limit=56):
    clean = re.sub(r"[\r\n。！？!?；;]+", "，", text).strip(" ，")
    return clean[:limit] + ("……" if len(clean) > limit else "")


# Gatekeeper order (問 → 應 → 轉介): ask about the thoughts before means, and never ask the same question twice.
THOUGHTS_QUESTION = "我想直接問你：你有想過結束自己的生命嗎？"
MEANS_QUESTION = "現在有已經準備好的工具或打算行動的時間嗎？"
COMPANY_QUESTION = "現在有人能到你身邊陪你嗎？"
# Answer to 「你會通報學校嗎」; honest about what consent to share means.
PRIVACY_LIMIT = ("這個網站不會自動通知學校或家人；如果你說的內容可能有安全危險，系統會把必要的安全資訊（不含你的暱稱和聯絡方式）送到真人工作臺，讓受過訓練的人優先查看。如果你同意分享摘要和對話紀錄，"
                 "輔導老師為了你的安全，可能需要和其他大人合作，這部分我沒辦法保證不讓人知道。")
SECRECY_ASKED = r"不要(?:告訴|跟.{0,6}(?:說|講))|保密|別說出去|不准說|怕他知道|不能讓.{0,6}知道"


def _unasked(state, *questions):
    """First question not already asked in this conversation (assistant turns and the last reply)."""
    asked = state.get("last_reply", "") + "".join(t.get("text", "") for t in state.get("history", [])
                                                 if t.get("role") == "assistant")
    return next((q for q in questions if q not in asked), "")


# The student is the one who might hurt someone (「我想揍他」), not the one in danger.
WANTS_TO_HURT = (r"我.{0,6}(?:想|要|會|打算|好想|真想|很想|忍不住).{0,12}"
                 r"(?:打|揍|殺|砍|捅|弄死|教訓|報復|算帳|堵|修理|給他好看)")


def safety_reply(message, state):
    """Type-specific safety response. Does not make diagnoses, dispatch or confidentiality promises.

    2026-10-23 simulation (counselling review): the full message once, then short follow-ups that do not
    repeat it or echo the student's words; the full message again only when this turn adds new danger."""
    action = state["safety_action"]
    other = state.get("risk_subject") == "other"
    who = "對方" if other else "你"
    night = state.get("night_review")
    if action == "brief_safety_check":
        if state.get("risk_type") == "violence":
            # Never a question about dying for angry words about someone else.
            return ("聽得出來你真的氣到不行。想先確認一下：你是氣到這樣說說，還是真的有打算動手？"
                    "不管是哪一種，都可以先說說發生了什麼事。")
        if state.get("pending_disambiguation") and state.get("risk_evidence") in message:
            # LIN-01: name the hyperbole as probably figurative, then check once, gently.
            return (f"「{quote(state['risk_evidence'], 20)}」聽起來比較像很誇張的形容，"
                    + ("不過現在很晚了，我還是想輕輕確認一下：" if night else "我先輕輕確認一下就好：")
                    + "你最近有沒有真的不想活了，或想傷害自己的念頭？")
        if state.get("risk_cue") == "affect_streak":
            # DYN-04: ordinary complaints in a row. Name the build-up instead of springing a question about dying.
            return ("這幾天好像累積了不少累和煩。想輕輕確認一下：有沒有哪一刻低落到冒出不想活、或想傷害自己的念頭？"
                    "沒有的話也很好，我們就照你的步調繼續聊。")
        if state.get("risk_evidence") and state["risk_evidence"] not in message:
            return "我有聽到你這一輪的話，先不往深處問；剛才那句讓我還有點擔心。你現在有沒有不想活了，或傷害自己的念頭？"
        # No echo of the student's whole sentence (2026-10-23 live test: 「你說『我想打老師』，我有認真聽」).
        return ("我有認真聽你剛才說的。" + ("現在很晚了，我還是想確認一下，" if night else "想先確認一下，")
                + f"{who}最近有沒有不想活了，或傷害自己的念頭？")
    first = state.get("safety_turns", 1) <= 1 or state.get("fresh_safety")
    privacy = PRIVACY_LIMIT if state.get("privacy_concern") else ""
    if re.search(r"(?:打了|撥了|打通|接通|打給).{0,8}(?:119|110|113|1925)|(?:119|110|113|1925).{0,6}(?:打了|接通|打通)", message):
        return "謝謝你打了電話。若已接通，先照接線人員的引導做，不用急著回這裡；我會在這裡。"
    if company := re.search(r"(媽媽|爸爸|家人|老師|朋友|大人).{0,8}(?:在旁邊|在身邊|陪著|陪我|過來了)", message):
        return (f"太好了，{company.group(1)}陪著你。先讓他知道前面提到的安全狀況，一起確認需要的協助；不用重講整段。"
                "若已受傷或有立即危險，請直接打 119 或 110；1925 也可以找人談。")
    if action == "digital_safety":
        return _digital_reply(message, state, first)
    if action == "child_protection":
        return _protection_reply(message, state, first) + privacy
    if action == "violence_safety" and re.search(WANTS_TO_HURT, message) and not other:
        # The student wants to hurt someone: cool down and step away, not 「保持距離、不要上前制止」.
        if not first:
            return "我還在。先離開那個人和那個地方，等身體的火降下來再決定；若有人可能立刻受傷，請直接打 110。" + privacy
        return ("聽得出來你真的氣炸了。先讓自己離開那個人和那個地方，慢慢吐幾口氣，等身體的火降下來再決定要怎麼做；"
                "動手會讓你自己也受傷或惹上麻煩。覺得快控制不住時，可以先打 1925 找人談，或找一位信任的大人陪你；"
                "若有人可能立刻受傷，請打 110。" + privacy + "現在你身邊有可以陪你的人嗎？")
    if action == "violence_safety":
        if not first:
            return "我還在。先和可能發生衝突的人保持距離；若有人可能立刻受傷，請直接打 110，有人受傷請打 119。" + privacy
        return ("先和可能發生衝突的人保持距離，不要靠近武器或上前制止。若有人可能立刻受傷，請直接打 110；有人受傷需急救請打 119，同時找可信任大人加入。"
                + privacy + "現在能到一個與衝突分開的安全地方嗎？")
    if other:
        # SOC-05: concrete steps for a friend in danger, plus care for the student who is holding it.
        urgent = ("對方可能已經吞藥或正在危險中，請現在就打 119，或馬上請身邊的大人幫忙打；"
                  if state.get("immediate_danger") == "imminent" else "")
        secret = "對方要你保密，但生命安全比保密更重要，告訴大人不是背叛。" if re.search(SECRECY_ASKED, message) else ""
        if not first:
            return (urgent + "你還在擔心對方，我也在。" + secret + "若對方已經行動或聯絡不到，請直接打 119 或 110，或請大人幫忙；"
                    "1925 也可以陪你想怎麼幫忙。" + _unasked(state, "現在有大人能聯繫或到對方身邊嗎？"))
        return (urgent + "你是在擔心對方，我不會把對方的念頭當成你的。" + secret
                + "先找可信任的大人一起確認對方安全，不用獨自承擔；若對方已經行動或可能立刻受傷，請直接打 119 或 110。"
                + "遇到這種事會害怕很正常，1925 也可以陪你討論怎麼幫忙。" + _unasked(state, "現在有大人能聯繫或到對方身邊嗎？"))
    if state.get("risk_level") == "red":
        if first:
            return ("謝謝你告訴我。現在先請可信任的大人到身邊；若已受傷、吃了藥或正要行動，請立即打 119，有人威脅安全可打 110，不要等這裡回覆。"
                    + privacy + "1925 二十四小時都有人接，你也可以繼續說。" + _unasked(state, COMPANY_QUESTION))
        return ("我還在。若已受傷、吃了藥或正要行動，請現在打 119，或請身邊的大人幫忙打。" + privacy
                + (_unasked(state, COMPANY_QUESTION) or "1925 二十四小時都有人接，我也會在這裡。"))
    # Means and timing only after the thoughts are confirmed; otherwise ask about the thoughts first.
    question = (_unasked(state, MEANS_QUESTION, COMPANY_QUESTION) if state.get("ideation_confirmed")
                else _unasked(state, THOUGHTS_QUESTION, COMPANY_QUESTION))
    if first:
        return ("謝謝你願意跟我說這麼重的事。" + question + "如果已經受傷、吃了藥或正要行動，請現在打 119 或 110；"
                "想找人談可以打 1925，二十四小時都有人接。" + privacy + "我會在這裡，你也可以繼續說。")
    # 「我可以跟誰說？」 in safety mode deserves an answer, not only the standing reminder.
    who = ("可以先找一位你信任的大人，例如導師、輔導老師或家人；也可以打 1925，和專人談談現在的感受。"
           if re.search(r"跟誰|找誰|可以找|能找|誰可以", message) else "")
    return ("我還在，也記得你剛才說的。" + who + privacy + question
            + "需要的時候，119、110 和 1925 一直都在，頁面上的求助資訊也隨時可以打開。")


def _protection_reply(message, state, first):
    """Abuse (113, 24 h) or physical bullying (school staff); opens with 「這不是你的錯」, not doubt."""
    peer = state.get("risk_cue") == "peer"
    secret = ("你怕說出來會更糟，這個擔心很合理。我不能答應完全不讓任何人知道，但找誰、怎麼說，可以先和"
              + (" 你信任的老師" if peer else " 113 或你信任的老師") + "一起想，把你的安全排在前面。"
              if re.search(SECRECY_ASKED, message) else "")
    if state.get("risk_level") == "red" and not peer:
        return ("如果他現在就在附近、你覺得危險，先到有其他人在或能鎖門的地方，能打的話現在就打 110；受傷了打 119。"
                + secret + "113 保護專線二十四小時都有人接。")
    if not first:
        return ("我還在。" + secret
                + ("如果又被堵或被打，請打 110，也告訴導師、輔導老師或學務處。" if peer
                   else "如果他現在在身邊、你覺得危險，請打 110；113 保護專線二十四小時都可以打。")
                + _unasked(state, "現在你身邊安全嗎？" if peer else "現在傷害你的人還在身邊嗎？"))
    if peer:
        return ("謝謝你說出來，被堵、被打不是你的錯。先離開那群人，到有大人在的地方；可以找導師、輔導老師或學務處，學校有責任處理這件事。"
                + secret + "如果正在被打或被威脅，請打 110；受傷了打 119。" + _unasked(state, "現在你身邊安全嗎？"))
    return ("謝謝你說出來，這不是你的錯。如果傷害你的人現在還在身邊、你覺得危險，請打 110；受傷了打 119。"
            "113 保護專線二十四小時都有人接，可以先跟專人討論怎麼做比較安全。" + secret
            + "能安全離開的話，先到有其他人在的地方，找不會傷害你的可信任大人；不要獨自和對方對質。"
            + _unasked(state, "現在傷害你的人還在身邊嗎？"))


def _digital_reply(message, state, first):
    """Leaked images vs a threat to post them; both: not your fault, keep evidence, 113, never send images here."""
    leaked = state.get("risk_cue") == "leaked"
    if not first:
        deadline = ("對方給的期限是他製造的壓力，不是你一定要做到的事。"
                    if not leaked and re.search(r"今晚|今天|明天|期限|不然|幾點", message) else "")
        return ("我還在。" + deadline + "先不要補傳照片或付錢，保留證據、找可信任的大人一起處理；113 保護專線二十四小時都可以打。"
                + _unasked(state, "現在有可以陪你一起處理的大人嗎？"))
    if leaked:
        return ("這不是你的錯，錯的是散布照片的人。先在安全的情況下截圖留下證據（網址、帳號、時間），找可信任的大人一起處理；"
                "可以向平台檢舉下架，也可以向衛福部的性影像處理中心申請協助，或打 113 保護專線（二十四小時）討論怎麼做。不用把照片傳給我。"
                "如果有人威脅你的人身安全，請打 110。" + _unasked(state, "現在有可以陪你一起處理的大人嗎？"))
    return ("這不是你的錯，錯的是威脅你的人。先不要付錢、補傳照片或獨自赴約；在安全的情況下保留威脅訊息和帳號，找可信任的大人一起處理，"
            "也可以打 113 保護專線（二十四小時）或向衛福部的性影像處理中心求助。不用把照片傳給我。"
            "如果對方正在威脅你的人身安全，請打 110。" + _unasked(state, "你現在和對方在同一個地方嗎？"))


def local_reply(message, state):
    if state["safety_check_required"]:
        return safety_reply(message, state)
    if state["current_goal"] == "configure_role":
        return role_acknowledgement(state)
    if state["current_goal"] == "clarify_identity":
        return identity_reply(message, state)
    attempts = detect_injection(message)
    notice = ("網站的內部設定和提示詞不會提供喔。" if "reveal" in attempts
              else "這些設定沒辦法從對話裡更改，我還是用原本的方式陪你。" if attempts else "")
    return _styled(notice + role_notice(state) + _local_reply(state.get("dialogue_content") or message, state),
                   state, message)


def identity_reply(message, state):
    """Honest answer about being an AI; mentions a role only when the student set one, and never a model name."""
    role = (state.get("companion_role") or {}).get("description")
    text = "我是 AI 陪伴夥伴，不是真人" + ("，可以用你描述的角色語氣陪你聊，但不是那位真人" if role else "，也不會假裝是真人") + "。"
    if re.search(r"模型|ChatGPT|GPT|Gemini|Claude|誰(?:做|開發|寫)|哪家", message, re.I):
        text += "背後用哪一套 AI 由網站管理者設定，你不用選，也不影響我陪你的方式。"
    if re.search(r"記(?:得|住)|會不會忘", message):
        text += "這次聊過的內容我會記得，最後一次使用後 24 小時自動失效。"
    return text + ("你可以隨時修改或取消這個角色設定。" if role else "想聊什麼都可以接著說。")


def _recent_replies(state, turns=3):
    """The assistant's last few replies (for avoiding repeats)."""
    replies = [t.get("text", "") for t in state.get("history", []) if t.get("role") == "assistant"][-turns:]
    return replies + [state.get("last_reply", "")]


def _fresh(state, options):
    """First wording not used in the last few replies (2026-10-23 simulation: one sentence was 48% of replies)."""
    recent = "".join(_recent_replies(state))
    return next((o for o in options if o not in recent), options[-1])


LISTENING = ("這件事我有在聽，不用急著一次說清楚。", "我在，慢慢說就好。", "嗯，我有在聽，想到哪裡說到哪裡都可以。",
             "我還在這裡，你可以接著說。")
STAYING = ("我有注意到你這一輪想表達的重點。先不用急著找結論，我們可以留在這裡。",
           "嗯，我在聽。不用急著整理成答案。", "這些話我有接到，先放在這裡也沒關係。")
FAREWELL_STUDENT = r"掰掰|拜拜|bye|晚安|先這樣|先走了|下次(?:再)?聊|先去(?:睡|洗澡|吃飯|寫作業)|我要去(?:睡|洗澡|吃飯)|我先睡了"


def _styled(text, state, message):
    """Apply the student's reply style to a local reply (safety replies never pass through here)."""
    style = state.get("effective_style", "warm")
    if style == "listen_only":
        sentences = [s for s in re.findall(r"[^。！？!?\n]+[。！？!?]?", text) if not re.search(r"[？?]", s)]
        return "".join(sentences[:2]) or "我在這裡，聽你說。"
    if style == "lively" and positive_context(message, state):
        return text.replace("聽到你有這樣的好心情，我也覺得很不錯。", "太讚了吧，聽得我也跟著開心起來！")
    return text


def _rational_plan(message, state=None):
    """Rational style: 1. points 2. sticking point 3. one optional step, built from the student's own words.
    Facts from the last few turns count too (2026-10-23 simulation: 「1. 重點整理：這件事。」)."""
    earlier = [t.get("text", "") for t in (state or {}).get("history", []) if t.get("role") == "user"][-4:]
    topic = _first(TOPIC_PATTERN, message) or next((_first(TOPIC_PATTERN, t) for t in reversed(earlier)
                                                     if _first(TOPIC_PATTERN, t)), "") or "這件事"
    message = "，".join(earlier + [message])
    facts = [f for f in (
        _first(r"(?:只剩|剩下?)[一二三四五六七八九十兩百\d]+(?:天|週|個禮拜)", message),
        _first(r"(?:翻|熬|拖)到凌晨[一二三四五六\d]點(?:才睡著?)?|睡不好|睡不著|失眠", message),
        _first(r"上課[^，。！？]{0,4}(?:恍神|分心|聽不懂)[^，。！？]{0,4}", message),
        _first(r"(?:爸媽|家人|老師)[^，。！？]{0,6}(?:逼問|一直問|催|唸|比較)[^，。！？]{0,8}", message),
    ) if f]
    sleep = re.search(r"睡|凌晨|失眠", "".join(facts))
    return ("1. 重點整理：" + topic + ("，" + "、".join(facts) if facts else "") + "。\n"
            "2. 目前卡點：時間和體力都有限，外面又有壓力，很難一次顧到全部。\n"
            "3. 下一步：先挑最要緊的一件事，排一個 25 分鐘的小段落開始"
            + ("，睡前留一點時間不碰課本" if sleep else "") + "；要不要這樣試，由你決定。")


def _first(pattern, text):
    match = re.search(pattern, text)
    return match.group(0) if match else ""


def is_positive_only(message):
    """開心／期待且沒有困擾字詞：回應那份好心情，不替對方補上壓力。"""
    message = re.sub(HAPPY_SLEEPLESS, "開心", message)  # 「開心到睡不著」 is good news, not insomnia
    # Someone else's quoted words are not the student's mood: 「『你們原住民有加分很爽齁』，我超不爽」.
    message = re.sub(QUOTED, "", message)
    return bool(re.search(POSITIVE_PATTERN, message) and not re.search(NEGATED_POSITIVE, message)
                and not re.search(NEGATIVE_PATTERN, message))


def positive_context(message, state=None):
    """本輪是好消息，或前文只分享過好消息而本輪沒有困擾字詞（例如「上次我還贏了他一局」）。"""
    if is_positive_only(message):
        return True
    # A question or a request for help is not good news, even right after a happy turn.
    if re.search(r"[？?]|怎麼辦|怎麼規劃|該怎麼|如何|幫我", message):
        return False
    users = [t["text"] for t in (state or {}).get("history", []) if t.get("role") == "user"]
    return (not re.search(NEGATIVE_PATTERN, message) and any(is_positive_only(t) for t in users)
            and not any(re.search(NEGATIVE_PATTERN, t) for t in users))


def _natural_reflection(message, state=None):
    """短小、基於本輪明確文字的離線回應；只重用學生說過的關鍵詞，不是新的語意推論或風險判斷。"""
    state = state or {}
    if re.search(r"(?:我想|想走|想讀|想選).{0,10}(?:設計|科系)", message) and re.search(r"家裡|家人|爸媽|父母|爸爸|媽媽", message):
        return "你想走自己喜歡的方向，家裡卻有不同的想法，這種拉扯不容易。"
    if re.search(r"(?:希望|只想).{0,24}(?:聽|講完|說完)", message):
        return "你希望自己的想法能先被好好聽見，不必馬上得到同意。"
    if re.search(r"(?:想|希望).{0,25}(?:自己做決定|當小孩|被尊重|自主)", message):
        return "你在意的不只是這件事，也希望自己的決定能被認真對待。"
    if "告白被打槍" in message or "告白被拒絕" in message:
        return "告白沒有得到期待的回應，心裡可能有些失落。"
    if re.search(r"不想講|不想說|不要問", message):
        return "好，這一刻先不用多說。"
    topic = _first(TOPIC_PATTERN, message)
    if avoid := _first(r"不敢[^，,。！!？?；;\s]{1,10}", message):
        others = _first(r"同學|朋友|別人|大家", message)
        return avoid + ("，又擔心" + others + "的眼光" if others else "") + "，這樣的顧慮很真實。"
    if is_positive_only(message):
        feel = _first(DEGREE + "(?:" + POSITIVE_PATTERN + ")", message)
        activity = _first(ACTIVITY_PATTERN, message)
        return ("想到" + activity + "就" if activity else "") + feel + "！聽到你有這樣的好心情，我也覺得很不錯。"
    if positive_context(message, state):
        return "這段聽起來很有意思，我在聽。"
    if body := _first(BODY_PATTERN, re.sub(HAPPY_SLEEPLESS, "", message)):
        return body + "很不舒服，身體的感覺也值得被在意，我先聽你說。"
    # 「沒有很開心」must not be reflected back as 「很開心」.
    if feel := _first(NEGATED_POSITIVE, message) or _first(DEGREE + "(?:" + FEELING_PATTERN + ")", message):
        core = feel if re.search(NEGATED_POSITIVE, feel) else _first(FEELING_PATTERN, feel)
        if not topic:
            # A short feeling-only follow-up keeps the earlier event the student named.
            old_event = state.get("event_summary", "").split(" ｜ ")[0]
            recalled = _first(TOPIC_PATTERN, old_event) if old_event != message[:240] else ""
            if recalled:
                return recalled + "的事還在心上，" + core + "的感覺也還在，不用急著讓它消失。"
            return feel + "的時候，不用急著說清楚原因，我先聽著。"
        contrast = _first(r"(?:但是?|不過|可是)[^，,。！!？?；;]{1,14}", message)
        contrast = re.sub(r"^(?:但是?|不過|可是)", "", contrast).replace("我", "你")
        return topic + "的事讓你" + feel + ("，不過你也說" + contrast if contrast else "") + "。"
    if topic:
        return topic + "的事，你可以慢慢說，我在聽。"
    return _fresh(state, LISTENING)


def _local_reply(message, state):
    goal = state["current_goal"]
    echo = _natural_reflection(message, state)
    if goal == "respect_boundary":
        return "好，我不追問，也不用現在把事情弄懂。想先停一下，或換個話題，都可以。" if state["boundary_active"] else "沒關係，我們不用現在弄懂。你不用急著整理好才說，也可以先停一下。"
    if goal == "stabilize":
        return echo + "現在先不用整理原因，也不急著做決定。我先聽，這輪不再加問題。"
    if goal == "establish_safety":
        specific = ("系統不會通知你的家人。" if re.search(r"爸|媽|家人", message) else "")
        if re.search(r"刪|關掉|錄|記錄|紀錄|保存|存", message):
            specific += "對話會暫存在這個網站，最後一次使用後 24 小時自動失效；目前沒有手動刪除的按鈕。"
        return (specific + "你在意誰會知道這些話，這點需要先說清楚。這個網站會暫存對話與整理，雲端 AI 啟用時也會收到對話文字；"
                "一般情況下，要你同意分享，摘要和這次的對話紀錄才會進工作臺；如果你說的內容可能有安全危險，系統會把必要的安全資訊（不含你的暱稱和聯絡方式）送到真人工作臺，讓受過訓練的人優先查看。"
                "目前沒有自動通知學校。我不能保證絕對保密，有立即危險時仍需要真人協助。")
    if state["safety_denied"]:
        # The review level stays for a human; the student gets the conversation back, with the door left open.
        door = "之後如果哪天真的冒出這種念頭，隨時可以跟我說，1925 二十四小時都有人接。"
        if re.search(CLARIFIED, message) or is_positive_only(message):
            # The student clarified a figure of speech; return to the light conversation they were having.
            return "好，了解，剛剛只是誇張的形容。" + (echo if is_positive_only(message) else "那就照你的節奏聊就好。") + door
        return ("好，謝謝你老實回答我，我不會一直追問。" + door +
                ("你說覺得自己沒用，那份自責還是值得被聽見；一件事的結果不能代表你整個人的價值。" if re.search(r"沒用|超廢|沒人要", message)
                 else "剛才那份不好受仍可以繼續說。"))
    if state.get("corrections") and state["corrections"][-1] == message[:240]:
        return echo + "剛才是我沒有聽準，我先收回那個解讀，照你現在說的來。"
    if goal == "respond_to_reaction":
        # Without the model we cannot re-explain the last sentence itself; own it and hand interpretation back.
        if state.get("reaction") == "ask":
            return "我剛剛可能說得太快了。我的意思只是先聽你說，不急著下結論；如果聽起來怪怪的，可以直接跟我說。"
        return "你好像不太確定我剛剛說的。我也可能沒聽準，有說錯的地方可以直接告訴我，照你的感覺為主。"
    if re.search(r"活著的意義|人生.*意義|生命.*意義", message):
        return echo + "活著的意義未必只有一個答案，也不一定要靠成績或成就來證明。現在還沒找到，也不用急著替自己下結論。"
    if goal == "support_choice" and state.get("effective_style") == "rational":
        return _rational_plan(message, state)
    if len(message) <= 25 and re.search(FAREWELL_STUDENT, message, re.I):
        return "好，謝謝你今天願意聊。想再說的時候隨時回來" + ("，晚安。" if re.search(r"晚安|睡", message) else "。")
    if goal == "support_choice":
        # A concrete, reversible communication step after implicit help-seeking.
        context = message + " ｜ " + state.get("event_summary", "") + " ｜ " + state.get("expectation_summary", "")
        if re.search(r"怎麼.{0,20}(?:說|講|談)|(?:不知|不會).{0,20}(?:溝通|開口)|(?:溝通|開口).{0,20}(?:吵|衝突)", message) and re.search(r"家裡|家人|爸媽|爸爸|媽媽|父母|我爸|我媽", context):
            if re.search(r"設計|科系|升學|選校|選系|職涯|工作|就業", context):
                return "你想讓家人先聽你把想法說完，也不希望每次都吵起來。可以挑比較平靜的時候試一句：『我知道你們希望我選比較穩定的方向，我也有認真想過。可以先讓我把想法說完，再一起討論嗎？』你可以改成自己的說法，不必一次說服他們。"
            return "你想跟家人好好談，又不希望一開口就吵起來。可以先找個比較平靜的時候說：『我想先把自己的想法說完，再聽聽你們的看法，好嗎？』要不要用這句，由你決定。"
        if state.get("known_expectation") or state.get("known_yearning"):
            need = state.get("yearning_summary") or state.get("expectation_summary")
            return "你已經提到自己很在意什麼了。可以先寫下一句最想說的話，或先練習怎麼開口；不用急著真的去說。"
        return echo + "可以先挑一個你做得到的小步驟，例如寫下一句最想表達的話；要不要使用由你決定。"
    # 「分組都沒人要跟我」 is about being left out, not self-blame.
    if state.get("known_self") and re.search(r"沒用|超廢|很廢|沒人要(?!跟)|很爛|好爛|不夠好|不值得|失敗|沒有人會喜歡", message):
        return echo + "這件事好像讓你把很多責怪都放到自己身上。一件事的結果，和你整個人的價值，是兩件不同的事；現在不用急著逼自己相信正面的話。"
    if state.get("meta_feeling_summary") == message[:240]:
        return echo + "除了原來的不好受，好像還多了對自己有這種感受的責怪。這兩份感受都可以先放在這裡，不用立刻改掉。"
    if state.get("coping_summary") == message[:240]:
        return echo + "表面上那個回應，和心裡的滋味可能不一樣。我不急著替你猜當時為什麼這樣做。"
    if goal == "integrate":
        need = state.get("yearning_summary", "").split(" ｜ ")[-1]
        if need and need == message[:240]:
            wish = _first(PATTERNS["yearning"], message).replace("我", "你")
            if wish:
                return (("能" if wish.startswith("被") else "") + wish
                        + "，對你來說很重要，你已經把它說出來了。先停在這裡也可以，不用馬上想下一步。")
            return "你已經說出自己很在意的事了。先停在這裡也可以，不用馬上想下一步。"
        return _fresh(state, STAYING)
    if state["uncertainty_streak"]:
        return "沒關係，有時候真的很難一下講清楚。我們先不用替感受取名字。"
    if message.strip().strip("。！!，, ") in ("好", "好喔", "好啊", "好吧", "謝謝", "沒有"):
        return "我有聽到，這輪先不替這個回應加上別的意思。你不用急著接話。"
    if re.fullmatch(r"\d", message.strip()):
        previous = state.get("last_reply", "")
        options = dict(re.findall(r"(?:^|[\n，；。])\s*(\d)[.、：:]\s*([^。；\n？?]{1,18})", previous))
        if message.strip() in options:
            return f"我接到你選的「{quote(options[message.strip()])}」，先照這個意思往下聊。你可以隨時換想法。"
        return "我看到這個數字，還不確定你指哪個選項，不會把它當量表分數。" + ("你指的是哪個選項？" if state["ask_question"] else "")
    body = ""
    if "告白被打槍" in message:
        body = "如果我理解錯了，你可以直接告訴我。"
    elif "只把我當朋友" in message:
        body = "現在不用急著決定以後要怎麼相處。"
    elif re.search(FEELING_PATTERN, message):
        body = ""
    # Retain early event when a later message only supplies a feeling.
    old_event = state.get("event_summary", "").split(" ｜ ")[0]
    if old_event and old_event != message[:240] and re.search(r"心情不好|難過", message) and len(message) < 20:
        body = "你可以只說現在最想談的部分。"
    questions = {
        "clarify_event": "哪一件事讓你最在意？",
        # Open, not leading: 「比較像失望」 chose the answer for the student (counselling review).
        "explore_feeling": "那時候你心裡是什麼感覺？想說再說。",
        "explore_perception": "這件事讓你怎麼看自己或對方？",
        "explore_expectation": "你原本希望對方怎麼回應你？",
        "explore_yearning": "如果對方願意這樣做，對你最重要的是什麼？",
    }
    ask = questions.get(goal, "") if state["ask_question"] else ""
    if ask and positive_context(message, state):
        ask = "想多說說這件事嗎？"  # Good news is not a cue to explore perceptions or problems.
    if ask and any(ask in reply for reply in _recent_replies(state)):
        ask = ""  # Not the same question again within a few turns (A, B, A rotation included).
    return echo + body + ask


FEELING_PATTERN = r"心情不好|難過|生氣|累|委屈|心慌|慌|不敢|害怕|怕|開心|胃痛|焦慮|緊張|失望|低落|孤單|煩"
POSITIVE_PATTERN = r"開心|高興|快樂|期待|興奮|好玩|滿足|幸福|感動|好爽|超爽|很爽|太棒|好棒"
NEGATED_POSITIVE = r"(?:不|沒有?|沒那麼|不太|一點也不)(?:很|太|那麼)?(?:開心|高興|快樂|期待|興奮|好玩)"
NEGATIVE_PATTERN = (r"心情不好|難過|生氣|累|委屈|慌|不敢|怕|痛|煩|焦慮|擔心|壓力|失望|緊張|低落|孤單|哭|討厭"
                    r"|睡不好|睡不著|失眠|吵架|被罵|不想|撐不|受不了|不爽|袂爽|歧視|被笑|嘲笑")
QUOTED = r"「[^」]*」|『[^』]*』|“[^”]*”"
ACTIVITY_PATTERN = r"羽球|籃球|桌球|排球|棒球|比賽|表演|旅行|出去玩|生日|畢業旅行|園遊會"
BODY_PATTERN = r"胃痛|頭痛|肚子痛|胸口悶|身體不舒服|睡不好|睡不著|失眠"
HAPPY_SLEEPLESS = r"(?:開心|興奮|期待|高興)(?:到|得)睡不著"
DEGREE = r"(?:最近|還是|一直|真的|有點|有一點|很|好|超|非常|蠻|滿|太)*"
TOPIC_PATTERN = (r"告白被打槍|告白被拒絕|告白|段考|期中考|期末考|模擬考|會考|學測|統測|考試|成績|作業|功課|分組|社團|輔導室"
                 r"|數學|英文|國文|理化|物理|化學|自然|社會|補習|志願|設計|音樂|畫畫|轉學|宿舍|部落|手機|遊戲|抽卡"
                 r"|同學|朋友|老師|爸媽|爸爸|媽媽|家人|家裡|哥哥|姊姊|姐姐|弟弟|妹妹|喜歡的人|分手|吵架|升學|科系"
                 r"|羽球|籃球|冠軍|比賽|表演")
# Psychological states a model may add on its own; flagged only when the student shared good news.
INVENTED_DISTRESS = r"壓力|緊繃|喘息|不好受|難受|委屈|沉重|焦慮|不容易|辛苦|煩惱|擔心|累積|撐|逃離|放鬆一下|承接|內在|負荷|課題"
EMBEDDED_QUESTION = (r"(?:不知道|不曉得|想知道|不確定|再來看|來看看|看看要|決定|想想|討論|規劃)[^。！？!?\n]{0,6}"
                     r"(?:怎麼|如何|什麼|哪[個一裡種]|是不是|有沒有|是否)")
# Proposal ethics 2: no medication or medical-treatment advice (what to take, how much, when to stop).
MEDICAL_ADVICE = (r"(?:建議|可以|試試|不妨|記得|最好|先)(?:你)?.{0,6}(?:吃|服用|吞|加量|減量|停掉|停用|戒掉).{0,8}"
                  r"(?:藥|安眠藥|褪黑激素|抗憂鬱|鎮定劑|止痛藥|保健食品)"
                  # A dose is a number tied to a medicine; 「咖啡因每天不超過 100 毫克」 (a cited guideline) is not.
                  r"|(?:吃|服用|吞)\s*(?:\d+|[一兩二三四五半])\s*(?:顆|粒|錠)|\d+\s*(?:毫克|mg|顆|粒|錠)\s*(?:的)?(?:藥|安眠藥|褪黑激素|鎮定劑|止痛藥)"
                  r"|(?:藥|安眠藥|褪黑激素|鎮定劑|止痛藥).{0,6}\d+\s*(?:毫克|mg|顆|粒|錠)"
                  r"|(?:自己)?(?:停藥|減藥|加藥)(?:看看|試試|也可以|沒關係)")
OVERPSYCHOLOGIZING = r"喘息空間|緊繃感|內在負荷|承接(?:情緒|你的情緒)|生命課題|內在小孩|療癒自己"


RATIONAL_LINES = re.compile(r"1[.．、]\s*重點整理[:：].+?2[.．、]\s*目前卡點[:：].+?3[.．、]\s*下一步[:：]\s*\S", re.S)


CHEERFUL_EMOJI = r"(?:🥰|😍|🤩|😆|😂|🤣|🎉|🥳|😁|😄|😃|😘|💕|💖|💗)️?"
# Cute spellings of 吧 seen in live Gemini output: 「心情多少會受影響包 🥰」, 「好ㄅ」.
# 包 is only rewritten right before an emoji or ～, and never after the first character of a real word (麵包、紅包…).
CUTESY_BA = (r"(?<=[一-鿿])(?:(?<![麵紅書錢背荷皮肉菜包打帶提拿買豆湯煎個這那手錢錢])包"
             r"(?=\s*(?:[\U0001F300-\U0001FAFF☀-➿]|[～~]))|ㄅ)")


def tidy_surface(reply, message, state=None):
    """Repair surface slips in a model reply instead of discarding it: 「包／ㄅ」 written for 「吧」, and
    party or heart emoji when the student is not sharing good news (「跟朋友有小摩擦」 → 🥰)."""
    text = re.sub(CUTESY_BA, "吧", reply.translate(SIMPLIFIED))
    if not positive_context(message, state) and re.search(CHEERFUL_EMOJI, text):
        text = re.sub(r"\s*(?:" + CHEERFUL_EMOJI + r")+\s*", "\0", text)
        # An emoji inside a sentence leaves a comma; a full stop there read like a typo (「這樣。真的」).
        text = re.sub(r"(?<=[一-鿿])\0(?=[一-鿿])", "，", text).replace("\0", "")
    return text.strip()


def drop_trailing_questions(reply, keep=0):
    """Models often append one more question after an otherwise good reply ("…你覺得呢？").
    Remove question sentences at the very end until at most `keep` remain: cutting every question when one was
    allowed left 「…可能已經陪你走了一陣子。」 with nothing to answer (2026-10-23 live test). None if nothing
    substantial would remain: 「抱歉，我剛才誤會了你的意思。」 alone read as a broken reply."""
    sentences = re.findall(r"[^。！？!?\n]+[。！？!?]?\n?", reply)
    while (sentences and re.search(r"[？?]", sentences[-1])
           and sum(bool(re.search(r"[？?]", s)) for s in sentences) > keep):
        sentences.pop()
    kept = "".join(sentences).strip()
    if len(kept) < max(20, len(reply.strip()) // 3):
        return None
    return kept if kept != reply.strip() else None


# Lines that decide for the student what they feel or need (2026-10-23 feedback: replies felt 自以為是).
PRESUMPTUOUS = (r"一定(?:很|是|會|不太|超|非常)|肯定(?:很|是|會)|其實你|你其實|你只是|說穿了|說到底|你要知道|相信我"
                r"|我(?:完全|都|真的)?(?:懂|明白|知道)(?:你|這種|你的感受)|我能理解你的感受|你(?:真正)?需要的是|你缺的是"
                r"|你應該要|你就是太")


# States a reply may pin on the student, and the words that show the student did bring them up
# (2026-10-23 live test: the student never said they were tired, the reply kept saying they were exhausted).
ASSUMED_STATES = (
    (r"疲憊|疲倦|累壞|很累|好累|太累|累了|累積了不少累|辛苦了|撐了|撐著|撐很久|沒電|耗盡|筋疲力盡|身心俱疲",
     r"累|疲|倦|沒力|沒電|撐|辛苦|睏|想睡|熬夜|忙|操|爆肝|好想睡"),
    (r"壓力(?:很大|好大|山大|不小)|壓得|緊繃|喘不過氣",
     r"壓力|壓|緊繃|焦慮|緊張|喘|考|作業|報告|比賽|忙|趕"),
    (r"委屈", r"委屈|不公平|冤|被罵|被誤會|針對|怪我"),
    (r"孤單|寂寞", r"孤單|寂寞|一個人|沒朋友|沒有朋友|沒人|排擠|落單"),
)
TENTATIVE = r"[？?]|會不會|是不是|有沒有|如果|或許|也許|不知道我有沒有"


def assumed_state(reply, state, message):
    """The reply asserts a state (tired, stressed, wronged, lonely) the student never mentioned in this
    conversation. A tentative question about it is allowed; telling them they feel it is not."""
    said = " ".join([message, *(t.get("text", "") for t in (state or {}).get("history", []) if t.get("role") == "user"),
                     *((state or {}).get(stage + "_summary", "") for stage in STAGES)])
    for sentence in re.findall(r"[^。！？!?\n]+[。！？!?]?", re.sub(QUOTED, "", reply or "")):
        if re.search(TENTATIVE, sentence):
            continue
        for pinned, mentioned in ASSUMED_STATES:
            if re.search(pinned, sentence) and not re.search(mentioned, said):
                return True
    return False


# Humility the prompt asks the model to hold, said out loud instead (2026-10-23 live test: 「我不在你家，沒辦法替你下答案」).
DISCLAIMER = r"我(?:又)?不在(?:你家|現場|你身邊|那裡)|我沒辦法替你下(?:答案|結論|定論)|我不能替你下(?:答案|結論)"


def presumptuous(reply):
    return bool(re.search(PRESUMPTUOUS, re.sub(QUOTED, "", reply or "")))


# Simplified characters a model sometimes slips into Traditional Chinese replies. Only characters whose
# Traditional form is unambiguous in this context (no 后/里/发/干 style one-to-many cases).
SIMPLIFIED = str.maketrans({
    "们": "們", "这": "這", "说": "說", "个": "個", "为": "為", "时": "時", "么": "麼", "还": "還", "没": "沒", "会": "會",
    "对": "對", "过": "過", "着": "著", "让": "讓", "样": "樣", "学": "學", "习": "習", "觉": "覺", "吗": "嗎", "开": "開",
    "关": "關", "应": "應", "该": "該", "现": "現", "实": "實", "问": "問", "题": "題", "谢": "謝", "帮": "幫", "难": "難",
    "欢": "歡", "爱": "愛", "听": "聽", "话": "話", "认": "認", "识": "識", "绪": "緒", "压": "壓", "试": "試", "办": "辦",
    "气": "氣", "长": "長", "怀": "懷", "疗": "療", "医": "醫", "师": "師", "动": "動", "运": "運", "边": "邊", "绝": "絕",
    "饭": "飯", "钟": "鐘", "体": "體", "种": "種", "论": "論", "专": "專", "线": "線", "电": "電", "脑": "腦", "机": "機",
    "网": "網", "经": "經", "历": "歷", "红": "紅", "黄": "黃", "发": "發", "头": "頭", "当": "當", "从": "從",
    "间": "間", "们": "們", "给": "給", "请": "請", "谁": "誰", "这": "這", "处": "處", "笔": "筆", "书": "書",
})


def parroting(reply, message):
    """The reply carries the student's own wording back (「聽到你最近心情很低落、提不起勁、覺得空虛」).
    Counselling calls this a simple reflection; strung together it reads as an echo (2026-10-23 live test).
    True when a run of 8+ of the student's characters reappears, or 40% of their two-character phrases do."""
    plain = lambda text: re.sub(r"[^㐀-鿿A-Za-z0-9]", "", re.sub(QUOTED, "", text or ""))
    said, answer = plain(message), plain(reply)
    if len(said) < 8:
        return False
    if any(said[i:i + 8] in answer for i in range(len(said) - 7)):
        return True
    grams = {said[i:i + 2] for i in range(len(said) - 1)}
    return len(said) >= 12 and sum(g in answer for g in grams) / len(grams) >= 0.4


def response_violations(reply, state, message="", offer=None):
    """Conservative mechanical checks, not a claim of complete semantic validation."""
    issues = []
    if not isinstance(reply, str) or not reply.strip():
        return ["empty"]
    # Quoted user punctuation is not a question asked by the assistant.
    body = re.sub(r"「[^」]*」|『[^』]*』|“[^”]*”", "", reply)
    issues.extend(relationship_violations(body))
    budget = state["max_questions"]
    questions = re.findall(r"[^。！？!?\n]*[？?]", body)
    # 「你不知道該怎麼規劃」「再來看怎麼安排」are statements, not hidden questions to the student.
    statements = re.sub(EMBEDDED_QUESTION, "", body)
    interrogatives = re.findall(r"(?:怎麼|如何|什麼|哪[個一裡種]|是不是|有沒有|是否|願不願意|能不能|可不可以|為什麼)", statements)
    if len(questions) > budget or (budget == 0 and interrogatives) or (budget == 1 and len(interrogatives) > 1):
        issues.append("questions")
    sentences = re.findall(r"[^。！？!?\n]+[。！？!?]?", body)
    style = state.get("effective_style", "warm")
    max_sentences, max_chars = ((3, 200) if offer else (2, 120) if style == "listen_only"
                                else (7, 360) if style == "rational" else (4, 280))
    if len(sentences) > max_sentences or len(reply) > max_chars:
        issues.append("length")
    # Green-level chats never get counselling jargon the student did not use.
    if state.get("risk_level", "green") == "green" and [w for w in re.findall(OVERPSYCHOLOGIZING, body) if w not in message]:
        issues.append("overpsychologizing")
    if re.search(r"你其實就是|你真正(?:想要|需要)的|因為你小時候|你是在投射|你(?:就是|患有|得了).*(?:憂鬱症|焦慮症)|你很棒|你超棒|往好處想|你要相信自己|至少你還有|一切都會好起來|根據薩提爾|你的核心需求|冰山層次", body):
        issues.append("interpretation")
    # Context consistency: good news gets a matching response, not an assumed hidden strain.
    if message and positive_context(message, state):
        invented = [w for w in re.findall(INVENTED_DISTRESS, body) if w not in message]
        if invented:
            issues.append("invented_distress")
    if re.search(r"(?:已經|已|會幫你).{0,5}(?:通知|通報|聯絡)|絕對保密|保證.*(?:保密|沒事)|只有你和我.*(?:知道|看到)", body):
        issues.append("boundary")
    if re.search(MEDICAL_ADVICE, body):
        issues.append("medical_advice")
    if "give_advice" in state["forbidden_actions"] and re.search(r"建議你|你應該|你要先|試著|不如你|你可以(?:先|去|把|找|做|試)|先(?:做|寫|去找|深呼吸|喝水)", body):
        issues.append("premature_advice")
    # If the student has asked for practical help and policy permits it, a pure empathy
    # paraphrase is not enough; use the concrete local fallback instead.
    if state.get("current_goal") == "support_choice" and state.get("advice_request"):
        if not re.search(r"可以先|可以試|可以說|可以寫|可以問|先試|先從|試著|試試|例如|比方說|像這樣|先找|先選|先挑|先把|先說|可以考慮|要不要先", body) \
                and not (style == "rational" and RATIONAL_LINES.search(body)):  # its line 3 is the step
            issues.append("missing_next_step")
    if "continue_drilling" in state["forbidden_actions"] and re.search(r"真正的渴望|背後的原因|這代表什麼|為什麼會|最深處", body):
        issues.append("drilling")
    if re.search(r"你(?:有|想|提到|說).{0,8}(?:自傷|自殺|傷害自己|想死)", body) and not state["safety_check_required"] and not re.search(r"自傷|自殺|傷害自己|想死", message):
        issues.append("invented_risk")
    # Rational style promises three labelled lines when the student asks for a plan.
    if style == "rational" and state.get("current_goal") == "support_choice" and not RATIONAL_LINES.search(body):
        issues.append("rational_structure")
    previous = state.get("last_reply", "")
    if previous and (reply == previous or (len(reply) > 35 and SequenceMatcher(None, reply, previous).ratio() > .92)):
        issues.append("repeat")
    if parroting(body, message):
        issues.append("parroting")
    if presumptuous(body):
        issues.append("presumptuous")
    if assumed_state(body, state, message):
        issues.append("assumed_state")
    if re.search(DISCLAIMER, body):
        issues.append("disclaimer")
    old_questions = re.findall(r"[^。！？!?\n]*[？?]", previous)
    if any(q.strip() in [old.strip() for old in old_questions] for q in questions):
        issues.append("repeated_question")
    return list(dict.fromkeys(issues))
