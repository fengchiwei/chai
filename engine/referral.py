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


def delete_student_context(context_id, email_hash):
    """The student started a new conversation: the old one (memory, transcript, unshared draft) is deleted.
    Cases already on the workbench are staff records and stay."""
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM student_contexts WHERE context_id=? AND email_hash=?", (context_id, email_hash))
        return cursor.rowcount == 1
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
            # The sentences that themselves raised orange/red: the only conversation text an automatic safety
            # alert may carry before the student consents (see auto_safety_handoff).
            risk_messages = list(previous.get("risk_messages", []))
            if message and triage["level"] in ("orange", "red") and _has_evidence(triage):
                risk_messages = (risk_messages + [message[:300]])[-5:]
            # 即使兩個分頁同時送出，也沿用原有「可升不可降」結果。
            before, now = RISK_LEVEL_WEIGHTS[previous_triage.get("level", "green")], RISK_LEVEL_WEIGHTS[triage["level"]]
            # 同一燈號的後續訊息若只是沿用先前燈號（沒有自己的證據），保留最危險那一輪的證據；
            # 否則紅燈個案會在工作臺顯示「目前輸入未檢出相關訊號」（2026-10-23 模擬測試）。
            if before > now or (before == now and _has_evidence(previous_triage) and not _has_evidence(triage)):
                triage = previous_triage
            draft = {
                "category": "想找老師聊聊最近的困擾", "duration": "尚未提及",
                "life_impact": "尚未提及", "support_system": "尚未提及", "bsrs5": {},
                **previous, **fields, "triage": triage, "risk_level": triage["level"], "risk_messages": risk_messages,
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
                            **({"source": e["source"]} if e.get("source") else {}),
                            **({"cards": list(e["cards"])[:3]} if e.get("cards") else {})} for e in exchange]
                context["transcript"] = (context.get("transcript", []) + entries)[-TRANSCRIPT_LIMIT:]
            _write(conn, context_id, email_hash, context)
        return context
    finally:
        conn.close()


AUTO_ALERT_STATUS = "auto_safety_alert"
AUTO_ALERT_ALIAS = "未具名學生（尚未同意分享身分）"
AUTO_ALERT_FIELDS = ["燈號與判斷理由", "引發警訊的原話（最多 5 句）", "BSRS-5 與自填檢核（有填時）", "時間", "鄉鎮"]
STUDENT_ALERT_NOTICE = ("因為你剛剛說的話或檢核的回答可能和安全有關，系統已把必要的安全資訊送到真人工作臺，讓受過訓練的人員優先查看："
                        "包含燈號、引發警訊的那幾句話、時間和鄉鎮，不含你的暱稱、學校、聯絡方式和完整對話。"
                        "這不會自動通知學校或家人；要分享完整對話或留下聯絡方式，仍由你決定。")


def auto_safety_handoff(context_id, email_hash):
    """Orange/red put the necessary safety information on the workbench without waiting for consent (proposal:
    中高風險時產生摘要並進入真人工作臺). Only the level, reasons, the sentences that raised it, the self-check
    answers if any, time and township; nickname, school, contact and the full conversation still need consent.

    Returns "created" or "raised" when the workbench received new information, else None (not orange/red, no
    higher than already sent, or the student has already consented: flag_risk_after_consent covers that case)."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            context = _read(conn, context_id, email_hash)
            if not context:
                return None
            draft = context["draft"]
            level = draft.get("risk_level", "green")
            if level not in ("orange", "red"):
                return None
            existing = get_case_by_id(context["case_id"])
            if existing and existing["summary"].get("student_consent"):
                return None
            if existing and RISK_LEVEL_WEIGHTS[level] <= RISK_LEVEL_WEIGHTS[existing["risk_level"]]:
                return None
            now = datetime.now(timezone.utc).isoformat()
            alert = {"level": level, "at": now, "fields": AUTO_ALERT_FIELDS, "student_informed": True,
                     "history": ((existing or {}).get("summary", {}).get("auto_alert", {}).get("history", [])
                                 + [{"level": level, "at": now}])}
            payload = {
                "case_id": context["case_id"],
                # A case staff already took up keeps their status; otherwise it waits for review.
                "status": existing["status"] if existing and existing["status"] != AUTO_ALERT_STATUS else AUTO_ALERT_STATUS,
                "student_alias": AUTO_ALERT_ALIAS, "student_email": "",
                "township": context["profile"]["township"], "risk_level": level,
                "category": "系統自動安全通報", "duration": draft.get("duration", "尚未提及"),
                "life_impact": draft.get("life_impact", "尚未提及"), "support_system": draft.get("support_system", "尚未提及"),
                "dialogue_snippet": "\n".join(draft.get("risk_messages", [])) or "（燈號來自自填檢核，沒有對話原話）",
                "bsrs5": draft.get("bsrs5", {}), "triage": draft["triage"],
                "created_at": existing["created_at"] if existing else None,
                "counselor_notes": existing["counselor_notes"] if existing else "",
                "decision_action": existing["decision_action"] if existing else "",
            }
            payload["summary"] = generate_counselor_one_page_summary(payload, draft["triage"])
            payload["summary"]["student_profile"] = {"township": context["profile"]["township"]}
            payload["summary"]["auto_alert"] = alert
            payload["summary"]["checkin_seconds"] = draft.get("checkin_seconds")
            save_case(payload, connection=conn)
            append_audit(conn, "system", "auto_safety_alert", context["case_id"],
                         f"對話燈號達{ {'orange': '橙色', 'red': '紅色'}[level] }，自動送出必要安全資訊（不含身分、聯絡方式與完整對話）",
                         timestamp=now)
        return "raised" if existing else "created"
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
            payload["summary"]["checkin_seconds"] = draft.get("checkin_seconds")
            if existing and existing["summary"].get("auto_alert"):
                payload["summary"]["auto_alert"] = existing["summary"]["auto_alert"]  # keep when the alert came first
            save_case(payload, connection=conn)
            context["consented_revision"] = revision
            _write(conn, context_id, email_hash, context)
            append_audit(conn, "student", "student_requested_referral" if kind == "referral" else "student_shared_summary",
                         payload["case_id"], "學生明確同意分享當前摘要；尚未對外轉介", timestamp=now)
        return payload
    finally:
        conn.close()
