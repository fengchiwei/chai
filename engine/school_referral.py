"""School counseling-office referral for gender-equity (性平) and bullying topics.

Whatever the risk level, a student who mentions sexual harassment / assault, intimate images, gender-based
teasing or bullying is told the school counseling office (輔導室) can help, and gets a referral note they can
edit and hand in. If they choose to name their school and the team has a verified contact for it, the note can
be opened as an email draft addressed to that office. Nothing is ever sent by the system: the student's own
mail app opens and the student decides whether to send.

School contacts live in data/school_counseling.json and are maintained by the team. Every entry needs an
https source page and a verification date; entries without them are ignored, so no address is ever guessed.
"""
import json
import os
import re
from urllib.parse import quote

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "school_counseling.json")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

TOPICS = {
    "gender_equity": {
        "label": "性平事件",
        "note_label": "性別平等（例如讓我不舒服的身體碰觸、言語或影像）",
        "pattern": re.compile(
            r"性騷擾?|性侵|強暴|猥褻|性平|性別平等|約會暴力|偷拍|裙底|私密(?:照|影片|影像)|裸照|色情(?:照|影片|圖)"
            r"|毛手毛腳|亂摸|摸我(?!的?(?:頭|頭髮|額頭|肩膀|臉頰))|摸(?:我的)?(?:胸|屁股|大腿|下面)"
            r"|逼我(?:脫|看(?:A片|色情)|拍(?:裸|私密))|要我(?:傳|拍)(?:裸照|私密照)"
            r"|娘炮|娘娘腔|男人婆|死gay|gay砲|人妖|(?:笑|罵|嘲笑|針對).{0,6}(?:性向|性別|同性戀|gay|太娘|不像男生|不像女生)",
            re.I),
    },
    "bullying": {
        "label": "霸凌",
        "note_label": "校園霸凌（被欺負、排擠或網路上被針對）",
        "pattern": re.compile(
            r"霸凌|被排擠|被孤立|被欺負|欺負我|(?:排擠|孤立|針對|嘲笑|取笑)我|被勒索|勒索我|被圍毆|圍毆我|被堵|被造謠|造我的?謠|散播.{0,6}謠言"
            r"|被肉搜|被起底|被公審|被(?:全班|大家|同學).{0,4}(?:笑|嘲笑|排擠|孤立|無視|針對|罵)"
            r"|同學都(?:不理我|笑我|討厭我|針對我|排擠我)|被取(?:難聽的)?綽號|(?:搶|藏|丟)我的?(?:東西|錢|書包|鞋子?|課本)|把我的?(?:東西|書包|鞋子?|課本)(?:丟|藏|搶|弄壞|撕)"),
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


def _normal(name):
    return re.sub(r"[\s　（）()]", "", (name or "")).replace("臺", "台")


def directory():
    """Verified school contacts only: a name, a valid email, an https source page and a verification date."""
    try:
        with open(DATA, encoding="utf-8") as f:
            schools = json.load(f).get("schools", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [s for s in schools if isinstance(s, dict) and s.get("name") and EMAIL.fullmatch(s.get("email", ""))
            and str(s.get("source_url", "")).startswith("https://") and s.get("verified_on")]


def find_school(name):
    """The directory entry the student's school name points to, or None. Partial names (「南投高中」) match
    an alias; a name shorter than 3 characters never matches, so 「高中」 alone finds nothing."""
    wanted = _normal(name)
    if len(wanted) < 3:
        return None
    for school in directory():
        names = [_normal(n) for n in [school["name"], *school.get("aliases", [])]]
        if any(wanted == n or (len(n) >= 3 and n in wanted) or wanted in n for n in names):
            return school
    return None


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


def mail_draft(school, note):
    """mailto: link that opens the student's own mail app with the note filled in; nothing is sent for them."""
    subject = "想跟輔導室約時間談談"
    return f"mailto:{school['email']}?subject={quote(subject)}&body={quote(note)}"


def payload(topic_keys, school_name=""):
    """What the student page shows: why, what happens next, the note, and (if found) the school's office."""
    school = find_school(school_name) if school_name else None
    note = referral_note(topic_keys, school["name"] if school else "")
    return {
        "topics": [TOPICS[k]["label"] for k in topic_keys if k in TOPICS],
        "message": "這類事情不用自己扛。學校輔導室有專業的輔導老師可以陪你處理，不管事情大或小都可以去談。"
                   "下面有一張可以修改的轉介單，你可以印出來、抄下來或直接拿給老師看。",
        "notices": [NOTICES[k] for k in topic_keys if k in NOTICES],
        "note": note,
        "school_asked": bool(school_name),
        "school": ({"name": school["name"], "office": school.get("office", "輔導室"), "email": school["email"],
                    "phone": school.get("phone", ""), "source_url": school["source_url"],
                    "mailto": mail_draft(school, note)} if school else None),
    }
