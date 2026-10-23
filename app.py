"""少年仔、安啦會客室：本機展示用 Flask 應用。"""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import weakref
from datetime import datetime
from functools import wraps

import io
import socket
import logging
import sqlite3

import segno
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from config import Config
from engine.ai_agent import (
    generate_counselor_one_page_summary,
    generate_help_seeking_draft,
    generate_youth_response,
    prepare_dialogue,
)
from engine import model_router, providers, school_referral, tts, webfetch
from engine.dialogue_ai import UNAVAILABLE_LABEL, _provider, model_status, reset_provider_cooldown
from engine.dialogue_policy import POLICY_VERSION, REPLY_STYLES, build_state, remember_turn
from engine.dialogue_reply import TOPIC_PATTERN
from engine.dialogue_role import public_role
from engine.explain import VERSION as EXPLAIN_VERSION, explain, load_scenarios
from engine.wellbeing_signals import update_wellbeing_signals
from engine.triage import RISK_LEVEL_WEIGHTS, perform_triage
from engine.support import choose_support_offer
from engine.bsrs5 import ITEMS as BSRS_ITEMS
from engine.referral import (
    STUDENT_ALERT_NOTICE, auto_safety_handoff, consent_kind, delete_student_context, get_student_context,
    record_student_consent,
    set_student_profile, stage_student_summary,
    save_dialogue_state,
)
from models.database import (
    STATUS_LABELS, STAFF_ROLES, authenticate_staff, backup_snapshot, count_active_admins, log_tool_run,
    recent_tool_runs, create_staff_user, list_staff_users, recent_audit_logs,
    update_staff_user, verify_audit_chain,
    get_all_cases,
    flag_risk_after_consent,
    get_case_by_id,
    get_setting,
    init_db,
    set_setting,
    log_audit,
    update_case_status,
)

app = Flask(__name__)
if Config.TRUSTED_PROXY_HOPS > 0:
    # Behind a TLS tunnel or reverse proxy, trust exactly this many X-Forwarded-For hops.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=Config.TRUSTED_PROXY_HOPS, x_proto=Config.TRUSTED_PROXY_HOPS)
class _ConversationLock:
    """One lock per conversation. Striped locks made unrelated students wait for each other's model calls:
    a 「我想自殺」 reply waited 24.7 s behind another student's timeout (2026-10-23 simulation)."""
    __slots__ = ("lock", "__weakref__")

    def __init__(self):
        self.lock = threading.RLock()


_dialogue_locks = weakref.WeakValueDictionary()  # entries vanish once no request holds them
_dialogue_locks_guard = threading.Lock()


def conversation_lock(context_id):
    with _dialogue_locks_guard:
        holder = _dialogue_locks.get(context_id)
        if holder is None:
            holder = _dialogue_locks[context_id] = _ConversationLock()
        return holder


class SlidingWindowLimiter:
    """In-memory, per-process limiter. Behind several workers, use a shared store (e.g. Redis) instead."""

    def __init__(self):
        self._hits, self._lock, self._pruned = {}, threading.Lock(), 0.0

    def hit(self, key, limit, window):
        """Atomically check and record one event; False when `key` already had `limit` events in `window` s."""
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, ()) if now - t < window]
            allowed = len(hits) < limit
            if allowed:
                hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 10000 and now - self._pruned > 60:  # bounded memory, pruned at most once a minute
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 600}
                self._pruned = now
            return allowed

    def forget_last(self, key):
        """Undo the most recent hit (a reserved login attempt that turned out to be correct)."""
        with self._lock:
            if self._hits.get(key):
                self._hits[key].pop()

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()
LOGIN_WINDOW = 600
app.config.from_object(Config)
init_db()


def restore_model_choice():
    """The model chosen in the workbench survives a restart (saved per service in app_settings)."""
    if providers.configured():
        provider = providers.name()
        model_router.set_manual(provider, get_setting("model:" + provider) or None)


restore_model_choice()

BASE_DIR = os.path.dirname(__file__)
with open(os.path.join(BASE_DIR, "data", "nantou_resources.json"), encoding="utf-8") as f:
    NANTOU_RESOURCES = json.load(f)
with open(os.path.join(BASE_DIR, "data", "mock_cases.json"), encoding="utf-8") as f:
    MOCK_CASES = json.load(f)
EXPLAIN_SCENARIOS = load_scenarios()
_asset_versions = {}


def asset(path):
    """`/static/<path>?v=<content hash>`: a changed file gets a new URL, so neither the browser cache nor
    the offline service worker can keep serving old JavaScript after an update."""
    full = os.path.join(app.static_folder, path)
    try:
        mtime = os.path.getmtime(full)
    except OSError:
        return url_for("static", filename=path)
    cached = _asset_versions.get(path)
    if not cached or cached[0] != mtime:
        with open(full, "rb") as f:
            cached = (mtime, hashlib.sha256(f.read()).hexdigest()[:10])
        _asset_versions[path] = cached
    return url_for("static", filename=path, v=cached[1])


app.jinja_env.globals["asset"] = asset

EMAIL_PATTERN = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,253}$")
TOWNSHIPS = {
    "南投市", "草屯鎮", "埔里鎮", "竹山鎮", "集集鎮", "名間鄉", "鹿谷鄉",
    "中寮鄉", "魚池鄉", "國姓鄉", "水里鄉", "信義鄉", "仁愛鄉",
}


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]


def csrf_valid():
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    return bool(token) and hmac.compare_digest(token, session.get("csrf_token", ""))


def require_csrf():
    if not csrf_valid():
        return jsonify({"error": "安全驗證已過期，請重新整理頁面"}), 403
    return None


def staff_only(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("staff"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "請先登入授權工作臺"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def admin_only(view):
    """Accounts, the AI model panel and the audit log are for administrators; counsellors work on cases."""
    @wraps(view)
    @staff_only
    def wrapper(*args, **kwargs):
        # A session from before personal accounts signed in with the shared password, i.e. as the admin.
        if session.get("staff_role", "admin") != "admin":
            return jsonify({"error": "這個功能只有管理員可以使用"}), 403
        return view(*args, **kwargs)
    return wrapper


BUILTIN_ADMIN = "admin"  # WORKBENCH_PASSWORD signs in as this built-in administrator (first login, recovery)
USERNAME_PATTERN = r"[A-Za-z0-9_.-]{3,30}"


def student_identity():
    # 身分只沿用伺服器 session；信箱是選填資料，不是登入憑證。
    if current_student_context() is None:
        return None
    return session.get("student_context_id")


def current_student_context():
    if not session.get("student_onboarded"):
        return None
    return get_student_context(session.get("student_context_id"), session.get("student_email_hash"))


def referral_resources(township):
    """鄉鎮用於就近資訊排序，不代表已派案或保證該單位受理。"""
    selected = [r for r in NANTOU_RESOURCES if
                r["id"] in ("stu_center", "crisis_1925") or
                township in r.get("suggested_townships", [])]
    return [{"name": r["name"], "phone": r["phone"],
             "phone_href": "tel:" + re.sub(r"[^0-9+]", "", r["phone"].split("#")[0]),
             "source_url": r.get("source_url", "")}
            for r in selected]


def student_next_steps(context):
    if not context:
        return None
    level = context["draft"].get("risk_level", "green")
    offered_level = session.get("referral_offer_level", "green")
    prompt_referral = level in ("orange", "red") and RISK_LEVEL_WEIGHTS[level] > RISK_LEVEL_WEIGHTS.get(offered_level, 0)
    if prompt_referral:
        session["referral_offer_level"] = level
    choices = {
        "green": [("continue", "繼續聊"), ("school", "了解學校輔導室"), ("resources", "看南投資源")],
        "yellow": [("draft", "幫我寫給輔導老師的字條"), ("resources", "看資源"), ("continue", "先繼續聊")],
        "orange": [("consent", "A 我願意轉介"), ("decline", "B 先不要轉介、只要專線")],
        "red": [("consent", "願意留稱呼請人看摘要"), ("call", "我先打電話")],
    }
    profile = context["profile"]
    # 「找真人幫忙」 is available at every level, so the student can always see what would be shared.
    preview = (
        f"學校：{profile.get('student_school') or '尚未填寫'}\n"
        f"信箱：{profile['student_email'] + '（未驗證）' if profile['student_email'] else '未提供'}\n鄉鎮：{profile['township']}\n"
        f"目前對話節錄：\n{context['draft'].get('dialogue_snippet') or '尚無對話文字'}\n"
        f"也會一起分享：這次的完整對話紀錄（你說的話和安啦的回覆，共 {len(context.get('transcript', []))} 則，"
        "到你按下同意為止；之後再聊的內容不會自動分享）"
    )
    return {
        "choices": [{"action": action, "label": label} for action, label in choices[level]],
        "revision": context["revision"], "consent_kind": consent_kind(context),
        "prompt_referral": prompt_referral, "can_request_help": True,
        "preferred_name": profile["student_alias"], "summary_preview": preview,
        "contact": {"student_email": profile["student_email"], "student_school": profile.get("student_school", "")},
        "township": profile["township"], "resources": referral_resources(profile["township"]),
        "recorded": context.get("consented_revision") == context["revision"],
    }


@app.before_request
def cors_preflight():
    # Cross-origin requests are refused unless the origin is explicitly whitelisted (CORS_ORIGINS).
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        allowed = request.headers.get("Origin") in Config.CORS_ORIGINS
        return ("", 204) if allowed else (jsonify({"error": "來源未被允許"}), 403)
    return None


@app.after_request
def sensitive_cache_policy(response):
    origin = request.headers.get("Origin")
    if origin and origin in Config.CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRF-Token"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Vary"] = "Origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Second line of defence behind escapeHtml/textContent: only this site's scripts, no plugins, no framing,
    # forms post here only. 'unsafe-inline' stays until the templates' inline onclick handlers move to JS files.
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    if request.path.startswith("/api/") or request.path in ("/", "/counselor", "/login", "/demo", "/explain"):
        response.headers["Cache-Control"] = "no-store"
    return response


CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                           "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                           "frame-ancestors 'none'; form-action 'self'")


@app.errorhandler(sqlite3.OperationalError)
def database_busy(exc):
    """A locked or unavailable database must not show a stack trace, and a student still sees where to get help."""
    logging.warning("資料庫暫時無法使用：%s", type(exc).__name__)
    return jsonify({"error": "系統忙碌中，請稍後再傳一次。若有立即危險，請直接撥打 119，或 1925 安心專線（24 小時）。",
                    "show_urgent_help": session.get("highest_risk") == "red"}), 503


@app.route("/")
def index():
    context = current_student_context()
    urgent = session.get("highest_risk") == "red" or (context or {}).get("draft", {}).get("risk_level") == "red"
    return render_template("index.html", csrf_token=csrf_token(), show_urgent_help=urgent,
                           demo_mode=Config.PUBLIC_DEMO_MODE)


@app.route("/resources")
def resources():
    context = current_student_context()
    township = context["profile"]["township"] if context else "all"
    return render_template("resources.html", initial_township=township)


@app.route("/login", methods=["GET", "POST"])
def login():
    if not Config.WORKBENCH_PASSWORD and not list_staff_users():
        return render_template("login.html", disabled=True, csrf_token=csrf_token()), 503
    if request.method == "POST":
        error = require_csrf()
        if error:
            return error
        login_key = "login:" + (request.remote_addr or "unknown")
        # Reserve an attempt atomically; a correct password gives the reservation back.
        if not limiter.hit(login_key, Config.LOGIN_MAX_FAILURES, LOGIN_WINDOW):
            return render_template("login.html", disabled=False, csrf_token=csrf_token(),
                                   error="嘗試次數過多，請 10 分鐘後再試"), 429
        password = request.form.get("password", "")
        username = request.form.get("username", "").strip() or BUILTIN_ADMIN
        account = None
        if username == BUILTIN_ADMIN and Config.WORKBENCH_PASSWORD:
            if hmac.compare_digest(password, Config.WORKBENCH_PASSWORD):
                # The shared built-in administrator: ask who is working so the audit log says who did what.
                name = re.sub(r"[\x00-\x1f<>]", "", request.form.get("staff_name", "")).strip()[:20]
                account = {"username": BUILTIN_ADMIN, "display_name": name or "管理員", "role": "admin"}
        elif re.fullmatch(USERNAME_PATTERN, username):
            account = authenticate_staff(username, password)
            if account:
                update_staff_user(username, last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if account:
            limiter.forget_last(login_key)
            # 同一瀏覽器的學生頁可能仍在對話；保留當前對話的安全警訊與 CSRF。
            session["staff"] = True
            session["staff_user"] = account["username"]
            session["staff_role"] = account["role"]
            session["staff_name"] = account["display_name"]
            log_audit(staff_actor(), "staff_login", "", f"角色：{STAFF_ROLES[account['role']]}")
            return redirect(url_for("counselor"))
        return render_template("login.html", disabled=False, error="帳號或密碼錯誤", csrf_token=csrf_token()), 401
    return render_template("login.html", disabled=False, csrf_token=csrf_token())


@app.route("/logout", methods=["POST"])
@staff_only
def logout():
    error = require_csrf()
    if error:
        return error
    for key in ("staff", "staff_user", "staff_role", "staff_name"):
        session.pop(key, None)
    return redirect(url_for("login"))


@app.route("/counselor")
@staff_only
def counselor():
    return render_template("counselor.html", csrf_token=csrf_token(), staff_role=session.get("staff_role", "admin"),
                           staff_name=session.get("staff_name", ""), staff_user=session.get("staff_user", BUILTIN_ADMIN),
                           role_label=STAFF_ROLES.get(session.get("staff_role", "admin"), ""))


@app.route("/demo")
@staff_only
def demo():
    return render_template("demo.html")


@app.route("/explain")
@staff_only
def explain_dashboard():
    return render_template("explain.html", csrf_token=csrf_token())


@app.route("/manifest.json")
def pwa_manifest():
    return send_from_directory(app.static_folder, "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    # Served from the root so the worker may control the whole site (offline lifeline).
    response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/offline")
def offline_page():
    return send_from_directory(app.static_folder, "offline.html")


def install_url():
    """URL a phone should open: PUBLIC_URL if set, else this server's LAN address (no packets are sent)."""
    if Config.PUBLIC_URL:
        return Config.PUBLIC_URL
    host, _, port = request.host.partition(":")
    if host in ("127.0.0.1", "localhost", "::1", "[::1]"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("10.255.255.255", 1))  # UDP connect only picks a route; nothing is transmitted
                host = probe.getsockname()[0]
        except OSError:
            pass
    return f"{request.scheme}://{host}" + (f":{port}" if port else "") + "/"


@app.route("/api/install-info")
def api_install_info():
    url = install_url()
    return jsonify({"url": url, "lan_reachable": Config.HOST != "127.0.0.1" or bool(Config.PUBLIC_URL),
                    "note": "手機需與伺服器在同一網路；伺服器需以 HOST=0.0.0.0 或 PUBLIC_URL 啟動，正式使用請改用 HTTPS。"})


@app.route("/api/qr.svg")
def api_install_qr():
    buffer = io.BytesIO()
    segno.make(install_url(), error="m").save(buffer, kind="svg", scale=6, border=2, dark="#1e293b", light="#ffffff")
    return app.response_class(buffer.getvalue(), mimetype="image/svg+xml")


@app.route("/api/status")
def api_status():
    """Public AI-connection status for the student page: a coarse state only. Provider and model names
    stay in the staff-only /api/config/llm (students never choose or see models)."""
    ai = model_status(probe=request.args.get("probe") == "1")
    return jsonify({"server": "ok", "ai": {k: ai[k] for k in ("configured", "state", "reason", "retry_in") if k in ai}})


# Staff-only per-turn diagnostics (external spec 5): no student words, no reply text, no keys. Kept in memory
# (the last 200 turns) and lost on restart.
from collections import deque  # noqa: E402
TURN_DIAGNOSTICS = deque(maxlen=200)


def record_diagnostics(reply, level, started, safety_action):
    origin = reply_source(reply["model_used"])
    TURN_DIAGNOSTICS.appendleft({
        "request_id": secrets.token_hex(4), "at": datetime.now().strftime("%H:%M:%S"),
        "provider": providers.name() if origin == "ai" else "",
        "model_used": reply["model_used"], "response_origin": origin,
        "fallback_reason": reply.get("fallback_reason") or "", "risk_level": level, "safety_action": safety_action,
        "latency_ms": round((time.monotonic() - started) * 1000),
        **{k: v for k, v in (reply.get("diagnostics") or {}).items()},
        "sources": [s["publisher"] for s in reply.get("sources", [])],
    })


def reply_source(model_used):
    """Coarse origin of a reply for the student page, without provider or model names."""
    if model_used.startswith(providers.LABELS):
        return "ai"
    if model_used == UNAVAILABLE_LABEL:
        return "unavailable"  # an honest outage notice, not a conversation reply
    return "safety" if model_used in ("安全回覆", "安全確認") else "rules" if model_used == "對話規則回覆" else "local"


@app.route("/api/tts/voices")
def api_tts_voices():
    """Cloud voices the student may pick for reading replies aloud; empty when no voice service is configured."""
    return jsonify({"voices": tts.voices()})


@app.route("/api/tts", methods=["POST"])
def api_tts():
    """Audio for one AI reply. Students only (after the privacy notice); per-conversation and site-wide limits
    keep this from becoming a free speech service. On any failure the page falls back to the device voice."""
    error = require_csrf()
    if error:
        return error
    if student_identity() is None:
        return jsonify({"error": "請先閱讀資料使用說明", "fallback": True}), 403
    data = request.get_json(silent=True) or {}
    text, voice = data.get("text"), data.get("voice")
    if not isinstance(text, str) or not text.strip() or len(text) > tts.MAX_CHARS or not isinstance(voice, str):
        return jsonify({"error": "朗讀內容需為 1 至 800 字", "fallback": True}), 400
    rate = data.get("rate", 1.0)
    if not isinstance(rate, (int, float)):
        rate = 1.0
    if not limiter.hit("tts:" + session["student_context_id"], 40, 600) or             not limiter.hit("tts:all", Config.TTS_CALLS_PER_MINUTE, 60):
        return jsonify({"error": "朗讀太頻繁了，先改用裝置內建的聲音", "fallback": True}), 429
    try:
        audio, mime = tts.synthesize(voice, text, rate)
    except tts.TtsError as exc:
        logging.info("雲端朗讀失敗：%s", exc)
        return jsonify({"error": "雲端語音暫時無法使用，先改用裝置內建的聲音", "reason": str(exc), "fallback": True}), 503
    return Response(audio, mimetype=mime, headers={"Cache-Control": "no-store"})


APP_VERSION = "2.9.4"  # shown on /health so you can tell which release a host (e.g. Render) is running


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "少年仔、安啦會客室 Demo", "version": APP_VERSION,
                    "dialogue_policy": POLICY_VERSION})


@app.route("/api/onboarding", methods=["POST"])
def api_onboarding():
    error = require_csrf()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "登錄資料格式不正確"}), 400
    email = data.get("student_email", "")
    if not isinstance(email, str) or (email.strip() and not EMAIL_PATTERN.fullmatch(email.strip())):
        return jsonify({"error": "電子郵件可留白；若要填寫，請使用有效的信箱格式"}), 400
    if data.get("privacy_acknowledged") is not True:
        return jsonify({"error": "請先閱讀並確認資料使用說明"}), 400
    alias = data.get("student_alias", "")
    alias = alias.strip()[:30] if isinstance(alias, str) else ""
    township = data.get("township", "南投市")
    school = data.get("student_school", "")
    if not isinstance(school, str) or len(school) > 100:
        return jsonify({"error": "學校名稱需為 100 字以內的文字"}), 400
    # 保留舊欄位名稱以相容既有暫存；新對話使用隨機識別，不能把所有空信箱視為同一人。
    if not session.get("student_email_hash"):
        session["student_email_hash"] = secrets.token_hex(32)
    email_hash = session["student_email_hash"]
    session["student_onboarded"] = True
    session["student_email_hash"] = email_hash
    session["student_alias"] = alias or "匿名同學"
    session["student_township"] = township if isinstance(township, str) and township in TOWNSHIPS else "南投市"
    # 補填或清除聯絡資料不會另開對話，也不會清除已出現的危機與資源邀請紀錄。
    if not session.get("student_context_id"):
        session["student_context_id"] = secrets.token_urlsafe(32)
    context = set_student_profile(session["student_context_id"], email_hash, {
        "student_email": email.strip().lower(), "student_alias": session["student_alias"],
        "student_school": school.strip(), "township": session["student_township"],
    })
    if not context["draft"] and session.get("highest_risk", "green") != "green":
        # 暫存到期後重新確認同一身分，也不清除原先已出現的求助訊號。
        triage = perform_triage(text="", previous_level=session["highest_risk"])
        context = stage_student_summary(session["student_context_id"], email_hash, triage, {})
    return jsonify({"success": True, "email_verified": False, "notification_connected": False,
                    "student_profile": context["profile"], "next_steps": student_next_steps(context),
                    "show_urgent_help": session.get("highest_risk") == "red" or context["draft"].get("risk_level") == "red"})


@app.route("/api/chat/state")
def api_chat_state():
    """重新整理學生頁時持續呈現必要的求助連結，不回傳後台燈號。"""
    context = current_student_context()
    return jsonify({
        "show_urgent_help": session.get("highest_risk") == "red" or (context or {}).get("draft", {}).get("risk_level") == "red",
        "student_profile": context["profile"] if context else None,
        "companion_role": public_role((context or {}).get("dialogue_state")),
        "reply_style": session.get("reply_style", "warm"),
        "style_overridden_by_safety": bool((context or {}).get("dialogue_state", {}).get("style_overridden_by_safety")),
        "next_steps": student_next_steps(context),
        "school_referral_available": bool(session.get("school_referral_topics")),
    })


# Session keys that belong to one conversation; 「開始新對話」 clears them (the reply style is the student's choice).
CONVERSATION_KEYS = ("student_context_id", "highest_risk", "safety_pending", "referral_offer_level",
                     "support_offer_state", "case_id", "school_referral_topics")


@app.route("/api/chat/reset", methods=["POST"])
def api_chat_reset():
    """Start a new conversation: delete the old one from the expiring store and forget its risk level, so a
    misread (「睡不著怎麼辦」 once kept a whole conversation in safety mode) does not follow the student.
    Workbench cases already created stay; the student keeps their nickname and township."""
    error = require_csrf()
    if error:
        return error
    context = current_student_context()
    if context is None:
        return jsonify({"error": "請先閱讀資料使用說明"}), 403
    holder = conversation_lock(session["student_context_id"])
    with holder.lock:
        case_id = session.get("case_id") or context.get("case_id", "")
        delete_student_context(session["student_context_id"], session["student_email_hash"])
        for key in CONVERSATION_KEYS:
            session.pop(key, None)
        session["student_context_id"] = secrets.token_urlsafe(32)
        set_student_profile(session["student_context_id"], session["student_email_hash"], context["profile"])
    log_audit("student", "student_reset_conversation", case_id if get_case_by_id(case_id) else "",
              "學生開始新對話，舊對話暫存已刪除（工作臺既有個案不受影響）")
    return jsonify({"ok": True, "message": "已開始新對話，剛才的對話已從暫存刪除。"})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    error = require_csrf()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "資料格式不正確"}), 400
    if student_identity() is None:
        return jsonify({"error": "請先閱讀資料使用說明；暱稱、學校與信箱皆可留白"}), 403
    message = data.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        return jsonify({"error": "訊息需為 1 至 2000 字"}), 400
    message = message.strip()
    # Never throttled: a message the rules rate orange/red, any message in a conversation that has reached
    # orange/red, or an answer to an open safety question (「有，藥已經準備好了」 got HTTP 429 before).
    urgent = (perform_triage(text=message)["level"] in ("orange", "red")
              or session.get("highest_risk") in ("orange", "red") or session.get("safety_pending", False))
    if not urgent and not limiter.hit("chat:" + session["student_context_id"], Config.CHAT_RATE_LIMIT, 60):
        # Even a throttled student sees where to get immediate help.
        return jsonify({"error": "訊息傳得太快了，請稍等一下再傳。若有立即危險，請直接撥打 119，或 1925 安心專線。",
                        "show_urgent_help": session.get("highest_risk") == "red"}), 429
    # The reply style is the student's own choice; it can never lower safety (see build_state).
    if data.get("reply_style") in REPLY_STYLES:
        session["reply_style"] = data["reply_style"]
    # Browser-provided history/state is not authoritative. The expiring server context owns memory.
    holder = conversation_lock(session["student_context_id"])
    with holder.lock:
        return process_chat_turn(message)


def process_chat_turn(message):
    started = time.monotonic()  # the whole turn, model call included (it runs in prepare_dialogue)
    context = current_student_context()
    if context is None:
        return jsonify({"error": "請重新確認登錄資料"}), 403
    previous_level = max(
        (session.get("highest_risk", "green"), context["draft"].get("risk_level", "green")),
        key=RISK_LEVEL_WEIGHTS.get,
    )
    triage = perform_triage(text=message, previous_level=previous_level)
    previous_state = context.get("dialogue_state", {})
    history = previous_state.get("history", [])
    # DYN-04: the server's local hour (Taiwan deployment) lets late-night ambiguous messages get human review.
    style = session.get("reply_style", "warm")
    chosen = {}

    def offer_chooser(state):
        # Single-call mode: pick the offer from the rule-based state so the model prompt matches it.
        chosen["offer"] = choose_support_offer(message, state["risk_level"], session.get("support_offer_state"), state)
        return chosen["offer"][0]

    triage, dialogue_state = prepare_dialogue(message, triage, previous_state, history,
                                              hour=datetime.now().hour, reply_style=style, offer_chooser=offer_chooser,
                                              township=context["profile"].get("township"))
    context = stage_student_summary(session["student_context_id"], session["student_email_hash"], triage, {}, message)
    saved_triage = context["draft"]["triage"]
    if RISK_LEVEL_WEIGHTS[saved_triage["level"]] > RISK_LEVEL_WEIGHTS[triage["level"]]:
        triage = saved_triage
        dialogue_state = build_state(message, triage, previous_state, history=history, reply_style=style)
    # v1.3-A: record evidence-bound wellbeing notes without affecting triage or the reply.
    dialogue_state["wellbeing_signals"] = update_wellbeing_signals(
        previous_state.get("wellbeing_signals"), message, dialogue_state)
    level = triage["level"]
    session["highest_risk"] = level
    if level in ("orange", "red") and re.search(r"^(?:我)?(?:現在|還是|改成)?(?:願意|想要?|要)轉介", message):
        session.pop("referral_offer_level", None)
    # Always decide the offer from the final state (hints may have raised risk since the draft was written).
    offer, offer_state = choose_support_offer(message, level, session.get("support_offer_state"), dialogue_state)
    if chosen and dialogue_state.get("_prepared_reply") and chosen["offer"][0] != offer:
        dialogue_state.pop("_prepared_reply")  # the draft was written for a different offer
    # (A draft written before the model's own analysis changed the safety situation is dropped in
    # generate_youth_response, which then sends the reviewed safety text.)
    reply = generate_youth_response(message, triage, history, support_offer=offer, dialogue_state=dialogue_state)
    record_diagnostics(reply, level, started, dialogue_state.get("safety_action", "none"))
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exchange = [{"role": "user", "text": message, "at": sent_at},
                {"role": "assistant", "text": reply["reply"], "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "source": reply_source(reply["model_used"]),
                 **({"cards": list(dict.fromkeys(s.get("card", s["title"]) for s in reply["sources"]))}
                    if reply.get("sources") else {})}]
    try:
        context = save_dialogue_state(session["student_context_id"], session["student_email_hash"],
            remember_turn(dialogue_state, message, reply["reply"]), previous_state.get("turn_count", 0),
            exchange=exchange)
    except ValueError as exc:
        return jsonify({"error": str(exc), "show_urgent_help": session.get("highest_risk") == "red"}), 409
    session["support_offer_state"] = offer_state
    session["safety_pending"] = bool(dialogue_state.get("safety_check_required"))
    if session.get("case_id"):
        flag_risk_after_consent(session["case_id"], level)
    alert = safety_alert(level)
    # 性平／霸凌: point to the school counseling office at every risk level. Sent with every message that names
    # the topic (the page shows each topic's card once), so a reply lost to a network error is not the only chance.
    seen = session.get("school_referral_topics", [])
    topics = school_referral.detect_topics(message)
    if topics:
        session["school_referral_topics"] = seen + [t for t in topics if t not in seen]
    return jsonify({
        "reply": reply["reply"],
        # Model names are backend-only; the student page only needs to know where the reply came from.
        "model_used": "雲端 AI" if reply_source(reply["model_used"]) == "ai" else reply["model_used"],
        "reply_source": reply_source(reply["model_used"]),
        # Why the local fallback answered (timeout, rate_limited, cooldown, rule_check…); no content.
        "fallback_reason": reply.get("fallback_reason"),
        "companion_role": public_role(dialogue_state),
        "reply_style": dialogue_state.get("reply_style", "warm"),
        "style_overridden_by_safety": bool(dialogue_state.get("style_overridden_by_safety")),
        "support_offer": offer,
        # Harness: the reviewed cards this reply cited (title, organisation, link).
        "sources": reply.get("sources", []),
        "show_urgent_help": level == "red",
        "show_support_help": level in ("orange", "red"),
        "notification_connected": False,
        "safety_alert": alert,
        "next_steps": student_next_steps(context),
        "school_referral": (school_referral.payload(session["school_referral_topics"], context["profile"].get("student_school", ""),
                                                    county=STUDENT_COUNTY) if topics else None),
        "school_referral_available": bool(session.get("school_referral_topics")),
    })


# Students choose a Nantou township, so among schools of the same name (中正國小) the Nantou one comes first.
STUDENT_COUNTY = "南投縣"


@app.route("/api/school-referral", methods=["POST"])
def api_school_referral():
    """The counseling-office card again, optionally for a school the student names here. The name is only used
    to look up the office; it is not saved and nothing is sent to the school."""
    error = require_csrf()
    if error:
        return error
    context = current_student_context()
    if context is None:
        return jsonify({"error": "請先閱讀資料使用說明"}), 403
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    code = data.get("code")
    if code is not None and (not isinstance(code, str) or not re.fullmatch(r"[0-9A-Za-z]{4,8}", code)):
        return jsonify({"error": "學校代碼不正確"}), 400
    school = data.get("school")
    if school is None:
        school = "" if code else context["profile"].get("student_school", "")
    if not isinstance(school, str) or len(school) > 100:
        return jsonify({"error": "學校名稱需為 100 字以內的文字"}), 400
    return jsonify({"school_referral": school_referral.payload(
        session.get("school_referral_topics", []), school.strip(), code=code, county=STUDENT_COUNTY)})


def safety_alert(level):
    """Orange/red: send the necessary safety information to the workbench (no identity, contact or full
    conversation) and tell the student exactly what was sent. None when nothing new was sent."""
    if level not in ("orange", "red") or Config.PUBLIC_DEMO_MODE:
        return None  # a public demo never writes formal cases; the urgent-help panel still shows
    sent = auto_safety_handoff(session["student_context_id"], session["student_email_hash"])
    return STUDENT_ALERT_NOTICE if sent else None


def assessment_feedback(triage, level):
    """What the student sees after the self-check: plain words and a next step, never a light, score band or
    label (the student page shows no triage colours; scores are for trained staff)."""
    bsrs = triage["bsrs_details"]
    lines = {
        "green": "謝謝你花時間填完。從你的回答看，最近的困擾還在你撐得住的範圍；如果哪天變重了，隨時回來聊，或找信任的大人說說。",
        "yellow": "謝謝你願意填完。看起來最近有些事情讓你不太好受，而且已經影響到生活。可以考慮找輔導老師或信任的大人聊聊，我也可以幫你寫一張字條。",
        "orange": "謝謝你老實回答。你最近承受的比想像中多，這不是你一個人要扛的事。想請你讓受過訓練的人一起幫忙；下方有現在就能撥的電話。",
        "red": "謝謝你告訴我。你現在的安全最重要：如果有立即危險，請馬上撥 119；想找人談可以打 1925，二十四小時都有人接。",
    }
    text = lines[level]
    if (bsrs.get("suicide_score") or 0) >= 1 and level != "red":
        text += "你在最後一題有勾選，想直接問你：你現在安全嗎？想說的話可以在對話框跟我說；需要時也可以直接打 1925。"
    return {"text": text, "ask_safety": (bsrs.get("suicide_score") or 0) >= 1}


@app.route("/api/assessment", methods=["POST"])
def api_assessment():
    error = require_csrf()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "資料格式不正確"}), 400
    if student_identity() is None:
        return jsonify({"error": "請先閱讀資料使用說明；不需要填寫學校電子郵件"}), 403
    try:
        triage = perform_triage(
            text=str(data.get("dialogue_snippet", ""))[:2000],
            bsrs5_answers=data.get("bsrs5"),
            duration=str(data.get("duration", ""))[:100],
            life_impact=str(data.get("life_impact", ""))[:300],
            support_system=str(data.get("support_system", ""))[:300],
            previous_level=session.get("highest_risk", "green"),
        )
        if not triage["bsrs_details"]["completed"]:
            raise ValueError("請完整填寫六題後再提交正式量表")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    context = current_student_context()
    if context is None:
        return jsonify({"error": "請重新確認登錄資料"}), 403
    context = stage_student_summary(
        session["student_context_id"], session["student_email_hash"], triage,
        {
            "category": str(data.get("category", "身心狀況檢核"))[:100],
            "duration": str(data.get("duration", "尚未提及"))[:100],
            "life_impact": str(data.get("life_impact", "尚未提及"))[:300],
            "support_system": str(data.get("support_system", "尚未提及"))[:300],
            "bsrs5": {key: int(data["bsrs5"][key]) for key in BSRS_ITEMS},
            # How long the self-check took (proposal goal: under 3 minutes); shown to staff only.
            **({"checkin_seconds": data["elapsed_seconds"]} if type(data.get("elapsed_seconds")) is int
               and 0 < data["elapsed_seconds"] < 3600 else {}),
        },
        message=str(data.get("dialogue_snippet", ""))[:1200] or None,
    )
    level = context["draft"]["risk_level"]
    session["highest_risk"] = level
    if session.get("case_id"):
        flag_risk_after_consent(session["case_id"], level)
    alert = safety_alert(level)
    return jsonify({
        "message": ("已完成自填檢核。" + (STUDENT_ALERT_NOTICE if alert else
                    "結果只存在這次的暫存；你同意分享後，摘要才會進入真人工作臺。")),
        "safety_alert": alert,
        "result": assessment_feedback(triage, level),
        "help_draft": generate_help_seeking_draft(context["draft"]),
        "show_urgent_help": level == "red", "notification_connected": False,
        "next_steps": student_next_steps(context),
    })


@app.route("/api/referral/consent", methods=["POST"])
def api_referral_consent():
    error = require_csrf()
    if error:
        return error
    context = current_student_context()
    if context is None:
        return jsonify({"error": "請先確認登錄資料"}), 403
    data = request.get_json(silent=True)
    allowed = {"consent", "preferred_name", "revision", "consent_kind", "note"}
    if not isinstance(data, dict) or set(data) - allowed or type(data.get("consent")) is not bool:
        return jsonify({"error": "請提供同意布林值；身分與鄉鎮由本次登錄帶入"}), 400
    name = data.get("preferred_name", "")
    if not isinstance(name, str) or len(name) > 30 or any(ord(c) < 32 for c in name):
        return jsonify({"error": "稱呼請填 30 字以內的單行文字，也可以留白"}), 400
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > 300 or any(ord(c) < 32 and c != "\n" for c in note):
        return jsonify({"error": "想讓老師知道的事請在 300 字以內，也可以留白"}), 400
    resources = referral_resources(context["profile"]["township"])
    if data["consent"] is False:
        return jsonify({"recorded": False, "resources": resources,
                        "message": "這次沒有新增分享摘要，你可以先打電話，也可以繼續說。",
                        "notification_connected": False, "external_referral_sent": False})
    if Config.PUBLIC_DEMO_MODE:
        return jsonify({"recorded": False, "demo_mode": True, "resources": resources,
                        "error": "這是公開示範網站，不會建立正式個案，也沒有人會收到。需要真人協助，請直接撥 1925（24 小時）"
                                 "或找學校輔導室；有立即危險請撥 119。"}), 403
    if type(data.get("revision")) is not int or data.get("consent_kind") not in ("summary", "referral", "request"):
        return jsonify({"error": "請先查看目前的下一步選擇與摘要"}), 400
    try:
        case = record_student_consent(
            session["student_context_id"], session["student_email_hash"],
            data["revision"], data["consent_kind"], name.strip(), note.strip(),
        )
    except ValueError as exc:
        latest = current_student_context()
        return jsonify({"error": str(exc), "next_steps": student_next_steps(latest),
                        "show_urgent_help": (latest or {}).get("draft", {}).get("risk_level") == "red"}), 409
    session["case_id"] = case["case_id"]
    is_referral = case["summary"]["student_consent"]["kind"] == "referral"
    response = {
        "recorded": True, "case_id": case["case_id"], "resources": resources,
        "message": "你同意分享的摘要已存入本網站的真人工作臺，等待授權人員查看。"
                   + ("" if case["student_email"] else "你沒有留下聯絡方式，工作人員無法主動聯絡你；想被聯絡可以補填信箱後再送一次。")
                   + "目前沒有自動通知學校，也沒有接通或送交南投輔導中心；需要立即協助請直接打電話。",
        "notification_connected": False, "external_referral_sent": False,
    }
    if is_referral:
        profile = case["summary"]["student_profile"]
        response["referral_form"] = (
            "少年仔、安啦會客室｜學生同意轉介單（尚未對外送出）\n"
            f"紀錄編號：{case['case_id']}\n希望被稱呼：{case['student_alias']}\n"
            f"學校：{profile.get('student_school') or '尚未填寫'}\n"
            f"信箱：{case['student_email'] + '（未驗證）' if case['student_email'] else '未提供'}\n鄉鎮：{case['township']}\n"
            f"同意時間：{case['summary']['student_consent']['consented_at']}\n"
            f"學生原話節錄：\n{case.get('dialogue_snippet') or '尚無對話文字'}\n\n"
            "公開聯絡電話：\n" + "\n".join(f"{r['name']}：{r['phone']}" for r in resources)
            + "\n本單只保存在本網站工作臺；實際聯絡、受理與轉介需由真人另行辦理。"
        )
    return jsonify(response)


@app.route("/api/config/llm", methods=["GET", "POST"])
@admin_only
def api_config_llm():
    """Staff-only model panel: which models the key can use, their ranking, health and the active one.
    POST {"action": "refresh"} re-reads the provider's model list (metadata only, no tokens);
    POST {"action": "select_model", "model": name or ""} puts a listed model first ("" = automatic)."""
    provider = _provider()
    configured = providers.configured()
    info = providers.active() or {}
    if request.method == "POST":
        error = require_csrf()
        if error:
            return error
        data = request.get_json(silent=True)
        action = data.get("action") if isinstance(data, dict) else None
        if action not in ("refresh", "select_model"):
            return jsonify({"error": "金鑰與服務商請在啟動前設定；這裡只能重新偵測或選擇模型"}), 400
        if not configured:
            return jsonify({"error": "尚未設定雲端 AI 金鑰"}), 400
        if action == "refresh":
            model_router.discover(provider, force=True)
            model_router.clear_pauses(provider)  # retry at once after a setting was fixed
            reset_provider_cooldown()
            log_audit(staff_actor(), "refresh_models", "", provider)
        else:
            model = data.get("model") or ""
            if not isinstance(model, str) or (model and model not in model_router.catalog_models(provider)):
                # Only names read from this key's model list: a typo or a model the key cannot use is refused.
                return jsonify({"error": "只能選擇這把金鑰可用的模型；清單沒有出現時請先按「重新偵測可用模型」"}), 400
            set_setting("model:" + provider, model)
            model_router.set_manual(provider, model or None)
            log_audit(staff_actor(), "select_model", "", f"{provider}：{model or '自動選擇'}")
    elif configured and Config.MODEL_AUTO_SELECT:
        model_router.discover(provider)  # cached for 30 minutes
    return jsonify({
        "provider": provider if configured else "builtin",
        # Service name only; the key itself never leaves the server.
        "provider_label": info.get("label") if configured else "本機回覆",
        "base_url": info.get("base_url") if configured and provider == "custom" else None,
        "configured": configured,
        "auto_select": Config.MODEL_AUTO_SELECT,
        "status": model_status(),
        "router": model_router.snapshot(provider) if configured else None,
        "temperature": Config.LLM_TEMPERATURE,
        "call_mode": Config.LLM_CALL_MODE,
    })


@app.route("/api/cases")
@staff_only
def api_get_cases():
    cases = get_all_cases(
        request.args.get("risk"), request.args.get("township"), request.args.get("status")
    )
    return jsonify({"cases": cases, "count": len(cases)})


@app.route("/api/cases/<case_id>")
@staff_only
def api_get_case(case_id):
    case = get_case_by_id(case_id)
    if not case:
        return jsonify({"error": "找不到個案"}), 404
    # Every staff read of a case is recorded in the hash-chained audit log.
    log_audit(staff_actor(), "view_case", case_id, "查閱個案摘要")
    return jsonify({"case": case})


@app.route("/api/cases/<case_id>/status", methods=["POST"])
@staff_only
def api_update_case_status(case_id):
    error = require_csrf()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    notes = data.get("notes", "")
    decision = data.get("decision_action", "")
    if not isinstance(notes, str) or not isinstance(decision, str) or len(notes) > 1000:
        return jsonify({"error": "備註格式不正確或過長"}), 400
    if status in ("contacted", "referred") and (not data.get("contact_confirmed") or not notes.strip()):
        return jsonify({"error": "請真人在系統外完成聯繫或轉介，並記錄處理方式與時間"}), 400
    case = get_case_by_id(case_id)
    if status == "completed" and case and case["risk_level"] in ("orange", "red") and not notes.strip():
        return jsonify({"error": "紅、橙燈個案結案前，請在備註記錄處理經過與結果"}), 400
    if not update_case_status(case_id, status, notes, decision[:200], actor=staff_actor()):
        return jsonify({"error": "個案不存在或狀態不正確"}), 400
    return jsonify({"success": True})


def staff_actor():
    user = session.get("staff_user") or BUILTIN_ADMIN
    name = session.get("staff_name") or "未填名字"
    return f"{name}（內建管理員帳號）" if user == BUILTIN_ADMIN else f"{name}（{user}）"


@app.route("/api/staff/users", methods=["GET", "POST"])
@admin_only
def api_staff_users():
    """GET lists accounts (never passwords). POST creates one: username, display_name, role, password."""
    if request.method == "GET":
        return jsonify({"users": list_staff_users(), "roles": STAFF_ROLES,
                        "builtin_admin": bool(Config.WORKBENCH_PASSWORD)})
    error = require_csrf()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    name = re.sub(r"[\x00-\x1f<>]", "", str(data.get("display_name", ""))).strip()[:20]
    password = data.get("password", "")
    if not re.fullmatch(USERNAME_PATTERN, username) or username == BUILTIN_ADMIN:
        return jsonify({"error": "帳號需為 3–30 個英數字、底線、點或連字號，且不能是 admin"}), 400
    if not name or not isinstance(password, str) or len(password) < 10:
        return jsonify({"error": "請填名字，密碼至少 10 個字元"}), 400
    try:
        create_staff_user(username, name, data.get("role"), password)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log_audit(staff_actor(), "staff_user_created", "", f"新增帳號 {username}（{STAFF_ROLES[data['role']]}）")
    return jsonify({"users": list_staff_users()})


@app.route("/api/staff/users/<username>", methods=["POST"])
@admin_only
def api_staff_user_update(username):
    """Change an account's role, switch it on or off, or set a new password."""
    error = require_csrf()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    changes = {key: data[key] for key in ("role", "active", "password") if key in data}
    if "password" in changes and (not isinstance(changes["password"], str) or len(changes["password"]) < 10):
        return jsonify({"error": "密碼至少 10 個字元"}), 400
    if "active" in changes and type(changes["active"]) is not bool:
        return jsonify({"error": "資料格式不正確"}), 400
    removes_admin = changes.get("role", "admin") != "admin" or changes.get("active") is False
    if removes_admin and not Config.WORKBENCH_PASSWORD and count_active_admins() <= 1 and any(
            u["username"] == username and u["role"] == "admin" and u["active"] for u in list_staff_users()):
        return jsonify({"error": "至少要保留一個可以登入的管理員"}), 400
    try:
        found = update_staff_user(username, **changes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not found:
        return jsonify({"error": "找不到這個帳號"}), 404
    done = "、".join(label for key, label in (("role", "改角色"), ("active", "啟用／停用"), ("password", "重設密碼"))
                    if key in changes)
    log_audit(staff_actor(), "staff_user_updated", "", f"帳號 {username}：{done}")
    return jsonify({"users": list_staff_users()})


@app.route("/api/staff/me/password", methods=["POST"])
@staff_only
def api_staff_change_password():
    """Personal accounts change their own password; the built-in admin's is WORKBENCH_PASSWORD."""
    error = require_csrf()
    if error:
        return error
    user = session.get("staff_user") or BUILTIN_ADMIN
    if user == BUILTIN_ADMIN:
        return jsonify({"error": "內建管理員的密碼是 WORKBENCH_PASSWORD，請在主機設定修改"}), 400
    data = request.get_json(silent=True) or {}
    new = data.get("new_password", "")
    if not authenticate_staff(user, str(data.get("current_password", ""))):
        return jsonify({"error": "目前的密碼不正確"}), 400
    if not isinstance(new, str) or len(new) < 10:
        return jsonify({"error": "新密碼至少 10 個字元"}), 400
    update_staff_user(user, password=new)
    log_audit(staff_actor(), "staff_password_changed", "", "本人修改密碼")
    return jsonify({"ok": True})


@app.route("/api/admin/backup", methods=["POST"])
@admin_only
def api_admin_backup():
    """Download a backup of the database (administrators only, logged). On Render's free plan the database is
    wiped on every redeploy, so this is the way to keep cases, accounts and the audit log."""
    error = require_csrf()
    if error:
        return error
    if not limiter.hit("backup:" + (session.get("staff_user") or BUILTIN_ADMIN), 10, 3600):
        return jsonify({"error": "備份下載太頻繁，請一小時後再試"}), 429
    data = backup_snapshot()
    name = datetime.now().strftime("anla_backup_%Y%m%d_%H%M.db")
    log_audit(staff_actor(), "admin_backup_downloaded", "",
              f"下載資料庫備份 {name}（{max(1, len(data) // 1024)} KB；不含未分享的對話暫存與加密金鑰）")
    return Response(data, mimetype="application/x-sqlite3",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


SOURCE_CHECK_BATCH = 12  # pages per request, so one request stays well under the server timeout


@app.route("/api/admin/sources", methods=["GET", "POST"])
@admin_only
def api_admin_sources():
    """「來源檢查」: really fetch approved official pages (engine/webfetch.py) and record each run.
    GET lists the approved URLs and the latest recorded runs; POST {"offset": n} checks the next batch."""
    urls = webfetch.approved_urls()
    if request.method == "GET":
        return jsonify({"total": len(urls), "runs": recent_tool_runs()})
    error = require_csrf()
    if error:
        return error
    offset = (request.get_json(silent=True) or {}).get("offset", 0)
    if type(offset) is not int or not 0 <= offset < max(len(urls), 1):
        return jsonify({"error": "範圍不正確"}), 400
    if offset == 0 and not limiter.hit("sources:" + (session.get("staff_user") or BUILTIN_ADMIN), 5, 3600):
        return jsonify({"error": "來源檢查太頻繁，請一小時後再試"}), 429
    from concurrent.futures import ThreadPoolExecutor
    batch = urls[offset:offset + SOURCE_CHECK_BATCH]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(webfetch.fetch_official_resource, batch))
    for result in results:
        log_tool_run(result, staff_actor())
    if offset + len(batch) >= len(urls):
        log_audit(staff_actor(), "source_check_finished", "", f"來源檢查完成：{len(urls)} 個核准網址")
    return jsonify({"total": len(urls), "next": offset + len(batch), "results": results})


@app.route("/api/admin/diagnostics")
@admin_only
def api_admin_diagnostics():
    """The last turns' diagnostics: which model answered, where the reply came from, how long it took, what the
    checks found. No conversation content."""
    return jsonify({"turns": list(TURN_DIAGNOSTICS)[:50], "demo_mode": Config.PUBLIC_DEMO_MODE})


@app.route("/api/audit")
@admin_only
def api_audit():
    """The latest operation records and whether the hash chain is intact (administrators only)."""
    ok, bad_id = verify_audit_chain()
    return jsonify({"logs": recent_audit_logs(100), "chain_ok": ok, "first_bad_id": bad_id})


@app.route("/api/cases/<case_id>/printed", methods=["POST"])
@staff_only
def api_case_printed(case_id):
    """Printing takes student records off the screen; it is audited like viewing."""
    error = require_csrf()
    if error:
        return error
    if not get_case_by_id(case_id):
        return jsonify({"error": "個案不存在"}), 404
    log_audit(staff_actor(), "print_case", case_id, "列印個案摘要")
    return jsonify({"success": True})


@app.route("/api/stats")
@staff_only
def api_stats():
    cases = get_all_cases()
    open_cases = [c for c in cases if c["status"] not in ("referred", "completed")]
    return jsonify({
        "total": len(cases),
        # Level counts are open cases only: a closed red case is no longer waiting for anyone.
        **{level: sum(c["risk_level"] == level for c in open_cases) for level in RISK_LEVEL_WEIGHTS},
        "pending": sum(c["status"] in ("pending", "student_requested_referral", "student_shared_summary", "auto_safety_alert",
                                       "student_requested_help")
                       for c in cases),
        "in_progress": sum(c["status"] in ("reviewing", "contacted") for c in cases),
        "completed": sum(c["status"] in ("referred", "completed") for c in cases),
        "townships_covered": len({c["township"] for c in cases}),
    })


SMALL_CELL = 3  # counts below this are not shown exactly, so a small school cannot work out who a case is


@app.route("/api/stats/breakdown")
@staff_only
def api_stats_breakdown():
    """De-identified statistics (proposal: 去識別化統計): counts only, no case ids, names or words."""
    from collections import Counter
    from engine.ai_agent import RISK_TYPE_LABELS
    cases = get_all_cases()
    levels = {"red": "紅色", "orange": "橙色", "yellow": "黃色", "green": "綠色"}
    counters = {
        "燈號": Counter(levels.get(c["risk_level"], c["risk_level"]) for c in cases),
        "來源": Counter("學生同意分享" if c["summary"].get("student_consent") else
                        "系統安全通報（未同意）" if c["summary"].get("auto_alert") else "其他" for c in cases),
        "處理狀態": Counter(STATUS_LABELS.get(c["status"], c["status"]) for c in cases),
        "鄉鎮": Counter(c["township"] for c in cases),
        "風險類型": Counter(RISK_TYPE_LABELS.get(t, t) for c in cases for t in set(
            ((c["triage"].get("dialogue_safety") or {}).get("risk_types") or [])) if t not in ("none", "other")),
        "建立月份": Counter((c["created_at"] or "")[:7] for c in cases),
        "完成自填檢核": Counter("有" if c["bsrs5"] else "沒有" for c in cases),
    }
    show = lambda n: str(n) if n >= SMALL_CELL else f"少於 {SMALL_CELL}"
    return jsonify({"total": show(len(cases)) if cases else "0", "groups": [
        {"title": title, "rows": [[label, show(n)] for label, n in counter.most_common()]}
        for title, counter in counters.items()]})


@app.route("/api/mock-cases")
@staff_only
def api_get_mock_cases():
    return jsonify({"mock_cases": MOCK_CASES, "count": len(MOCK_CASES)})


@app.route("/api/demo/evaluate/<case_id>")
@staff_only
def api_demo_evaluate(case_id):
    """只讀的示範評估；絕不把模擬案例灌進真實工作臺。"""
    item = next((case for case in MOCK_CASES if case.get("case_id") == case_id), None)
    if item is None:
        return jsonify({"error": "找不到模擬案例"}), 404
    triage = perform_triage(
        text=item.get("dialogue_snippet", ""),
        bsrs5_answers=item.get("bsrs5"),
        duration=item.get("duration", ""),
        life_impact=item.get("life_impact", ""),
        support_system=item.get("support_system", ""),
    )
    return jsonify({
        "case_id": case_id,
        "expected_level": item.get("risk_level"),
        "actual_level": triage["level"],
        "explainability": triage["explainability"],
        "theoretical_basis": triage.get("theoretical_basis", []),
        "pending_disambiguation": triage.get("pending_disambiguation", False),
        "summary": generate_counselor_one_page_summary(item, triage),
    })


@app.route("/api/explain/scenarios")
@staff_only
def api_explain_scenarios():
    """v1.3-B：只列出虛構重播情境，不讀取任何真實對話。"""
    return jsonify({"version": EXPLAIN_VERSION, "scenarios": [
        {"id": s["id"], "title": s.get("title", s["id"]), "purpose": s.get("purpose", ""),
         "turn_count": len(s["turns"]), "expected_highest": s.get("expected_highest")}
        for s in EXPLAIN_SCENARIOS]})


@app.route("/api/explain/<scenario_id>")
@staff_only
def api_explain_scenario(scenario_id):
    """離線重播虛構對話；不呼叫模型、不寫入資料庫、不建立個案。"""
    scenario = next((s for s in EXPLAIN_SCENARIOS if s["id"] == scenario_id), None)
    if scenario is None:
        return jsonify({"error": "找不到虛構情境"}), 404
    return jsonify(explain(scenario))


@app.route("/api/resources")
def api_get_resources():
    township = request.args.get("township", "all")
    category = request.args.get("category", "all")
    keyword = request.args.get("keyword", "").strip().lower()
    matches = [
        resource for resource in NANTOU_RESOURCES
        if (township == "all" or resource["township"] == township
            or "全國" in resource["township"]
            or (township in TOWNSHIPS and resource["id"] == "stu_center")
            or township in resource.get("suggested_townships", []))
        and (category == "all" or category in resource["category"])
        and (not keyword or keyword in resource["name"].lower()
             or keyword in resource["township"].lower()
             or any(keyword in service.lower() for service in resource["services"]))
    ]
    return jsonify({"resources": matches, "total": len(matches)})


DRAFT_EXTRA = r"睡不好|睡不著|失眠|壓力|心情不好|焦慮|人際|被排擠|被笑|霸凌|課業"


def draft_topics(context):
    """Up to three topic words the student used (「數學、睡不好」), never their sentences."""
    texts = [t.get("text", "") for t in (context.get("dialogue_state") or {}).get("history", []) if t.get("role") == "user"]
    texts = texts or (context["draft"].get("dialogue_snippet", "").split("\n"))
    found = []
    for text in texts:
        for match in re.finditer(TOPIC_PATTERN + "|" + DRAFT_EXTRA, text):
            if match.group(0) not in found:
                found.append(match.group(0))
    return "、".join(found[:3])


@app.route("/api/generate-draft", methods=["POST"])
def api_generate_draft():
    error = require_csrf()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    context = current_student_context()
    if context is None:
        return jsonify({"error": "請先確認登錄資料"}), 403
    if not isinstance(data, dict):
        return jsonify({"error": "資料格式不正確"}), 400
    target = data.get("target", "輔導老師")
    if target not in ("輔導老師", "班導師", "家長"):
        return jsonify({"error": "求助對象不正確"}), 400
    draft = context["draft"]
    case_info = {**draft, "category": draft_topics(context), "category_auto": False}
    return jsonify({"target": target, "draft": generate_help_seeking_draft(case_info, target),
                    "next_steps": student_next_steps(context),
                    "show_urgent_help": context["draft"].get("risk_level") == "red"})


if __name__ == "__main__":
    app.run(host=Config.HOST, port=5000, debug=Config.DEBUG)
