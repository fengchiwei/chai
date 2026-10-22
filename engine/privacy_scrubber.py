"""v2.3 Phase 2: mask personal identifiers before any text leaves for a cloud model.

Only the copy sent to the model is masked. Safety rules, wellbeing notes and the encrypted
database keep the original words, because a masked crisis sentence must still be detected.
Pattern-based masking misses unusual formats; it reduces exposure, it does not guarantee it.
"""
import re

_SURNAMES = ("陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余盧梁趙顏柯翁"
             "魏孫戴范方宋鄧杜傅侯曹薛丁卓阮馬董温溫唐藍蔣石古紀姚連馮歐程湯田康姜白汪鄒尤巫鐘黎涂龔嚴韓袁"
             "金童陸夏柳邵錢伍倪于譚駱熊任甘秦顧毛章史官萬俞雷粘饒")
_SURNAME = r"(?:歐陽|司馬|張簡|范姜|[" + _SURNAMES + r"])"
_HAN = r"[\u4e00-\u9fff]"
# Chinese characters count as word characters, so ASCII identifiers use explicit lookarounds, not \b.

PII_RULES = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[帳號已隱碼]"),
    ("social", re.compile(r"(?i)(?<![A-Za-z])(line|ig|instagram|fb|facebook|discord|dc|threads|tiktok)\s*(?:id|帳號)?\s*[:：是]?\s*@?[A-Za-z0-9_.-]{3,30}"),
     r"\1 [帳號已隱碼]"),
    ("national_id", re.compile(r"(?<![A-Za-z0-9])[A-Z][1289A-D]\d{8}(?![0-9])"), "[身分證/學號已隱碼]"),
    ("student_id", re.compile(r"(學號|座號|准考證號?)\s*[:：是]?\s*[A-Za-z]?\d{4,10}"), r"\1[身分證/學號已隱碼]"),
    ("phone", re.compile(r"(?:\+886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}|\(?0\d{1,2}\)?[-\s]?\d{3,4}[-\s]?\d{4}"), "[電話已隱碼]"),
    ("address", re.compile(
        r"(?:" + _HAN + r"{2}[縣市])?" + _HAN + r"{1,3}[鄉鎮市區]" + _HAN + r"{0,6}?(?:路|街|大道)"
        r"(?:[一二三四五六七八九十\d]+段)?(?:\d+巷)?(?:\d+弄)?\d+號(?:之\d+)?(?:\d+樓)?"
        r"|" + _HAN + r"{1,6}(?:路|街|大道)(?:[一二三四五六七八九十\d]+段)?(?:\d+巷)?(?:\d+弄)?\d+號(?:之\d+)?(?:\d+樓)?"), "[地址已隱碼]"),
    ("name", re.compile(r"(我叫|我的名字(?:是|叫)|名字叫|本名(?:是|叫)?)(" + _SURNAME + _HAN + r"{1,2}|[小阿]" + _HAN + r"{1,2})"),
     r"\1[姓名已隱碼]"),
    ("name", re.compile(r"(我是)(" + _SURNAME + _HAN + r"{1,2})(?=[，,。！!？?\s]|$)"), r"\1[姓名已隱碼]"),
]
_LEAD = "住在於"


def _mask_address(match):
    text = match.group(0)
    # Keep a leading verb such as 住/在 that the optional county prefix may have absorbed.
    return (text[0] + "[地址已隱碼]") if text[0] in _LEAD else "[地址已隱碼]"


def scrub_pii(text):
    if not isinstance(text, str) or not text:
        return text
    for kind, pattern, replacement in PII_RULES:
        text = pattern.sub(_mask_address if kind == "address" else replacement, text)
    return text


def pii_findings(text):
    """Kinds of identifiers found (for tests and the explain dashboard); never returns the values."""
    if not isinstance(text, str):
        return []
    return list(dict.fromkeys(kind for kind, pattern, _ in PII_RULES if pattern.search(text)))
