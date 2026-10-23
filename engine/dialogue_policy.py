"""Satir v1.1 dialogue policy. Rules own decisions; LLM observations are evidence-bound hints.

State is a bounded, server-side conversation aid, not a diagnosis or a clinical score.
Unconfirmed signals and confirmed high-water risk are intentionally separate.
"""
from copy import deepcopy
import re
from engine.dialogue_role import asks_identity, resolve_role
from engine.knowledge import asks_information

POLICY_VERSION = "satir-2026-10-19.2"
WEIGHTS = {"green": 1, "yellow": 2, "orange": 3, "red": 4}
STAGES = ("event", "feeling", "perception", "expectation", "yearning", "self")
RISK_TYPES = ("none", "self_harm", "suicide", "abuse", "violence", "digital_sexual_violence", "other")
REPLY_STYLES = ("warm", "lively", "humor", "rational", "listen_only")
# Short reactions to the assistant's last sentence (punctuation already removed by compact()).
REACTION_DOUBT = r"真的(?:嗎|假的|喔|哦)?|真假|是喔|是哦|是嗎|有嗎|會嗎|你確定(?:嗎)?|是這樣嗎|蛤|騙人|最好是"
REACTION_ASK = r"為什麼|為啥|怎麼說|什麼意思|啥意思|然後呢|所以呢|例如呢|比如說呢?"
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
    "self": (r"我.*(?:很沒用|超廢|很廢|沒人要(?!跟)|不夠好|不值得|什麼都做不好|很失敗|很爛|好爛|很差勁|一無是處)"
             r"|沒有人會喜歡我|我是不是.*(?:沒用|不好)"),
}


# 將「我不知道怎麼跟他們講」這類帶有行動對象的困難，辨識成隱含求助。
# 單純「不知道怎麼說心情／我不知道」不算求方法，仍依意願傾聽。
_EXPLICIT_HELP = re.compile(
    r"怎麼辦|怎麼做|可以怎樣|該怎麼|該如何|要如何|有什麼辦法|有沒有辦法|"
    r"給我.{0,8}建議|幫我.{0,8}(?:想|寫)|想了解.{0,8}資源|可以找誰|想看.{0,8}資源|"
    r"(?:教我|幫我看看).{0,12}(?:怎麼|如何)|(?:^|[？?])(?:怎麼|如何)(?:跟|和|向|對).{0,12}(?:說|講|談|開口|溝通|表達)"
    # 2026-10-23 simulation: these direct questions were answered with 「那一刻比較像失望…」.
    r"|(?:要|該|可以|才能)(?:怎麼|如何)(?:跟|和|對|向|做|回|補|讀|排|準備|處理|開口|說|講|溝通|規劃|安排|面對|道歉)"
    r"|幫我.{0,6}(?:排|規劃|安排|想想|看看)|有沒有.{0,8}(?:具體|實際|好)?的?(?:方法|辦法|建議|技巧)"
    r"|(?:我)?可以(?:先)?(?:找|去|跟|試|用|請).{0,12}嗎|你覺得(?:我)?(?:要|應該|該|可以).{0,14}嗎"
    # v2.8 harness: coping questions 「有什麼方法可以放鬆」「睡不著怎麼辦」「怎麼紓壓」 ask for a way, not to be explored.
    r"|有(?:什麼|甚麼|哪些|沒有).{0,6}(?:方法|辦法|技巧|撇步|建議)|(?:紓壓|舒壓|減壓|放鬆)(?:的)?(?:方法|技巧|撇步)"
    r"|(?:怎麼|如何|要怎樣)(?:才能|才可以|可以)?(?:放鬆|紓壓|舒壓|減壓|冷靜|入睡|睡著|專心|不緊張|不焦慮|停下來|戒掉)"
    r"|(?:睡不著|失眠|好緊張|好焦慮|一直擔心|停不下來|好生氣|好孤單|讀不下|拖延).{0,8}(?:怎麼辦|該怎麼做|要怎麼做)"
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
        "safety_lifted": False, "safety_turns": 0, "fresh_safety": False, "ideation_confirmed": False,
        "risk_cue": "", "night_review": False, "fresh_level": "green",
        "emotion_intensity": "low", "conversation_willingness": "medium", "privacy_concern": False,
        "confidentiality_limit_needed": False, "advice_request": False, "info_request": False,
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


# Everyday distress is not a safety cue on its own. The model's analysis once quoted 「睡不著」 from 「睡不著怎麼辦」
# as a suicide signal, and the student was asked about ending their life instead of getting help to sleep
# (2026-10-23 live test). A model risk hint whose quote holds nothing beyond these words is ignored.
EVERYDAY_DISTRESS = (r"睡不著|睡不好|失眠|熬夜|起不來|好累|很累|累|壓力|心情不好|低落|好煩|很煩|煩|焦慮|緊張|擔心|害怕"
                     r"|考試|段考|作業|讀書|頭痛|胃痛|肚子痛|吃不下|提不起勁|沒動力|空虛|難過|想哭|哭|孤單|寂寞|無聊"
                     r"|生氣|吵架|不開心|心累|好悶|悶")
FILLER = (r"怎麼辦|怎麼|該怎麼|要怎麼|有點|一直|最近|每天|晚上|今天|常常|一點|真的|好像|覺得|感覺|是不是"
          r"|[我你他她好很太超都也就了的啊喔欸呢嗎吧該要會是這那樣又還]")


# 「我想打老師」 is anger to be heard, not a safety check (2026-10-23 live test: the model labelled it violence and
# the student was asked about suicide). A model violence hint counts only with a plan, weapon, time or a lethal verb.
VIOLENCE_PLAN = (r"刀|槍|武器|棍|球棒|鐵條|已經準備|準備好|計畫|打算|明天|今天|今晚|等一下|放學|下課後|堵他|堵她|約他出來"
                 r"|約她出來|帶.{0,4}(?:去|到)學校|殺|砍|捅|弄死|打死|同歸於盡")


def everyday_distress_only(evidence):
    rest = re.sub(FILLER, "", re.sub(EVERYDAY_DISTRESS, "", evidence or ""))
    return len(re.sub(r"[^㐀-鿿A-Za-z]", "", rest)) <= 1


def _affirmative_matches(pattern, text):
    for clause in re.split(r"[。！？!?；;\n]|但是|可是|不過|但", text):
        for match in re.finditer(pattern, clause):
            before = clause[max(0, match.start() - 16):match.start()]
            # A negation before a comma does not negate an unrelated clause.
            before = re.split(r"[,，、]", before)[-1]
            if re.search(r"(?:沒有|並未|從未|不會|不打算|不是|不想|不要|並不).{0,4}$|(?:不覺得|不認為|才不是).{0,6}$", before):
                continue
            if re.search(r"(?:沒有|不會|並未|從未|不打算).{0,6}(?:打我|揍我|性侵|拿刀|帶刀|持刀|殺|砍|捅|威脅|自殺|傷害|吃掉|吞|吃完)", match.group()):
                continue
            yield clause, match.group()


def _context_escalation(message, scan, previous):
    """(kind, subject, evidence) when a follow-up adds timing, a place, ready means, final words or a
    yes to the means question to a concern that is already orange; otherwise None."""
    kind = previous.get("risk_type")
    # An open gentle check counts too: 「有，藥已經準備好了」 answers it with ready means.
    concern = (WEIGHTS.get(previous.get("risk_level"), 1) >= WEIGHTS["orange"]
               or (previous.get("pending_safety_check") and kind in ("suicide", "self_harm")))
    if not concern or kind not in ("suicide", "self_harm", "abuse", "digital_sexual_violence"):
        return None
    if re.search(CLARIFIED, message):
        return None
    subject = previous.get("risk_subject") if previous.get("risk_subject") in ("self", "other") else "self"
    # Short answers to the protection questions: the person is still there / not safe right now.
    asked, answer = previous.get("last_reply", ""), message.strip()
    if (("還在身邊嗎" in asked or "在同一個地方嗎" in asked) and re.search(YES_ANSWER, answer)) or (
            "身邊安全嗎" in asked and re.search(r"^(?:不|沒有|不太|不安全|不是很)", answer)):
        return kind, subject, message[:120]
    if kind == "digital_sexual_violence":
        return None
    patterns = ([ESCALATION_ABUSE] if kind == "abuse"
                else [ESCALATION_SUICIDE, FINAL_WORDS] + ([ESCALATION_OTHER] if subject == "other" else []))
    for pattern in patterns:
        for _, evidence in _affirmative_matches(pattern, scan):
            return kind, subject, evidence
    if kind != "abuse" and re.search("藥", scan + previous.get("risk_evidence", "")):
        for _, evidence in _affirmative_matches(PILL_PLAN, scan):
            return kind, subject, evidence
    # 「有」 answers the means-and-timing question only if that was the question just asked.
    if "工具或打算行動的時間" in previous.get("last_reply", "") and re.search(YES_ANSWER, message.strip()):
        return kind, subject, message[:120]
    return None


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


# v2.3 Phase 1 cross-disciplinary signals. All of them can only RAISE a floor or ask a soft
# question; none lowers a rule or high-water level. Codes refer to docs/THEORETICAL_FOUNDATIONS.md.
# PSY-02 IPTS: perceived burdensomeness / thwarted belongingness.
PERCEIVED_BURDEN = (r"累贅|拖累(?:大家|家裡|家人|你們|他們)|(?:是|成了|變成)(?:大家|家裡|家人|爸媽|他們)?的?負擔"
                    r"|沒有我.{0,12}(?:更好|輕鬆|比較好|沒差|快樂)|少了我.{0,6}(?:更好|輕鬆|比較好)")
THWARTED_BELONGING = (r"沒(?:有)?人要我|沒(?:有)?人在乎我|沒有人需要我|格格不入|像(?:個)?透明人|沒有(?:半個|任何)朋友"
                      r"|被所有人討厭|不屬於這裡|全世界都不要我")
# PSY-03 IMV: entrapment.
ENTRAPMENT = r"逃不出去|逃不掉|沒有出路|走投無路|無路可逃|怎麼掙扎都|被困住|困在這裡|看不到出口|掉進深淵|永遠不會好"
# DYN-04 (heuristic only): negative-affect runs and abrupt farewells. A few turns cannot measure
# critical slowing down; this is a digital-phenotype prompt for a human check, not CSD detection.
NEGATIVE_AFFECT = (r"難過|好累|很累|好煩|痛苦|沒意義|無望|絕望|崩潰|想哭|哭了|沒希望|空虛|撐不|受不了|不開心|低落|孤單"
                   r"|討厭自己|好糟|很糟|好爛|心好痛")
FAREWELL = r"(?:(?:算了|謝謝你?(?:陪我)?|再見|掰掰|拜拜|bye|就這樣吧?|不用了)[\s，,。！!~～…\.]*){1,3}"
# SOC-05: a friend's crisis disclosed to the student.
THIRD_PARTY = (r"(?:朋友|同學|閨蜜|好友|室友|網友|學長|學姊|學姐|弟弟|妹妹|哥哥|姊姊|姐姐|表[哥姊姐弟妹]|他|她)"
               r".{0,20}(?:說|表示|提到|傳|告訴我).{0,20}"
               r"(?:不想活|想死|自殺|傷害自己|吞藥|吞了.{0,10}(?:藥|安眠藥)|吃了.{0,8}(?:很多|好多|一堆|整瓶|整包|全部).{0,4}藥"
               r"|割(?:腕|手)|跳樓|燒炭|上吊|(?:頂樓|樓頂|天台|陽台|橋|高樓|窗戶).{0,6}跳下去)")
# 2026-10-23 simulation: abuse by relatives, sextortion, leaked images and physical bullying went undetected.
ABUSE = (r"(?:爸|媽|家人|大人|老師|教練|叔叔|阿姨|繼父|繼母|舅舅|舅媽|伯伯|伯父|伯母|姑姑|姑丈|姨丈|阿公|爺爺|外公"
         r"|鄰居|乾爹|男友|男朋友|同居人).{0,18}"
         r"(?:打我(?!(?:最)?(?:喜歡|愛)?的?(?:羽球|籃球|桌球|排球|網球|棒球|電動|遊戲|球))|揍我"
         r"|摸我(?!的?(?:頭|頭髮|額頭|肩膀|臉頰))|逼我脫|性侵)"
         r"|(?:我|同學).{0,6}(?:被虐待|被性侵|被強暴|被家暴|被打(?!槍|敗|爆|球|工|卡|電話|針|招呼))")
DIGITAL_SEXUAL_VIOLENCE = (r"(?:威脅|恐嚇|逼我|強迫).{0,25}(?:私密照|裸照|性影像|性愛影片|私密影片|不雅照)"
                           r"|(?:私密照|裸照|性影像|私密影片|不雅照|性愛影片).{0,25}"
                           r"(?:外流|威脅|散布|散佈|公開|PO|po|貼|傳(?:出去|給|到)|上傳|流出)")
# Physical bullying only; verbal teasing stays with PEER_REJECTION. 「被打敗／打爆」 are games, not violence.
PEER_VIOLENCE = (r"(?:同學|他們|學長|學姊|學姐|班上的人|一群人|那群人|有人).{0,12}(?:打我(?!一下)|揍我|踹我|圍毆我|堵我)"
                 r"|被(?:同學|學長|學姊|學姐|他們|一群人|那群人)?(?:圍毆|毆打|揍)"
                 r"|被(?:同學|學長|學姊|學姐|他們|一群人|那群人)打(?!敗|爆|槍|球|工|卡|電話|針|字|掃|招呼|成|平)")
# PSY-01 passive death wish: one gentle check (yellow); the late-night rule raises it for human review.
PASSIVE_DEATH_WISH = (r"(?:覺得|乾脆|我)消失(?:了)?(?:也|就)?(?:沒差|沒關係|比較好|算了)|(?:^|乾脆)消失算了"
                      r"|我不在了?(?:也|就)(?:沒差|沒關係|比較好)|睡著(?:了)?就(?:不要|不再|別)醒來")
# Follow-up details that make an existing orange concern imminent (red).
ESCALATION_SUICIDE = (r"(?:今晚|今天晚上|明天晚上|明晚|等一下|待會|馬上|現在就).{0,10}"
                      r"(?:吞|割|跳下|結束|動手|行動|去死|吃掉|吃完|全部吃|吃下去)"
                      # 「我們在頂樓曬衣服」 is not a location of danger: 在／到 needs 已經／現在／正.
                      r"|(?:(?:已經|現在|正)(?:在|到)|站在|坐在|爬上)(?:了)?(?:頂樓|樓頂|天台|橋上|河邊|海邊|鐵軌|月台邊|陽台外)"
                      r"|(?:刀片|美工刀|刀子|刀|藥|安眠藥|繩子|繩|木炭|炭).{0,6}(?:準備好|藏好|存好|買好|藏起來|存起來|拿出來)"
                      r"|(?:準備好|藏好|存好|買好)了?.{0,4}(?:刀片|美工刀|刀子|藥|繩|炭)")
ESCALATION_OTHER = r"已讀不回|聯絡不到|不接(?:電話)?|找不到(?:他|她|人)|關機了"
ESCALATION_ABUSE = r"(?:還在|在)(?:家|客廳|旁邊|身邊|門外|門口|房間外)|又(?:打|揍|來了)|(?:現在|正在).{0,6}(?:打|揍|摔|砸)|喝醉(?:了)?回來"
# 「五十顆」「今晚吃」 mean an overdose plan only when pills are already part of the conversation.
PILL_PLAN = r"(?:\d+|[一二三四五六七八九十兩幾半百]+)(?:顆|錠|排|瓶|盒)|(?:今晚|今天晚上|明天晚上|明晚|等一下|待會|馬上|現在就).{0,6}吃"
YES_ANSWER = r"^(?:有|有啊|有喔|有耶|有的|對|對啊|嗯|是|是啊|都有|有準備)(?:$|[，,。!！\s])"
CLARIFIED = r"只是(?:在)?(?:抱怨|開玩笑|說說|講講|誇張|形容|比喻|發牢騷)|開玩笑的|講好玩的|形容(?:詞|一下)?(?:啦|而已)"
# PSY-01 preparatory acts. Alone → orange (gentle check); with final-goodbye wording → red.
# Acts only: "last chat" or "won't need it" are final words, not acts, so they cannot make a red alone.
PREPARATORY = (r"(?:把|將).{0,14}(?:帳號|裝備|收藏|寵物|心愛的|最喜歡的|存款|寶貝).{0,10}(?:送給|送人|送掉|留給|分給)"
               r"|(?:把|將).{0,6}(?:所有|全部)(?:的)?東西.{0,6}(?:送給|送人|送掉|留給|分給)"
               r"|(?:東西|帳號|裝備|收藏)(?:全部|都)(?:送人|送掉|送出去|分掉)|交代(?:好)?後事|託付.{0,6}(?:給你|給你們|照顧)"
               r"|以後(?:就)?(?:麻煩|拜託)?(?:你|你們)?(?:幫我|替我)?照顧(?:好)?(?:我的)?(?:貓|狗|寵物|妹妹|弟弟)"
               r"|寫好.{0,4}(?:遺書|給大家的信)")
PREPARATORY_EXCLUDE = r"保管|借給|借我|幫我收|代收|作業|報告|講義"
FINAL_WORDS = r"最後一次(?:聊天|見面|說話|跟你)|再見了|永別|不用再|不會再見|以後都不|以後(?:都|也)?用不到了|告別|不在了|離開這個世界"
# PSY-03 volitional moderator: means available to a person who feels trapped.
MEANS = r"美工刀|刀片|刀子|安眠藥|一整瓶藥|一整罐藥|藥(?:都)?(?:存|準備|收集)好|繩子|頂樓|跳下去|燒炭|農藥|模仿.{0,6}(?:自殺|跳樓)"
# In later turns a means only counts with an access/readiness verb (「站在頂樓」, not 「在頂樓曬衣服」).
MEANS_ACCESS = r"(?:有|準備(?:好)?|買好|存好|站在|拿著|藏(?:好)?|收集)(?:了)?.{0,6}(?:" + MEANS + r")"
# SOC-05 microsystems: family and peers both failing, and no one to tell.
FAMILY_STRAIN = (r"(?:爸媽|爸爸|媽媽|家人|父母).{0,12}(?:吵架|罵我|不理我|不要我|討厭我|冷戰|逼我|對我很失望)"
                 r"|家裡.{0,4}(?:很亂|待不下去|好可怕)")
PEER_REJECTION = r"沒(?:有)?人要我|被排擠|被霸凌|沒有朋友|同學都(?:不理我|笑我|討厭我)|被孤立|格格不入"
NO_SUPPORT = (r"(?:沒有人|沒人|找不到人|不知道(?:要)?找誰).{0,10}(?:可以)?(?:說|聊|幫|講|理解)"
              r"|不敢(?:跟|告訴)(?:任何人|別人|大人|家人|老師|爸媽)|只能自己(?:撐|扛)")
CONCERNING_PRIORS = {"sleep": ("reported_difficulty",), "daily_function": ("reported_impact",),
                     "support_system": ("difficulty_seeking_support",), "safety": ("requires_human_review", "clarification_needed")}


def _concerning_priors(previous):
    """SIG-02 (heuristic): count earlier evidence-bound concerns. No probability is computed; the
    threshold only encodes asymmetric costs (a miss is worse than a false alarm), not predictive validity."""
    domains = ((previous.get("wellbeing_signals") or {}).get("domains") or {})
    count = sum(1 for key, statuses in CONCERNING_PRIORS.items()
                if (domains.get(key) or {}).get("status") in statuses)
    return count + len(previous.get("ipts") or {})


def _last_user_text(previous):
    users = [t.get("text", "") for t in previous.get("history", []) if isinstance(t, dict) and t.get("role") == "user"]
    return users[-1] if users else ""


def observe_safety(message, triage, previous=None, hints=None, hour=None):
    """`hour` is the student's local send hour; only the live chat route supplies it (DYN-04)."""
    from engine.rules import mask_hyperbole
    previous = previous or {}
    rules = triage.get("rule_details", {})
    current = rules.get("triggered_level", "green")
    scan, hyperbole = mask_hyperbole(message)
    risk = {"risk_signal": "none", "risk_type": "none", "risk_subject": "unknown",
            "risk_evidence": "", "immediate_danger": "none", "safety_denied": False,
            "pending_safety_check": False, "minimum_level": "green", "risk_types": [],
            "theoretical_basis": [], "pending_disambiguation": False,
            "ipts": dict(previous.get("ipts") or {}),
            "secondary_trauma_risk": bool(previous.get("secondary_trauma_risk")),
            "dyn_checked": bool(previous.get("dyn_checked")), "negative_streak": 0,
            "microsystem": dict(previous.get("microsystem") or {}),
            "microsystem_flagged": bool(previous.get("microsystem_flagged")),
            # risk_cue picks the wording (peer bullying, leaked images, affect streak); fresh_level is what THIS
            # message shows on its own, for the student-facing safety mode (night review and carry-overs excluded).
            "risk_cue": "", "night_review": False, "fresh_level": "green", "thoughts_confirmed": False}
    candidates = []

    def add(kind, signal, danger, evidence, floor, subject="self", basis=(), cue="", carry=False):
        candidates.append({"risk_signal": signal, "risk_type": kind, "risk_subject": subject,
                           "risk_evidence": evidence[:240], "immediate_danger": danger,
                           "minimum_level": floor, "theoretical_basis": list(basis),
                           "_cue": cue, "_carry": carry, "_night": False})

    # Existing explicit rules and quantitative/high-water levels cannot be vetoed by the LLM.
    if current in ("orange", "red"):
        evidence = "；".join(rules.get("red_flags", []) or rules.get("orange_flags", []))
        kind = "abuse" if re.search(r"被打(?!槍)|家暴", evidence) else "suicide" if re.search(
            r"想死|自殺|自傷|不想活|活不下去|活著|死亡|遺書|吞|藥|跳樓|跳橋|燒炭|上吊|不想醒|不要醒|結束(?:生命|自己|這一切)"
            r"|離開這個世界|不在了|消失|工具", evidence) else "self_harm"
        add(kind, "direct", "imminent" if current == "red" else "possible", evidence, current,
            basis=triage.get("theoretical_basis") or ("PSY-01",))

    specs = [
        (DIGITAL_SEXUAL_VIOLENCE, "digital_sexual_violence", "orange", ""),
        (ABUSE, "abuse", "orange", ""),
        # Physical bullying shares the protection type; its own wording points to school staff (cue "peer").
        (PEER_VIOLENCE, "abuse", "orange", "peer"),
        (r"(?:我|他|她|有人).{0,16}(?:拿|帶|持)(?:刀|球棒|棍子|鐵條|武器|槍).{0,18}(?:殺|砍|捅|堵|打|揍|門外|門口|付出代價|報仇|算帳|教訓)"
         r"|(?:我|他|她).{0,14}(?:要殺|想殺|要砍|要捅).{0,6}(?:人|他|她|同學|我)", "violence", "orange", ""),
        (r"(?:我今晚|我現在|我等一下|我今天).{0,12}(?:打算|要).{0,12}(?:這些藥|全部.*藥|整瓶.*藥).{0,8}(?:吃掉|吞|吃完)", "suicide", "red", ""),
    ]
    for pattern, kind, floor, cue in specs:
        for clause, evidence in _affirmative_matches(pattern, scan):
            if kind in ("abuse", "violence") and re.search(r"現在|正在|今晚|等一下|門外|門口|拿刀|帶刀|持刀", clause):
                floor = "red"
            if kind == "digital_sexual_violence":
                # Images already posted vs a threat to post them need different first steps.
                cue = "threat" if re.search(r"威脅|恐嚇|逼我|強迫|勒索|不(?:再)?傳.{0,10}就|不然", clause) else "leaked"
            add(kind, "direct", "imminent" if floor == "red" else "possible", evidence, floor, basis=("PSY-01",), cue=cue)

    # Follow-up details turn an existing orange concern red (2026-10-23 simulation: these stayed orange/green).
    escalation = _context_escalation(message, scan, previous)
    if escalation:
        kind, subject, evidence = escalation
        add(kind, "direct", "imminent", evidence, "red", subject, ("PSY-01",))

    # SOC-05: third-party disclosure stays third-party; it is still a reason to pause and help connect.
    for clause, evidence in _affirmative_matches(THIRD_PARTY, scan):
        danger = "imminent" if re.search(r"今晚|現在|正在|已經|等一下|剛剛|剛才|吞了|吃了|頭很暈|昏", clause) else "possible"
        add("suicide", "direct", danger, evidence, "red" if danger == "imminent" else "orange", "other", ("SOC-05", "PSY-01"))
        risk["secondary_trauma_risk"] = True

    ambiguous = r"撐不下去|受不了了|不想撐了|快撐不住"
    indirect = (r"少了我.{0,4}也沒差|沒有我.{0,8}(?:更好|沒差)|(?:如果|希望).{0,5}(?:不要|不再)醒來|希望睡了就不醒|不想醒來"
                r"|" + PASSIVE_DEATH_WISH)
    for pattern, signal in ((ambiguous, "ambiguous"), (indirect, "indirect")):
        for _, evidence in _affirmative_matches(pattern, scan):
            add("suicide", signal, "possible", evidence, "yellow", basis=("PSY-01",))

    # PSY-02 / PSY-03: burdensomeness and thwarted belonging accumulate within the conversation.
    hits = {}
    for key, pattern in (("pb", PERCEIVED_BURDEN), ("tb", THWARTED_BELONGING), ("entrapment", ENTRAPMENT)):
        for _, evidence in _affirmative_matches(pattern, scan):
            hits[key] = evidence[:120]
            break
    if hits:
        ipts = {**risk["ipts"], **hits}
        risk["ipts"] = ipts
        combined = ("pb" in ipts and "tb" in ipts) or ("entrapment" in ipts and ("pb" in ipts or "tb" in ipts))
        basis = (["PSY-02"] if hits.keys() & {"pb", "tb"} or combined else []) + (["PSY-03"] if "entrapment" in ipts else [])
        add("suicide", "indirect", "possible", next(iter(hits.values())), "orange" if combined else "yellow", basis=basis)

    # PSY-01 (C-SSRS preparatory behaviour): giving away treasured things, settling affairs, last goodbyes.
    preparatory = [(clause, evidence) for clause, evidence in _affirmative_matches(PREPARATORY, scan)
                   if not re.search(PREPARATORY_EXCLUDE, clause)]
    if preparatory:
        # Final-goodbye wording counts only near the act (same sentence, outside the matched act itself).
        clause, act = preparatory[0]
        around = clause.replace(act, "　" * len(act))
        final = bool(re.search(FINAL_WORDS, around))
        add("suicide", "direct", "imminent" if final else "possible", act,
            "red" if final or len(preparatory) > 1 else "orange", basis=("PSY-01",))

    # PSY-03 volitional moderator: entrapment together with access to a means.
    if "entrapment" in risk["ipts"]:
        means = MEANS if "entrapment" in hits else MEANS_ACCESS
        for _, evidence in _affirmative_matches(means, scan):
            add("suicide", "direct", "imminent", evidence, "red", basis=("PSY-03", "PSY-01"))
            break

    # SOC-05 microsystem double break: family strain + peer rejection + nobody to turn to (across turns).
    micro, fresh = dict(risk["microsystem"]), False
    for key, pattern in (("family", FAMILY_STRAIN), ("peer", PEER_REJECTION), ("support", NO_SUPPORT)):
        for _, evidence in _affirmative_matches(pattern, scan):
            micro[key], fresh = evidence[:120], True
            break
    risk["microsystem"] = micro
    if fresh and len(micro) == 3 and not risk["microsystem_flagged"]:
        add("suicide", "indirect", "possible", micro["support"], "orange", basis=("SOC-05",))
        risk["microsystem_flagged"] = True

    # LIN-01 + SIG-02: hyperbole is checked softly; with >=2 earlier concerns it goes to orange for human review.
    if hyperbole:
        own = any(not re.search(r"(?:朋友|同學|他|她|閨蜜|好友).{0,6}" + re.escape(span), message) for span in hyperbole)
        floor = "orange" if _concerning_priors(previous) >= 2 else "yellow"
        # Someone else's everyday hyperbole (spec case S01 「同學說他熱到想死了，今天真的好熱」) is not a reason to
        # ask about that person dying; the student's own hyperbole still gets one gentle check.
        if own:
            add("suicide", "ambiguous", "possible", hyperbole[0], floor, "self", ("LIN-01", "SIG-02"))

    # DYN-04: affect inertia and abrupt farewell raise one soft check per conversation.
    risk["negative_streak"] = previous.get("negative_streak", 0) + 1 if re.search(NEGATIVE_AFFECT, scan) else 0
    if not risk["dyn_checked"]:
        farewell = (re.fullmatch(FAREWELL, message.strip(), re.I) and len(_last_user_text(previous)) >= 40
                    and (previous.get("negative_streak", 0) >= 1 or WEIGHTS.get(previous.get("risk_level", "green"), 1) >= 2))
        if risk["negative_streak"] >= 3 or farewell:
            add("suicide", "ambiguous", "possible", message[:120], "yellow", basis=("DYN-04",),
                cue="" if farewell else "affect_streak")
            risk["dyn_checked"] = True
    if hour is not None and 1 <= hour < 5:
        # Late-night disclosures: an ambiguous or indirect signal is escalated for HUMAN REVIEW only; the student
        # still gets the gentle daytime check (2026-10-23 simulation). A run of ordinary complaints is not a
        # risk signal by itself and is not escalated.
        for candidate in candidates:
            if (candidate["risk_signal"] in ("ambiguous", "indirect") and candidate["minimum_level"] == "yellow"
                    and candidate["_cue"] != "affect_streak"):
                candidate["minimum_level"] = "orange"
                candidate["theoretical_basis"] = candidate["theoretical_basis"] + ["DYN-04"]
                candidate["_night"] = True

    # A short answer is interpreted only against a server-recorded pending safety question, or while the
    # student is in the full safety mode (so 「沒有啦，開玩笑的」 can end it for an orange concern).
    pending = previous.get("pending_safety_check", False) or bool(previous.get("safety_override"))
    # A bare 「沒有／有」 answers only the thoughts question: 「沒有」 to 「有人能陪你嗎？」 or to the means
    # question is not a denial of suicidal thoughts, and 「嗯」 to 「有人陪你嗎」 is not an admission.
    asked_thoughts = previous.get("pending_safety_check") or "結束自己的生命嗎" in previous.get("last_reply", "")
    denied = bool((asked_thoughts and re.search(r"^(?:沒有啦|沒有|沒啦|並沒有|沒有耶)(?:$|[，,。!！\s])", message))
                  or re.search(r"(?:沒有|不會|不想).{0,4}(?:傷害自己|自殺)|沒有.{0,3}(?:不想活|想死)", message)
                  or re.search(CLARIFIED, message))
    if pending and not candidates:
        reaffirms = _reaffirms_after_denial(message)
        if reaffirms:
            add(previous.get("risk_type") if previous.get("risk_type") in RISK_TYPES[1:] else "suicide",
                "direct", "possible", reaffirms, "orange",
                previous.get("risk_subject") if previous.get("risk_subject") in ("self", "other") else "self", ("PSY-01",))
            risk["thoughts_confirmed"] = True
        elif denied:
            risk["safety_denied"] = True
        elif asked_thoughts and re.search(r"^(?:有|有啊|有耶|對|是|嗯|有一點|會|想過)(?:$|[，,。!！\s])", message):
            add(previous.get("risk_type", "suicide"), "direct", "possible", message, "orange",
                previous.get("risk_subject", "self"), ("PSY-01",))
            risk["thoughts_confirmed"] = True
        elif previous.get("pending_safety_check"):
            # An unanswered gentle check stays open (the full safety mode carries over in build_state instead).
            add(previous.get("risk_type", "suicide"), previous.get("risk_signal", "ambiguous"),
                "possible", previous.get("risk_evidence", ""), "yellow", previous.get("risk_subject", "self"),
                previous.get("theoretical_basis") or (), cue=previous.get("risk_cue", ""), carry=True)

    observation = _valid_observations(hints, message).get("risk", {})
    # Grounding alone is insufficient: a quote can explicitly deny a harmful intention.
    if re.search(r"(?:沒有|並未|從未|不會|不打算|不是).{0,5}(?:想|要|打算)?(?:自傷|自殺|傷害自己|想死|不想活)", observation.get("evidence", "")):
        observation = {}
    if observation and everyday_distress_only(observation.get("evidence", "")):
        observation = {}  # 「睡不著」「好累」 alone are not a risk signal, whatever the model labels them
    if observation.get("type") == "violence" and not re.search(VIOLENCE_PLAN, message):
        observation = {}  # angry words without a plan: listen to the anger instead of starting a safety check
    if observation.get("affirmed") is True and not (pending and denied and not candidates):
        kind, signal, danger = observation.get("type"), observation.get("signal"), observation.get("danger")
        if kind in RISK_TYPES[1:] and signal in ("ambiguous", "indirect", "direct") and danger in ("none", "possible", "imminent"):
            floor = "red" if signal == "direct" and danger == "imminent" else "orange" if signal == "direct" else "yellow"
            add(kind, signal, danger, observation["evidence"], floor,
                observation.get("subject") if observation.get("subject") in ("self", "other") else "unknown",
                ("ENG-03",))
    if candidates:
        # A direct current safety threat wins ties over a less specific signal.
        selected = max(candidates, key=lambda c: (WEIGHTS[c["minimum_level"]], c["immediate_danger"] == "imminent",
                                                    c["risk_signal"] == "direct",
                                                    c["risk_type"] in ("violence", "abuse", "digital_sexual_violence"),
                                                    c["risk_subject"] == "self"))
        risk.update({k: v for k, v in selected.items() if not k.startswith("_")})
        risk["risk_cue"], risk["night_review"] = selected["_cue"], selected["_night"]
        own = [("yellow" if c["_night"] else c["minimum_level"]) for c in candidates if not c["_carry"]]
        risk["fresh_level"] = max(own, key=WEIGHTS.get) if own else "green"
        risk["risk_types"] = list(dict.fromkeys(c["risk_type"] for c in candidates))
        risk["theoretical_basis"] = list(dict.fromkeys(code for c in candidates for code in c["theoretical_basis"]))
        risk["pending_safety_check"] = selected["risk_signal"] in ("ambiguous", "indirect")
        risk["pending_disambiguation"] = "LIN-01" in selected["theoretical_basis"]
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
    result["theoretical_basis"] = list(dict.fromkeys(
        list(result.get("theoretical_basis") or []) + list(safety.get("theoretical_basis") or [])))
    result["dialogue_safety"] = safety
    return result


def build_state(message, triage, previous=None, hints=None, history=None, reply_style=None):
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
    # The review level never drops; what the student sees can (2026-10-23 simulation: the full safety script
    # repeated every turn after 「開玩笑的」, and night review turned a hyperbole into a means question).
    fresh = safety.get("fresh_level", "green")
    if WEIGHTS[fresh] >= WEIGHTS["orange"]:
        lifted = False                      # new danger in this message: full safety reply again
    elif state["safety_denied"] and state["risk_level"] != "red":
        lifted = True                       # denied/clarified an orange concern: back to conversation
    elif safety.get("night_review") and WEIGHTS[old.get("risk_level", "green")] < WEIGHTS["orange"]:
        lifted = True                       # orange for human review only; the student gets the gentle check
    else:
        lifted = bool(old.get("safety_lifted"))
    state["safety_lifted"] = lifted
    state["safety_override"] = state["risk_level"] in ("orange", "red") and not lifted
    state["safety_check_required"] = state["safety_override"] or state["pending_safety_check"]
    state["human_escalation_required"] = state["risk_level"] in ("orange", "red")
    state["safety_turns"] = old.get("safety_turns", 0) + 1 if state["safety_override"] else 0
    # The full safety message comes back only when the level rises (orange → red), not on every new cue.
    state["fresh_safety"] = WEIGHTS[state["risk_level"]] > WEIGHTS[old.get("risk_level", "green")]
    # Gatekeeper order: the means question waits until the student has answered the thoughts question.
    state["ideation_confirmed"] = bool(old.get("ideation_confirmed") or safety.get("thoughts_confirmed"))
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
    # Bounded gaps: an unbounded 「不想.*知道」 matched across a 1,650-character story (2026-10-23 simulation).
    state["privacy_concern"] = bool(re.search(
        r"不能.{0,12}(?:講|說)|不要.{0,8}(?:告訴|跟.{0,6}講)|保密|會.{0,12}(?:告訴|知道|看到)"
        r"|不想.{0,10}(?:老師|爸媽|班導|同學).{0,8}知道|(?:會|要)(?:不會)?.{0,6}通報"
        # 「你會跟我爸媽講嗎」「這個有錄下來嗎」「可以刪掉我的紀錄嗎」 (2026-10-23 simulation)
        r"|跟(?:我)?(?:爸|媽|爸媽|家人|老師|學校|班導|導師|別人).{0,4}(?:講|說)(?:嗎|喔|吧|[？?])"
        r"|(?:這個|對話|聊天|我說的|這些).{0,6}(?:有|會)(?:沒有|不會)?(?:被)?(?:錄|記錄|紀錄|保存|存)(?:下來|起來)?"
        r"|刪(?:掉|除).{0,6}(?:紀錄|記錄|對話|資料)|關掉.{0,6}(?:就)?(?:沒了|消失)", message))
    state["confidentiality_limit_needed"] = state["privacy_concern"] or state["safety_override"]
    state["advice_request"] = wants_practical_help(message)
    state["info_request"] = asks_information(message)
    # 「我說的是未來3天之後」 corrects the last reply just like 「不是啦」 (2026-10-23 live test).
    correction = bool(re.search(r"^(?:不是|不對)|你誤會|你聽錯|你搞錯|不是那個意思|我不是.{0,6}[，,].*(?:是|而是)"
                                r"|^.{0,4}(?:我(?:剛剛|剛才)?(?:說|講|指)的是|我是說|我的意思是)", message)) and not state["safety_denied"]
    # 「真的嗎」「為什麼」right after a reply react to that reply; they are not a new event to explore.
    replied = any(t["role"] == "assistant" for t in turns)
    stripped = re.sub(r"[～~…]+", "", text)
    state["reaction"] = ("doubt" if replied and re.fullmatch(REACTION_DOUBT, stripped)
                         else "ask" if replied and re.fullmatch(REACTION_ASK, stripped) else "")
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
    elif state["info_request"]:
        # v2.8 harness: a question about facts or ways (「電子煙有什麼影響」「15 歲可以打工嗎」) gets an answer.
        goal, strategy, ask = "answer_question", "inform", True
    elif correction:
        # Own the misreading, answer the corrected meaning, and ask once if it is still unclear what they mean.
        goal, strategy, ask = "repair_understanding", "reflect_then_ask", True
    elif state["known_yearning"] or "self" in found or re.search(r"原來我|明白自己|比較平靜|輕鬆一點", message):
        goal, strategy, ask = "integrate", "summarize", False
    elif state["reaction"]:
        goal, strategy, ask = "respond_to_reaction", "reflect_only", False
    elif short:
        goal, strategy, ask = "explore_feeling", "reflect_only", False
    else:
        for known, next_goal in (("expectation", "explore_yearning"), ("perception", "explore_expectation"),
                                 ("feeling", "explore_perception"), ("event", "explore_feeling")):
            if state["known_" + known]:
                goal, strategy = next_goal, "reflect_then_ask"
                break
    recent = [t["text"] for t in turns if t["role"] == "assistant"][-2:]
    # The rest after two questioning turns does not apply when the student is correcting a misreading.
    if goal not in ("safety_support", "repair_understanding") and len(recent) == 2 and all(re.search(r"[？?]", r) for r in recent):
        ask, strategy = False, "reflect_only"
    # v2.3 reply styles are the student's choice; any safety check takes the tone back (safety override).
    style = reply_style if reply_style in REPLY_STYLES else old.get("reply_style") if old.get("reply_style") in REPLY_STYLES else "warm"
    overridden = style != "warm" and state["safety_check_required"]
    preferences = " ".join(state.get("companion_role", {}).get("preferences", []))
    quiet = (style == "listen_only" and not overridden) or bool(re.search(r"不要.{0,8}問|別.{0,3}問|不想被問", preferences))
    no_advice = (style == "listen_only" and not overridden) or bool(re.search(r"不(?:要|用).{0,8}建議|不要.{0,4}教我", preferences))
    if quiet and goal != "safety_support":
        ask, strategy = False, "reflect_only"
    if no_advice and goal == "support_choice":
        goal, strategy = "integrate", "reflect_only"
    state.update(reply_style=style, style_overridden_by_safety=overridden,
                 effective_style="safety" if overridden else style)
    state.update(current_goal=goal, response_strategy=strategy, ask_question=ask, max_questions=int(ask))
    banned = ["ask_multiple_questions", "diagnose", "interpret_for_user", "force_positive", "promise_absolute_confidentiality", "minimize_risk"]
    if goal not in ("support_choice", "answer_question") or no_advice:
        banned.append("give_advice")
    if goal in ("safety_support", "stabilize", "respect_boundary", "establish_safety", "integrate", "respond_to_reaction",
                "repair_understanding"):
        banned.extend(("explore_yearning", "deep_reflection", "continue_drilling"))
    state["forbidden_actions"] = banned
    return state


def remember_turn(state, message, reply):
    saved = deepcopy(state)
    saved["history"] = (history_clean(state.get("history"), message) + [
        {"role": "user", "text": message[:2000]}, {"role": "assistant", "text": reply[:2000]}])[-24:]
    saved["last_reply"] = reply[:2000]
    saved.pop("_turn_deadline", None)
    saved.pop("_prepared_reply", None)
    return saved
