"""문서 라이브러리 요약 브랜치 read-only API 테스트 (AXKG-SPEC-013, PLAN-012-T-006).

계약 SSOT: SPEC-013 §4 Interface Contract (GET /summaries, GET /summaries/{source_id}).
커버:
- GET /summaries: active 요약을 가진 source만 목록({ items: [{ source_id, name, path }] })
- 빈 목록(요약 없음)
- GET /summaries/{source_id}: active 요약 본문(markdown_full = 보관 md 렌더와 정합)
- SUMMARY_NOT_FOUND(404): 대상 source 없음 / active 요약 없는 source
- 접근 경계: staff·admin 모두 열람(문서 라이브러리 경계 상속), 미인증 401
- 서빙 소스 = DB 요약 원본. active 버전 revision 조인(포인터 체계). 파일시스템 무접촉.
"""
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.models.base import utcnow
from axkg.repositories.sources import SourceRepository
from axkg.services.summary_archive import slugify

ADMIN_EMAIL = "kknaks@medisolveai.com"
STAFF_EMAIL = "dr.jinlee@kakao.com"
SEED_PASSWORD = "1234"

SUMMARY_V1 = {
    "title": "Graph RAG 실전 설계",
    "summary": "짧은 카드 요약.",
    "keywords": ["graph-rag", "retriever"],
    "source_type": "article",
    "body_markdown": "## 개요\n\n장문 정리본 v1 본문.",
}


async def _token(client: AsyncClient, email: str) -> str:
    res = await client.post("/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _summarized_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    payload: dict = SUMMARY_V1,
    url: str = "https://example.com/s",
):
    """요약 완료(active summary revision 보유) source 하나를 만든다."""
    async with session_factory() as session:
        repo = SourceRepository(session)
        src = await repo.create(
            source_url=url,
            normalized_url=url,
            source_channel="manual",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text=None,
        )
        await repo.set_summary(src.id, payload)
        await session.commit()
        return src.id


async def _received_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    url: str = "https://example.com/no-summary",
):
    """요약이 아직 없는 source(active revision 없음)."""
    async with session_factory() as session:
        src = await SourceRepository(session).create(
            source_url=url,
            normalized_url=url,
            source_channel="manual",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text=None,
        )
        await session.commit()
        return src.id


# --- GET /summaries -----------------------------------------------------------


async def test_list_summaries_returns_active_summary_sources(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source_id = await _summarized_source(session_factory)
    token = await _token(client, STAFF_EMAIL)

    res = await client.get("/summaries", headers=_headers(token))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["source_id"] == str(source_id)
    assert item["name"] == SUMMARY_V1["title"]
    assert item["path"] == f"summaries/{slugify(SUMMARY_V1['title'])}.md"


async def test_list_summaries_excludes_sources_without_active_summary(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _summarized_source(session_factory, url="https://example.com/has")
    await _received_source(session_factory)  # 요약 없음 → 목록에서 제외
    token = await _token(client, STAFF_EMAIL)

    res = await client.get("/summaries", headers=_headers(token))
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["path"].startswith("summaries/")


async def test_list_summaries_empty(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client, STAFF_EMAIL)
    res = await client.get("/summaries", headers=_headers(token))
    assert res.status_code == 200
    assert res.json() == {"items": []}


# --- GET /summaries/{source_id} ----------------------------------------------


async def test_get_summary_returns_markdown_full(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source_id = await _summarized_source(session_factory)
    token = await _token(client, STAFF_EMAIL)

    res = await client.get(f"/summaries/{source_id}", headers=_headers(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_id"] == str(source_id)
    assert body["name"] == SUMMARY_V1["title"]
    assert body["path"] == f"summaries/{slugify(SUMMARY_V1['title'])}.md"
    # markdown_full = 보관 md 렌더(frontmatter + body_markdown)와 동일한 표현을 DB에서 서빙.
    assert "type: summary" in body["markdown_full"]
    assert SUMMARY_V1["title"] in body["markdown_full"]
    assert "장문 정리본 v1 본문." in body["markdown_full"]


async def test_get_summary_active_version_after_refeedback(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """재요약(v2) 후 본문은 active(v2)만 반환 — 포인터 체계 준수."""
    source_id = await _summarized_source(session_factory)
    v2 = {**SUMMARY_V1, "body_markdown": "## 개요\n\n개정된 장문 v2 본문."}
    async with session_factory() as session:
        await SourceRepository(session).set_summary(source_id, v2)
        await session.commit()
    token = await _token(client, STAFF_EMAIL)

    res = await client.get(f"/summaries/{source_id}", headers=_headers(token))
    assert res.status_code == 200
    assert "개정된 장문 v2 본문." in res.json()["markdown_full"]
    assert "장문 정리본 v1 본문." not in res.json()["markdown_full"]


async def test_get_summary_not_found_missing_source(
    client: AsyncClient,
) -> None:
    token = await _token(client, STAFF_EMAIL)
    res = await client.get(
        "/summaries/00000000-0000-0000-0000-000000000000", headers=_headers(token)
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "SUMMARY_NOT_FOUND"


async def test_get_summary_not_found_source_without_summary(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source_id = await _received_source(session_factory)
    token = await _token(client, STAFF_EMAIL)
    res = await client.get(f"/summaries/{source_id}", headers=_headers(token))
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "SUMMARY_NOT_FOUND"


# --- 접근 경계 (AXKG-SPEC-008 §4 문서 라이브러리 행) --------------------------


async def test_summaries_require_auth(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _summarized_source(session_factory)
    assert (await client.get("/summaries")).status_code == 401
    assert (
        await client.get("/summaries/00000000-0000-0000-0000-000000000000")
    ).status_code == 401


async def test_summaries_accessible_by_admin_and_staff(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _summarized_source(session_factory)
    for email in (ADMIN_EMAIL, STAFF_EMAIL):
        token = await _token(client, email)
        res = await client.get("/summaries", headers=_headers(token))
        assert res.status_code == 200, f"{email}: {res.text}"
