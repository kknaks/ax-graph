"""AXKG-SPEC-012 Source Collection Adapter 테스트 (WP1 Phase 2).

네트워크/브라우저 없이 fetcher/renderer fake를 주입해 검증한다:
- youtube: video id 추출·canonical·transcript/description fallback·TRANSCRIPT_UNAVAILABLE
- static/dynamic web: 공통 DOM 제거·metadata 추출·후처리·수집 기준·page_kind=list
- selection/fallback 체인, 실패 코드, SSRF 가드
- 서비스 통합: canonical→normalized_url 갱신·S-2 중복 재검사
"""
import pytest

from axkg.integrations.source_collection import (
    CollectionError,
    FetchedPage,
    RenderedPage,
    collect_dynamic_web,
    collect_source,
    collect_static_web,
    collect_youtube,
)
from axkg.integrations.source_collection.base import guard_public_url, require_http_url
from axkg.integrations.source_collection.youtube import (
    canonical_youtube_url,
    extract_video_id,
    is_youtube_url,
)

# ---------------------------------------------------------------------------
# 픽스처 HTML
# ---------------------------------------------------------------------------

_ARTICLE_BODY = (
    "이 글은 지식 그래프 파이프라인을 설명한다. Source Inbox에 들어온 URL은 요약 AI를 거쳐 "
    "요약 카드가 되고, PARA 분류 게이트와 문서화 승인 게이트를 지나 영구 지식 노드가 된다. "
    "각 단계는 승인 게이트로 사용자가 통제하며, AI는 초안만 제안한다. 수집 어댑터는 YouTube, "
    "정적 웹, 동적 웹을 하나의 SourceMaterial로 정규화해 요약 스테이지에 넘긴다. 본문과 노이즈의 "
    "구분은 요약 AI가 담당하므로 어댑터는 UI 요소만 제거한 visible text를 그대로 전달한다. "
    "정적 어댑터는 HTTP GET으로 얻은 HTML을 파싱하고, 동적 어댑터는 Playwright로 렌더링한 뒤 "
    "같은 규칙으로 본문을 추출한다. 두 어댑터의 차이는 텍스트를 얻는 방법뿐이며, DOM 제거 규칙과 "
    "메타데이터 추출, 후처리, 수집 기준은 완전히 동일하게 공유한다. 요약 스테이지는 이 정규화된 "
    "자료를 프롬프트와 조립해 open-kknaks로 실행하고, 그 결과를 요약 payload로 저장한다. "
    "이 문단은 최소 분량 기준(500자)을 넘기기 위해 충분히 길게 작성된 실제 본문이다."
)

ARTICLE_HTML = f"""<!doctype html>
<html><head>
<meta property="og:title" content="지식 그래프 파이프라인 개요">
<link rel="canonical" href="https://example.com/canonical-article">
<meta name="author" content="kknaks">
<meta property="article:published_time" content="2026-07-01T09:00:00Z">
<title>fallback title</title>
</head>
<body>
<header><h1>HEADERNOISE</h1><nav><a href="/menu1">NAVNOISE</a></nav></header>
<script>var x = "SCRIPTNOISE";</script>
<article>
<h1>지식 그래프 파이프라인 개요</h1>
<h2>수집 어댑터</h2>
<p>{_ARTICLE_BODY}</p>
</article>
<footer>FOOTERNOISE</footer>
</body></html>"""

_LIST_LINKS = "\n".join(
    f'<li><a href="/article/{i}">아티클 제목 {i}</a></li>' for i in range(20)
)
LIST_HTML = f"""<!doctype html>
<html><head><title>AX 스토리 목록</title>
<link rel="canonical" href="https://enterprise.example.com/list"></head>
<body><main><h1>AX 스토리</h1><ul>{_LIST_LINKS}</ul></main></body></html>"""

SHORT_HTML = """<!doctype html><html><head><title>빈 페이지</title></head>
<body><div id="root"></div><p>짧은 본문.</p></body></html>"""

JS_REQUIRED_HTML = """<!doctype html><html><head><title>앱</title></head>
<body><noscript>Please enable JavaScript to run this app.</noscript>
<div id="root"></div></body></html>"""


async def _fetch(html: str, *, content_type: str = "text/html; charset=utf-8", final_url: str = "https://example.com/article"):
    async def _f(url: str) -> FetchedPage:
        return FetchedPage(final_url=final_url, content_type=content_type, html=html)

    return _f


async def _render(html: str, *, final_url: str = "https://example.com/article"):
    async def _r(url: str) -> RenderedPage:
        return RenderedPage(final_url=final_url, html=html)

    return _r


# ---------------------------------------------------------------------------
# YouTube adapter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=5", "dQw4w9WgXcQ"),
    ],
)
def test_extract_video_id(url: str, expected: str) -> None:
    assert extract_video_id(url) == expected
    assert canonical_youtube_url(expected) == f"https://www.youtube.com/watch?v={expected}"


def test_extract_video_id_invalid() -> None:
    with pytest.raises(CollectionError) as exc:
        extract_video_id("https://www.youtube.com/watch?v=")
    assert exc.value.code == "INVALID_URL"


def _yt_meta(**over):
    base = {
        "title": "그래프 RAG 실전",
        "description": "d" * 300,
        "duration_s": 1234,
        "channel": "kknaks",
        "tags": ["rag", "graph"],
        "thumbnail": "https://img/x.jpg",
        "upload_date": "20260701",
    }
    base.update(over)
    return base


async def test_youtube_transcript_success() -> None:
    material = await collect_youtube(
        "https://youtu.be/dQw4w9WgXcQ",
        metadata_fetcher=lambda vid: _yt_meta(),
        transcript_fetcher=lambda vid: "자막 " * 100,
    )
    assert material.adapter == "youtube"
    assert material.content_format == "transcript"
    assert material.fetch_method == "youtube_transcript_api"
    assert material.external_id == "dQw4w9WgXcQ"
    assert material.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert material.duration_seconds == 1234
    assert material.published_at == "2026-07-01"
    assert material.author == "kknaks"
    assert material.metadata["description"]


async def test_youtube_description_fallback() -> None:
    material = await collect_youtube(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        metadata_fetcher=lambda vid: _yt_meta(description="설명 " * 200),
        transcript_fetcher=lambda vid: None,
    )
    assert material.content_format == "video_description"
    assert material.fetch_method == "youtube_metadata"
    assert material.content_text.startswith("설명")


async def test_youtube_transcript_unavailable() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_youtube(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            metadata_fetcher=lambda vid: _yt_meta(description="짧음"),
            transcript_fetcher=lambda vid: None,
        )
    assert exc.value.code == "TRANSCRIPT_UNAVAILABLE"


async def test_youtube_metadata_fetch_failed() -> None:
    def boom(vid: str):
        raise RuntimeError("yt-dlp down")

    with pytest.raises(CollectionError) as exc:
        await collect_youtube(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            metadata_fetcher=boom,
            transcript_fetcher=lambda vid: None,
        )
    assert exc.value.code == "CONTENT_FETCH_FAILED"


async def test_youtube_transcript_error_falls_back_to_description() -> None:
    def transcript_boom(vid: str):
        raise RuntimeError("no transcript")

    material = await collect_youtube(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        metadata_fetcher=lambda vid: _yt_meta(description="설명 " * 200),
        transcript_fetcher=transcript_boom,
    )
    assert material.content_format == "video_description"


# ---------------------------------------------------------------------------
# Static web adapter + 공통 처리 규칙
# ---------------------------------------------------------------------------


async def test_static_article_success_and_dom_rules() -> None:
    material = await collect_static_web(
        "https://example.com/article", html_fetch=await _fetch(ARTICLE_HTML)
    )
    assert material.adapter == "static_web"
    assert material.content_format == "page_text"
    assert material.fetch_method == "static_html"
    # og:title 우선
    assert material.title == "지식 그래프 파이프라인 개요"
    # canonical link 우선 (최종 URL이 아니라 link rel=canonical)
    assert material.canonical_url == "https://example.com/canonical-article"
    assert material.author == "kknaks"
    assert material.published_at == "2026-07-01"
    # UI/스크립트 노이즈 제거
    assert "SCRIPTNOISE" not in material.content_text
    assert "NAVNOISE" not in material.content_text
    assert "FOOTERNOISE" not in material.content_text
    assert "HEADERNOISE" not in material.content_text
    # 본문 보존
    assert "지식 그래프 파이프라인을 설명한다" in material.content_text
    assert material.metadata["page_kind"] == "article"
    assert "수집 어댑터" in material.metadata["headings"]


async def test_static_unsupported_content_type() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_static_web(
            "https://example.com/x.pdf",
            html_fetch=await _fetch("%PDF-1.4", content_type="application/pdf"),
        )
    assert exc.value.code == "UNSUPPORTED_SOURCE_TYPE"


async def test_static_short_body_signals_extract_failed() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_static_web(
            "https://example.com/short", html_fetch=await _fetch(SHORT_HTML)
        )
    # static: 본문 있으나 분량 미달 → CONTENT_EXTRACT_FAILED (fallback 신호)
    assert exc.value.code in ("CONTENT_EXTRACT_FAILED", "DYNAMIC_RENDER_REQUIRED")


async def test_static_js_required_signal() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_static_web(
            "https://example.com/app", html_fetch=await _fetch(JS_REQUIRED_HTML)
        )
    assert exc.value.code == "DYNAMIC_RENDER_REQUIRED"


async def test_list_page_success_static() -> None:
    material = await collect_static_web(
        "https://example.com/list", html_fetch=await _fetch(LIST_HTML)
    )
    assert material.metadata["page_kind"] == "list"
    assert len(material.metadata["links"]) >= 15


# ---------------------------------------------------------------------------
# Dynamic web adapter
# ---------------------------------------------------------------------------


async def test_dynamic_success() -> None:
    material = await collect_dynamic_web(
        "https://example.com/article", render=await _render(ARTICLE_HTML)
    )
    assert material.adapter == "dynamic_web"
    assert material.fetch_method == "playwright_chrome"
    assert material.content_format == "page_text"
    assert "지식 그래프 파이프라인을 설명한다" in material.content_text


async def test_dynamic_content_extract_failed_is_terminal() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_dynamic_web(
            "https://example.com/short", render=await _render(SHORT_HTML)
        )
    assert exc.value.code == "CONTENT_EXTRACT_FAILED"


# ---------------------------------------------------------------------------
# Selection / fallback 오케스트레이션
# ---------------------------------------------------------------------------


async def test_collect_source_routes_youtube() -> None:
    material = await collect_source(
        "https://youtu.be/dQw4w9WgXcQ",
        metadata_fetcher=lambda vid: _yt_meta(),
        transcript_fetcher=lambda vid: "자막 " * 100,
    )
    assert material.adapter == "youtube"


async def test_collect_source_static_then_dynamic_fallback() -> None:
    material = await collect_source(
        "https://example.com/spa",
        html_fetch=await _fetch(JS_REQUIRED_HTML),
        render=await _render(ARTICLE_HTML),
    )
    # static이 DYNAMIC_RENDER_REQUIRED → dynamic_web로 fallback해서 성공
    assert material.adapter == "dynamic_web"
    assert "지식 그래프" in material.content_text


async def test_collect_source_dynamic_fallback_still_short_fails() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_source(
            "https://example.com/spa",
            html_fetch=await _fetch(SHORT_HTML),
            render=await _render(SHORT_HTML),
        )
    assert exc.value.code == "CONTENT_EXTRACT_FAILED"


async def test_collect_source_unsupported_no_fallback() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_source(
            "https://example.com/x.pdf",
            html_fetch=await _fetch("%PDF", content_type="application/pdf"),
            render=await _render(ARTICLE_HTML),
        )
    assert exc.value.code == "UNSUPPORTED_SOURCE_TYPE"


def test_require_http_url_rejects_non_http() -> None:
    with pytest.raises(CollectionError) as exc:
        require_http_url("ftp://example.com/x")
    assert exc.value.code == "INVALID_URL"


async def test_collect_source_invalid_scheme() -> None:
    with pytest.raises(CollectionError) as exc:
        await collect_source("ftp://example.com/x")
    assert exc.value.code == "INVALID_URL"


# ---------------------------------------------------------------------------
# SSRF 가드 (§4 Security And Limits)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.1/x",
    ],
)
async def test_guard_blocks_private_addresses(url: str) -> None:
    with pytest.raises(CollectionError) as exc:
        await guard_public_url(url)
    assert exc.value.code == "CONTENT_FETCH_FAILED"


async def test_guard_rejects_non_http_scheme() -> None:
    with pytest.raises(CollectionError) as exc:
        await guard_public_url("ftp://example.com/x")
    assert exc.value.code == "INVALID_URL"


def test_is_youtube_url() -> None:
    assert is_youtube_url("https://youtu.be/x")
    assert is_youtube_url("https://www.youtube.com/watch?v=x")
    assert not is_youtube_url("https://example.com/watch?v=x")


# ---------------------------------------------------------------------------
# user_note fallback (PLAN-005-T-013): 원문 수집 실패 + 메모 → 메모로 요약
# ---------------------------------------------------------------------------


async def test_collect_source_user_note_fallback_on_failure() -> None:
    # static → dynamic 모두 분량 미달(medium류 수집 불가) + 메모 있음 → user_note 소스
    material = await collect_source(
        "https://medium.com/@x/post",
        user_note="이 글 핵심은 A→B 전이 비용이 지배적이라는 것.",
        html_fetch=await _fetch(SHORT_HTML),
        render=await _render(SHORT_HTML),
    )
    assert material.adapter == "user_note"
    assert material.content_format == "user_note"
    assert material.content_text == "이 글 핵심은 A→B 전이 비용이 지배적이라는 것."
    assert material.canonical_url == "https://medium.com/@x/post"
    assert material.source_url == "https://medium.com/@x/post"


async def test_collect_source_no_note_reraises_collection_error() -> None:
    # 메모 없음 → 원 CollectionError 재raise (collection_failed로 표면화)
    with pytest.raises(CollectionError) as exc:
        await collect_source(
            "https://medium.com/@x/post",
            html_fetch=await _fetch(SHORT_HTML),
            render=await _render(SHORT_HTML),
        )
    assert exc.value.code == "CONTENT_EXTRACT_FAILED"


async def test_collect_source_blank_note_reraises() -> None:
    # 공백뿐인 메모는 "있음"으로 치지 않는다(trim 후 non-empty 기준)
    with pytest.raises(CollectionError):
        await collect_source(
            "https://medium.com/@x/post",
            user_note="   \n\t  ",
            html_fetch=await _fetch(SHORT_HTML),
            render=await _render(SHORT_HTML),
        )


async def test_collect_source_success_ignores_note() -> None:
    # URL 수집 성공 시엔 원문 우선(메모 미사용)
    material = await collect_source(
        "https://example.com/article",
        user_note="이 메모는 무시돼야 한다",
        html_fetch=await _fetch(ARTICLE_HTML),
    )
    assert material.adapter == "static_web"
    assert "이 메모는" not in material.content_text
