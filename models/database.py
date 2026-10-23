"""
SQLite 資料庫管理模組 (Database & Persistence Layer)
儲存個案紀錄、分流評估結果、一頁式摘要、輔導員處理狀態與稽核軌跡
遵循最小必要資料原則與去識別化規範
"""

import hashlib
import hmac
import os
import sqlite3
import json
from uuid import uuid4
from datetime import datetime
from config import Config
from engine.crypto_store import decrypt_text, encrypt_text

DB_PATH = Config.DATABASE_PATH
# v2.3 Phase 2: columns holding student words or contact data are stored as ciphertext.
# case_id / township / risk_level / status / timestamps stay plain for filtering and sorting.
ENCRYPTED_CASE_FIELDS = ("student_alias", "student_email", "category", "duration", "life_impact",
                         "support_system", "dialogue_snippet", "bsrs5_json", "triage_json", "summary_json",
                         "counselor_notes", "decision_action")
AUDIT_GENESIS = "GENESIS"


def seal(value):
    return encrypt_text(value, DB_PATH)


def unseal(value):
    return decrypt_text(value, DB_PATH)


def get_connection():
    # Wait for a busy database instead of failing: 50 students at once hit "database is locked" with the
    # 5-second default (2026-10-23 simulation). WAL mode (set in init_db) lets reads run during a write.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # Overwrite deleted rows so expired conversations do not linger in free pages.
    conn.execute("PRAGMA secure_delete=ON")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            student_alias TEXT,
            student_email TEXT DEFAULT '',
            township TEXT,
            risk_level TEXT,
            status TEXT DEFAULT 'pending',
            category TEXT,
            duration TEXT,
            life_impact TEXT,
            support_system TEXT,
            dialogue_snippet TEXT,
            bsrs5_json TEXT,
            triage_json TEXT,
            summary_json TEXT,
            counselor_notes TEXT DEFAULT '',
            decision_action TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # 自動補充舊版本缺少之欄位
    for col in ["student_email", "decision_action"]:
        try:
            cursor.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            actor TEXT,
            action TEXT,
            case_id TEXT,
            details TEXT
        )
    """)
    for col in ("prev_hash", "entry_hash"):
        try:
            cursor.execute(f"ALTER TABLE audit_logs ADD COLUMN {col} TEXT")
        except Exception:
            pass

    # 對話暫存與工作臺案件分開；只有明確同意才建立 cases 紀錄。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_contexts (
            context_id TEXT PRIMARY KEY,
            email_hash TEXT NOT NULL,
            data_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    # Expired-context cleanup scans by time; without an index every write read the whole table.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_student_contexts_updated ON student_contexts(updated_at)")
    # Operator settings made in the workbench (e.g. the chosen model); no student data.
    cursor.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    # Personal workbench accounts (proposal: 角色權限). Passwords are stored only as salted PBKDF2 hashes.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff_users (
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            last_login TEXT
        )
    """)

    conn.commit()
    conn.execute("PRAGMA journal_mode=WAL")  # persistent per database file
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str):
    """Empty value removes the setting."""
    conn = get_connection()
    try:
        with conn:
            if value:
                conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
            else:
                conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
    finally:
        conn.close()

    # 展示案例只從 data/mock_cases.json 讀取，不灌入真實個案資料表。


STAFF_ROLES = {"admin": "管理員", "counselor": "輔導人員"}
PASSWORD_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def _public_user(r):
    return {"username": r["username"], "display_name": r["display_name"], "role": r["role"],
            "active": bool(r["active"]), "created_at": r["created_at"], "last_login": r["last_login"] or ""}


def list_staff_users():
    conn = get_connection()
    try:
        return [_public_user(r) for r in conn.execute("SELECT * FROM staff_users ORDER BY role, username")]
    finally:
        conn.close()


def create_staff_user(username: str, display_name: str, role: str, password: str):
    if role not in STAFF_ROLES:
        raise ValueError("角色只能是管理員或輔導人員")
    conn = get_connection()
    try:
        with conn:
            if conn.execute("SELECT 1 FROM staff_users WHERE username = ?", (username,)).fetchone():
                raise ValueError("這個帳號已經存在")
            conn.execute("INSERT INTO staff_users (username, display_name, role, password_hash, active, created_at) "
                         "VALUES (?, ?, ?, ?, 1, ?)", (username, display_name, role, hash_password(password),
                                                       datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    finally:
        conn.close()


def update_staff_user(username: str, **changes):
    """changes: role, active (bool) or password. Returns False when the account does not exist."""
    sets, values = [], []
    if "role" in changes:
        if changes["role"] not in STAFF_ROLES:
            raise ValueError("角色只能是管理員或輔導人員")
        sets.append("role = ?"); values.append(changes["role"])
    if "active" in changes:
        sets.append("active = ?"); values.append(1 if changes["active"] else 0)
    if "password" in changes:
        sets.append("password_hash = ?"); values.append(hash_password(changes["password"]))
    if "last_login" in changes:
        sets.append("last_login = ?"); values.append(changes["last_login"])
    if not sets:
        return True
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(f"UPDATE staff_users SET {', '.join(sets)} WHERE username = ?", (*values, username))
            return cursor.rowcount == 1
    finally:
        conn.close()


def authenticate_staff(username: str, password: str):
    """The account's public fields when the password matches an active account, else None."""
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM staff_users WHERE username = ?", (username,)).fetchone()
    finally:
        conn.close()
    if not r or not r["active"] or not password_matches(password, r["password_hash"]):
        return None
    return _public_user(r)


def count_active_admins() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM staff_users WHERE role = 'admin' AND active = 1").fetchone()[0]
    finally:
        conn.close()


def recent_audit_logs(limit: int = 100):
    conn = get_connection()
    try:
        return [dict(timestamp=r["timestamp"], actor=r["actor"], action=r["action"], case_id=r["case_id"],
                     details=r["details"])
                for r in conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()

def _audit_hash(prev_hash, timestamp, actor, action, case_id, details):
    body = json.dumps([timestamp, actor, action, case_id, details], ensure_ascii=False)
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def append_audit(conn, actor: str, action: str, case_id: str = "", details: str = "", timestamp=None):
    """Append to the SHA-256 hash chain; call inside the caller's write transaction."""
    row = conn.execute("SELECT entry_hash FROM audit_logs WHERE entry_hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = row[0] if row else AUDIT_GENESIS
    timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry_hash = _audit_hash(prev_hash, timestamp, actor, action, case_id, details)
    conn.execute("""
        INSERT INTO audit_logs (timestamp, actor, action, case_id, details, prev_hash, entry_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, actor, action, case_id, details, prev_hash, entry_hash))


def log_audit(actor: str, action: str, case_id: str = "", details: str = ""):
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            append_audit(conn, actor, action, case_id, details)
    finally:
        conn.close()


def verify_audit_chain():
    """Return (ok, first_bad_id). Legacy rows written before the chain existed are skipped."""
    conn = get_connection()
    try:
        prev_hash, started = AUDIT_GENESIS, False
        for r in conn.execute("SELECT * FROM audit_logs ORDER BY id"):
            if r["entry_hash"] is None:
                if started:
                    return False, r["id"]
                continue
            started = True
            expected = _audit_hash(prev_hash, r["timestamp"], r["actor"], r["action"], r["case_id"], r["details"])
            if r["prev_hash"] != prev_hash or r["entry_hash"] != expected:
                return False, r["id"]
            prev_hash = r["entry_hash"]
        return True, None
    finally:
        conn.close()

def save_case(case_data: dict, connection=None) -> str:
    conn = connection if connection is not None else get_connection()
    cursor = conn.cursor()
    case_id = case_data.get("case_id") or f"CASE-{uuid4().hex[:16]}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT OR REPLACE INTO cases (
            case_id, student_alias, student_email, township, risk_level, status, category,
            duration, life_impact, support_system, dialogue_snippet,
            bsrs5_json, triage_json, summary_json, counselor_notes, decision_action,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        case_id,
        seal(case_data.get("student_alias", case_data.get("persona", "匿名同學"))),
        seal(case_data.get("student_email", "")),
        case_data.get("township", "南投市"),
        case_data.get("risk_level", "green"),
        case_data.get("status", "pending"),
        seal(case_data.get("category", "生活與學習調適")),
        seal(case_data.get("duration", "近期")),
        seal(case_data.get("life_impact", "")),
        seal(case_data.get("support_system", "")),
        seal(case_data.get("dialogue_snippet", "")),
        seal(json.dumps(case_data.get("bsrs5", {}), ensure_ascii=False)),
        seal(json.dumps(case_data.get("triage", {}), ensure_ascii=False)),
        seal(json.dumps(case_data.get("summary", {}), ensure_ascii=False)),
        seal(case_data.get("counselor_notes", "")),
        seal(case_data.get("decision_action", "")),
        case_data.get("created_at") or now_str,
        now_str
    ))

    if connection is None:
        conn.commit()
        conn.close()
        log_audit("system", "save_case", case_id, f"風險等級: {case_data.get('risk_level')}")
    return case_id


def _row_to_case(r):
    keys = r.keys()
    value = lambda name: unseal(r[name]) if name in keys else ""
    load = lambda name: json.loads(value(name)) if value(name) else {}
    return {
        "case_id": r["case_id"],
        "student_alias": value("student_alias"),
        "student_email": value("student_email") or "",
        "township": r["township"],
        "risk_level": r["risk_level"],
        "status": r["status"],
        "category": value("category"),
        "duration": value("duration"),
        "life_impact": value("life_impact"),
        "support_system": value("support_system"),
        "dialogue_snippet": value("dialogue_snippet"),
        "bsrs5": load("bsrs5_json"),
        "triage": load("triage_json"),
        "summary": load("summary_json"),
        "counselor_notes": value("counselor_notes"),
        "decision_action": value("decision_action") or "",
        "created_at": r["created_at"],
        "updated_at": r["updated_at"]
    }


def get_all_cases(risk_filter=None, township_filter=None, status_filter=None):
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM cases WHERE 1=1"
    params = []

    if risk_filter and risk_filter != "all":
        query += " AND risk_level = ?"
        params.append(risk_filter)

    if township_filter and township_filter != "all":
        query += " AND township = ?"
        params.append(township_filter)

    if status_filter == "pending":
        # 「待覆核」 includes cases a student just shared or asked to be referred (2026-10-23 simulation: always 0).
        query += (" AND status IN ('pending', 'student_requested_referral', 'student_shared_summary',"
                  " 'auto_safety_alert', 'student_requested_help')")
    elif status_filter and status_filter != "all":
        query += " AND status = ?"
        params.append(status_filter)

    query += """
        ORDER BY
            CASE WHEN status IN ('completed', 'referred') THEN 1 ELSE 0 END,
            CASE risk_level
                WHEN 'red' THEN 1
                WHEN 'orange' THEN 2
                WHEN 'yellow' THEN 3
                ELSE 4
            END,
            updated_at DESC
    """

    cursor.execute(query, params)
    results = [_row_to_case(r) for r in cursor.fetchall()]
    conn.close()
    return results


def flag_risk_after_consent(case_id: str, level: str):
    """The student's conversation rose above the level they agreed to share. Record only the level and time
    (no new content) so staff know to reach out or ask for consent again."""
    case = get_case_by_id(case_id)
    if not case or RISK_ORDER.get(level, 0) <= RISK_ORDER.get(case["risk_level"], 0):
        return False
    summary = dict(case.get("summary") or {})
    if (summary.get("raised_after_consent") or {}).get("level") == level:
        return False
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary["raised_after_consent"] = {"level": level, "at": now_str}
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE cases SET summary_json = ?, updated_at = ? WHERE case_id = ?",
                         (seal(json.dumps(summary, ensure_ascii=False)), now_str, case_id))
    finally:
        conn.close()
    log_audit("system", "risk_raised_after_consent", case_id, f"學生同意分享後，對話燈號升至 {level}（未分享新內容）")
    return True


def get_case_by_id(case_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
    r = cursor.fetchone()
    conn.close()
    return _row_to_case(r) if r else None


STATUS_LABELS = {"pending": "待覆核", "reviewing": "審查中", "contacted": "已聯絡", "referred": "已轉介", "completed": "已結案",
                 "student_requested_referral": "學生提出轉介", "student_shared_summary": "學生分享摘要",
                 "auto_safety_alert": "系統安全通報", "student_requested_help": "學生主動請求協助"}
STAFF_STATUSES = {"reviewing", "contacted", "referred", "completed"}
RISK_ORDER = {"green": 1, "yellow": 2, "orange": 3, "red": 4}


def update_case_status(case_id: str, new_status: str, counselor_notes: str = "", decision_action: str = "", actor: str = "counselor"):
    """Staff set only their own statuses; notes are appended to a timeline, never overwritten
    (2026-10-23 simulation: closing a red case with an empty note erased 「02:30 已聯絡生輔組」)."""
    if new_status not in STAFF_STATUSES:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = cursor.execute("SELECT counselor_notes FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        conn.close()
        return False
    timeline = unseal(row["counselor_notes"]) if row["counselor_notes"] else ""
    entry = f"{now_str[:16]}｜{actor}｜{STATUS_LABELS[new_status]}" + (f"｜{counselor_notes.strip()}" if counselor_notes.strip() else "")
    timeline = (timeline + "\n" + entry).strip()

    cursor.execute("""
        UPDATE cases
        SET status = ?, counselor_notes = ?, decision_action = ?, updated_at = ?
        WHERE case_id = ?
    """, (new_status, seal(timeline), seal(decision_action), now_str, case_id))

    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()

    if changed:
        log_audit(actor, "update_status", case_id, f"變更狀態為 {new_status}；聯繫與轉介由真人於系統外確認")
    return changed
