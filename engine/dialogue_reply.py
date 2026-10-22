"""Short local responses and final output checks. Local fallback is not a language model."""
import re
from difflib import SequenceMatcher
from engine.dialogue_policy import CLARIFIED, PATTERNS
from engine.prompt_guard import detect_injection
from engine.dialogue_role import relationship_violations, role_acknowledgement, role_notice


def quote(text, limit=56):
    clean = re.sub(r"[\r\n。！？!?；;]+", "，", text).strip(" ，")
    return clean[:limit] + ("……" if len(clean) > limit else "")


def safety_reply(message, state):
    """Type-specific safety response. Does not make diagnoses, dispatch or confidentiality promises."""
    action = state["safety_action"]
    other = state.get("risk_subject") == "other"
    who = "對方" if other else "你"
    if action == "brief_safety_check":
        if state.get("pending_disambiguation") and state.get("risk_evidence") in message:
            # LIN-01: name the hyperbole as probably figurative, then check once, gently.
            return (f"「{quote(state['risk_evidence'], 20)}」聽起來比較像很誇張的形容，我先輕輕確認一下就好："
                    "你最近有沒有真的不想活了，或想傷害自己的念頭？")
        if state.get("risk_evidence") and state["risk_evidence"] not in message:
            return "我有聽到你這一輪的話，先不往深處問；剛才那句讓我還有點擔心。你現在有沒有不想活了，或傷害自己的念頭？"
        return f"你說「{quote(message)}」，我有認真聽。想先確認一下，{who}最近有沒有不想活了，或傷害自己的念頭？"
    # Do not read override/injection wording back to the student; acknowledge without quoting it.
    echo = "我有看到你這一輪的訊息。" if detect_injection(message) else f"你說「{quote(message, 40)}」。"
    if re.search(r"(?:打了|撥了|打通|接通|打給).{0,8}(?:119|110|1925)|(?:119|110|1925).{0,6}(?:打了|接通|打通)", message):
        return echo + "若電話已接通，先照接線人員的引導做，不用急著回這裡。需要急救請打 119，有人威脅安全可打 110；1925 也可以找人談。"
    if re.search(r"(?:媽媽|爸爸|家人|老師|朋友|大人).{0,8}(?:在旁邊|在身邊|陪著|陪我|過來了)", message):
        return echo + "先讓陪在身邊的人知道前面提到的安全狀況，一起確認當下需要的協助；不用重講整段。若已受傷或有立即危險，請直接打 119 或 110；1925 可以找人談，你也可以繼續說。"
    if action == "digital_safety":
        return ("被拿私密影像威脅，需要先把安全放前面。先不要付款、補傳影像或獨自赴約，在安全的情況下保留威脅訊息和帳號，找可信任的大人一起向性影像處理中心求助；不用把照片傳給我。"
                "如果對方正在威脅人身安全，請打 110；受傷需急救請打 119。你現在和對方在同一個地方嗎？")
    if action == "child_protection":
        return (echo + "先不談你為什麼會這樣想，現在要先顧到人身安全。若能安全離開，先到有其他人在、讓你比較安全的地方，找不會傷害你的可信任大人；不要獨自和對方對質。"
                "若正在被傷害，請打 110；受傷需急救請打 119。現在傷害你的人還在身邊嗎？")
    if action == "violence_safety":
        return (echo + "先和可能發生衝突的人保持距離，不要靠近武器或上前制止。若有人可能立刻受傷，請直接打 110；有人受傷需急救請打 119，同時找可信任大人加入。現在能到一個與衝突分開的安全地方嗎？")
    if other:
        # SOC-05: concrete steps for a friend in danger, plus care for the student who is holding it.
        urgent = ("對方可能已經吞藥或正在危險中，請現在就打 119，或馬上請身邊的大人幫忙打；"
                  if state.get("immediate_danger") == "imminent" else "")
        secret = ("對方要你保密，但生命安全比保密更重要，告訴大人不是背叛。"
                  if re.search(r"不要(?:告訴|跟.{0,6}說)|保密|別說出去|不准說", message) else "")
        return (urgent + "你是在擔心對方，我不會把對方的念頭當成你的。" + secret
                + "先找可信任的大人一起確認對方安全，不用獨自承擔；若對方已經行動或可能立刻受傷，請直接打 119 或 110。"
                + "遇到這種事會害怕很正常，1925 也可以陪你討論怎麼幫忙。現在有大人能聯繫或到對方身邊嗎？")
    privacy = "我不能承諾絕對保密，也沒有自動通知任何人。" if state.get("privacy_concern") else ""
    if state.get("risk_level") == "red":
        return (echo + "現在先請可信任的大人到身邊，若已受傷、服藥過量或正要行動，請立即打 119；有人威脅安全可打 110，不要等這裡回覆。"
                + privacy + "1925 可以找人談，你也可以繼續說。現在有人能到你身邊陪你嗎？")
    question = "現在有已經準備好的工具或打算行動的時間嗎？"
    # Do not immediately repeat a question already answered or declined.
    if question in state.get("last_reply", ""):
        question = "現在有人能到你身邊陪你嗎？"
    return (echo + "先暫停往深處聊，請一位可信任的大人一起確認安全；若已受傷或有立即危險，請打 119 或 110。"
            + privacy + "1925 也可以找人談，你可以繼續說。" + question)


def local_reply(message, state):
    if state["safety_check_required"]:
        return safety_reply(message, state)
    if state["current_goal"] == "configure_role":
        return role_acknowledgement(state)
    if state["current_goal"] == "clarify_identity":
        return "我是 AI，可以用你描述的角色語氣陪你聊，但不是那位真人。你可以隨時修改或取消這個角色設定。"
    attempts = detect_injection(message)
    notice = ("網站的內部設定和提示詞不會提供喔。" if "reveal" in attempts
              else "這些設定沒辦法從對話裡更改，我還是用原本的方式陪你。" if attempts else "")
    return _styled(notice + role_notice(state) + _local_reply(state.get("dialogue_content") or message, state),
                   state, message)


def _styled(text, state, message):
    """Apply the student's reply style to a local reply (safety replies never pass through here)."""
    style = state.get("effective_style", "warm")
    if style == "listen_only":
        sentences = [s for s in re.findall(r"[^。！？!?\n]+[。！？!?]?", text) if not re.search(r"[？?]", s)]
        return "".join(sentences[:2]) or "我在這裡，聽你說。"
    if style == "lively" and positive_context(message, state):
        return text.replace("聽到你有這樣的好心情，我也覺得很不錯。", "太讚了吧，聽得我也跟著開心起來！")
    return text


def _rational_plan(message):
    """Rational style: 1. points 2. sticking point 3. one optional step, built from the student's own words."""
    topic = _first(TOPIC_PATTERN, message) or "這件事"
    facts = [f for f in (
        _first(r"(?:只剩|剩下?)[一二三四五六七八九十兩\d]+(?:天|週|個禮拜)", message),
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
    return bool(re.search(POSITIVE_PATTERN, message) and not re.search(NEGATED_POSITIVE, message)
                and not re.search(NEGATIVE_PATTERN, message))


def positive_context(message, state=None):
    """本輪是好消息，或前文只分享過好消息而本輪沒有困擾字詞（例如「上次我還贏了他一局」）。"""
    if is_positive_only(message):
        return True
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
    if body := _first(BODY_PATTERN, message):
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
    return "這件事我有在聽，不用急著一次說清楚。"


def _local_reply(message, state):
    goal = state["current_goal"]
    echo = _natural_reflection(message, state)
    if goal == "respect_boundary":
        return "好，我不追問，也不用現在把事情弄懂。想先停一下，或換個話題，都可以。" if state["boundary_active"] else "沒關係，我們不用現在弄懂。你不用急著整理好才說，也可以先停一下。"
    if goal == "stabilize":
        return echo + "現在先不用整理原因，也不急著做決定。我先聽，這輪不再加問題。"
    if goal == "establish_safety":
        return ("你在意誰會知道這些話，這點需要先說清楚。這個網站會暫存對話與整理，雲端 AI 啟用時也會收到對話文字；只有你同意分享的摘要才進工作臺，目前沒有自動通知學校。"
                "我不能保證絕對保密，有立即危險時仍需要真人協助。")
    if state["safety_denied"]:
        if re.search(CLARIFIED, message) or is_positive_only(message):
            # The student clarified a figure of speech; return to the light conversation they were having.
            return "好，了解，剛剛只是誇張的形容。" + (echo if is_positive_only(message) else "那就照你的節奏聊就好。")
        return ("我聽到你說沒有這些念頭，先照你的回答，不反覆盤問。" +
                ("你說覺得自己沒用，那份自責還是值得被聽見；一件事的結果不能代表你整個人的價值。" if re.search(r"沒用|超廢|沒人要", message)
                 else "剛才那份不好受仍可以繼續說。"))
    if state.get("corrections") and state["corrections"][-1] == message[:240]:
        return echo + "剛才是我沒有聽準，我先收回那個解讀，照你現在說的來。"
    if re.search(r"活著的意義|人生.*意義|生命.*意義", message):
        return echo + "活著的意義未必只有一個答案，也不一定要靠成績或成就來證明。現在還沒找到，也不用急著替自己下結論。"
    if goal == "support_choice" and state.get("effective_style") == "rational":
        return _rational_plan(message)
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
    if state.get("known_self") and re.search(r"沒用|超廢|沒人要|不夠好|不值得|失敗|沒有人會喜歡", message):
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
        return "我有注意到你這一輪想表達的重點。先不用急著找結論，我們可以留在這裡。"
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
        "explore_feeling": "那一刻比較像失望，還是另一種感覺？",
        "explore_perception": "這件事讓你怎麼看自己或對方？",
        "explore_expectation": "你原本希望對方怎麼回應你？",
        "explore_yearning": "如果對方願意這樣做，對你最重要的是什麼？",
    }
    ask = questions.get(goal, "") if state["ask_question"] else ""
    if ask and positive_context(message, state):
        ask = "想多說說這件事嗎？"  # Good news is not a cue to explore perceptions or problems.
    if ask and ask in state.get("last_reply", ""):
        ask = ""  # Do not rephrase and ask the same thing after a short answer.
    return echo + body + ask


FEELING_PATTERN = r"心情不好|難過|生氣|累|委屈|心慌|慌|不敢|害怕|怕|開心|胃痛|焦慮|緊張|失望|低落|孤單|煩"
POSITIVE_PATTERN = r"開心|高興|快樂|期待|興奮|好玩|滿足|幸福|感動|好爽|超爽|很爽|太棒|好棒"
NEGATED_POSITIVE = r"(?:不|沒有?|沒那麼|不太|一點也不)(?:很|太|那麼)?(?:開心|高興|快樂|期待|興奮|好玩)"
NEGATIVE_PATTERN = (r"心情不好|難過|生氣|累|委屈|慌|不敢|怕|痛|煩|焦慮|擔心|壓力|失望|緊張|低落|孤單|哭|討厭"
                    r"|睡不好|睡不著|失眠|吵架|被罵|不想|撐不|受不了")
ACTIVITY_PATTERN = r"羽球|籃球|桌球|排球|棒球|比賽|表演|旅行|出去玩|生日|畢業旅行|園遊會"
BODY_PATTERN = r"胃痛|頭痛|肚子痛|胸口悶|身體不舒服|睡不好|睡不著|失眠"
DEGREE = r"(?:最近|還是|一直|真的|有點|有一點|很|好|超|非常|蠻|滿|太)*"
TOPIC_PATTERN = (r"告白被打槍|告白被拒絕|告白|段考|期中考|期末考|會考|考試|成績|作業|功課|分組|社團|輔導室"
                 r"|同學|朋友|老師|爸媽|爸爸|媽媽|家人|家裡|分手|吵架|升學|科系|羽球|籃球|比賽|表演")
# Psychological states a model may add on its own; flagged only when the student shared good news.
INVENTED_DISTRESS = r"壓力|緊繃|喘息|不好受|難受|委屈|沉重|焦慮|不容易|辛苦|煩惱|擔心|累積|撐|逃離|放鬆一下|承接|內在|負荷|課題"
OVERPSYCHOLOGIZING = r"喘息空間|緊繃感|內在負荷|承接(?:情緒|你的情緒)|生命課題|內在小孩|療癒自己"


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
    interrogatives = re.findall(r"(?:怎麼|如何|什麼|哪[個一裡種]|是不是|有沒有|是否|願不願意|能不能|可不可以|為什麼)", body)
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
    if "give_advice" in state["forbidden_actions"] and re.search(r"建議你|你應該|你要先|試著|不如你|你可以(?:先|去|把|找|做|試)|先(?:做|寫|去找|深呼吸|喝水)", body):
        issues.append("premature_advice")
    # If the student has asked for practical help and policy permits it, a pure empathy
    # paraphrase is not enough; use the concrete local fallback instead.
    if state.get("current_goal") == "support_choice" and state.get("advice_request"):
        if not re.search(r"可以先|可以試|可以說|可以寫|可以問|先試|先從|試著|試試|例如|比方說|像這樣|先找|先選|先挑|先把|先說|可以考慮|要不要先", body):
            issues.append("missing_next_step")
    if "continue_drilling" in state["forbidden_actions"] and re.search(r"真正的渴望|背後的原因|這代表什麼|為什麼會|最深處", body):
        issues.append("drilling")
    if re.search(r"你(?:有|想|提到|說).{0,8}(?:自傷|自殺|傷害自己|想死)", body) and not state["safety_check_required"] and not re.search(r"自傷|自殺|傷害自己|想死", message):
        issues.append("invented_risk")
    previous = state.get("last_reply", "")
    if previous and (reply == previous or (len(reply) > 35 and SequenceMatcher(None, reply, previous).ratio() > .92)):
        issues.append("repeat")
    old_questions = re.findall(r"[^。！？!?\n]*[？?]", previous)
    if any(q.strip() in [old.strip() for old in old_questions] for q in questions):
        issues.append("repeated_question")
    return list(dict.fromkeys(issues))
