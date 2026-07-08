"""수집 adapter 공통 — 실패 계약·SSRF 가드·web 문서 처리 (AXKG-SPEC-012 §2/§3/§4).

- static_web / dynamic_web는 텍스트 획득 방식만 다르고, DOM 제거·metadata 추출·후처리·
  수집 기준은 전부 공통(process_web_document).
- transcript/page_text 전문은 로그에 남기지 않는다(Security And Limits).
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from axkg.dto.source_material import SourceMaterial

# --- 실패 코드 (AXKG-SPEC-012 §3 Failure Contract) ---
INVALID_URL = "INVALID_URL"
UNSUPPORTED_SOURCE_TYPE = "UNSUPPORTED_SOURCE_TYPE"
CONTENT_FETCH_FAILED = "CONTENT_FETCH_FAILED"
CONTENT_EXTRACT_FAILED = "CONTENT_EXTRACT_FAILED"
TRANSCRIPT_UNAVAILABLE = "TRANSCRIPT_UNAVAILABLE"
DYNAMIC_RENDER_REQUIRED = "DYNAMIC_RENDER_REQUIRED"
DYNAMIC_RENDER_FAILED = "DYNAMIC_RENDER_FAILED"
PAYWALL_OR_AUTH_REQUIRED = "PAYWALL_OR_AUTH_REQUIRED"
SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
FETCH_TIMEOUT = "FETCH_TIMEOUT"

# --- 한계값 (§2 수집 기준 · §4 Security And Limits) ---
MIN_CONTENT_LENGTH = 500  # UI 제거·후처리 후 최소 본문 길이
MAX_CONTENT_LENGTH = 200_000  # 초과 시 chunk 분할 (병합은 SPEC-011 요약 stage)
MAX_LINKS = 50
MAX_IMAGES = 30

_DOM_REMOVE_TAGS = (
    "script", "style", "noscript", "svg", "canvas", "template", "iframe",
    "header", "nav", "footer", "form", "dialog",
    "button", "input", "select", "textarea",
)
_JS_REQUIRED_MARKERS = (
    "enable javascript",
    "please enable js",
    "javascript is required",
    "자바스크립트를 활성화",
)
_PAYWALL_MARKERS = (
    "sign in to continue",
    "subscribe to read",
    "create a free account to",
    "로그인 후 이용",
    "구독을 해야",
)


class CollectionError(Exception):
    """수집 실패 — code는 AXKG-SPEC-012 Failure Contract 값."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# user_note fallback: 원문 수집이 모두 실패했을 때 사용자 메모/복붙 텍스트를 요약 입력으로
# 삼는 최종 fallback 소스의 adapter/format 값. medium류(Cloudflare) 등 원문 수집 불가
# 케이스를 메모로 구제한다 (PLAN-005-T-013). content_text는 메모 전문이라 로그에 남기지 않는다.
USER_NOTE_ADAPTER = "user_note"
USER_NOTE_FORMAT = "user_note"


def build_user_note_material(source_url: str, note: str) -> SourceMaterial:
    """사용자 메모(note)를 요약 입력 SourceMaterial로 감싼다 (수집 실패 최종 fallback).

    canonical_url은 원 URL 그대로 둔다(중복 판정·표시용). title/author 등 원문 메타는 없다.
    """
    return SourceMaterial(
        source_url=source_url,
        canonical_url=source_url,
        adapter=USER_NOTE_ADAPTER,
        title=None,
        author=None,
        published_at=None,
        duration_seconds=None,
        content_text=note,
        content_format=USER_NOTE_FORMAT,
        fetch_method=USER_NOTE_ADAPTER,
        fetched_at=utc_now_iso(),
        external_id=None,
        metadata={},
    )


def require_http_url(url: str) -> None:
    """scheme이 http/https가 아니면 INVALID_URL (§4 http/https만 허용)."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise CollectionError(INVALID_URL, "http/https 절대 URL만 허용")


async def guard_public_url(url: str) -> None:
    """private/loopback/link-local/non-global IP로 resolve되는 URL 차단 (SSRF, §4).

    실패 코드는 별도 SSRF 코드가 계약에 없어 CONTENT_FETCH_FAILED로 표면화한다.
    """
    require_http_url(url)
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, port)
    except socket.gaierror as exc:
        raise CollectionError(CONTENT_FETCH_FAILED, "host를 resolve할 수 없음") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise CollectionError(
                CONTENT_FETCH_FAILED, "비공개/비글로벌 주소로 resolve되는 URL 차단"
            )


# ---------------------------------------------------------------------------
# 공통 web 문서 처리 (static/dynamic 동일 규칙)
# ---------------------------------------------------------------------------


def _first_meta(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None):
    if prop is not None:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
    if name is not None:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    og = _first_meta(soup, prop="og:title")
    if og:
        return og
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text:
            return text
    return None


def _extract_canonical(soup: BeautifulSoup, final_url: str) -> str:
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        return urljoin(final_url, link["href"].strip())
    return final_url


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r"(\d{4})[-/.](\d{2})[-/.](\d{2})", raw)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", raw.strip())
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def _extract_published_at(soup: BeautifulSoup) -> str | None:
    meta = _first_meta(soup, prop="article:published_time")
    if meta:
        return _normalize_date(meta)
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict) and item.get("datePublished"):
                normalized = _normalize_date(str(item["datePublished"]))
                if normalized:
                    return normalized
    time_tag = soup.find("time")
    if time_tag:
        return _normalize_date(time_tag.get("datetime") or time_tag.get_text(strip=True))
    return None


def _extract_author(soup: BeautifulSoup) -> str | None:
    return _first_meta(soup, prop="article:author") or _first_meta(soup, name="author")


def _post_process_text(text: str) -> str:
    """반복 공백·3연속 이상 빈 줄 축소, 동일 라인 연속 반복 제거 (§2 후처리)."""
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
    out: list[str] = []
    blank_run = 0
    prev = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_run += 1
            if blank_run <= 1:
                out.append("")
            continue
        blank_run = 0
        if stripped == prev:
            continue
        prev = stripped
        out.append(stripped)
    return "\n".join(out).strip()


def _classify_page_kind(content_text: str, links: list[dict[str, str]]) -> str:
    """heuristic: 링크 후보가 많고 본문이 짧으면 list, 아니면 article (§2 page_kind)."""
    if len(links) >= 15 and len(content_text) < MIN_CONTENT_LENGTH * 2:
        return "list"
    if content_text:
        return "article"
    return "unknown"


def process_web_document(
    html: str,
    final_url: str,
    *,
    adapter: str,
    fetch_method: str,
    source_url: str,
    allow_dynamic_fallback: bool,
) -> SourceMaterial:
    """DOM 제거 → visible text·metadata 추출 → 후처리 → 수집 기준 판정 → SourceMaterial.

    allow_dynamic_fallback=True(static)면 JS 의존·분량 미달을 fallback 신호로 raise한다.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # 정체성 metadata는 chrome 제거 전 전체 DOM에서 읽는다(byline/head 참조).
    title = _extract_title(soup)
    canonical_url = _extract_canonical(soup, final_url)
    author = _extract_author(soup)
    published_at = _extract_published_at(soup)

    # UI 제거 후, 콘텐츠 구조(headings/links/images/text)는 정리된 DOM에서 뽑는다.
    for tag in soup(list(_DOM_REMOVE_TAGS)):
        tag.decompose()

    headings = [
        h.get_text(strip=True)
        for h in soup.find_all(["h1", "h2", "h3"])
        if h.get_text(strip=True)
    ]
    links: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if not text:
            continue
        links.append({"url": urljoin(final_url, a["href"].strip()), "text": text})
        if len(links) >= MAX_LINKS:
            break
    images: list[dict[str, str]] = []
    for img in soup.find_all("img", src=True):
        images.append(
            {"url": urljoin(final_url, img["src"].strip()), "alt": (img.get("alt") or "").strip()}
        )
        if len(images) >= MAX_IMAGES:
            break

    raw_text = soup.get_text(separator="\n")
    content_text = _post_process_text(raw_text)

    lowered = content_text.lower()
    if any(marker in lowered for marker in _PAYWALL_MARKERS) and len(content_text) < MIN_CONTENT_LENGTH:
        raise CollectionError(PAYWALL_OR_AUTH_REQUIRED, "로그인/paywall 안내가 본문을 대체")

    links_len = len(links)
    page_kind = _classify_page_kind(content_text, links)

    # list page는 분량 미달이어도 성공 — links를 후보로 반환 (§2 수집 기준)
    if page_kind != "list" and len(content_text) < MIN_CONTENT_LENGTH:
        if allow_dynamic_fallback:
            if any(marker in lowered for marker in _JS_REQUIRED_MARKERS) or links_len == 0:
                raise CollectionError(DYNAMIC_RENDER_REQUIRED, "JS 렌더링 없이 본문 부족")
            raise CollectionError(CONTENT_EXTRACT_FAILED, "정적 추출 본문 분량 미달")
        raise CollectionError(CONTENT_EXTRACT_FAILED, "동적 fallback 이후에도 본문 분량 미달")

    metadata: dict[str, Any] = {
        "headings": headings,
        "links": links,
        "images": images,
        "page_kind": page_kind,
    }
    return SourceMaterial(
        source_url=source_url,
        canonical_url=canonical_url,
        adapter=adapter,
        title=title,
        author=author,
        published_at=published_at,
        duration_seconds=None,
        content_text=content_text[:MAX_CONTENT_LENGTH],
        content_format="page_text",
        fetch_method=fetch_method,
        fetched_at=utc_now_iso(),
        external_id=None,
        metadata=metadata,
    )
