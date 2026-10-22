"""
SQLite 資料庫管理模組 (Database & Persistence Layer)
儲存個案紀錄、分流評估結果、一頁式摘要、輔導員處理狀態與稽核軌跡
遵循最小必要資料原則與去識別化規範
"""

import hashlib
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
    conn = sqlite3.connect(DB_PATH)
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

    conn.commit()
    conn.close()

    # 展示案例只從 data/mock_cases.json 讀取，不灌入真實個案資料表。

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

    if status_filter and status_filter != "all":
        query += " AND status = ?"
        params.append(status_filter)

    query += """
        ORDER BY
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


def get_case_by_id(case_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
    r = cursor.fetchone()
    conn.close()
    return _row_to_case(r) if r else None


def update_case_status(case_id: str, new_status: str, counselor_notes: str = "", decision_action: str = "", actor: str = "counselor"):
    if new_status not in {"pending", "reviewing", "contacted", "referred", "completed",
                          "student_requested_referral", "student_shared_summary"}:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        UPDATE cases
        SET status = ?, counselor_notes = ?, decision_action = ?, updated_at = ?
        WHERE case_id = ?
    """, (new_status, seal(counselor_notes), seal(decision_action), now_str, case_id))

    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()

    if changed:
        log_audit(actor, "update_status", case_id, f"變更狀態為 {new_status}；聯繫與轉介由真人於系統外確認")
    return changed
