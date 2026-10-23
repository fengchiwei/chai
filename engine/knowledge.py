"""Stress-relief knowledge harness (docs/HARNESS_PLAN.md, phases P0–P2).

When a student on a green or yellow turn asks for a way to cope (the policy goal is support_choice), the most
relevant reviewed "knowledge cards" are found locally and given to the model as reference, so the reply rests on
current, cited sources instead of the model's memory. Nothing is fetched while chatting and the student's words are
never sent anywhere new. Safety turns never use cards; the existing safety flow answers them.

Cards live in data/knowledge/cards.json. Only cards whose every source is on the allowlist
(data/knowledge/sources.json), that are approved or in pilot, and that have not expired are used.
"""
import json
import logging
import math
import os
import re
from collections import Counter
from datetime import date
from urllib.parse import urlparse

BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "knowledge")
USABLE_STATUSES = {"approved", "pilot"}  # pilot: sources checked, waiting for a counsellor's review (P5)
MAX_CARDS = 2
MIN_SCORE = 4.0  # a topic or keyword match is needed; shared wording alone (「今天午餐吃咖哩飯」) is not enough
_cache = {}

# A question about facts or ways of doing something (「電子煙有什麼影響」「15 歲可以打工嗎」「被霸凌可以找誰」).
QUESTION = (r"[？?]|嗎|呢$|怎麼|如何|什麼|甚麼|哪裡|哪些|哪個|找誰|跟誰|多少|幾歲|幾點|多久|是不是|會不會|有沒有|要不要"
            r"|可以.{0,12}嗎|能不能|該不該")


def _load(name):
    path = os.path.join(BASE, name)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _cache[name] = (mtime, data)
    return data


def topics():
    data = _load("topics.json") or {}
    return data.get("topics", [])


def topic_hints():
    return {t["id"]: t["hints"] for t in topics() if t.get("hints")}


def matched_topics(message):
    return {topic for topic, pattern in topic_hints().items() if re.search(pattern, message or "")}


def asks_information(message):
    """A question on one of the knowledge-base topics; cards (or careful general facts) answer it."""
    return bool(re.search(QUESTION, message or "")) and bool(matched_topics(message))


def allowed_domains():
    data = _load("sources.json") or {}
    return {d for source in data.get("sources", []) for d in source.get("domains", [])}


def _domain_allowed(url, domains):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def usable(card, domains=None, today=None):
    """A card may reach students only if it is approved or in pilot, not expired, and fully sourced."""
    domains = allowed_domains() if domains is None else domains
    sources = card.get("sources") or []
    expires = card.get("expires_at")
    return (card.get("status") in USABLE_STATUSES and card.get("steps") and sources
            and all(s.get("url", "").startswith("https://") and _domain_allowed(s["url"], domains) for s in sources)
            and not (expires and expires < (today or date.today().isoformat())))


def cards():
    data = _load("cards.json") or []
    domains = allowed_domains()
    good = [c for c in data if usable(c, domains)]
    if len(good) != len(data):
        logging.info("知識卡：%d 張中有 %d 張不可用（未核可、過期或來源不在白名單）", len(data), len(data) - len(good))
    return good


def _grams(text):
    text = re.sub(r"[^\w㐀-鿿]", "", (text or "").lower())
    return [text[i:i + 2] for i in range(len(text) - 1)]


def _document(card):
    return " ".join([card.get("title", ""), card.get("summary", ""), " ".join(card.get("keywords", [])),
                     " ".join(card.get("steps", []))])


def search(message, limit=MAX_CARDS, pool=None):
    """Best cards for the message. A card is a candidate only if the message names its topic (topics.json hints)
    or one of its keywords; candidates are ranked by BM25 over character bigrams plus those matches."""
    pool = cards() if pool is None else pool
    if not pool:
        return []
    docs = [Counter(_grams(_document(c))) for c in pool]
    avg = sum(sum(d.values()) for d in docs) / len(docs)
    query = set(_grams(message))
    wanted_topics = matched_topics(message)
    scored = []
    for card, doc in zip(pool, docs):
        keyword_hits = sum(1 for k in card.get("keywords", []) if k and k in message)
        if not keyword_hits and card.get("topic") not in wanted_topics:
            continue  # shared wording alone (「我昨天去看電影」) never pulls a card
        length = sum(doc.values())
        score = 0.0
        for gram in query:
            if gram in doc:
                df = sum(1 for d in docs if gram in d)
                idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
                tf = doc[gram]
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg))
        score += 3.0 * keyword_hits
        if card.get("topic") in wanted_topics:
            score += 4.0  # the topic the student's words point to outweighs shared wording
        scored.append((score, card))
    scored.sort(key=lambda pair: -pair[0])
    return [card for score, card in scored[:limit] if score >= MIN_SCORE]


def wanted(state):
    """Cards are used only on non-safety turns where the policy decided to give a way to cope (support_choice) or
    to answer a question (answer_question), and the student has not asked for no advice."""
    return (state.get("current_goal") in ("support_choice", "answer_question")
            and "give_advice" not in state.get("forbidden_actions", [])
            and state.get("risk_level", "green") in ("green", "yellow")
            and not state.get("safety_check_required") and not state.get("safety_override"))


RESOURCES = os.path.join(os.path.dirname(BASE), "nantou_resources.json")
TOWNSHIPS = ("南投市", "埔里鎮", "草屯鎮", "竹山鎮", "集集鎮", "名間鄉", "鹿谷鄉", "中寮鄉", "魚池鄉", "國姓鄉", "水里鄉",
             "信義鄉", "仁愛鄉")
# 「南投哪裡可以諮商」「埔里附近有衛生所嗎」: a question about where to go, answered from the verified resource list.
LOCAL_INTENT = r"南投|附近|在地|哪裡|去哪|哪邊|找誰|衛生所|心衛中心|社區心理|諮商所|治療所|身心科|精神科|看醫生|掛號"
PLACE_KINDS = ((r"身心科|精神科|看醫生|醫院|掛號", ("醫院", "身心科診所", "地區醫院")),
               (r"衛生所", ("鄉鎮市衛生所",)),
               (r"諮商|心理|輔導|聊|談", ("社區心衛中心", "心理及聯合治療所", "校園輔導主管機構", "鄉鎮市衛生所")))
PUBLISHERS = (("data.gov.tw", "南投縣政府（政府資料開放平臺）"), ("ntshb.gov.tw", "南投縣政府衛生局"),
              ("mohw.gov.tw", "衛生福利部"), ("ntct.edu.tw", "南投縣政府教育處"), ("life1995.org.tw", "生命線協會"),
              ("1980.org.tw", "張老師基金會"))


def _publisher(url):
    host = urlparse(url).hostname or ""
    return next((name for domain, name in PUBLISHERS if host == domain or host.endswith("." + domain)), host)


def _township(message, state):
    for name in TOWNSHIPS:
        if name in message or name[:-1] in message:
            return name
    return (state or {}).get("township") or "南投市"


def local_resource_cards(message, state, limit=3):
    """Cards made from data/nantou_resources.json (phone, address, hours, source) for a 「where can I go」
    question about Nantou. Only entries with a recorded source; nearest township first."""
    topics = matched_topics(message)
    if not re.search(LOCAL_INTENT, message) or not (topics & {"counseling_access", "hotlines", "talking"}
                                                     or re.search(r"南投|" + "|".join(t[:-1] for t in TOWNSHIPS), message)):
        return []
    try:
        with open(RESOURCES, encoding="utf-8") as f:
            resources = json.load(f)
    except (OSError, ValueError):
        return []
    town = _township(message, state)
    kinds = next((k for pattern, k in PLACE_KINDS if re.search(pattern, message)), PLACE_KINDS[-1][1])
    nearby = [r for r in resources if r.get("source_url", "").startswith("https://") and any(k in r.get("category", "") for k in kinds)
              and (r.get("township") == town or town in (r.get("suggested_townships") or []))]
    nearby.sort(key=lambda r: next(i for i, k in enumerate(kinds) if k in r.get("category", "")))
    cards = []
    for r in nearby[:limit]:
        publisher = _publisher(r["source_url"])
        steps = [f"電話：{r['phone']}", f"地址：{r.get('address', '請先打電話詢問')}",
                 f"服務時間：{r['service_hours']}" if r.get("service_hours") else "第一次去之前，先打電話問怎麼預約、要帶什麼"]
        cards.append({"id": "resource-" + r["id"], "topic": "local_resources", "title": r["name"],
                      "summary": f"{r.get('category', '')}，在{r.get('township', town)}。", "steps": steps,
                      "when_to_seek_help": "有立即危險請直接撥 119；想馬上找人談可以打 1925（24 小時）。",
                      "sources": [{"publisher": publisher, "name": f"{r['name']}（{publisher}資料）", "url": r["source_url"],
                                   "supports": "名稱、電話、地址與服務時間"}]})
    return cards


def select(message, state):
    if not wanted(state):
        return []
    local = local_resource_cards(message, state)
    return (local + search(message, limit=1))[:MAX_CARDS + 1] if local else search(message)


def publishers(card):
    return [s.get("publisher") or s.get("name", "") for s in card.get("sources", [])]


REFERENCE_HEADER = "【本輪參考資料卡"


def prompt_block(selected):
    """Reference cards for the reply prompt; the student's words never go into card selection elsewhere."""
    if not selected:
        return ""
    lines = [REFERENCE_HEADER + "（來源已核對；學生在問方法或資訊）】",
             "請從下面挑最合適的一張，用自己的話回答學生的問題，或給一個做得到的小步驟（最多兩個選項），不要整張照念。"
             "卡片沒寫到的數字、日期、法規細節不要自己補；電話、地址照卡片原樣寫，不要改動。",
             "每張卡的來源各自支持不同重點（見「來源」）。句尾用「（資料來源：機構名稱）」標出你實際用到的那個重點的來源機構，"
             "用到兩個來源的重點就標兩個；只能寫下面列出的機構，不要提到其他研究或機構，也不要加入用藥建議。"]
    for i, card in enumerate(selected, 1):
        sources = "；".join(f"{s.get('publisher') or s.get('name')}〈{s.get('name', '')}〉支持：{s.get('supports', '')}"
                           for s in card["sources"])
        lines.append(f"卡{i}｜{card['title']}｜重點：{card.get('summary', '')}｜步驟：{'；'.join(card['steps'])}"
                     + (f"｜注意：{'；'.join(card['cautions'])}" if card.get("cautions") else "")
                     + f"｜何時找人：{card.get('when_to_seek_help', '')}｜來源：{sources}")
    return "\n".join(lines)


# Organisations a reply might name, with their other names. Naming one that is not on this turn's cards is an
# invented source; naming any alias of a card's organisation counts as citing that card.
ORG_GROUPS = [("世界衛生組織", "WHO", "World Health Organization"), ("衛福部", "衛生福利部"), ("國健署", "國民健康署"),
              ("心理健康司",), ("保護服務司",), ("食藥署", "食品藥物管理署"), ("教育部",), ("勞動部",),
              ("警政署", "刑事警察局", "165"), ("消防署",), ("iWIN", "網路內容防護"), ("疾管署", "疾病管制署"),
              ("CDC", "疾病管制與預防中心", "Centers for Disease Control"),
              ("NHS", "國民保健署", "National Health Service"),
              ("NIMH", "國家心理衛生研究院", "National Institute of Mental Health"),
              ("UNICEF", "聯合國兒童基金會"), ("哈佛", "Harvard"), ("史丹佛", "Stanford"), ("美國心理學會", "APA"),
              ("美國兒科醫學會", "AAP", "HealthyChildren", "American Academy of Pediatrics"),
              ("美國睡眠醫學會", "AASM"), ("Cochrane",), ("董氏基金會",), ("梅約", "Mayo"), ("臺大醫院", "台大醫院"),
              ("北榮", "臺北榮民總醫院", "台北榮總")]


def _aliases(publisher):
    names = {publisher, *re.findall(r"[（(]([^）)]+)[）)]", publisher), re.sub(r"[（(].*?[）)]", "", publisher).strip()}
    for group in ORG_GROUPS:
        if any(alias.lower() in publisher.lower() for alias in group):
            names.update(group)
    return {n for n in names if n and len(n) >= 2}


def _mentions(text, publisher):
    return any(name.lower() in text.lower() for name in _aliases(publisher))


def cited(reply, selected):
    """Cards whose source organisation the reply names (shown to the student as links)."""
    return [card for card in selected if any(name and _mentions(reply, name) for name in publishers(card))]


def invented_source(reply, selected):
    """True when the reply cites a source that was not given: a 「資料來源：X」 naming none of this turn's cards, or
    a known organisation that is not among this turn's card publishers."""
    given = [p for card in selected for p in publishers(card)]
    # Pointing to 1925 (衛福部安心專線) is a hotline, not a cited source.
    reply = re.sub(r"(?:衛福部|衛生福利部)\s*的?\s*(?:1925|安心專線)", "", reply)
    for named in re.findall(r"資料來源[:：]\s*([^）)\n。]+)", reply):
        if not any(_mentions(named, p) for p in given):
            return True
    for group in ORG_GROUPS:
        if any(alias.lower() in reply.lower() for alias in group) and not any(
                alias.lower() in p.lower() for p in given for alias in group):
            return True
    return False


def public_sources(reply, selected, limit=2):
    """The pages the reply actually drew on, for the links under it: each source whose organisation the reply
    names, best match to the reply first, labelled with the page's own title. A link labelled with the card's title
    once pointed to a press release about quitting smoking (2026-10-23 live test)."""
    words = set(_grams(reply))
    found = []
    for card in selected:
        for source in card.get("sources", []):
            publisher = source.get("publisher") or source.get("name", "")
            if not _mentions(reply, publisher):
                continue
            overlap = len(words & set(_grams(source.get("supports", "") + source.get("name", ""))))
            found.append((overlap, {"title": source.get("name") or card["title"], "publisher": publisher,
                                    "url": source["url"], "card": card["title"]}))
    found.sort(key=lambda pair: -pair[0])
    shown, seen = [], set()
    for _, item in found:
        if item["url"] not in seen:
            seen.add(item["url"])
            shown.append(item)
    return shown[:limit]
