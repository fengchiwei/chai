"""青少年支持對話介面及經同意才分享的摘要工具。"""
import requests  # 保留既有整合測試的 API mock 入口。
from engine.dialogue_ai import (
    SYSTEM_PROMPT, ULTRA_WARM_SYSTEM_PROMPT, generate_youth_response,
    get_auto_warm_response, prepare_dialogue,
)

def _known(value):
    return isinstance(value, str) and value.strip() and value.strip() not in ("尚未提及", "尚未確認", "未提及", "近期")


def _impact_sentence(life_impact):
    """The self-check answers are labels (「有一點」「明顯影響（例如…）」), not examples: 「生活上也有些影響，例如有一點。」
    read badly (2026-10-23 live test). Free text from the conversation is still quoted as an example."""
    if not _known(life_impact):
        return ""
    value = life_impact.strip()
    if value.startswith(("沒有", "說不上來")):
        return ""
    if value.startswith("有一點"):
        return "生活上也受到一點影響。"
    if value.startswith("明顯影響"):
        return "已經明顯影響到上學或日常生活。"
    return f"生活上也有些影響，例如{value}。"


def generate_help_seeking_draft(case_info: dict, target: str = "輔導老師") -> str:
    """A short note the student can edit and send. Only a short topic is used, never the conversation itself,
    and fields the student has not mentioned are left out (2026-10-23 simulation: the note copied the chat
    verbatim and kept 「【尚未提及】」 blanks)."""
    # The workbench's own label (「自傷、家庭衝突」) never goes into a note the student hands to a teacher.
    concern = (case_info.get("category") if _known(case_info.get("category")) and not case_info.get("category_auto")
               else "心情和生活")
    duration = case_info.get("duration")
    life_impact = case_info.get("life_impact")
    since = f"，大概持續了{duration}" if _known(duration) and duration.strip() != "說不上來" else ""
    impact = _impact_sentence(life_impact)

    if target == "輔導老師":
        return (
            f"老師您好，我是＿年＿班的同學。\n"
            f"我最近因為{concern}的事情有些困擾{since}。{impact}\n"
            f"我一直不知道該怎麼開口，但覺得自己需要找人談一談。"
            f"請問老師這週是否有方便的時間，我可以去輔導室跟您聊聊大約 20 分鐘嗎？謝謝老師！"
        )
    elif target == "班導師":
        return (
            f"導師您好，想跟您說一下我最近的狀況。\n"
            f"我最近在{concern}上遇到了一些困難{since}。{impact}我希望能好好調適，想先讓老師知道我的情形，"
            f"如果有合適的資源或建議，再麻煩老師協助我，謝謝導師關心！"
        )
    else:
        return (
            f"爸媽/家人好，我最近一直有件事情壓在心裡不太舒服，是關於{concern}{since}。{impact}\n"
            f"我希望能跟你們坐下來好好聊聊，聽聽你們的想法，也希望你們能先聽聽我的感受，不要生氣好嗎？謝謝你們。"
        )

# Reminders for school staff by risk type. They point to the duty, not to a legal opinion; the system never
# reports on anyone's behalf (2026-10-23 simulation: no reporting prompt for abuse, no timeline for red cases).
REPORTING = {
    "suicide": "自殺／自傷風險：依校內自殺防治與三級輔導流程處理；有立即危險先打 119；依校內規定通知家長或監護人並留存紀錄；校安通報依教育部規定時限辦理。",
    "abuse": "疑似兒少保護或家庭暴力：教育人員知悉後應立即通報縣市主管機關，至遲不得超過 24 小時（兒少權法第 53 條、家庭暴力防治法第 50 條；可用「關懷 e 起來」線上通報或 113），並辦理校安通報。",
    "peer": "疑似校園霸凌（肢體）：先確保學生在校安全；依校園霸凌防制準則通報學校防制霸凌因應小組，並辦理校安通報。",
    "digital_sexual_violence": "疑似兒少性剝削或私密影像外流：教育人員知悉後應立即通報縣市主管機關（兒少性剝削防制條例）；涉及校園性別事件依性別平等教育法於 24 小時內通報；協助保全證據、申請下架。",
    "violence": "可能傷害他人：評估是否有立即危險，必要時報警（110）；通知學務處並依校安通報規定處理。",
}
# Same wording as the 燈號判讀說明 page (static/js/explain.js); staff never see the internal codes.
RISK_TYPE_LABELS = {"suicide": "自殺意念", "self_harm": "自傷", "abuse": "受虐／家暴", "violence": "暴力",
                    "digital_sexual_violence": "數位性暴力", "other": "其他"}
SUBJECT_LABELS = {"self": "學生本人", "other": "他人（朋友、同學等）", "unknown": "待確認"}
REPORTING_NOTE ="法條與時限請以最新公告及校內規定為準；本系統不會代為通報。"


def reporting_checklist(level, safety):
    if level not in ("orange", "red"):
        return []
    types = [t for t in (safety.get("risk_types") or [safety.get("risk_type")]) if t and t not in ("none", "other")]
    items = []
    for kind in types or ["suicide"]:
        key = "peer" if kind == "abuse" and safety.get("risk_cue") == "peer" else "suicide" if kind == "self_harm" else kind
        if REPORTING.get(key) and REPORTING[key] not in items:
            items.append(REPORTING[key])
    return items + [REPORTING_NOTE] if items else []


def generate_counselor_one_page_summary(case_info: dict, triage_result: dict) -> dict:
    bsrs = triage_result.get("bsrs_details", {})
    rules = triage_result.get("rule_details", {})
    level = triage_result.get("level", "green")
    
    if level == "red":
        safety_status = "【需立即確認】對話出現急迫危險訊號；規則檢出可能有誤，需真人立即覆核。"
        action_recommendation = "立刻由受訓人員確認現況；若正有立即危險，請撥打 119 並依所在機構正式流程處理。系統尚未自動通報。"
    elif level == "orange":
        safety_status = "【需優先覆核】對話或量表出現困擾／自傷相關訊號；當下安全狀態仍待確認。"
        action_recommendation = "由受訓人員優先確認當下安全及支持系統，再決定適當求助、聯繫或轉介。"
    elif level == "yellow":
        safety_status = "【待了解】有生活困擾訊號，現有資料不足以判斷完整狀況。"
        action_recommendation = "提供低門檻求助方式，必要時由真人進一步了解生活影響與安全狀態。"
    else:
        safety_status = "【資料有限】目前未偵測到規則警訊，不代表已完成安全評估。"
        action_recommendation = "保持一般關懷；有需要時提供求助資源。"

    self_harm_signals = []
    if (bsrs.get("suicide_score") or 0) > 0:
        self_harm_signals.append(f"量表自殺想法分數: {bsrs.get('suicide_score')} 分")
    if rules.get("red_flags"):
        self_harm_signals.extend([f"高危訊號: {f}" for f in rules["red_flags"]])
    if rules.get("orange_flags"):
        self_harm_signals.extend([f"規則安全訊號（類型待核對）: {f}" for f in rules["orange_flags"]])
    dialogue_safety = triage_result.get("dialogue_safety", {})
    if dialogue_safety.get("risk_signal", "none") != "none":
        kind = dialogue_safety.get("risk_type", "other")
        subject = dialogue_safety.get("risk_subject", "unknown")
        self_harm_signals.append("對話安全線索（非診斷）：" + RISK_TYPE_LABELS.get(kind, kind)
            + "；對象：" + SUBJECT_LABELS.get(subject, subject) + "；" + dialogue_safety.get("risk_evidence", ""))
    if not self_harm_signals:
        self_harm_signals.append("目前輸入未檢出相關訊號，不能據此排除風險")

    return {
        "summary_id": f"SUM-{case_info.get('case_id', 'ONLINE')}",
        "timestamp": case_info.get("created_at", "即時評估"),
        "student_alias": case_info.get("student_alias", case_info.get("persona", "匿名同學")),
        "township": case_info.get("township", "南投縣"),
        "risk_level": level,
        "risk_label": triage_result.get("label", "一般支持"),
        "primary_concern": case_info.get("category", "課業與人際適應"),
        "duration": case_info.get("duration", "近期"),
        "life_impact": case_info.get("life_impact", "日常生活一般維持"),
        "self_harm_signals": self_harm_signals,
        "current_safety": safety_status,
        "bsrs5_summary": {
            "total_score": bsrs.get("total_score"),
            "category": bsrs.get("category", "未施測"),
            "suicide_score": bsrs.get("suicide_score"),
            "details": bsrs.get("item_details", {})
        },
        "action_recommendation": action_recommendation,
        "reporting_checklist": reporting_checklist(level, dialogue_safety),
        "triage_explainability": triage_result.get("explainability", "評估完畢")
    }
