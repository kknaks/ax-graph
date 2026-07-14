"""AXKG-SPEC-003 S-5 / WORK-010 — 인박스 md 업로드 intake (PLAN-013-T-009).

커버(계약 SSOT: SPEC-003 §4 API·Validation·Case Matrix·S-5, SPEC-008 소스 Inbox 표면 경계):
- 정상 업로드(admin) → source_channel=upload / source_url·normalized_url null / slack_ts null /
  raw_text=md 본문 / original_filename 보존 / received
- staff 403(업로드는 admin 전용 표면 — 개방 금지)
- 비md 422(UNSUPPORTED_UPLOAD_TYPE) + source 미생성
- 요약 직행(adapter 미경유 — received→start_summary→summarizing + collect_source_summary)
- frontmatter 보존(strip 안 함) / 빈 md 거부 / 크기 상한(구현 기본값)
"""
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from axkg.services.sources import (
    MAX_UPLOAD_SIZE_BYTES,
    EmptyUploadTextError,
    SourceService,
    UnsupportedUploadTypeError,
    UploadTooLargeError,
)

ADMIN_EMAIL = "kknaks@medisolveai.com"
STAFF_EMAIL = "dr.jinlee@kakao.com"
SEED_PASSWORD = "1234"

MD_BODY = "# AX 노트\n\nGraph RAG는 검색과 지식그래프를 결합한다.\n"


async def _headers(client: AsyncClient, email: str = ADMIN_EMAIL) -> dict[str, str]:
    res = await client.post("/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _file(name: str, body: bytes, mime: str = "text/markdown") -> dict:
    return {"file": (name, body, mime)}


# ---------------------------------------------------------------------------
# 정상 업로드 (admin)
# ---------------------------------------------------------------------------


async def test_upload_creates_upload_source(client: AsyncClient) -> None:
    headers = await _headers(client, ADMIN_EMAIL)
    res = await client.post(
        "/sources/upload", files=_file("ax-note.md", MD_BODY.encode()), headers=headers
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "received"
    assert body["source_channel"] == "upload"
    assert body["source_url"] is None
    assert body["normalized_url"] is None
    assert body["slack_message_ts"] is None
    assert body["raw_text"] == MD_BODY
    assert body["original_filename"] == "ax-note.md"
    assert body["submitted_by"]
    assert body["visible_in_inbox"] is True


async def test_upload_appears_in_inbox_list(client: AsyncClient) -> None:
    headers = await _headers(client, ADMIN_EMAIL)
    created = (
        await client.post(
            "/sources/upload", files=_file("note.md", MD_BODY.encode()), headers=headers
        )
    ).json()
    listing = await client.get("/sources", headers=headers)
    ids = [s["id"] for s in listing.json()["sources"]]
    assert created["id"] in ids


# ---------------------------------------------------------------------------
# 접근 경계 — admin 전용 (staff 403)
# ---------------------------------------------------------------------------


async def test_upload_forbidden_for_staff(client: AsyncClient) -> None:
    headers = await _headers(client, STAFF_EMAIL)
    res = await client.post(
        "/sources/upload", files=_file("note.md", MD_BODY.encode()), headers=headers
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "FORBIDDEN"


async def test_upload_requires_auth(client: AsyncClient) -> None:
    res = await client.post("/sources/upload", files=_file("note.md", MD_BODY.encode()))
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 비md 거부 (UNSUPPORTED_UPLOAD_TYPE) + source 미생성
# ---------------------------------------------------------------------------


async def test_upload_non_md_rejected_no_source(client: AsyncClient) -> None:
    headers = await _headers(client, ADMIN_EMAIL)
    res = await client.post(
        "/sources/upload",
        files=_file("doc.pdf", b"%PDF-1.4 ...", "application/pdf"),
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "UNSUPPORTED_UPLOAD_TYPE"
    # source가 생성되지 않았다(intake validation, 수집 실패 아님).
    listing = await client.get("/sources", headers=headers)
    assert listing.json()["sources"] == []


async def test_upload_txt_extension_rejected(client: AsyncClient) -> None:
    headers = await _headers(client, ADMIN_EMAIL)
    res = await client.post(
        "/sources/upload", files=_file("note.txt", MD_BODY.encode()), headers=headers
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "UNSUPPORTED_UPLOAD_TYPE"


async def test_upload_empty_md_rejected(client: AsyncClient) -> None:
    headers = await _headers(client, ADMIN_EMAIL)
    res = await client.post(
        "/sources/upload", files=_file("empty.md", b"   \n"), headers=headers
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "EMPTY_UPLOAD_TEXT"


# ---------------------------------------------------------------------------
# frontmatter 보존 (strip 안 함 — 구현 기본값)
# ---------------------------------------------------------------------------


async def test_upload_preserves_frontmatter(client: AsyncClient) -> None:
    headers = await _headers(client, ADMIN_EMAIL)
    md = "---\ntitle: 실험 노트\ntags: [ax]\n---\n\n본문 내용\n"
    res = await client.post(
        "/sources/upload", files=_file("fm.md", md.encode()), headers=headers
    )
    assert res.status_code == 201
    # frontmatter를 strip하지 않고 본문 그대로 보존한다.
    assert res.json()["raw_text"] == md


async def test_upload_uppercase_extension_accepted(client: AsyncClient) -> None:
    headers = await _headers(client, ADMIN_EMAIL)
    res = await client.post(
        "/sources/upload", files=_file("NOTE.MD", MD_BODY.encode()), headers=headers
    )
    assert res.status_code == 201
    assert res.json()["source_channel"] == "upload"


# ---------------------------------------------------------------------------
# 요약 직행 (adapter 미경유) — 서비스 레벨
# ---------------------------------------------------------------------------


async def test_upload_source_joins_summary_pipeline(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """upload source는 URL 수집 없이 received→요약 파이프라인에 직행한다 (C-3, adapter 미경유)."""
    async with session_factory() as s:
        service = SourceService(s)
        source = await service.create_upload(
            filename="note.md", content=MD_BODY.encode(), submitted_by=None
        )
        assert source.status == "received"
        assert source.source_channel == "upload"
        assert source.source_url is None  # 수집 대상 URL이 없다
        assert source.raw_text == MD_BODY  # md 본문 자체가 원문
        assert source.original_filename == "note.md"

        triggered = await service.start_summary(source.id)
        assert triggered.source.status == "summarizing"
        assert triggered.ai_task.task_type == "collect_source_summary"
        await s.commit()


# ---------------------------------------------------------------------------
# 서비스 유닛 — 확장자/크기/빈본문/디코딩
# ---------------------------------------------------------------------------


async def test_create_upload_rejections(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        service = SourceService(s)

        for exc, kwargs in [
            (UnsupportedUploadTypeError, {"filename": "x.pdf", "content": b"data"}),
            (UnsupportedUploadTypeError, {"filename": None, "content": b"data"}),
            (UnsupportedUploadTypeError, {"filename": "x.md", "content": b"\xff\xfe\x00bad"}),
            (EmptyUploadTextError, {"filename": "x.md", "content": b"  \n "}),
            (
                UploadTooLargeError,
                {"filename": "big.md", "content": b"a" * (MAX_UPLOAD_SIZE_BYTES + 1)},
            ),
        ]:
            raised = False
            try:
                await service.create_upload(submitted_by=None, **kwargs)
            except exc:
                raised = True
            assert raised, f"expected {exc.__name__} for {kwargs.get('filename')}"
