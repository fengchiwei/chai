"""School counseling-office referral for gender-equity (性平) and bullying topics.

Whatever the risk level, a student who mentions sexual harassment / assault, intimate images, gender-based
teasing or bullying is told the school counseling office (輔導室) can help, and gets a referral note they can
edit and hand in. If they choose to name their school, any of the 4,000-odd schools in the Ministry of Education
directory (data/schools_moe.json: main phone, address, website) can be found; when the team has also verified
that school's counseling-office email, the note can be opened as an email draft. Nothing is ever sent by the
system: the student's own mail app opens and the student decides whether to send.

Verified counseling contacts live in data/school_counseling.json. Every entry needs an https source page and a
verification date; entries without them are ignored, so no address is ever guessed.
"""
import json
import os
import re
from urllib.parse import quote

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "school_counseling.json")
MOE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "schools_moe.json")
MOE_PAGE = "https://depart.moe.edu.tw/ED4500/News.aspx?n=63F5AB3D02A8BBAC&sms=1FF9979D10DBF9F3"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

TOPICS = {
    "gender_equity": {
        "label": "性平事件",
        "note_label": "性別平等（例如讓我不舒服的身體碰觸、言語或影像）",
        "pattern": re.compile(
            r"性騷擾?|性侵|強暴|猥褻|性平|性別平等|約會暴力|偷拍|裙底|私密(?:照|影片|影像)|裸照|色情(?:照|影片|圖)"
            r"|毛手毛腳|亂摸|摸我(?!的?(?:頭|頭髮|額頭|肩膀|臉頰))|摸(?:我的)?(?:胸|屁股|大腿|下面)"
            r"|逼我(?:脫|看(?:A片|色情)|拍(?:裸|私密))|要我(?:傳|拍)(?:裸照|私密照)"
            r"|娘炮|娘娘腔|男人婆|死gay|gay砲|人妖|(?:笑|罵|嘲笑|針對).{0,6}(?:性向|性別|同性戀|gay|太娘|不像男生|不像女生)"
            # Grooming-like messages (2026-10-23 live test: 「補習班老師一直私訊我，說我身材很好，還叫我不要跟別人說」).
            r"|(?:說|誇|評論|問|摸)我的?(?:身材|胸部?|腿|屁股|身體|內衣)"
            r"|私訊.{0,30}(?:身材|性感|單獨見面|約我出去|不要跟別人|別跟別人|不能跟別人|不要告訴|別告訴)"
            r"|(?:傳|私訊|寄).{0,8}(?:噁心|色色|色情|曖昧|露骨)的?(?:訊息|照片|話|圖|影片)",
            re.I),
    },
    "bullying": {
        "label": "霸凌",
        "note_label": "校園霸凌（被欺負、排擠或網路上被針對）",
        "pattern": re.compile(
            r"霸凌|被排擠|被孤立|被欺負|欺負我|(?:排擠|孤立|針對|嘲笑|取笑)我|被勒索|勒索我|被圍毆|圍毆我|被堵|被造謠|造我的?謠|散播.{0,6}謠言"
            r"|被肉搜|被起底|被公審|被(?:全班|大家|同學).{0,4}(?:笑|嘲笑|排擠|孤立|無視|針對|罵)"
            r"|同學都(?:不理我|笑我|討厭我|針對我|排擠我)|被取(?:難聽的)?綽號"
            # Online bullying (2026-10-23 live test: 「他們一直在LINE群組裡笑我，還把我的照片做成梗圖」).
            r"|(?:群組|班群|IG|限動|貼文|LINE|Line|留言|Dcard|脆).{0,10}(?:笑我|罵我|嘲笑我|酸我|嗆我|針對我|公審我)"
            r"|(?:一直|都在|大家都|全班都).{0,4}(?:笑我|酸我|嗆我)"
            r"|(?:把我|我的).{0,10}(?:照片|醜照|影片).{0,12}(?:梗圖|亂傳|傳到|貼到|散布|散佈|P成|p成)|把我.{0,6}做成梗圖"
            r"|(?:搶|藏|丟)我的?(?:東西|錢|書包|鞋子?|課本)|把我的?(?:東西|書包|鞋子?|課本)(?:丟|藏|搶|弄壞|撕)"),
    },
}
# 「沒有被霸凌」「不是性騷擾」 deny the event; 「被數學霸凌」「被考試霸凌」 are jokes about schoolwork.
NEGATED = re.compile(r"(?:沒有|沒|不是|並未|從未|不算)被?\s*$")
JOKE = re.compile(r"(?:數學|英文|國文|物理|化學|考試|作業|功課|題目|天氣|老天|鬧鐘|段考)\s*$")

NOTICES = {
    "gender_equity": {
        "text": "學校老師知道性平事件後，依法要在 24 小時內通報，並交給學校的性別平等教育委員會處理；你和相關的人的身分、資料依法要保密。"
                "你不用先判斷「這算不算」，老師會陪你一起弄清楚。發生在校外、或不方便找學校時，可以打 113 保護專線（24 小時）。",
        "source": {"publisher": "全國法規資料庫", "title": "性別平等教育法",
                   "url": "https://edu.law.moe.gov.tw/LawContent.aspx?id=FL030508"},
    },
    "bullying": {
        "text": "學校接到後會啟動防制霸凌的處理，先保護你的安全；你也可以請信任的同學陪你一起去。"
                "不方便直接找學校時，可以打教育部反霸凌專線 1953（24 小時）。",
        "source": {"publisher": "教育部防制校園霸凌專區", "title": "被霸凌或看見霸凌，可以怎麼做",
                   "url": "https://bully.moe.edu.tw/details/208"},
    },
}


def detect_topics(text):
    """Topic keys mentioned in the student's own words (not denied, not a joke about homework)."""
    found = []
    for key, topic in TOPICS.items():
        for match in topic["pattern"].finditer(text or ""):
            before = text[max(0, match.start() - 6):match.start()]
            if NEGATED.search(before) or (key == "bullying" and JOKE.search(before)):
                continue
            found.append(key)
            break
    return found


LONG_FORMS = (("國民小學", "國小"), ("國民中學", "國中"), ("高級中等學校", "高中"), ("高級中學", "高中"),
              ("完全中學", "高中"))
PREFIX = re.compile(r"^(?:國立|私立|公立|縣立|市立|..[縣市]立)")


def _variants(name):
    """Ways a student may write a school name: 「國立南投高中」→ 南投高中; 「私立均頭國中(小)」→ 均頭國中, 均頭國中小.
    Names shorter than 3 characters (「高中」) are dropped, so they never match anything."""
    full = re.sub(r"[\s　]", "", name or "").replace("臺", "台").replace("（", "(").replace("）", ")")
    for long, short in LONG_FORMS:
        full = full.replace(long, short)
    bare = PREFIX.sub("", full)
    names = {full, bare, re.sub(r"\(.*?\)", "", bare), re.sub(r"[()]", "", bare)}
    # 「建國高中」 is listed as 「建國中學」, and the other way round.
    names |= {n[:-2] + ("中學" if n.endswith("高中") else "高中") for n in names if n.endswith(("高中", "中學"))}
    return {v for v in names if len(v) >= 3}


_moe = {"mtime": None, "schools": []}


def moe_schools():
    """Every school in the Ministry of Education directory (scripts/import_moe_schools.py), with name variants."""
    try:
        mtime = os.path.getmtime(MOE)
        if _moe["mtime"] != mtime:
            with open(MOE, encoding="utf-8") as f:
                schools = json.load(f).get("schools", [])
            _moe.update(mtime=mtime, schools=[{**s, "_names": _variants(s["name"])} for s in schools
                                              if isinstance(s, dict) and s.get("code") and s.get("name")])
    except (OSError, ValueError, AttributeError):
        return []
    return _moe["schools"]


def directory():
    """Verified counseling-office contacts only: a name, a valid email, an https source page and a date."""
    try:
        with open(DATA, encoding="utf-8") as f:
            schools = json.load(f).get("schools", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [s for s in schools if isinstance(s, dict) and s.get("name") and EMAIL.fullmatch(s.get("email", ""))
            and str(s.get("source_url", "")).startswith("https://") and s.get("verified_on")]


def verified_contact(school):
    """The team-verified counseling contact for a directory school (same code, or same name), or None."""
    for entry in directory():
        names = set().union(*(_variants(n) for n in [entry["name"], *entry.get("aliases", [])]))
        if entry.get("code") == school["code"] or names & school["_names"]:
            return entry
    return None


def _score(school, wanted):
    if wanted & school["_names"]:
        return 3  # the name itself
    if any(n in w for n in school["_names"] for w in wanted):
        return 2  # 「我讀南投國中二年級」
    if any(w in n for n in school["_names"] for w in wanted):
        return 1  # 「暨大附」
    return 0


def search_schools(text, county=None, limit=8):
    """Directory schools the student's words point to, best first: exact names before partial ones, and among
    schools of the same name (中正國小) the student's own county first."""
    wanted = _variants(text)
    if not wanted:
        return []
    scored = [(score, school) for school in moe_schools() if (score := _score(school, wanted))]
    scored.sort(key=lambda x: (-x[0], x[1]["county"] != county, x[1]["code"]))
    return [(score, school) for score, school in scored[:limit]]


def pick_school(text=None, code=None, county=None):
    """(school, choices): one school when the words point to one; when several share the name and one is in the
    student's county, that one plus the others as choices (「不是這間？」); otherwise up to 8 choices."""
    if code:
        return next((s for s in moe_schools() if s["code"] == code), None), []
    matches = search_schools(text, county)
    if not matches:
        return None, []
    best = [school for score, school in matches if score == matches[0][0]]
    local = [school for school in best if school["county"] == county]
    if len(best) == 1:
        return best[0], []
    if len(local) == 1:
        return local[0], [school for school in best if school is not local[0]]
    return None, [school for _, school in matches]


def contact(school, note):
    """What the page shows for one school: its main line, website and the directory source, plus the
    verified counseling-office email (and a mail draft) only when the team has one."""
    verified = verified_contact(school)
    out = {"code": school["code"], "name": school["name"], "county": school["county"],
           "address": school["address"], "phone": school["phone"],
           "phone_href": "tel:" + re.sub(r"[^0-9]", "", school["phone"]) if school["phone"] else "",
           "website": school["website"] if re.match(r"https?://", school.get("website") or "") else "",
           "source": "教育部統計處各級學校名錄", "source_url": MOE_PAGE,
           "office": "輔導室", "email": "", "mailto": ""}
    if verified:
        out.update(office=verified.get("office", "輔導室"), email=verified["email"],
                   email_source_url=verified["source_url"], office_phone=verified.get("phone", ""),
                   mailto=mail_draft(verified, note))
    return out


def referral_note(topic_keys, school_name=""):
    """A note the student can edit and hand to the counseling office. Only the topic is named, never what the
    student wrote, so the student decides how much to tell."""
    topics = "、".join(TOPICS[k]["note_label"] for k in topic_keys if k in TOPICS) or "最近在學校遇到的事"
    to = f"{school_name}輔導室老師您好：" if school_name else "輔導室老師您好："
    return (
        f"{to}\n\n"
        f"我想跟輔導室談一件和{topics}有關的事。\n"
        "這件事讓我有些困擾，想找老師當面談談，也想先了解接下來學校會怎麼處理、有哪些人會知道。\n\n"
        "我是：＿＿＿＿（班級、姓名，也可以見面時再說）\n"
        "方便談的時間：＿＿＿＿\n"
        "可以聯絡我的方式：＿＿＿＿\n\n"
        "謝謝老師。\n"
        "（這張轉介單是我在「少年仔、安啦會客室」整理的，要不要交出去由我自己決定。）"
    )


def mail_draft(entry, note):
    """mailto: link that opens the student's own mail app with the note filled in; nothing is sent for them."""
    subject = "想跟輔導室約時間談談"
    return f"mailto:{entry['email']}?subject={quote(subject)}&body={quote(note)}"


def payload(topic_keys, school_name="", code=None, county=None):
    """What the student page shows: why, what happens next, the note, and the school the student named
    (or choices when the name fits several schools)."""
    school, choices = pick_school(school_name, code, county) if (school_name or code) else (None, [])
    note = referral_note(topic_keys, school["name"] if school else "")
    return {
        "topics": [TOPICS[k]["label"] for k in topic_keys if k in TOPICS],
        "message": "這類事情不用自己扛。學校輔導室有專業的輔導老師可以陪你處理，不管事情大或小都可以去談。"
                   "下面有一張可以修改的轉介單，你可以印出來、抄下來或直接拿給老師看。",
        "notices": [NOTICES[k] for k in topic_keys if k in NOTICES],
        "note": note,
        "school_asked": bool(school_name or code),
        "school": contact(school, note) if school else None,
        "choices": [{"code": s["code"], "name": s["name"], "county": s["county"]} for s in choices],
    }
