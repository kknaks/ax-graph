"""정적 웹 adapter (AXKG-SPEC-012 §2 Web Adapter).

HTTP GET → content-type: text/html 확인 → 공통 처리(process_web_document). 분량 미달·JS
의존은 dynamic_web fallback 신호로 raise한다. 텍스트 획득만 다르고 추출/후처리는 공통.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from axkg.dto.source_material import SourceMaterial
from axkg.integrations.source_collection.base import (
    CONTENT_FETCH_FAILED,
    FETCH_TIMEOUT,
    SOURCE_TOO_LARGE,
    UNSUPPORTED_SOURCE_TYPE,
    CollectionError,
    guard_public_url,
    process_web_document,
)

_MAX_BYTES = 10_000_000
_MAX_REDIRECTS = 3
_TIMEOUT = 15.0
_USER_AGENT = "axkg-collector/1.0"


@dataclass(frozen=True)
class FetchedPage:
    final_url: str
    content_type: str
    html: str


# 테스트는 fake fetcher를 주입한다. 기본은 SSRF 가드 + 제한 redirect의 bounded httpx GET.
HtmlFetcher = Callable[[str], Awaitable[FetchedPage]]


async def default_html_fetch(source_url: str) -> FetchedPage:
    current = source_url
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            await guard_public_url(current)
            try:
                async with client.stream(
                    "GET", current, headers={"User-Agent": _USER_AGENT}
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise CollectionError(CONTENT_FETCH_FAILED, "redirect에 location 없음")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > _MAX_BYTES:
                            raise CollectionError(SOURCE_TOO_LARGE, "size limit 초과")
                        chunks.append(chunk)
                    raw = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                    return FetchedPage(final_url=current, content_type=content_type, html=raw)
            except httpx.TimeoutException as exc:
                raise CollectionError(FETCH_TIMEOUT, "정적 수집 timeout") from exc
            except httpx.HTTPError as exc:
                raise CollectionError(CONTENT_FETCH_FAILED, "정적 수집 HTTP 실패") from exc
    raise CollectionError(CONTENT_FETCH_FAILED, "redirect 횟수 초과")


async def collect_static_web(
    source_url: str, *, html_fetch: HtmlFetcher | None = None
) -> SourceMaterial:
    html_fetch = html_fetch or default_html_fetch
    page = await html_fetch(source_url)

    if "text/html" not in page.content_type.lower():
        raise CollectionError(
            UNSUPPORTED_SOURCE_TYPE, f"MVP adapter 없는 content-type: {page.content_type}"
        )

    return process_web_document(
        page.html,
        page.final_url,
        adapter="static_web",
        fetch_method="static_html",
        source_url=source_url,
        allow_dynamic_fallback=True,
    )
