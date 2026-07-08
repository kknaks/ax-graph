"""AXKG-SPEC-003 Source Inbox API 테스트 (WP1 Phase 1).

커버: S-3(직접 입력)·S-2(중복 링크/후보)·U-1(목록 status 필터)·U-2(상세·error_message·ai-tasks)
+ 요약 재시도 큐잉(collection_failed → summarizing, 새 queued task + 실패 task 불변)
+ Case Matrix(INVALID_URL/DUPLICATE_SOURCE/MANUAL_NOTE_TOO_LONG/COLLECTION_RETRY_NOT_ALLOWED)
+ owner 인증. 응답은 FE 클라이언트 계약(bare Source)을 따른다.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.dto.source_material import SourceMaterial
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.sources import SourceService, normalize_url


def _material(source_url: str, canonical_url: str) -> SourceMaterial:
    return SourceMaterial(
        source_url=source_url,
        canonical_url=canonical_url,
        adapter="static_web",
        content_text="x" * 600,
        content_format="page_text",
        fetch_method="static_html",
        fetched_at="2026-07-07T00:00:00+00:00",
    )

SEED_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"


async def _token(client: AsyncClient) -> str:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    assert res.status_code == 200
    return res.json()["token"]


async def _auth(client: AsyncClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _token(client)}"}


async def _create(client: AsyncClient, headers: dict[str, str], url: str, **kw) -> dict:
    res = await client.post(
        "/sources/manual", json={"source_url": url, **kw}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------------------
# S-3 직접 입력 + U-3 modal 저장 결과
# ---------------------------------------------------------------------------


async def test_manual_create_received(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        "/sources/manual",
        json={"source_url": "https://example.com/ax-article", "raw_text": "읽어볼 것"},
        headers=headers,
    )
    assert res.status_code == 201
    source = res.json()
    assert source["status"] == "received"
    assert source["source_channel"] == "manual"
    assert source["source_url"] == "https://example.com/ax-article"
    assert source["raw_text"] == "읽어볼 것"
    assert source["submitted_at"]
    assert source["submitted_by"]
    assert source["visible_in_inbox"] is True


async def test_manual_requires_auth(client: AsyncClient) -> None:
    res = await client.post(
        "/sources/manual", json={"source_url": "https://example.com/x"}
    )
    assert res.status_code == 401


async def test_manual_invalid_url(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        "/sources/manual", json={"source_url": "not-a-url"}, headers=headers
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "INVALID_URL"


async def test_manual_ftp_scheme_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        "/sources/manual", json={"source_url": "ftp://example.com/x"}, headers=headers
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "INVALID_URL"


async def test_manual_note_too_long(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        "/sources/manual",
        json={"source_url": "https://example.com/x", "raw_text": "a" * 2001},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "MANUAL_NOTE_TOO_LONG"


# ---------------------------------------------------------------------------
# S-2 중복 URL 처리
# ---------------------------------------------------------------------------


async def test_duplicate_links_to_existing(client: AsyncClient) -> None:
    headers = await _auth(client)
    existing_id = (await _create(client, headers, "https://example.com/dup"))["id"]

    # 정규화가 같은 변형 URL(대문자 host + 말미 슬래시)로 재수신 → DUPLICATE_SOURCE
    second = await client.post(
        "/sources/manual",
        json={"source_url": "https://Example.com/dup/", "raw_text": "다시 봄"},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "DUPLICATE_SOURCE"

    # 새 row를 만들지 않고 기존 source에 이벤트를 누적한다(부수효과가 커밋된다)
    detail = (await client.get(f"/sources/{existing_id}", headers=headers)).json()
    events = detail["metadata"]["slack_events"]
    assert len(events) == 1
    assert events[0]["channel"] == "manual"
    assert events[0]["text"] == "다시 봄"

    # 목록에는 여전히 1건만
    listing = await client.get("/sources", headers=headers)
    assert len(listing.json()["sources"]) == 1


async def test_duplicate_of_documented_marks_candidate(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client)
    source_id = uuid.UUID((await _create(client, headers, "https://example.com/done"))["id"])

    async with session_factory() as session:
        await SourceRepository(session).set_status(source_id, "documented")
        await session.commit()

    res = await client.post(
        "/sources/manual", json={"source_url": "https://example.com/done"}, headers=headers
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "DUPLICATE_SOURCE"

    detail = (await client.get(f"/sources/{source_id}", headers=headers)).json()
    assert detail["metadata"]["duplicate_candidate"] is True


# ---------------------------------------------------------------------------
# U-1 목록 status 필터
# ---------------------------------------------------------------------------


async def test_list_filters_by_status(client: AsyncClient) -> None:
    headers = await _auth(client)
    await _create(client, headers, "https://example.com/a")
    await _create(client, headers, "https://example.com/b")

    received = await client.get("/sources?status=received", headers=headers)
    assert received.status_code == 200
    assert len(received.json()["sources"]) == 2

    summarized = await client.get("/sources?status=summarized", headers=headers)
    assert summarized.json()["sources"] == []


async def test_default_list_hides_documented(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client)
    visible_id = (await _create(client, headers, "https://example.com/v"))["id"]
    hidden_id = uuid.UUID((await _create(client, headers, "https://example.com/h"))["id"])
    async with session_factory() as session:
        await SourceRepository(session).set_status(hidden_id, "documented")
        await session.commit()

    listing = await client.get("/sources", headers=headers)
    ids = [s["id"] for s in listing.json()["sources"]]
    assert visible_id in ids
    assert str(hidden_id) not in ids


# ---------------------------------------------------------------------------
# U-2 상세 / ai-tasks
# ---------------------------------------------------------------------------


async def test_get_detail_and_missing(client: AsyncClient) -> None:
    headers = await _auth(client)
    source_id = (await _create(client, headers, "https://example.com/detail"))["id"]

    res = await client.get(f"/sources/{source_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == source_id

    missing = await client.get(f"/sources/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == "SOURCE_NOT_FOUND"


async def test_ai_tasks_empty_for_new_source(client: AsyncClient) -> None:
    headers = await _auth(client)
    source_id = (await _create(client, headers, "https://example.com/tasks"))["id"]
    res = await client.get(f"/sources/{source_id}/ai-tasks", headers=headers)
    assert res.status_code == 200
    assert res.json()["ai_tasks"] == []


# ---------------------------------------------------------------------------
# 요약 재시도 큐잉
# ---------------------------------------------------------------------------


async def _make_collection_failed(
    session_factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> uuid.UUID:
    """source를 collection_failed로 두고 실패한 collect_source_summary task 1건을 남긴다."""
    async with session_factory() as session:
        tasks = AiTaskRepository(session)
        task = await tasks.create(
            task_type="collect_source_summary",
            task_definition_id=None,
            provider="claude",
            model=None,
            options={},
            provider_options={},
            source_id=source_id,
        )
        await tasks.mark_running(task.id)
        await tasks.mark_failed(
            task.id, error_code="OPEN_KKNAKS_TASK_FAILED", error_message="boom"
        )
        await SourceRepository(session).set_status(source_id, "collection_failed")
        await session.commit()
        return task.id


async def test_collection_failed_detail_surfaces_error_message(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client)
    source_id = uuid.UUID((await _create(client, headers, "https://example.com/failed"))["id"])
    await _make_collection_failed(session_factory, source_id)

    detail = (await client.get(f"/sources/{source_id}", headers=headers)).json()
    assert detail["status"] == "collection_failed"
    assert detail["error_message"] == "boom"


async def test_queue_collection_retries_and_preserves_failed(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client)
    source_id = uuid.UUID((await _create(client, headers, "https://example.com/retry"))["id"])
    failed_id = await _make_collection_failed(session_factory, source_id)

    res = await client.post(f"/sources/{source_id}/queue-collection", headers=headers)
    assert res.status_code == 200
    # source는 summarizing으로 전이
    assert res.json()["status"] == "summarizing"

    # ai-tasks 이력: 실패 task 불변 + 새 queued task(retry_of_task_id로 연결)
    tasks = (await client.get(f"/sources/{source_id}/ai-tasks", headers=headers)).json()[
        "ai_tasks"
    ]
    assert len(tasks) == 2
    by_id = {t["id"]: t for t in tasks}
    assert by_id[str(failed_id)]["status"] == "failed"
    assert by_id[str(failed_id)]["error_code"] == "OPEN_KKNAKS_TASK_FAILED"
    new_task = next(t for t in tasks if t["id"] != str(failed_id))
    assert new_task["status"] == "queued"
    assert new_task["retry_of_task_id"] == str(failed_id)
    assert new_task["retry_count"] == 1


async def test_queue_collection_with_note_updates_raw_text(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # 단건 호출로 메모 저장 + 재요약 큐잉 (PLAN-005-T-013, FE T-014 계약)
    headers = await _auth(client)
    source_id = uuid.UUID(
        (await _create(client, headers, "https://medium.com/@x/note-retry"))["id"]
    )
    await _make_collection_failed(session_factory, source_id)

    res = await client.post(
        f"/sources/{source_id}/queue-collection",
        headers=headers,
        json={"note": "복붙한 원문 메모: 세 가지 함의"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "summarizing"
    assert res.json()["raw_text"] == "복붙한 원문 메모: 세 가지 함의"

    async with session_factory() as session:
        src = await SourceRepository(session).get(source_id)
        assert src.raw_text == "복붙한 원문 메모: 세 가지 함의"


async def test_queue_collection_note_too_long_returns_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client)
    source_id = uuid.UUID(
        (await _create(client, headers, "https://example.com/note-long"))["id"]
    )
    await _make_collection_failed(session_factory, source_id)

    res = await client.post(
        f"/sources/{source_id}/queue-collection",
        headers=headers,
        json={"note": "x" * 2001},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "MANUAL_NOTE_TOO_LONG"


async def test_queue_collection_not_allowed_for_received(client: AsyncClient) -> None:
    headers = await _auth(client)
    source_id = (await _create(client, headers, "https://example.com/nope"))["id"]
    res = await client.post(f"/sources/{source_id}/queue-collection", headers=headers)
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "COLLECTION_RETRY_NOT_ALLOWED"


async def test_queue_collection_missing_source(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(f"/sources/{uuid.uuid4()}/queue-collection", headers=headers)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# URL 정규화 단위 (중복 판정 근거)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 수집 결과 반영 — canonical → normalized_url 갱신 + S-2 중복 재검사 (SPEC-012)
# ---------------------------------------------------------------------------


async def test_apply_collection_updates_normalized_url(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client)
    source_id = uuid.UUID((await _create(client, headers, "https://youtu.be/abc123XYZ_"))["id"])

    async with session_factory() as session:
        result = await SourceService(session).apply_collection_result(
            source_id,
            _material(
                "https://youtu.be/abc123XYZ_",
                "https://www.youtube.com/watch?v=abc123XYZ_",
            ),
        )
        await session.commit()

    assert result.normalized_url_changed is True
    assert result.merged_into is None
    detail = (await client.get(f"/sources/{source_id}", headers=headers)).json()
    assert detail["normalized_url"] == normalize_url(
        "https://www.youtube.com/watch?v=abc123XYZ_"
    )


async def test_apply_collection_merges_into_existing_canonical(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client)
    # A: 이미 canonical 형태로 존재
    a_id = uuid.UUID(
        (await _create(client, headers, "https://www.youtube.com/watch?v=abc123XYZ_"))["id"]
    )
    # B: youtu.be 단축형 — 수집 후 canonical이 A와 합류
    b_id = uuid.UUID((await _create(client, headers, "https://youtu.be/abc123XYZ_"))["id"])

    async with session_factory() as session:
        result = await SourceService(session).apply_collection_result(
            b_id,
            _material(
                "https://youtu.be/abc123XYZ_",
                "https://www.youtube.com/watch?v=abc123XYZ_",
            ),
        )
        await session.commit()

    assert result.merged_into == a_id
    # A에 병합 이벤트가 연결된다 (S-2 append_intake_event 재사용)
    detail_a = (await client.get(f"/sources/{a_id}", headers=headers)).json()
    events = detail_a["metadata"]["slack_events"]
    assert any(e["channel"] == "collection_merge" for e in events)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://Example.com/a/", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a/", "http://example.com/a"),
        ("https://example.com/a#frag", "https://example.com/a"),
        ("https://example.com/a?q=1", "https://example.com/a?q=1"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected
