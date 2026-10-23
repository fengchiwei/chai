"""學生同意前的暫存、明確同意後的摘要快照；不執行任何外部轉介。"""
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from engine.ai_agent import generate_counselor_one_page_summary
from engine.triage import RISK_LEVEL_WEIGHTS
from models.database import append_audit, get_connection, get_case_by_id, save_case, seal, unseal

CONTEXT_TTL = 24 * 60 * 60
PURGE_EVERY = 10 * 60  # expired contexts are removed at most this often, not inside every write
_last_purge = [0.0]


def _read(conn, context_id, email_hash):
    row = conn.execute(
        "SELECT data_json FROM student_contexts WHERE context_id=? AND email_hash=? AND updated_at>=?",
        (context_id, email_hash, int(time.time()) - CONTEXT_TTL),
    ).fetchone()
    return json.loads(unseal(row["data_json"])) if row else None


def _write(conn, context_id, email_hash, context):
    now = int(time.time())
    if now - _last_purge[0] >= PURGE_EVERY:
        # Reads already ignore expired rows (see _read); deleting them is housekeeping.
        conn.execute("DELETE FROM student_contexts WHERE updated_at<?", (now - CONTEXT_TTL,))
        _last_purge[0] = now
    conn.execute(
        "INSERT OR REPLACE INTO student_contexts VALUES (?, ?, ?, ?)",
        (context_id, email_hash, seal(json.dumps(context, ensure_ascii=False)), now),
    )


def get_student_context(context_id, email_hash):
    conn = get_connection()
    try:
        return _read(conn, context_id, email_hash)
    finally:
        conn.close()


def set_student_profile(context_id, email_hash, profile):
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            context = _read(conn, context_id, email_hash) or {
                "revision": 0, "draft": {}, "case_id": f"CASE-{uuid4().hex[:16]}"
            }
            # 資料改動後需重新確認，避免把舊畫面的同意套用到新身分資訊。
            if context.get("profile") != profile:
                context["revision"] += 1
            context["profile"] = profile
            _write(conn, context_id, email_hash, context)
        return context
    finally:
        conn.close()


def _has_evidence(triage):
    """Whether this triage carries its own reasons (rule hits, a questionnaire score or a dialogue safety cue)."""
    rules = triage.get("rule_details") or {}
    safety = triage.get("dialogue_safety") or {}
    return bool(rules.get("red_flags") or rules.get("orange_flags") or rules.get("yellow_flags")
                or (triage.get("bsrs_details") or {}).get("total_score") is not None
                or (safety.get("risk_signal", "none") != "none" and safety.get("risk_evidence")))


def stage_student_summary(context_id, email_hash, triage, fields, message=None):
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            context = _read(conn, context_id, email_hash)
            if context is None:
                raise ValueError("對話資料已過期，請重新確認登錄資料")
            previous = context["draft"]
            previous_triage = previous.get("triage", {})
            # 即使兩個分頁同時送出，也沿用原有「可升不可降」結果。
            before, now = RISK_LEVEL_WEIGHTS[previous_triage.get("level", "green")], RISK_LEVEL_WEIGHTS[triage["level"]]
            # 同一燈號的後續訊息若只是沿用先前燈號（沒有自己的證據），保留最危險那一輪的證據；
            # 否則紅燈個案會在工作臺顯示「目前輸入未檢出相關訊號」（2026-10-23 模擬測試）。
            if before > now or (before == now and _has_evidence(previous_triage) and not _has_evidence(triage)):
                triage = previous_triage
            draft = {
                "category": "想找老師聊聊最近的困擾", "duration": "尚未提及",
                "life_impact": "尚未提及", "support_system": "尚未提及", "bsrs5": {},
                **previous, **fields, "triage": triage, "risk_level": triage["level"],
            }
            if message is not None:
                draft["dialogue_snippet"] = (
                    previous.get("dialogue_snippet", "") + "\n" + message
                ).strip()[-1200:]
            context["draft"] = draft
            context["revision"] += 1
            _write(conn, context_id, email_hash, context)
        return context
    finally:
        conn.close()


TRANSCRIPT_LIMIT = 400  # entries (200 exchanges); the context itself still expires after CONTEXT_TTL


def save_dialogue_state(context_id, email_hash, state, expected_turn, exchange=None):
    """Keep bounded memory inside the existing expiring context, never in the browser cookie.

    `exchange` (the student's message and the reply, with times) is appended to the full transcript. It stays
    in this encrypted, expiring context and reaches the workbench only as a snapshot when the student consents."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            context = _read(conn, context_id, email_hash)
            if not context:
                raise ValueError("對話資料已過期，請重新確認登錄資料")
            current_turn = context.get("dialogue_state", {}).get("turn_count", 0)
            if current_turn != expected_turn:
                raise ValueError("另一個分頁已更新對話，請等候該輪完成後再傳送")
            # Concurrent assessment or another worker cannot publish a lower-risk reply.
            if RISK_LEVEL_WEIGHTS[context["draft"].get("risk_level", "green")] > RISK_LEVEL_WEIGHTS[state["risk_level"]]:
                raise ValueError("安全資訊已有更新，請重新送出這一輪訊息以確認安全")
            context["dialogue_state"] = state
            if exchange:
                entries = [{"role": e["role"], "text": str(e["text"])[:2000], "at": e.get("at", ""),
                            **({"source": e["source"]} if e.get("source") else {})} for e in exchange]
                context["transcript"] = (context.get("transcript", []) + entries)[-TRANSCRIPT_LIMIT:]
            _write(conn, context_id, email_hash, context)
        return context
    finally:
        conn.close()


def consent_kind(context):
    level = context.get("draft", {}).get("risk_level", "green")
    return "referral" if level in ("orange", "red") else "summary" if level == "yellow" else None


def record_student_consent(context_id, email_hash, revision, kind, preferred_name):
    """同意與案件快照在同一交易內完成；同一版重送不重建案件或覆蓋真人處理。"""
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            context = _read(conn, context_id, email_hash)
            if not context or not consent_kind(context):
                raise ValueError("目前沒有可分享的摘要；可以繼續聊或查看資源")
            if revision != context["revision"] or kind != consent_kind(context):
                raise ValueError("對話已有更新，請查看最新摘要後再決定是否同意")
            existing = get_case_by_id(context["case_id"])
            if existing and context.get("consented_revision") == revision:
                return existing
            profile = context["profile"]
            draft = context["draft"]
            now = datetime.now(timezone.utc).isoformat()
            status = "student_requested_referral" if kind == "referral" else "student_shared_summary"
            if existing and existing["summary"].get("student_consent", {}).get("kind") == kind:
                if RISK_LEVEL_WEIGHTS[draft["risk_level"]] <= RISK_LEVEL_WEIGHTS[existing["risk_level"]]:
                    status = existing["status"]
            payload = {
                **draft, "case_id": context["case_id"], "status": status,
                "student_alias": preferred_name or profile["student_alias"],
                "student_email": profile["student_email"], "township": profile["township"],
                "created_at": existing["created_at"] if existing else None,
                "counselor_notes": existing["counselor_notes"] if existing else "",
                "decision_action": existing["decision_action"] if existing else "",
            }
            payload["summary"] = generate_counselor_one_page_summary(payload, draft["triage"])
            payload["summary"]["student_profile"] = profile
            # Evidence-bound wellbeing notes travel only inside the snapshot the student agreed to share.
            payload["summary"]["wellbeing_signals"] = (
                (context.get("dialogue_state") or {}).get("wellbeing_signals") or {}).get("domains", {})
            payload["summary"]["student_consent"] = {
                "kind": kind, "consented_at": now, "revision": revision,
                "preferred_name": payload["student_alias"], "external_referral_sent": False,
                "includes_transcript": True,
            }
            # The whole conversation up to this consent (the student was told it would be shared); nothing later.
            payload["summary"]["transcript"] = list(context.get("transcript", []))
            save_case(payload, connection=conn)
            context["consented_revision"] = revision
            _write(conn, context_id, email_hash, context)
            append_audit(conn, "student", "student_requested_referral" if kind == "referral" else "student_shared_summary",
                         payload["case_id"], "學生明確同意分享當前摘要；尚未對外轉介", timestamp=now)
        return payload
    finally:
        conn.close()
