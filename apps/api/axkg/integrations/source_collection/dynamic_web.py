"""동적 웹 adapter (AXKG-SPEC-012 §2 Web Adapter · §4 Security And Limits).

Playwright/Chrome 렌더링(domcontentloaded → networkidle → 제한 scroll) 후 DOM을 얻어
static_web과 **동일한** 공통 처리(process_web_document)를 적용한다. 렌더링 실패는
DYNAMIC_RENDER_FAILED, fallback 이후에도 분량 미달이면 CONTENT_EXTRACT_FAILED.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from axkg.dto.source_material import SourceMaterial
from axkg.integrations.source_collection.base import (
    DYNAMIC_RENDER_FAILED,
    CollectionError,
    guard_public_url,
    process_web_document,
)

_NAV_TIMEOUT_MS = 20_000
_NETWORKIDLE_TIMEOUT_MS = 8_000
_MAX_SCROLLS = 5
_SCROLL_WAIT_MS = 600


@dataclass(frozen=True)
class RenderedPage:
    final_url: str
    html: str


# 테스트는 fake renderer를 주입한다. 기본은 Playwright chromium headless.
PageRenderer = Callable[[str], Awaitable[RenderedPage]]


async def default_render(source_url: str) -> RenderedPage:
    """Playwright로 렌더링. 다운로드/팝업/새 창은 차단하고 실행 시간·scroll을 제한한다."""
    from playwright.async_api import async_playwright  # lazy — 실행 환경/브라우저에만 필요

    await guard_public_url(source_url)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(accept_downloads=False)
                page = await context.new_page()
                # 새 창/팝업 차단
                context.on("page", lambda popup: asyncio.ensure_future(popup.close()))
                await page.goto(source_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                try:
                    await page.wait_for_load_state(
                        "networkidle", timeout=_NETWORKIDLE_TIMEOUT_MS
                    )
                except Exception:  # noqa: BLE001 — networkidle 미도달은 치명적이지 않다
                    pass
                for _ in range(_MAX_SCROLLS):
                    await page.mouse.wheel(0, 20_000)
                    await page.wait_for_timeout(_SCROLL_WAIT_MS)
                html = await page.content()
                final_url = page.url
                return RenderedPage(final_url=final_url, html=html)
            finally:
                await browser.close()
    except CollectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — 렌더링 실패/timeout은 상태로 보존
        raise CollectionError(DYNAMIC_RENDER_FAILED, "브라우저 렌더링 실패/timeout") from exc


async def collect_dynamic_web(
    source_url: str, *, render: PageRenderer | None = None
) -> SourceMaterial:
    render = render or default_render
    page = await render(source_url)
    return process_web_document(
        page.html,
        page.final_url,
        adapter="dynamic_web",
        fetch_method="playwright_chrome",
        source_url=source_url,
        allow_dynamic_fallback=False,
    )
