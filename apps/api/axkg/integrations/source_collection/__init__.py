"""Source Collection Adapter — adapter 선택 + 수집 오케스트레이션 (AXKG-SPEC-012 §2).

선택 3단계:
1. URL host/path로 명확한 전용 adapter 판정(YouTube는 content-type 확인 전에 youtube).
2. 전용 adapter가 없으면 static_web 시도(content-type: text/html).
3. static_web이 DYNAMIC_RENDER_REQUIRED/CONTENT_EXTRACT_FAILED로 실패하면 dynamic_web 시도.

수집 방식(adapter)만 다르고 SourceMaterial 계약은 공통. 실 fetcher는 기본 구현이며
테스트는 fake를 주입한다(네트워크/브라우저 없이 검증).
"""
from __future__ import annotations

from axkg.dto.source_material import SourceMaterial
from axkg.integrations.source_collection.base import (
    CONTENT_EXTRACT_FAILED,
    DYNAMIC_RENDER_REQUIRED,
    CollectionError,
    build_user_note_material,
    require_http_url,
)
from axkg.integrations.source_collection.dynamic_web import (
    PageRenderer,
    RenderedPage,
    collect_dynamic_web,
)
from axkg.integrations.source_collection.static_web import (
    FetchedPage,
    HtmlFetcher,
    collect_static_web,
)
from axkg.integrations.source_collection.youtube import (
    MetadataFetcher,
    TranscriptFetcher,
    collect_youtube,
    is_youtube_url,
)

# static_web 실패 시 dynamic_web로 fallback을 시도하는 코드 집합.
_FALLBACK_CODES = frozenset({DYNAMIC_RENDER_REQUIRED, CONTENT_EXTRACT_FAILED})

__all__ = [
    "CollectionError",
    "SourceMaterial",
    "build_user_note_material",
    "collect_source",
    "collect_static_web",
    "collect_dynamic_web",
    "collect_youtube",
    "is_youtube_url",
    "FetchedPage",
    "RenderedPage",
]


async def collect_source(
    source_url: str,
    *,
    user_note: str | None = None,
    metadata_fetcher: MetadataFetcher | None = None,
    transcript_fetcher: TranscriptFetcher | None = None,
    html_fetch: HtmlFetcher | None = None,
    render: PageRenderer | None = None,
) -> SourceMaterial:
    """URL을 adapter로 라우팅해 SourceMaterial로 수집한다. 실패는 CollectionError(code).

    URL 수집이 CollectionError로 실패하면, `user_note`가 (trim 후) 비어있지 않을 때
    사용자 메모를 요약 입력으로 삼는 `user_note` SourceMaterial을 최종 fallback으로 반환한다
    (medium류 원문 수집 불가 구제, PLAN-005-T-013). 메모가 없으면 원 CollectionError를
    그대로 재raise해 `collection_failed`로 표면화한다. URL 수집 성공 시엔 원문을 우선한다.
    """
    require_http_url(source_url)

    try:
        return await _collect_from_url(
            source_url,
            metadata_fetcher=metadata_fetcher,
            transcript_fetcher=transcript_fetcher,
            html_fetch=html_fetch,
            render=render,
        )
    except CollectionError:
        # 최종 fallback — 원문 수집 실패 + 메모 있으면 메모로 요약한다.
        note = (user_note or "").strip()
        if note:
            return build_user_note_material(source_url, note)
        raise


async def _collect_from_url(
    source_url: str,
    *,
    metadata_fetcher: MetadataFetcher | None,
    transcript_fetcher: TranscriptFetcher | None,
    html_fetch: HtmlFetcher | None,
    render: PageRenderer | None,
) -> SourceMaterial:
    """URL adapter 라우팅(youtube → static → dynamic fallback). 메모 fallback 이전 단계."""
    if is_youtube_url(source_url):
        return await collect_youtube(
            source_url,
            metadata_fetcher=metadata_fetcher,
            transcript_fetcher=transcript_fetcher,
        )

    try:
        return await collect_static_web(source_url, html_fetch=html_fetch)
    except CollectionError as exc:
        if exc.code not in _FALLBACK_CODES:
            raise
        # static 미달/JS 의존 → dynamic_web fallback (§2 선택 3단계)
        return await collect_dynamic_web(source_url, render=render)
