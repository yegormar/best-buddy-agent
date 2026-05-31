"""Web search and URL fetch tools (DuckDuckGo + HTTP)."""

from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ..config import WebSettings

_USER_AGENT = (
    "Mozilla/5.0 (compatible; BestBuddyAgent/1.0; +https://github.com/best-buddy)"
)

_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.goog",
    "localhost",
})

_ALWAYS_BLOCKED_IPS = frozenset({
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("169.254.169.253"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("::ffff:169.254.169.254"),
    ipaddress.ip_address("::ffff:169.254.170.2"),
    ipaddress.ip_address("::ffff:169.254.169.253"),
    ipaddress.ip_address("::ffff:100.100.100.200"),
})

_ALWAYS_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::ffff:169.254.0.0/112"),
    ipaddress.ip_network("100.64.0.0/10"),
)


class ToolError(Exception):
    """Raised when a web tool cannot run."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        raw = "\n".join(self._chunks)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip in _ALWAYS_BLOCKED_IPS:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
        return True
    for network in _ALWAYS_BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


def _validate_url(url: str) -> str:
    if not url or not url.strip():
        raise ToolError("url is required")
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("url must start with http:// or https://")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ToolError("url must include a hostname")
    if hostname in _BLOCKED_HOSTNAMES:
        raise ToolError(f"url hostname is not allowed: {hostname}")
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if _is_blocked_ip(ip):
                raise ToolError(f"url resolves to a blocked address: {hostname}")
    except socket.gaierror as exc:
        raise ToolError(f"could not resolve hostname: {hostname}") from exc
    return cleaned


def _extract_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def web_search(config: WebSettings, query: str, max_results: int | None = None) -> str:
    if not query or not query.strip():
        raise ToolError("query is required")
    limit = config.max_results if max_results is None else max_results
    limit = max(1, min(int(limit), 10))

    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise ToolError("ddgs not installed — pip install ddgs") from exc

    results: list[dict[str, str]] = []
    try:
        with DDGS() as client:
            for i, hit in enumerate(client.text(query.strip(), max_results=limit)):
                if i >= limit:
                    break
                results.append(hit)
    except Exception as exc:
        raise ToolError(f"web search failed: {exc}") from exc

    if not results:
        return f"No results found for: {query.strip()}"

    parts: list[str] = []
    for i, hit in enumerate(results, 1):
        title = str(hit.get("title") or "")
        snippet = str(hit.get("body") or hit.get("snippet") or "")
        link = str(hit.get("href") or hit.get("url") or "Unknown")
        parts.append(
            f"[Result {i}] {title}\n"
            f"{snippet}\n"
            f"SOURCE_URL: {link}"
        )
    return "\n\n---\n\n".join(parts)


def fetch_url(config: WebSettings, url: str) -> str:
    safe_url = _validate_url(url)

    try:
        import httpx
    except ImportError as exc:
        raise ToolError("httpx not installed — pip install httpx") from exc

    try:
        response = httpx.get(
            safe_url,
            timeout=config.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(f"failed to fetch URL: {exc}") from exc

    content_type = response.headers.get("content-type", "").lower()
    body = response.text

    if "html" in content_type or body.lstrip().startswith("<"):
        text = _extract_text(body)
    else:
        text = body

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if not text:
        return f"SOURCE_URL: {safe_url}\n\nThe page was fetched but no readable text content was found."

    max_chars = config.max_fetch_chars
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[Truncated: first {max_chars} chars shown]"

    return f"SOURCE_URL: {safe_url}\n\n{text}"
