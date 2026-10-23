"""
危機關鍵規則引擎 (Crisis Rule Engine)
負責分析青少年文字對話與輸入中的危機訊號：
1. 紅色：高致命性、具體工具已備妥、具體時間地點、正在行動或立即生命危險
2. 橙色：自傷意念、非自殺性自殘(NSSI)、衝動涉險、模糊自殺想法、身心嚴重受損
3. 黃色：持續困擾、失眠、拒學、人際困擾、家庭衝突、飲食困擾
"""
import re

# 紅色：高致命性、具體工具/時地/正在行動 (Immediate lethality & action)
RED_PATTERNS = [
    # 已準備好工具並給出近期時間或行動；細節仍須真人確認。
    r"(?:我|自己).{0,18}(?:工具|東西|刀|藥|繩).{0,14}(?:準備好|備妥|拿出來|藏好|弄好|存好|存起來|收集好|買好)"
    r".{0,30}(?:今晚|今天晚上|明天|明晚|等一下|待會|倒數|就要|行動)",
    # 自殺意念＋手段已備妥（「我想吞藥自殺，藥已經準備好了」，2026-10-23 模擬測試漏判）。
    r"(?:自殺|想死|不想活|吞藥|結束(?:自己|生命|這一切)).{0,20}(?:藥|刀|刀片|美工刀|繩子?|木炭|炭).{0,6}"
    r"(?:都)?(?:已經)?(?:準備好|備妥|存好|藏好|買好|拿出來)",
    # 手上有手段＋近期要行動（「我現在手上還有美工刀，今晚還想再割」）。
    r"(?:手上|身上|旁邊|口袋).{0,4}(?:有|還有|拿著|放著).{0,4}(?:美工刀|刀片|刀子|刀|藥|繩子?)"
    r".{0,20}(?:今晚|今天晚上|現在|等一下|待會|馬上).{0,8}(?:想|要|會|就).{0,4}(?:割|劃|吞|自殺|死|結束)",
    r"(?:我|現在).{0,20}(?:一個人|鎖在房間).{0,24}(?:倒數|五分鐘|全部解決)",
    r"遺書.{0,25}(?:明天|今晚|最後|結束這一切)",
    r"(?:現在|今晚|今天晚上|明天|明天晚上|明晚|等一下|待會|倒數).{0,22}(?:就要|要|會|就想|想).{0,8}"
    r"(?:自殺|結束這一切|離開這個世界)",
    r"(?:我|自己).{0,15}(?:計畫好|決定).{0,35}(?:明天|今晚|等一下).{0,45}(?:結束這一切|自殺|離開這個世界)",
    r"(?:我|自己).{0,12}(?:決定|計畫).{0,8}(?:今晚|今天晚上|明天).{0,20}(?:全部解決掉|全部解決|一次解決).{0,26}(?:數量|藥|夠)",
    # 炭火/密閉 (具體工具準備或點火)
    r"(木炭|整包炭|炭火|噴槍).*?(買好|準備好|點火|燒|貼好膠帶)",
    r"(買好|準備好|點|燒).*?(木炭|整包炭|炭火)",
    r"(?:我|自己|現在|等一下|今晚).{0,12}燒炭|燒炭.{0,12}(?:我|自己|現在|等一下|今晚)",
    # 高處/跳樓/跳橋 (現場正在危險邊緣)
    r"(頂樓|女兒牆|大橋|欄杆|陽台外).*?(坐在|站在|跨過|跳下去|風好大)",
    # 藥物過量 (正在吞服大量藥物)
    r"(吞|吃|喝).*?(\d+|幾十|整包|整瓶|整排|整盒|整罐|大量|全部|很多|好多|一堆).*?(顆|瓶|包|丸)?.*?(安眠藥|藥|百憂解|可樂配)",
    r"安眠藥.*?全部.*?吞",
    # 嚴重銳器大出血
    r"(割腕|劃深|噴血|流好多血|血一直|地毯都是血|發冷發麻)",
    # 上吊/繩索備妥
    r"(童軍繩|繩索|繩子).*?(綁在|梁柱|上吊|吊死)",
    # 遺書與告別
    r"(遺書.*?(寫好|桌上|交代)|最後說話|不用找我|大家保重|今晚就要走了)"
]

# 橙色：自傷意念、非自殺性自殘、模糊自殺想法、衝動涉險
ORANGE_PATTERNS = [
    r"(?:想|會|要)?傷害自己",
    r"(?:突然)?消失(?:在世界上)?[，,。\s]*(?:對大家都好|沒人在意)",
    r"(?:再也|永遠)(?:不要|不會)醒來",
    r"(?:要是|如果)(?:我)?(?:死了|不在了|消失了)[，,]?.{0,18}(?:解脫|比較好|輕鬆|開心|更好|沒差)",
    # 囤藥是準備行為（「我已經把藥都存起來了」）；「把藥收好」「幫阿嬤把藥準備好」不算。
    r"(?:安眠藥|藥).{0,4}(?:都)?(?:存起來|存好|收集起來|收集好|囤起來|囤好|藏起來|藏好)|(?:存|囤|收集)了.{0,6}(?:安眠藥|藥)",
    r"(?:割|劃|划)過(?:手|手腕|手臂|自己)",
    r"一死百了|去死一死|被撞死.{0,16}(?:結束|就好)",
    # 要辨識身體與傷害語境，不能把「劃好重點」「切割紙張」的一個字當成自傷。
    r"(?:割|劃|划)(?:傷)?(?:自己|手腕|手臂|手|皮膚|身體|腿)|(?:割|劃|划)(?:下去|幾刀|了幾刀)",
    r"(?:拿|用)(?:著)?(?:美工刀|刀).{0,12}(?:自己|手腕|手臂|皮膚|割|劃|划|傷害)|圓規戳|流血才能|感覺自己活著",
    r"(?:不想|不願|不想要)(?:再|繼續)?活(?:了|著|下去)|(?:不想|不願).{0,4}繼續活",
    r"(想死|好想消失|一睡不醒|結束一切|直接死掉)",
    r"(?:想|要|打算|計畫)(?:去)?(?:吞藥|跳樓|上吊|燒炭|割腕|喝農藥)?自殺|(?:有|出現)(?:了)?自殺(?:的)?(?:念頭|想法)|想結束(?:自己的)?生命",
    r"(?:想|打算|計畫|準備)(?:要)?(?:去)?(?:跳樓(?!梯)|上吊|燒炭|割腕|喝農藥|臥軌)",
    r"(活著好累|為什麼要生我|叫我去死|恨自己|為什麼不能一睡不醒)",
    r"(跳河|陽台跳|如果我死了)",
    r"(自殘|自傷|虐待自己)",
    r"(開快車|衝下山|撞死算了)",
    # 「被打槍」是拒絕的口語；只排除此語詞，仍檢查同句的其他危險訊號。
    r"(暴力|砸東西|被打(?!槍)|家暴|逃家)"
]

# 黃色：持續困擾、失眠、拒學、人際孤立、飲食困擾
YELLOW_PATTERNS = [
    r"(不想上學|拒學|請假|逃避學校|不想起床)",
    r"(睡不著|連續.*失眠|凌晨.*醒|惡夢)",
    r"(比不上別人|沒用|廢物|被排擠|被笑|被嘲諷)",
    r"(吵架|離婚|爸媽吵|家庭壓力|透不過氣)",
    r"(催吐|容貌焦慮|厭食)",
    r"(胃痛|胸悶|心悸|發抖|頭痛)"
]

# LIN-01 言語行為理論：「熱到想死」「累到快往生」是表達性（expressive）誇飾，不是行動宣告（commissive）。
# 只遮蔽誇飾片語本身；同句其他警訊照常比對，誇飾另行回報為待消歧（黃色＋軟性確認），不會被直接忽略。
# 「難過到想死」等情緒字不在清單內，仍照原規則處理。此調整仍需輔導／心理專業覆核。
HYPERBOLE_PATTERN = re.compile(
    r"(?:熱|冷|餓|累|睏|忙|吵|笑|無聊|煩|難|曬|悶|痛|撐|飽|臭|擠)(?:到|得)(?:快|要|都)?"
    r"(?:想死|死掉|要死|死了|往生|升天|昇天|想撞牆|撞牆|去世|想去世)")


def mask_hyperbole(text: str):
    """Return (text with hyperbole spans blanked at the same positions, list of spans)."""
    spans = [m.group(0) for m in HYPERBOLE_PATTERN.finditer(text or "")]
    return HYPERBOLE_PATTERN.sub(lambda m: "　" * len(m.group(0)), text or ""), spans


def analyze_crisis_rules(text: str) -> dict:
    if not text:
        return {
            "triggered_level": "green",
            "red_flags": [],
            "orange_flags": [],
            "yellow_flags": [],
            "hyperbole_flags": [],
            "has_immediate_danger": False,
            "has_self_harm_signal": False
        }
    text, hyperbole = mask_hyperbole(text)

    def current_clause(start: int, end: int) -> str:
        left = max((text.rfind(mark, 0, start) for mark in "。！？；，\n"), default=-1)
        right_candidates = [text.find(mark, end) for mark in "。！？；，\n"]
        right = min((n for n in right_candidates if n >= 0), default=len(text))
        return text[left + 1:right]

    def is_quoted_or_negated(match: re.Match) -> bool:
        clause = current_clause(match.start(), match.end())
        before = text[max(0, match.start() - 12):match.start()]
        if re.search(r"(?:沒有|不會|不打算|並未|從未).{0,4}(?:準備|備妥|拿|做|行動)", match.group(0)):
            return True
        # 第三人稱敘述先視為對他人的關心；當事人若也說明自己的行動，另行匹配。
        if (re.search(r"(朋友|同學|他|她|家人|老師).{0,5}(說|表示|提到|想|要|會)", clause)
                or re.search(r"(閨蜜|好友|朋友|同學|室友|網友|學長|學姊|學姐).{0,12}(傳|跟我說|告訴我)", clause)) \
                and not re.search(r"我(也|自己|現在|已經|準備)", clause):
            return True
        if re.search(r"(沒有|並未|從未|不會|不打算|不是|不想|別|不要).{0,3}$", before):
            return True
        if re.search(r"^(我)?(沒有|並未|從未|不會|不打算|不是|不想).{0,8}$", before):
            return True
        return False

    red_matches = []
    for pattern in RED_PATTERNS:
        red_matches.extend(match.group(0) for match in re.finditer(pattern, text, re.IGNORECASE)
                           if not is_quoted_or_negated(match))

    orange_matches = []
    for pattern in ORANGE_PATTERNS:
        orange_matches.extend(match.group(0) for match in re.finditer(pattern, text, re.IGNORECASE)
                              if not is_quoted_or_negated(match))

    yellow_matches = []
    for pattern in YELLOW_PATTERNS:
        yellow_matches.extend(match.group(0) for match in re.finditer(pattern, text, re.IGNORECASE)
                              if not is_quoted_or_negated(match))

    has_immediate_danger = len(red_matches) > 0
    has_self_harm_signal = len(orange_matches) > 0 or has_immediate_danger

    if has_immediate_danger:
        triggered_level = "red"
    elif has_self_harm_signal:
        triggered_level = "orange"
    elif len(yellow_matches) > 0:
        triggered_level = "yellow"
    else:
        triggered_level = "green"

    return {
        "triggered_level": triggered_level,
        "red_flags": red_matches,
        "orange_flags": orange_matches,
        "yellow_flags": yellow_matches,
        "hyperbole_flags": hyperbole,
        "has_immediate_danger": has_immediate_danger,
        "has_self_harm_signal": has_self_harm_signal
    }
