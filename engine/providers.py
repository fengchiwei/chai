"""Which cloud model service the operator's API key belongs to, and how to talk to it.

Three wire formats cover the common services:
- "gemini": Google Generative Language API (generateContent).
- "anthropic": Anthropic Messages API.
- "openai": the OpenAI chat-completions format, also offered by DeepSeek, Groq, OpenRouter, xAI, Mistral
  and self-hosted servers (set LLM_BASE_URL for anything not listed).

The service is taken from LLM_PROVIDER, or recognised from the key's prefix. An ambiguous key is never
sent to another company "to see if it works": that would hand the key to a third party.
Students never see any of this; the staff panel shows the service and model names.
"""
import os

from config import Config

# name -> wire format, label (backend only), base URL, fallback model when the model list cannot be read.
REGISTRY = {
    "gemini": {"api": "gemini", "label": "Google Gemini",
               "base_url": "https://generativelanguage.googleapis.com/v1beta", "default_model": "gemini-2.5-flash"},
    "anthropic": {"api": "anthropic", "label": "Anthropic Claude",
                  "base_url": "https://api.anthropic.com/v1", "default_model": "claude-sonnet-5-5"},
    "openai": {"api": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4o"},
    "deepseek": {"api": "openai", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                 "default_model": "deepseek-chat"},
    "groq": {"api": "openai", "label": "Groq", "base_url": "https://api.groq.com/openai/v1",
             "default_model": "llama-3.3-70b-versatile"},
    "openrouter": {"api": "openai", "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
                   "default_model": "openai/gpt-4o-mini"},
    "xai": {"api": "openai", "label": "xAI Grok", "base_url": "https://api.x.ai/v1", "default_model": "grok-3-mini"},
    "mistral": {"api": "openai", "label": "Mistral", "base_url": "https://api.mistral.ai/v1",
                "default_model": "mistral-small-latest"},
    # Any other OpenAI-compatible endpoint (a school server, Ollama, vLLM…): LLM_BASE_URL is required.
    "custom": {"api": "openai", "label": "OpenAI 相容服務", "base_url": "", "default_model": ""},
}
LABELS = tuple(info["label"] for info in REGISTRY.values())

# Distinctive key prefixes, longest first. A bare "sk-" is shared by OpenAI, DeepSeek and others.
KEY_PREFIXES = (("sk-ant-", "anthropic"), ("sk-or-", "openrouter"), ("sk-proj-", "openai"), ("sk-svcacct-", "openai"),
                ("gsk_", "groq"), ("xai-", "xai"), ("AIza", "gemini"), ("AQ.", "gemini"))


def detect(key):
    """Service name for a key with a distinctive prefix, otherwise None (the operator must choose)."""
    key = (key or "").strip()
    return next((name for prefix, name in KEY_PREFIXES if key.startswith(prefix)), None)


def _legacy_key(name):
    """Keys set the older, service-specific way still work."""
    if name == "gemini":
        return Config.GEMINI_API_KEY
    if name == "anthropic":
        return getattr(Config, "ANTHROPIC_API_KEY", "")
    return Config.OPENAI_API_KEY


def active():
    """The configured service as a dict (name, api, label, base_url, key, default_model), or None for builtin."""
    selected = (Config.LLM_PROVIDER or "auto").strip().lower()
    generic = (getattr(Config, "LLM_API_KEY", "") or "").strip()
    if selected == "builtin":
        return None
    if selected == "auto":
        if generic:
            selected = detect(generic) or ("custom" if getattr(Config, "LLM_BASE_URL", "") else "openai")
        elif Config.GEMINI_API_KEY:
            selected = "gemini"
        elif getattr(Config, "ANTHROPIC_API_KEY", ""):
            selected = "anthropic"
        elif Config.OPENAI_API_KEY:
            selected = "openai"
        else:
            return None
    if selected not in REGISTRY:
        return {"name": selected, "api": None, "label": selected, "base_url": "", "key": "", "default_model": ""}
    info = REGISTRY[selected]
    base_url = getattr(Config, "LLM_BASE_URL", "") or ""
    if not base_url and info["api"] == "openai" and Config.OPENAI_BASE_URL.rstrip("/") != REGISTRY["openai"]["base_url"]:
        base_url = Config.OPENAI_BASE_URL  # older OPENAI_BASE_URL setting for a compatible server
    default = info["default_model"]
    if selected == "gemini":
        default = Config.GEMINI_MODEL or default
    elif selected == "openai":
        default = Config.OPENAI_MODEL or default
    return {"name": selected, "api": info["api"], "label": info["label"],
            "base_url": (base_url or info["base_url"]).rstrip("/"), "key": generic or _legacy_key(selected),
            "default_model": getattr(Config, "LLM_MODEL", "") or default}


def name():
    """Short service name for routing and caches ("builtin" when no cloud model is configured)."""
    info = active()
    return info["name"] if info else "builtin"


def configured():
    info = active()
    return bool(info and info["api"] and info["key"] and info["base_url"])


def pinned_model():
    """A model the administrator chose explicitly (kept first in line); None means pick automatically."""
    info = active()
    if not info:
        return None
    legacy = {"gemini": "GEMINI_MODEL", "openai": "OPENAI_MODEL", "anthropic": "ANTHROPIC_MODEL"}.get(info["name"])
    return os.environ.get("LLM_MODEL") or (os.environ.get(legacy) if legacy else None) or None


def auth_headers(info):
    if info["api"] == "gemini":
        return {"x-goog-api-key": info["key"]}
    if info["api"] == "anthropic":
        return {"x-api-key": info["key"], "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {info['key']}"}
