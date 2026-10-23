"""Restricted fetching of approved official pages (external spec 1.2; docs/IMPROVEMENT_BACKLOG.md).

Used only by staff tools (the workbench 「來源檢查」), never by the chat model: students' answers come from reviewed
knowledge cards and resource data, so no web page can put instructions into a reply.

Safety limits:
- Only URLs already listed in the knowledge cards or the Nantou resource data (human-approved) can be fetched.
- HTTPS on the standard port only; no IP literals; every address the name resolves to must be public (no
  localhost, private, link-local / cloud metadata, reserved or multicast ranges).
- Redirects are followed by hand (at most 3) and each target is checked the same way and must stay on an
  approved domain.
- Connect / read timeouts, a 1 MB cap, text or HTML only; TLS certificates are verified.
- Only the page title and a short plain-text excerpt are kept; text that tries to give instructions is flagged.
"""
import html
import ipaddress
import json
import os
import re
import socket
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests

from engine import knowledge
from engine.prompt_guard import detect_injection

TIMEOUT = (3, 8)
MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
EXCERPT_CHARS = 600
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
RESOURCES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "nantou_resources.json")


def approved_urls():
    """Every source URL a person has approved: knowledge-card sources and Nantou resource sources."""
    urls = {s["url"] for card in knowledge.cards() for s in card.get("sources", []) if s.get("url")}
    try:
        with open(RESOURCES, encoding="utf-8") as f:
            for item in json.load(f):
                urls.update(item[key] for key in ("source_url", "phone_source_url") if item.get(key))
    except (OSError, ValueError):
        pass
    return sorted(u for u in urls if u.startswith("https://"))


def approved_domains():
    return knowledge.allowed_domains() | {urlparse(u).hostname for u in approved_urls()}


def _on_domain(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


class Blocked(Exception):
    pass


def check_url(url, domains=None):
    """Raise Blocked unless the URL is safe to request. Resolves the name and checks every address."""
    parts = urlparse(url)
    if parts.scheme != "https":
        raise Blocked("not_https")
    if parts.port not in (None, 443):
        raise Blocked("port_not_allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise Blocked("no_host")
    try:
        ipaddress.ip_address(host)
        raise Blocked("ip_literal")
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise Blocked("private_address")
    if not _on_domain(host, approved_domains() if domains is None else domains):
        raise Blocked("domain_not_approved")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except socket.gaierror as exc:
        raise Blocked("dns_failed") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise Blocked("private_address")


def _text(body):
    title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', body) or \
        re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", body)
    cleaned = html.unescape(re.sub(r"(?s)<[^>]+>", " ", cleaned))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (html.unescape(re.sub(r"\s+", " ", title.group(1))).strip()[:200] if title else ""), cleaned


def fetch_official_resource(url):
    """Structured result for one approved page; never raises. Keys: ok, source_url, final_url, retrieved_at,
    http_status, title, text_excerpt, error_type, elapsed_ms, bytes, injection_suspected."""
    started = time.monotonic()
    result = {"ok": False, "source_url": url, "final_url": url, "content_type": "", "retrieved_at": datetime.now().isoformat(timespec="seconds"),
              "http_status": None, "title": "", "text_excerpt": "", "error_type": "", "elapsed_ms": 0, "bytes": 0,
              "injection_suspected": False}
    try:
        if url not in approved_urls():
            raise Blocked("url_not_approved")
        domains = approved_domains()
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current, domains)
            response = requests.get(current, timeout=TIMEOUT, allow_redirects=False, stream=True,
                                    headers={"User-Agent": "anla-youth-source-check/1.0"})
            result["http_status"] = response.status_code
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
                current = urljoin(current, response.headers["Location"])
                response.close()
                continue
            break
        else:
            raise Blocked("too_many_redirects")
        result["final_url"] = current
        if response.status_code >= 400:
            raise Blocked(f"http_{response.status_code}")
        kind = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        result["content_type"] = kind
        if kind == "application/pdf":
            response.close()  # reachable; the file itself is never downloaded or read
            result["ok"] = True
            return result
        if kind not in TEXT_TYPES:
            raise Blocked("not_text")
        body = b""
        for chunk in response.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise Blocked("too_large")
        result["bytes"] = len(body)
        encoding = response.encoding if response.encoding and response.encoding.lower() != "iso-8859-1" else None
        text = body.decode(encoding or "utf-8", errors="replace")
        result["title"], plain = _text(text)
        result["text_excerpt"] = plain[:EXCERPT_CHARS]
        # Page text is untrusted data: words that try to give orders are flagged, never followed. 【】 headings are
        # ordinary on Taiwanese sites, so the student-text check for imitated prompt markers does not apply here.
        result["injection_suspected"] = any(name != "fake_marker" for name in detect_injection(plain[:20000]))
        result["ok"] = True
    except Blocked as exc:
        result["error_type"] = str(exc)
    except requests.exceptions.SSLError:
        result["error_type"] = "tls_error"
    except requests.Timeout:
        result["error_type"] = "timeout"
    except requests.RequestException:
        result["error_type"] = "network_error"
    finally:
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result
