"""BSRS-5 前五題及自殺想法附加題的自填計分；未施測不等於零分。"""

ITEMS = {
    "sleep": "睡眠困難",
    "anxiety": "緊張不安",
    "anger": "苦惱動怒",
    "depression": "憂鬱低落",
    "inferiority": "比不上別人",
    "suicide": "自殺想法（附加題）",
}
LABELS = {0: "完全沒有", 1: "輕微", 2: "中等程度", 3: "厲害", 4: "非常厲害"}


def evaluate_bsrs5(answers: dict | None) -> dict:
    if not answers:
        return {
            "completed": False,
            "total_score": None,
            "max_score": 20,
            "suicide_score": None,
            "category": "未施測",
            "category_desc": "沒有填寫正式 BSRS-5，不能據此推論分數或安全狀態。",
            "baseline_risk": "green",
            "suicide_alert": False,
            "item_details": {},
        }
    if not isinstance(answers, dict) or any(key not in answers for key in ITEMS):
        raise ValueError("BSRS-5 需完整填寫六題；未施測請不要提交答案")

    scores = {}
    for key in ITEMS:
        value = answers[key]
        if isinstance(value, bool) or isinstance(value, float) or not str(value).isdigit():
            raise ValueError(f"{ITEMS[key]} 必須為 0 至 4 的整數")
        value = int(value)
        if not 0 <= value <= 4:
            raise ValueError(f"{ITEMS[key]} 必須為 0 至 4 的整數")
        scores[key] = value

    total = sum(scores[key] for key in list(ITEMS)[:5])
    suicide = scores["suicide"]
    if total <= 5:
        category = "一般範圍"
        baseline = "green"
    elif total <= 9:
        category = "輕度情緒困擾"
        baseline = "yellow"
    elif total <= 14:
        category = "中度情緒困擾"
        baseline = "yellow"
    else:
        category = "重度情緒困擾"
        baseline = "orange"
    # 1 分應進一步詢問；2 分以上需要優先由真人覆核。單一分數不判定立即危機。
    if suicide >= 2:
        baseline = "orange"
    elif suicide == 1 and baseline == "green":
        baseline = "yellow"

    return {
        "completed": True,
        "total_score": total,
        "max_score": 20,
        "suicide_score": suicide,
        "category": category,
        "category_desc": "量表供自我檢視與真人覆核參考，不能單獨作為診斷或危機結論。",
        "baseline_risk": baseline,
        "suicide_alert": suicide >= 2,
        "item_details": {
            key: {"score": value, "label": ITEMS[key], "rating": LABELS[value]}
            for key, value in scores.items()
        },
    }
