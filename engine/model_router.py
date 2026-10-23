"""Pick the best model the configured API key can use, and fail over when one misbehaves.

Model choice is an operator concern: students never see model names (backend only).
- Discovery reads the provider's model list (no generation, no token cost) and caches it.
- Ranking is a transparent heuristic, not a benchmark (see rank_key): newer version first, then
  pro > flash > flash-lite (or full > mini > nano), stable before preview. Models whose average reply
  time exceeds SLOW_SECONDS are moved to the back. GEMINI_MODEL / OPENAI_MODEL pin a first choice.
- Health is per model: quota (429) and "not found" pause a model at once; timeouts, 5xx, empty or
  malformed replies pause it after FAILURES_BEFORE_PAUSE consecutive failures.
"""
import logging
import re
import threading
import time

import requests

from config import Config
from engine import providers

DISCOVERY_TTL = 30 * 60
DISCOVERY_RETRY = 60  # a failed model-list read is tried again after a minute
MAX_FAILOVER = 3
SLOW_SECONDS = 15
FAILURES_BEFORE_PAUSE = 2
PAUSE_SECONDS = {"rate_limited": 60, "model_not_found": 24 * 3600, "rejected": 30 * 60,
                 "unavailable": 30, "timeout": 30, "empty": 60, "bad_response": 60}
# A timeout pauses a model at once (briefly): otherwise every student in that minute waits on it too.
IMMEDIATE = {"rate_limited", "model_not_found", "rejected", "timeout"}
MAX_PAUSE = 300  # cap for Retry-After hints
# Statuses that say "this model, right now" — the same turn may try the next model.
MODEL_LEVEL = {"rate_limited", "model_not_found", "rejected", "unavailable", "timeout", "empty", "bad_response"}

GEMINI_EXCLUDE = re.compile(r"tts|image|imagen|embed|aqa|veo|audio|live|robotics|computer-use|learnlm|gemma|"
                            r"omni|nano-banana|native|dialog|transcri|search", re.I)
OPENAI_INCLUDE = re.compile(r"^(?:gpt-\d|o\d)", re.I)
OPENAI_EXCLUDE = re.compile(r"audio|realtime|transcribe|tts|image|search|embedding|instruct|whisper|dall|"
                            r"moderation|codex|computer", re.I)
# Other OpenAI-compatible services list everything they host; keep chat models only.
COMPATIBLE_EXCLUDE = re.compile(r"embed|whisper|tts|audio|speech|transcri|image|vision-only|dall|stable-diffusion|"
                                r"flux|moderation|guard|rerank|ocr|realtime|search|code(?:stral)?-embed", re.I)

_clock = time.monotonic
_lock = threading.Lock()
_catalog = {}   # provider -> {"models": [...], "at": float, "error": str | None}
_health = {}    # (provider, model) -> dict


def reset():
    with _lock:
        _catalog.clear()
        _health.clear()
        _manual.clear()


_manual = {}  # provider -> model chosen by staff in the workbench panel (saved by the app, restored at start)


def set_manual(provider, model):
    """Staff choice from the panel; None goes back to automatic selection. Failover still applies."""
    with _lock:
        if model:
            _manual[provider] = model
        else:
            _manual.pop(provider, None)


def manual_model(provider):
    with _lock:
        return _manual.get(provider)


def catalog_models(provider):
    """Models read from the key's model list (what staff may choose from)."""
    with _lock:
        return list(_catalog.get(provider, {}).get("models", []))


def _api(provider):
    return providers.REGISTRY.get(provider, {}).get("api", "openai")


def default_model(provider):
    info = providers.active()
    if info and info["name"] == provider and info["default_model"]:
        return info["default_model"]
    return providers.REGISTRY.get(provider, {}).get("default_model") or "gpt-4o"


def pinned_model(provider):
    """A model chosen explicitly (kept first in line): the workbench choice, else LLM_MODEL from the environment."""
    return manual_model(provider) or (providers.pinned_model() if providers.name() == provider else None)


def usable(provider, name):
    api = _api(provider)
    if api == "gemini":
        return name.startswith("gemini-") and not GEMINI_EXCLUDE.search(name)
    if api == "anthropic":
        return name.startswith("claude-")
    if provider == "openai":
        return bool(OPENAI_INCLUDE.search(name)) and not OPENAI_EXCLUDE.search(name)
    return not COMPATIBLE_EXCLUDE.search(name)


def rank_key(provider, name):
    """Higher sorts first: (stable release, version, tier). Explicit names beat '-latest' aliases."""
    api = _api(provider)
    if api == "anthropic":
        # claude-opus-5-5, claude-sonnet-4-5-20250929, claude-3-5-haiku-20241022: dated ids are stable snapshots.
        stable = 0 if re.search(r"preview|exp", name) else 1
        digits = re.findall(r"-(\d{1,2})(?=-|$)", name)
        version = float(".".join(digits[:2])) if digits else 0.0
        tier = 3 if "opus" in name else 1 if "haiku" in name else 2
        return (stable, version, tier)
    stable = 0 if re.search(r"preview|exp|experimental|\d{4}-\d{2}-\d{2}|-\d{3,}$", name) else 1
    version = re.search(r"(?:gemini|gpt|o|claude|deepseek|llama|grok|mistral|qwen)-?v?(\d+(?:\.\d+)?)", name, re.I)
    version = float(version.group(1)) if version and "latest" not in name else 0.0
    if api == "gemini":
        tier = 1 if "lite" in name else 3 if "pro" in name else 2 if "flash" in name else 0
    elif provider == "openai":
        tier = 1 if "nano" in name else 2 if "mini" in name else 3
    else:
        low = re.search(r"nano|mini|small|lite|tiny|flash|\b(?:1|3|7|8)b\b|-(?:1|3|7|8)b", name, re.I)
        high = re.search(r"large|pro|max|opus|405b|70b|72b|reasoner", name, re.I)
        tier = 1 if low else 3 if high else 2
    return (stable, version, tier)


def _health_of(provider, model):
    return _health.setdefault((provider, model), {
        "ok": 0, "fail": 0, "streak": 0, "paused_until": 0.0, "last_error": None, "latency": None, "last_ok_at": None})


def discover(provider, force=False):
    """Refresh the ranked catalogue from the provider's model list (metadata only, no tokens)."""
    with _lock:
        cached = _catalog.get(provider)
        if cached and not force and _clock() - cached["at"] < DISCOVERY_TTL:
            return cached
    info = providers.active()
    if not info or info["name"] != provider or not info["base_url"]:
        return {"models": [], "at": _clock(), "error": "not_configured"}
    names, error = [], None
    try:
        api = info["api"]
        response = requests.get(f"{info['base_url']}/models",
                                params={"pageSize": 200} if api == "gemini" else {"limit": 100} if api == "anthropic" else None,
                                headers=providers.auth_headers(info), proxies={"http": None, "https": None, "all": None},
                                timeout=(max(0.5, Config.LLM_CONNECT_TIMEOUT), 10))
        data = response.json() if response.status_code == 200 else {}
        if api == "gemini":
            names = [m["name"].split("/")[-1] for m in data.get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
        else:
            names = [m["id"] for m in data.get("data", [])]
        if response.status_code != 200:
            error = f"HTTP {response.status_code}"
    except Exception as exc:  # network, JSON or shape problems: keep whatever we had before
        error = type(exc).__name__
        names = []
    models = sorted({n for n in names if isinstance(n, str) and usable(provider, n)},
                    key=lambda n: rank_key(provider, n), reverse=True)
    with _lock:
        previous = _catalog.get(provider, {}).get("models", [])
        # A failed read is retried after DISCOVERY_RETRY seconds instead of being cached for half an hour.
        at = _clock() if models else _clock() - DISCOVERY_TTL + DISCOVERY_RETRY
        entry = {"models": models or previous, "at": at, "error": error if not models else None}
        _catalog[provider] = entry
    if error:
        logging.warning("模型清單讀取失敗（%s）：%s", provider, error)
    return entry


def ranked(provider):
    """All known models, best first: pinned model, then catalogue order, slow models last."""
    with _lock:
        models = list(_catalog.get(provider, {}).get("models", []))
        health = {m: dict(_health.get((provider, m), {})) for m in models}
    order = models or [default_model(provider)]
    slow = [m for m in order if (health.get(m, {}).get("latency") or 0) > SLOW_SECONDS]
    order = [m for m in order if m not in slow] + slow
    pin = pinned_model(provider)
    if pin:
        order = [pin] + [m for m in order if m != pin]
    return order


def candidates(provider, limit=MAX_FAILOVER):
    """Healthy models to try this turn, best first."""
    now = _clock()
    with _lock:
        paused = {m for (p, m), h in _health.items() if p == provider and h["paused_until"] > now}
    return [m for m in ranked(provider) if m not in paused][:limit]


def record(provider, model, status, latency=None, retry_after=None, detail=None):
    """`detail` is the provider's own error text, kept for the staff panel (never shown to students)."""
    with _lock:
        h = _health_of(provider, model)
        now = _clock()
        if status == "ok":
            h.update(ok=h["ok"] + 1, streak=0, paused_until=0.0, last_error=None, last_ok_at=now, detail=None)
            if latency is not None:
                h["latency"] = latency if h["latency"] is None else 0.7 * h["latency"] + 0.3 * latency
            return
        if status not in MODEL_LEVEL:
            return
        h.update(fail=h["fail"] + 1, streak=h["streak"] + 1, last_error=status, detail=(detail or "")[:200] or None)
        if status in IMMEDIATE or h["streak"] >= FAILURES_BEFORE_PAUSE:
            pause = PAUSE_SECONDS[status]
            if status == "rate_limited" and retry_after:
                pause = min(retry_after, MAX_PAUSE)
            h["paused_until"] = now + pause


def latency(provider, model):
    """Measured average reply time in seconds, or None before the first successful reply."""
    with _lock:
        return (_health.get((provider, model)) or {}).get("latency")


def clear_pauses(provider):
    """Staff pressed 「重新偵測」 (typically after fixing a setting): let every paused model be tried again."""
    with _lock:
        for (p, _), h in _health.items():
            if p == provider:
                h.update(paused_until=0.0, streak=0)


def pause_summary(provider):
    """(most recent error among paused models, seconds until the first one is back) when none is usable."""
    now = _clock()
    with _lock:
        paused = [(h["paused_until"], h["last_error"]) for (p, _), h in _health.items()
                  if p == provider and h["paused_until"] > now]
    if not paused:
        return None, 0
    soonest = min(paused)
    return soonest[1], soonest[0] - now


def snapshot(provider):
    """Backend view: catalogue, ranking and per-model health. Never includes keys."""
    now = _clock()
    with _lock:
        entry = dict(_catalog.get(provider, {}))
        health = {m: dict(h) for (p, m), h in _health.items() if p == provider}
    order = ranked(provider)
    active = (candidates(provider, 1) or [None])[0]
    rows = []
    for rank, model in enumerate(order, 1):
        h = health.get(model, {})
        paused = max(0.0, h.get("paused_until", 0.0) - now)
        rows.append({"model": model, "rank": rank, "active": model == active, "pinned": model == pinned_model(provider),
                     "state": "paused" if paused else "ok" if h.get("ok") else "retry" if h.get("fail") else "untested",
                     "paused_for": round(paused), "last_error": h.get("last_error"),
                     "latency": round(h["latency"], 1) if h.get("latency") is not None else None,
                     "ok": h.get("ok", 0), "fail": h.get("fail", 0), "detail": h.get("detail")})
    manual = manual_model(provider)
    return {"provider": provider, "active": active, "pinned": pinned_model(provider), "models": rows,
            "manual": manual, "pinned_source": "manual" if manual else "env" if pinned_model(provider) else None,
            "choices": catalog_models(provider),
            "discovered": bool(entry.get("models")),
            "discovered_ago": round(now - entry["at"]) if entry.get("at") else None,
            "discovery_error": entry.get("error"),
            "ranking_rule": "版本越新越前；同版本較大的型號優先（pro > flash > lite、opus > sonnet > haiku、完整 > mini > nano）；"
                            f"正式版優先於預覽版；平均回覆超過 {SLOW_SECONDS} 秒的模型排到最後；"
                            "在這裡手動選擇（或啟動前設定 LLM_MODEL）的模型排第一順位，故障時仍會暫時改用下一個。"}
