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
import os
import re
import threading
import time

import requests

from config import Config

DISCOVERY_TTL = 30 * 60
MAX_FAILOVER = 3
SLOW_SECONDS = 15
FAILURES_BEFORE_PAUSE = 2
PAUSE_SECONDS = {"rate_limited": 60, "model_not_found": 24 * 3600, "rejected": 30 * 60,
                 "unavailable": 30, "timeout": 60, "empty": 60, "bad_response": 60}
IMMEDIATE = {"rate_limited", "model_not_found", "rejected"}
MAX_PAUSE = 300  # cap for Retry-After hints
# Statuses that say "this model, right now" — the same turn may try the next model.
MODEL_LEVEL = {"rate_limited", "model_not_found", "rejected", "unavailable", "timeout", "empty", "bad_response"}

GEMINI_EXCLUDE = re.compile(r"tts|image|imagen|embed|aqa|veo|audio|live|robotics|computer-use|learnlm|gemma|"
                            r"omni|nano-banana|native|dialog|transcri|search", re.I)
OPENAI_INCLUDE = re.compile(r"^(?:gpt-\d|o\d)", re.I)
OPENAI_EXCLUDE = re.compile(r"audio|realtime|transcribe|tts|image|search|embedding|instruct|whisper|dall|"
                            r"moderation|codex|computer", re.I)

_clock = time.monotonic
_lock = threading.Lock()
_catalog = {}   # provider -> {"models": [...], "at": float, "error": str | None}
_health = {}    # (provider, model) -> dict


def reset():
    with _lock:
        _catalog.clear()
        _health.clear()


def default_model(provider):
    return (Config.GEMINI_MODEL or "gemini-2.5-flash") if provider == "gemini" else (Config.OPENAI_MODEL or "gpt-4o")


def pinned_model(provider):
    """A model the administrator chose explicitly via the environment (kept first in line)."""
    return os.environ.get("GEMINI_MODEL" if provider == "gemini" else "OPENAI_MODEL") or None


def usable(provider, name):
    if provider == "gemini":
        return name.startswith("gemini-") and not GEMINI_EXCLUDE.search(name)
    return bool(OPENAI_INCLUDE.search(name)) and not OPENAI_EXCLUDE.search(name)


def rank_key(provider, name):
    """Higher sorts first: (stable release, version, tier). Explicit names beat '-latest' aliases."""
    stable = 0 if re.search(r"preview|exp|experimental|\d{4}-\d{2}-\d{2}|-\d{3,}$", name) else 1
    version = re.search(r"(?:gemini|gpt|o)-?(\d+(?:\.\d+)?)", name)
    version = float(version.group(1)) if version and "latest" not in name else 0.0
    if provider == "gemini":
        tier = 1 if "lite" in name else 3 if "pro" in name else 2 if "flash" in name else 0
    else:
        tier = 1 if "nano" in name else 2 if "mini" in name else 3
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
    names, error = [], None
    try:
        if provider == "gemini":
            response = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                                    params={"pageSize": 200}, headers={"x-goog-api-key": Config.GEMINI_API_KEY},
                                    proxies={"http": None, "https": None, "all": None},
                                    timeout=(max(0.5, Config.LLM_CONNECT_TIMEOUT), 10))
            data = response.json() if response.status_code == 200 else {}
            names = [m["name"].split("/")[-1] for m in data.get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
        else:
            response = requests.get(f"{Config.OPENAI_BASE_URL.rstrip('/')}/models",
                                    headers={"Authorization": f"Bearer {Config.OPENAI_API_KEY}"},
                                    timeout=(max(0.5, Config.LLM_CONNECT_TIMEOUT), 10))
            data = response.json() if response.status_code == 200 else {}
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
        entry = {"models": models or previous, "at": _clock(), "error": error if not models else None}
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


def record(provider, model, status, latency=None, retry_after=None):
    with _lock:
        h = _health_of(provider, model)
        now = _clock()
        if status == "ok":
            h.update(ok=h["ok"] + 1, streak=0, paused_until=0.0, last_error=None, last_ok_at=now)
            if latency is not None:
                h["latency"] = latency if h["latency"] is None else 0.7 * h["latency"] + 0.3 * latency
            return
        if status not in MODEL_LEVEL:
            return
        h.update(fail=h["fail"] + 1, streak=h["streak"] + 1, last_error=status)
        if status in IMMEDIATE or h["streak"] >= FAILURES_BEFORE_PAUSE:
            pause = PAUSE_SECONDS[status]
            if status == "rate_limited" and retry_after:
                pause = min(retry_after, MAX_PAUSE)
            h["paused_until"] = now + pause


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
                     "ok": h.get("ok", 0), "fail": h.get("fail", 0)})
    return {"provider": provider, "active": active, "pinned": pinned_model(provider), "models": rows,
            "discovered": bool(entry.get("models")),
            "discovered_ago": round(now - entry["at"]) if entry.get("at") else None,
            "discovery_error": entry.get("error"),
            "ranking_rule": "版本越新越前；同版本 pro > flash > flash-lite（或 完整 > mini > nano）；正式版優先於預覽版；"
                            f"平均回覆超過 {SLOW_SECONDS} 秒的模型排到最後；GEMINI_MODEL／OPENAI_MODEL 可指定第一順位。"}
