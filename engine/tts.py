"""Cloud voices for reading replies aloud, as an alternative to the device's built-in voice.

Three services are supported; each is offered only when its key is configured, and students choose a voice:
- "azure": Azure AI Speech neural voices; the zh-TW voices speak Taiwanese Mandarin (AZURE_SPEECH_KEY + REGION).
- "openai": OpenAI text-to-speech (OPENAI_API_KEY, or the main LLM key when the LLM service is OpenAI).
- "gemini": Gemini speech generation (GEMINI_API_KEY, or the main LLM key when the LLM service is Gemini).

Only reply text is sent, never the student's messages. Keys stay on the server; the browser receives audio.
"""
import base64
import hashlib
import io
import re
import threading
import wave
from collections import OrderedDict
from xml.sax.saxutils import escape

import requests

from config import Config
from engine import providers

MAX_CHARS = 800
STYLE = "Read aloud in Taiwanese Mandarin, in a warm, calm and gentle voice, at a relaxed pace"

# (voice id, label shown to students). Labels describe the sound, not a person.
VOICES = {
    "azure": [("zh-TW-HsiaoChenNeural", "曉臻・溫柔女聲（台灣華語）"), ("zh-TW-HsiaoYuNeural", "曉雨・清亮女聲（台灣華語）"),
              ("zh-TW-YunJheNeural", "雲哲・沉穩男聲（台灣華語）")],
    "openai": [("coral", "Coral・溫暖"), ("nova", "Nova・明亮"), ("shimmer", "Shimmer・柔和"), ("sage", "Sage・平靜"),
               ("alloy", "Alloy・中性"), ("echo", "Echo・低沉"), ("onyx", "Onyx・渾厚")],
    "gemini": [("Sulafat", "Sulafat・溫暖"), ("Achernar", "Achernar・柔和"), ("Vindemiatrix", "Vindemiatrix・溫柔"),
               ("Achird", "Achird・友善"), ("Aoede", "Aoede・輕快"), ("Puck", "Puck・活潑")],
}
LABELS = {"azure": "Azure 語音", "openai": "OpenAI 語音", "gemini": "Gemini 語音"}

_cache, _cache_lock = OrderedDict(), threading.Lock()
CACHE_SIZE = 64
_gemini_model = {}


class TtsError(Exception):
    pass


def _llm_key(name):
    info = providers.active()
    return info["key"] if info and info.get("name") == name else ""


def _key(service):
    if service == "azure":
        return Config.AZURE_SPEECH_KEY if Config.AZURE_SPEECH_REGION else ""
    if service == "openai":
        return Config.OPENAI_API_KEY or _llm_key("openai")
    if service == "gemini":
        return Config.GEMINI_API_KEY or _llm_key("gemini")
    return ""


def services():
    """Configured voice services, best Taiwanese Mandarin first."""
    if not Config.TTS_ENABLED:
        return []
    return [s for s in ("azure", "openai", "gemini") if _key(s)]


def voices():
    return [{"id": f"{s}:{v}", "label": label, "service": LABELS[s]} for s in services() for v, label in VOICES[s]]


def _clean(text):
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿️]", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def synthesize(voice_id, text, rate=1.0):
    """(audio bytes, mime type) for one reply. Raises TtsError with a short reason."""
    service, _, voice = (voice_id or "").partition(":")
    if service not in services() or voice not in dict(VOICES[service]):
        raise TtsError("voice_unavailable")
    text = _clean(text)[:MAX_CHARS]
    if not text:
        raise TtsError("empty")
    rate = min(max(float(rate), 0.7), 1.3)
    key = hashlib.sha256(f"{voice_id}|{rate}|{text}".encode("utf-8")).hexdigest()
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    try:
        audio = {"azure": _azure, "openai": _openai, "gemini": _gemini}[service](voice, text, rate)
    except requests.RequestException as exc:
        raise TtsError("network") from exc
    with _cache_lock:
        _cache[key] = audio
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return audio


def _check(response):
    if response.status_code in (401, 403):
        raise TtsError("auth_error")
    if response.status_code == 429:
        raise TtsError("rate_limited")
    if response.status_code >= 400:
        raise TtsError(f"http_{response.status_code}")


def _azure(voice, text, rate):
    percent = round((rate - 1) * 100)
    ssml = (f"<speak version='1.0' xml:lang='zh-TW' xmlns='http://www.w3.org/2001/10/synthesis'>"
            f"<voice name='{voice}'><prosody rate='{percent:+d}%'>{escape(text)}</prosody></voice></speak>")
    response = requests.post(
        f"https://{Config.AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"), timeout=(Config.LLM_CONNECT_TIMEOUT, 20),
        headers={"Ocp-Apim-Subscription-Key": Config.AZURE_SPEECH_KEY, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3", "User-Agent": "anla-youth"})
    _check(response)
    return response.content, "audio/mpeg"


def _openai(voice, text, rate):
    response = requests.post(
        Config.OPENAI_BASE_URL.rstrip("/") + "/audio/speech", timeout=(Config.LLM_CONNECT_TIMEOUT, 30),
        headers={"Authorization": f"Bearer {_key('openai')}"},
        json={"model": Config.TTS_OPENAI_MODEL, "voice": voice, "input": text, "instructions": STYLE + ".",
              "response_format": "mp3", "speed": rate})
    _check(response)
    return response.content, "audio/mpeg"


def _gemini_tts_model(key):
    """The configured model, else the key's own speech model (names change between preview releases)."""
    if Config.TTS_GEMINI_MODEL:
        return Config.TTS_GEMINI_MODEL
    if key not in _gemini_model:
        names = []
        try:
            response = requests.get(f"{providers.REGISTRY['gemini']['base_url']}/models", timeout=(3, 10),
                                    headers={"x-goog-api-key": key}, params={"pageSize": 200})
            if response.ok:
                names = [m.get("name", "").removeprefix("models/") for m in response.json().get("models", [])]
        except (requests.RequestException, ValueError):
            pass
        speech = sorted((n for n in names if "tts" in n), key=lambda n: ("flash" not in n, "preview" in n, n))
        _gemini_model[key] = speech[0] if speech else "gemini-2.5-flash-preview-tts"
    return _gemini_model[key]


def _gemini(voice, text, rate):
    key = _key("gemini")
    pace = "a little slower" if rate < 0.95 else "a little faster" if rate > 1.05 else "a relaxed pace"
    response = requests.post(
        f"{providers.REGISTRY['gemini']['base_url']}/models/{_gemini_tts_model(key)}:generateContent",
        timeout=(Config.LLM_CONNECT_TIMEOUT, 40), headers={"x-goog-api-key": key},
        json={"contents": [{"parts": [{"text": f"{STYLE.replace('at a relaxed pace', 'at ' + pace)}: {text}"}]}],
              "generationConfig": {"responseModalities": ["AUDIO"],
                                   "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}})
    _check(response)
    try:
        part = response.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm = base64.b64decode(part["data"])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise TtsError("bad_response") from exc
    sample_rate = int((re.search(r"rate=(\d+)", part.get("mimeType", "")) or [None, 24000])[1])
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:  # Gemini returns raw 16-bit mono PCM; browsers need a container
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue(), "audio/wav"


def reset_cache():
    with _cache_lock:
        _cache.clear()
    _gemini_model.clear()
