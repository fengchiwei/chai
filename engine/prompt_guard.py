"""v1.3-B.1: keep student text as data when it enters a model prompt; catch leaked internals.

Defence in depth only. Safety levels are decided by rules before any model call and can
never be lowered by a model, so this module never changes triage or the safety path.
Stored quotes stay verbatim; only the copy sent to a model is neutralised.
"""
import re

PATTERNS = {
    "override": re.compile(
        r"(?:忽略|無視|忘記|忘掉|跳過|不要理會?)(?:你)?(?:之前|先前|以上|上面|前面|所有|全部|原本|原來|一切)+的?(?:所有)?"
        r"(?:指令|指示|規則|設定|限制|提示詞|提示|prompt)"
        r"|ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|rules|prompts?)"
        r"|disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above)", re.I),
    "reveal": re.compile(
        r"(?:系統|內部|原始|隱藏|後台)(?:提示詞|提示|指令|prompt)"
        r"|system\s*prompt|你的(?:提示詞|指令|prompt|規則全文)"
        r"|(?:顯示|列出|貼出|貼給我|告訴我|輸出|印出|複製).{0,12}(?:提示詞|prompt|指令|系統設定|內部設定)", re.I),
    "jailbreak": re.compile(
        r"開發者模式|developer\s*mode|\bDAN\b|越獄|jailbreak|沒有(?:任何)?(?:限制|規則)的\s*AI"
        r"|(?:解除|關閉|取消)(?:所有|你的)?(?:限制|安全(?:流程|規則|限制)?)", re.I),
    "fake_marker": re.compile(
        r"(?im)^\s*(?:system|assistant|developer|系統|助理|管理員|開發者)\s*[:：]"
        r"|【[^】]{0,20}(?:系統|決策|指令|規則|記憶|設定)[^】]{0,20}】"
        r"|<\|[^|>]{0,20}\|>|</?(?:system|assistant|user)>"
        r"|\"(?:current_goal|risk_level|max_questions|safety_[a-z_]+)\"\s*:", re.I),
}

_BRACKET = re.compile(r"【([^】]{0,40})】")
_ROLE_PREFIX = re.compile(r"(?im)^(\s*)(system|assistant|developer|user|系統|助理|管理員|開發者)\s*[:：]")
_SPECIAL = re.compile(r"<\|[^|>]{0,20}\|>|</?(?:system|assistant|user)>", re.I)

# Field names of the internal decision state and prompt headings that must never reach a student.
_INTERNAL = re.compile(
    r"current_goal|response_strategy|max_questions|forbidden_actions|safety_check_required|safety_override"
    r"|risk_level|iceberg_stage|semantic_status|dialogue_content|human_escalation"
    r"|系統提示詞(?:是|如下|內容)|我的(?:系統)?(?:提示詞|指令)(?:是|如下)|以下是我的(?:設定|指令|提示詞)")
_JAILBREAK_ACK = re.compile(
    r"(?:開發者|越獄|DAN|無限制)模式(?:已|已經)?(?:啟用|開啟|啟動)"
    r"|(?:安全|所有)?(?:限制|規則|過濾)(?:都)?(?:已|已經)(?:解除|關閉|移除|取消)"
    r"|我(?:現在)?(?:沒有|不受)任何(?:限制|規則)", re.I)
_MIN_LEAK_LINE = 14


def detect_injection(text):
    """Names of override patterns found in a student's text; empty for ordinary messages."""
    if not isinstance(text, str):
        return []
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


def as_data(text):
    """Copy of student text for a model prompt that cannot imitate our section markers or chat roles."""
    if not isinstance(text, str):
        return ""
    text = _SPECIAL.sub("", text)
    text = _BRACKET.sub(r"［\1］", text)
    return _ROLE_PREFIX.sub(r"\1\2（學生輸入的文字）：", text)


def _prompt_lines(prompt):
    return [line.strip() for line in (prompt or "").splitlines() if len(line.strip()) >= _MIN_LEAK_LINE]


def output_issues(reply, prompt=""):
    """Mechanical leak checks on a model reply, used alongside response_violations."""
    issues = []
    if not isinstance(reply, str):
        return issues
    headings = re.findall(r"【[^】]{2,20}】", prompt or "")
    if _INTERNAL.search(reply) or any(h in reply for h in headings) or any(
            line in reply for line in _prompt_lines(prompt)):
        issues.append("internal_leak")
    if _JAILBREAK_ACK.search(reply):
        issues.append("jailbreak_ack")
    return issues
