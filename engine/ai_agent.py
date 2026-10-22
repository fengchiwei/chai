"""青少年支持對話介面及經同意才分享的摘要工具。"""
import requests  # 保留既有整合測試的 API mock 入口。
from engine.dialogue_ai import (
    SYSTEM_PROMPT, ULTRA_WARM_SYSTEM_PROMPT, generate_youth_response,
    get_auto_warm_response, prepare_dialogue,
)

def generate_help_seeking_draft(case_info: dict, target: str = "輔導老師") -> str:
    concern = case_info.get("category", "近期心理與生活困擾")
    duration = case_info.get("duration", "最近一段時間")
    life_impact = case_info.get("life_impact", "情緒低落與睡眠不佳")

    if target == "輔導老師":
        return (
            f"老師您好，我是班上的同學。\n"
            f"我最近因為【{concern}】的事情，大概持續了【{duration}】，"
            f"生活上有些影響，例如【{life_impact}】。\n"
            f"我一直不知道該怎麼開口，但覺得自己需要找人談一談。"
            f"請問老師這週是否有方便的時間，我可以去輔導室跟您聊聊大約 20 分鐘嗎？謝謝老師！"
        )
    elif target == "班導師":
        return (
            f"導師您好，想跟您說一下我最近的狀況。\n"
            f"我最近在【{concern}】上遇到了困難，感到有些焦慮和吃力，"
            f"狀況大概有【{duration}】了。我希望能好好調適，想先讓老師知道我的情形，"
            f"如果有合適的資源或建議，再麻煩老師協助我，謝謝導師關心！"
        )
    else:
        return (
            f"爸媽/家人好，我最近一直有件事情壓在心裡不太舒服，是關於【{concern}】。\n"
            f"已經煩惱了【{duration}】，我發現自己晚上常常睡不好，也很難專心。"
            f"我希望能跟你們坐下來好好聊聊，聽聽你們的想法，也希望你們能先聽聽我的感受，不要生氣好嗎？謝謝你們。"
        )

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
        self_harm_signals.append("對話安全線索（非診斷）：" + dialogue_safety.get("risk_type", "other")
            + "；對象：" + dialogue_safety.get("risk_subject", "unknown") + "；" + dialogue_safety.get("risk_evidence", ""))
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
        "triage_explainability": triage_result.get("explainability", "評估完畢")
    }
