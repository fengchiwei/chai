"""
四級風險分流決策引擎 (4-Tier Risk Triage Engine)
整合:
1. BSRS-5 簡式健康量表 (量化評估)
2. 危機關鍵規則引擎 (質性語意/固定條件)
3. 質性情境核對 (持續時間、生活功能影響、支持系統)

核心原則 (依計畫書規範):
- 質性資料與生活受損可「提高」風險層級，但「絕不任意降低」量表或危機規則所指出的風險！
- 自殺想法附加題 >= 2 分 或 出現自傷意念 -> 至少「橙色｜優先覆核」並阻斷一般 AI 回應。
- 具備具體工具、時間、地點或正在行動 -> 直接進入「紅色｜立即危機」。
"""

from engine.bsrs5 import evaluate_bsrs5
from engine.rules import analyze_crisis_rules

RISK_LEVEL_WEIGHTS = {
    "green": 1,
    "yellow": 2,
    "orange": 3,
    "red": 4
}

RISK_METADATA = {
    "green": {
        "label": "一般支持",
        "badge_color": "#10b981",
        "description": "短期一般壓力、情緒低落，生活功能大致維持。",
        "system_action": "AI 持續提供情緒整理、自我照顧與心理健康資訊。",
        "human_role": "原則上不需立即介入，定期追蹤即可。",
        "circuit_breaker": False,
        "counselor_required": False
    },
    "yellow": {
        "label": "建議求助",
        "badge_color": "#f59e0b",
        "description": "困擾持續、睡眠或上學受影響，但未發現立即危機。",
        "system_action": "建議聯繫可信任成人、輔導老師或心理資源，並提供求助文字草稿。",
        "human_role": "由使用者主動選擇是否聯繫，輔導室可提供低門檻信箱諮詢。",
        "circuit_breaker": False,
        "counselor_required": False
    },
    "orange": {
        "label": "優先覆核",
        "badge_color": "#f97316",
        "description": "對話出現自傷想法、過度壓力造成之不確定行為、生活功能明顯下降、支持系統不足，立即性尚待確認。",
        "system_action": "停止一般建議，確認當下安全，產生一頁式摘要並進入真人工作臺。",
        "human_role": "受訓輔導人員或心理師優先覆核與聯繫。",
        "circuit_breaker": True,
        "counselor_required": True
    },
    "red": {
        "label": "立即危機",
        "badge_color": "#ef4444",
        "description": "有具體自傷計畫、工具、時間、正在行動或當下人身安全有立即疑慮。",
        "system_action": "立即停止一般對話，顯示緊急求助與可信任成人聯繫方式，啟動最高優先真人流程。",
        "human_role": "由真人依機構 SOP 及警消醫療機制進行緊急危機處理。",
        "circuit_breaker": True,
        "counselor_required": True
    }
}

def perform_triage(
    text: str = "",
    bsrs5_answers: dict = None,
    duration: str = "",
    life_impact: str = "",
    support_system: str = "",
    previous_level: str = "green"
) -> dict:
    bsrs_result = evaluate_bsrs5(bsrs5_answers)
    rule_result = analyze_crisis_rules(f"{text} {life_impact}")

    current_level = bsrs_result["baseline_risk"]
    reasons = []

    # 1. 檢視 BSRS-5 分數
    if bsrs_result["suicide_score"] is not None and bsrs_result["suicide_score"] >= 2:
        current_level = "orange"
        reasons.append(f"簡式健康量表自殺想法附加題得分為 {bsrs_result['suicide_score']} 分 (中等度以上警戒)")
    elif bsrs_result["total_score"] is not None and bsrs_result["total_score"] >= 15:
        if RISK_LEVEL_WEIGHTS["orange"] > RISK_LEVEL_WEIGHTS[current_level]:
            current_level = "orange"
        reasons.append(f"簡式健康量表前5題總分為 {bsrs_result['total_score']} 分 (重度困擾)")
    elif bsrs_result["total_score"] is not None and bsrs_result["total_score"] >= 10:
        if RISK_LEVEL_WEIGHTS["yellow"] > RISK_LEVEL_WEIGHTS[current_level]:
            current_level = "yellow"
        reasons.append(f"簡式健康量表前5題總分為 {bsrs_result['total_score']} 分 (中度困擾)")

    # 2. 檢視危機關鍵規則引擎 (可單向拉高至紅/橙)
    if rule_result["has_immediate_danger"]:
        current_level = "red"
        reasons.append(f"偵測到立即致命性危機特徵/工具/行動: {', '.join(rule_result['red_flags'])}")
    elif rule_result["has_self_harm_signal"]:
        if RISK_LEVEL_WEIGHTS["orange"] > RISK_LEVEL_WEIGHTS[current_level]:
            current_level = "orange"
        reasons.append(f"偵測到需優先核對的安全警訊: {', '.join(rule_result['orange_flags'])}")
    elif len(rule_result["yellow_flags"]) > 0:
        if RISK_LEVEL_WEIGHTS["yellow"] > RISK_LEVEL_WEIGHTS[current_level]:
            current_level = "yellow"
        reasons.append(f"文字呈現顯著壓力或困擾訊號: {', '.join(rule_result['yellow_flags'])}")

    # 3. 質性加權考量 (只能拉高，不可降低)
    duration_clean = duration.replace(" ", "").lower()
    if any(k in duration_clean for k in ["1個月", "超過", "2個月", "3週", "4週", "長期"]) and current_level == "green":
        # 困擾若已持續 3 週以上或達 1 個月，即使量表在輕度區間亦建議求助
        current_level = "yellow"
        reasons.append(f"困擾持續時間長達 {duration}，已超出短期調適週期")

    if life_impact:
        impact_clean = life_impact.replace(" ", "").lower()
        if any(w in impact_clean for w in ["中輟", "拒學", "嚴重失眠", "無法出門", "喪親"]):
            if RISK_LEVEL_WEIGHTS["yellow"] > RISK_LEVEL_WEIGHTS[current_level]:
                current_level = "yellow"
            reasons.append(f"生活功能或就學狀態顯著受損: {life_impact}")

    if support_system:
        sup_clean = support_system.replace(" ", "").lower()
        if any(w in sup_clean for w in ["孤立", "沒有人", "不敢說", "無人陪伴", "隱瞞"]):
            if current_level == "yellow":
                reasons.append("支持系統顯著缺乏或無法發揮保護功能")

    if previous_level in RISK_LEVEL_WEIGHTS and RISK_LEVEL_WEIGHTS[previous_level] > RISK_LEVEL_WEIGHTS[current_level]:
        current_level = previous_level
        reasons.append("本次對話先前曾出現較高安全警訊，仍需真人覆核")

    meta = RISK_METADATA[current_level]

    return {
        "level": current_level,
        "label": meta["label"],
        "badge_color": meta["badge_color"],
        "description": meta["description"],
        "system_action": meta["system_action"],
        "human_role": meta["human_role"],
        "circuit_breaker": meta["circuit_breaker"],
        "counselor_required": meta["counselor_required"],
        "bsrs_details": bsrs_result,
        "rule_details": rule_result,
        "reasons": reasons,
        "explainability": "；".join(reasons) if reasons else "目前資訊不足以判定完整身心狀態；暫未偵測到規則警訊。"
    }
