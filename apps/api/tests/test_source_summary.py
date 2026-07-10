"""AXKG-SPEC-011 ① 요약 스테이지 배선 테스트 (WP1 Phase 3).

커버:
- chunk_content / merge_chunk_summaries 유틸 (긴 원문 chunk 요약 병합)
- SourceSummaryContextBuilder: SourceMaterial 데이터 블록만 구성(요약 지침은 worker
  workspace의 프로젝트 context 소관 — api가 로드하지 않음), 수집 실패→ContextBuildError
- execute_source_summary 오케스트레이션: received→summarizing→summarized/collection_failed
  - 성공: summary_payload 저장 + summarized (fake open-kknaks client)
  - 수집 실패(CollectionError): collection_failed + task CONTENT_FETCH_FAILED
  - 스키마 불일치: collection_failed + task OUTPUT_SCHEMA_MISMATCH (부분 소비 금지)
  - 재시도(queue_collection이 만든 task) 실행 연결
- SourceService.start_summary: received → summarizing + queued task
- 라우트 자동 트리거: fake client 주입 시 manual 입력 → 최종 summarized

fake open-kknaks client와 fake collect로 네트워크/브라우저/redis 없이 검증한다.
"""
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.dto.source_material import SourceMaterial
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.integrations.source_collection import CollectionError
from axkg.integrations.source_collection.base import (
    CONTENT_FETCH_FAILED,
    build_user_note_material,
)
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.source_summary import (
    SourceSummaryContextBuilder,
    chunk_content,
    merge_chunk_summaries,
)
from axkg.services.sources import ManualNoteTooLongError, SourceService
from axkg.services.summary_execution import execute_source_summary
from axkg.models.base import utcnow

VALID_SUMMARY = {
    "title": "Graph RAG 실전 설계",
    "summary": "문서 그래프를 검색 컨텍스트로 삼는 RAG 설계 자료 요약.",
    "keywords": ["graph-rag", "retriever"],
    "source_type": "article",
    "body_markdown": "## 배경\n문서 그래프를 검색 컨텍스트로 삼는다.\n\n## 근거\n저자는 링크 밀도가 recall을 높인다고 주장한다.",
}


def _material(
    url: str = "https://example.com/a",
    *,
    content_text: str = "본문 " * 300,
    adapter: str = "static_web",
    content_format: str = "page_text",
) -> SourceMaterial:
    return SourceMaterial(
        source_url=url,
        canonical_url=url,
        adapter=adapter,
        title="예시 제목",
        content_text=content_text,
        content_format=content_format,
        fetch_method="static_html",
        fetched_at="2026-07-08T00:00:00+00:00",
        metadata={"page_kind": "article"},
    )


class FakeClient(OpenKknaksClient):
    def __init__(self, *, result_text: str | None = None, status: str = "done") -> None:
        self._result_text = result_text
        self._status = status
        self.requests: list[OpenKknaksTaskRequest] = []

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        self.requests.append(request)
        return "okk-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return self._status

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(
            task_id=task_id,
            status=self._status,  # type: ignore[arg-type]
            result_text=self._result_text,
            session_id="okk-sess-1",
        )


async def _collect_ok(url: str, *, user_note: str | None = None) -> SourceMaterial:
    return _material(url)


async def _collect_forbidden(url: str, *, user_note: str | None = None) -> SourceMaterial:
    """피드백 재요약은 세션 resume이라 원문을 재수집하면 안 된다 — 호출되면 실패시킨다."""
    raise AssertionError("feedback re-summary must not re-collect source content")


class SessionFakeClient(OpenKknaksClient):
    """제출 request와 반환 session_id를 관찰 가능한 fake (resume 배선 검증용)."""

    def __init__(self, *, result_text: str, session_id: str = "okk-sess-1") -> None:
        self._result_text = result_text
        self._session_id = session_id
        self.requests: list[OpenKknaksTaskRequest] = []

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        self.requests.append(request)
        return "okk-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return "done"

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(
            task_id=task_id,
            status="done",
            result_text=self._result_text,
            session_id=self._session_id,
        )


def _collect_fail(code: str = CONTENT_FETCH_FAILED):
    async def _c(url: str, *, user_note: str | None = None) -> SourceMaterial:
        raise CollectionError(code, "수집 실패")

    return _c


def _collect_fail_unless_note(code: str = CONTENT_FETCH_FAILED):
    """실제 collect_source의 fallback을 흉내낸다 — 메모 있으면 user_note 소스, 없으면 실패."""

    async def _c(url: str, *, user_note: str | None = None) -> SourceMaterial:
        note = (user_note or "").strip()
        if note:
            return build_user_note_material(url, note)
        raise CollectionError(code, "수집 실패")

    return _c


async def _auth_headers(ac: AsyncClient) -> dict[str, str]:
    """seed 사용자로 로그인해 Bearer 헤더를 만든다 (sources 라우터는 전역 Bearer 적용)."""
    login = await ac.post(
        "/auth/login", json={"email": "kknaks@medisolveai.com", "password": "1234"}
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


async def _new_source(session: AsyncSession, url: str = "https://example.com/a") -> uuid.UUID:
    src = await SourceRepository(session).create(
        source_url=url,
        normalized_url=url,
        source_channel="manual",
        submitted_by=None,
        submitted_at=utcnow(),
        raw_text=None,
    )
    return src.id


# ---------------------------------------------------------------------------
# chunk 유틸
# ---------------------------------------------------------------------------


def test_chunk_content_short_single() -> None:
    assert chunk_content("짧은 본문", max_chars=100) == ["짧은 본문"]
    assert chunk_content("", max_chars=100) == [""]


def test_chunk_content_splits_on_paragraph_boundary() -> None:
    text = "\n\n".join(["A" * 40, "B" * 40, "C" * 40])
    chunks = chunk_content(text, max_chars=90)
    assert len(chunks) >= 2
    assert all(len(c) <= 90 for c in chunks)
    # 원문 문자가 보존된다 (경계 결합 문자 제외하고 조각 합이 원문 커버)
    assert "A" * 40 in chunks[0]


def test_chunk_content_hard_splits_oversized_paragraph() -> None:
    chunks = chunk_content("X" * 250, max_chars=100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_merge_chunk_summaries_single_passthrough() -> None:
    assert merge_chunk_summaries([VALID_SUMMARY]) == VALID_SUMMARY


def test_merge_chunk_summaries_dedupes_and_majority() -> None:
    merged = merge_chunk_summaries(
        [
            {"title": "T1", "summary": "s1", "keywords": ["a", "b"], "source_type": "article", "body_markdown": "b1"},
            {"title": "T2", "summary": "s2", "keywords": ["b", "c"], "source_type": "article", "body_markdown": "b2"},
            {"title": "T3", "summary": "s3", "keywords": ["c"], "source_type": "video", "body_markdown": "b3"},
        ]
    )
    assert merged["title"] == "T1"  # 첫 chunk title
    assert merged["summary"] == "s1\n\ns2\n\ns3"
    assert merged["keywords"] == ["a", "b", "c"]  # 순서 보존 중복 제거
    assert merged["source_type"] == "article"  # 최빈값


def test_merge_chunk_summaries_concats_body_markdown_in_order() -> None:
    # PLAN-009-T-001: chunk별 body_markdown을 원문 순서대로 이어붙인다.
    merged = merge_chunk_summaries(
        [
            {"title": "T", "summary": "s1", "keywords": ["a"], "source_type": "article", "body_markdown": "## 1\n앞부분"},
            {"title": "T", "summary": "s2", "keywords": ["b"], "source_type": "article", "body_markdown": "## 2\n뒷부분"},
        ]
    )
    assert merged["body_markdown"] == "## 1\n앞부분\n\n## 2\n뒷부분"


def test_merge_chunk_summaries_skips_empty_body_markdown() -> None:
    # 빈 body_markdown chunk는 병합에서 스킵된다(빈 조각이 이음매를 오염시키지 않게).
    merged = merge_chunk_summaries(
        [
            {"title": "T", "summary": "s1", "keywords": ["a"], "source_type": "article", "body_markdown": "본문 A"},
            {"title": "T", "summary": "s2", "keywords": ["b"], "source_type": "article", "body_markdown": ""},
            {"title": "T", "summary": "s3", "keywords": ["c"], "source_type": "article", "body_markdown": "본문 C"},
        ]
    )
    assert merged["body_markdown"] == "본문 A\n\n본문 C"


def test_source_summary_schema_requires_body_markdown() -> None:
    """seed output_schema가 body_markdown을 required로 강제한다 — 누락 payload는 검증 실패."""
    import jsonschema

    from axkg.seeds import PROMPT_SEEDS

    schema = next(s for s in PROMPT_SEEDS if s["key"] == "source_summary")["output_schema"]
    assert "body_markdown" in schema["required"]

    # 온전한 payload는 통과.
    jsonschema.validate(VALID_SUMMARY, schema)

    # body_markdown만 빠지면 스키마 검증 실패(pipeline OUTPUT_SCHEMA_MISMATCH 경로와 동일).
    missing = {k: v for k, v in VALID_SUMMARY.items() if k != "body_markdown"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(missing, schema)


# ---------------------------------------------------------------------------
# context builder
# ---------------------------------------------------------------------------


async def test_builder_blocks_are_source_material_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)
        task = await SourceService(session)._enqueue_summary_task(source_id, None)
        definition = await SourceService(session)._definitions.get_by_key(
            "collect_source_summary"
        )
        builder = SourceSummaryContextBuilder(session, collect=_collect_ok)

        blocks = await builder.build_data_blocks(task, definition)
        labels = [b.label for b in blocks]
        # 런타임 데이터만 공급 — 요약 지침(guide) 블록은 더 이상 조립하지 않는다.
        assert "collection_guide" not in labels
        assert "source" in labels
        assert "content" in labels
        assert builder.last_material is not None
        assert builder.last_chunk_count == 1
        # SourceMaterial 메타가 source 블록에 직렬화된다
        source_block = next(b for b in blocks if b.label == "source")
        assert "canonical_url" in source_block.text
        assert "예시 제목" in source_block.text


async def test_builder_collection_failure_raises_context_build_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from axkg.services.ai.context import ContextBuildError

    async with session_factory() as session:
        source_id = await _new_source(session)
        svc = SourceService(session)
        task = await svc._enqueue_summary_task(source_id, None)
        definition = await svc._definitions.get_by_key("collect_source_summary")
        builder = SourceSummaryContextBuilder(session, collect=_collect_fail())

        with pytest.raises(ContextBuildError) as exc:
            await builder.build_data_blocks(task, definition)
        assert exc.value.error_code == CONTENT_FETCH_FAILED


async def test_builder_chunks_long_content(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)
        svc = SourceService(session)
        task = await svc._enqueue_summary_task(source_id, None)
        definition = await svc._definitions.get_by_key("collect_source_summary")

        async def _big(url: str, *, user_note: str | None = None) -> SourceMaterial:
            return _material(url, content_text="가" * 130_000)

        builder = SourceSummaryContextBuilder(session, collect=_big)
        blocks = await builder.build_data_blocks(task, definition)
        labels = [b.label for b in blocks]
        assert builder.last_chunk_count >= 2
        assert "content_chunked" in labels
        assert any(label.startswith("content_chunk_") for label in labels)


async def test_builder_user_note_fallback_when_collection_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # source에 저장된 메모(raw_text)가 user_note로 주입돼 수집 실패를 구제한다.
    async with session_factory() as session:
        src = await SourceRepository(session).create(
            source_url="https://medium.com/@x/p",
            normalized_url="https://medium.com/@x/p",
            source_channel="manual",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text="핵심 메모: 전이 비용이 지배적",
        )
        svc = SourceService(session)
        task = await svc._enqueue_summary_task(src.id, None)
        definition = await svc._definitions.get_by_key("collect_source_summary")
        builder = SourceSummaryContextBuilder(
            session, collect=_collect_fail_unless_note()
        )

        blocks = await builder.build_data_blocks(task, definition)
        assert builder.last_material is not None
        assert builder.last_material.adapter == "user_note"
        assert builder.last_material.content_text == "핵심 메모: 전이 비용이 지배적"
        labels = [b.label for b in blocks]
        assert "content" in labels


# ---------------------------------------------------------------------------
# resume 잠복 버그 (PLAN-010-T-008): bare resume=true + 세션 유실 → full 컨텍스트
# ---------------------------------------------------------------------------


async def _summary_feedback_task(session, source_id, *, options, feedback="더 짧게"):
    svc = SourceService(session)
    task = await svc._enqueue_summary_task(source_id, None)
    definition = await svc._definitions.get_by_key("collect_source_summary")
    task = task.model_copy(update={"options": options, "payload": {"feedback": feedback}})
    return task, definition


async def test_summary_feedback_bare_resume_rebuilds_full_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 글로벌 bare resume=true + 세션 없음: feedback-only가 아니라 원문/본문 full 재공급 + 피드백.
    async with session_factory() as session:
        source_id = await _new_source(session)
        task, definition = await _summary_feedback_task(
            session, source_id, options={"resume": True}
        )
        builder = SourceSummaryContextBuilder(session, collect=_collect_ok)
        blocks = await builder.build_data_blocks(task, definition)
        labels = [b.label for b in blocks]
        assert "source" in labels and "content" in labels  # 원문 컨텍스트 재공급
        assert "feedback" in labels  # + 피드백
        assert builder.last_material is not None  # 실제로 재수집됨


async def test_summary_feedback_real_session_stays_feedback_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 실세션 dict일 때만 feedback-only 유지 — 원문 재수집하면 _collect_forbidden이 실패시킨다.
    async with session_factory() as session:
        source_id = await _new_source(session)
        task, definition = await _summary_feedback_task(
            session,
            source_id,
            options={"resume": {"mode": "session", "session_id": "sess-1"}},
        )
        builder = SourceSummaryContextBuilder(session, collect=_collect_forbidden)
        blocks = await builder.build_data_blocks(task, definition)
        assert [b.label for b in blocks] == ["feedback"]


# ---------------------------------------------------------------------------
# execute_source_summary 오케스트레이션
# ---------------------------------------------------------------------------


async def test_execute_success_stores_summary_and_summarized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)
        result = await SourceService(session).start_summary(source_id)
        await session.commit()
        task_id = result.ai_task.id

    client = FakeClient(result_text=json.dumps(VALID_SUMMARY))
    done = await execute_source_summary(
        task_id, source_id, client=client, session_factory=session_factory, collect=_collect_ok
    )
    assert done.status == "succeeded"

    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "summarized"
        assert source.summary_payload == VALID_SUMMARY
    # DB 프롬프트(작업 지시) + output contract가 프롬프트에 조립됐다.
    # 요약 "방법" 지침(guide)은 worker workspace의 프로젝트 context 소관이라 여기 없다.
    assert "요약" in client.requests[0].prompt  # 활성 source_summary 프롬프트 본문
    assert "JSON Schema" in client.requests[0].prompt


async def test_execute_collection_failure_marks_collection_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)
        result = await SourceService(session).start_summary(source_id)
        await session.commit()
        task_id = result.ai_task.id

    client = FakeClient(result_text=json.dumps(VALID_SUMMARY))
    done = await execute_source_summary(
        task_id,
        source_id,
        client=client,
        session_factory=session_factory,
        collect=_collect_fail(),
    )
    assert done.status == "failed"
    assert done.error_code == CONTENT_FETCH_FAILED
    # 수집 실패라 open-kknaks 실행에는 도달하지 않는다
    assert client.requests == []

    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "collection_failed"
        assert source.summary_payload == {}


async def test_execute_schema_mismatch_marks_collection_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)
        result = await SourceService(session).start_summary(source_id)
        await session.commit()
        task_id = result.ai_task.id

    # title만 — required(summary/keywords/source_type) 누락
    client = FakeClient(result_text=json.dumps({"title": "T"}))
    done = await execute_source_summary(
        task_id, source_id, client=client, session_factory=session_factory, collect=_collect_ok
    )
    assert done.status == "failed"
    assert done.error_code == "OUTPUT_SCHEMA_MISMATCH"

    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "collection_failed"
        assert source.summary_payload == {}  # 부분 소비 금지


async def test_start_summary_transitions_and_enqueues(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)
        result = await SourceService(session).start_summary(source_id)
        await session.commit()

        assert result.source.status == "summarizing"
        assert result.ai_task.status == "queued"
        assert result.ai_task.task_type == "collect_source_summary"
        assert result.ai_task.source_id == source_id


async def test_retry_task_from_queue_collection_executes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # collection_failed 이후 queue_collection이 만든 task를 실제 실행으로 연결
    async with session_factory() as session:
        source_id = await _new_source(session)
        # 최초 실패 상황 구성
        r = await SourceService(session).start_summary(source_id)
        await session.commit()
        first_task = r.ai_task.id
    client_fail = FakeClient(result_text="not-json")
    await execute_source_summary(
        first_task, source_id, client=client_fail, session_factory=session_factory, collect=_collect_ok
    )
    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "collection_failed"
        retry = await SourceService(session).queue_collection(source_id)
        await session.commit()
        retry_task_id = retry.ai_task.id
        assert retry.ai_task.retry_of_task_id == first_task

    client_ok = FakeClient(result_text=json.dumps(VALID_SUMMARY))
    done = await execute_source_summary(
        retry_task_id, source_id, client=client_ok, session_factory=session_factory, collect=_collect_ok
    )
    assert done.status == "succeeded"
    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "summarized"


async def test_queue_collection_with_note_updates_and_resummarizes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 메모 없이 최초 실패 → collection_failed. 메모 첨부 재큐 → user_note fallback으로 summarized.
    async with session_factory() as session:
        source_id = await _new_source(session)  # raw_text None
        r = await SourceService(session).start_summary(source_id)
        await session.commit()
        first_task = r.ai_task.id

    await execute_source_summary(
        first_task,
        source_id,
        client=FakeClient(result_text=json.dumps(VALID_SUMMARY)),
        session_factory=session_factory,
        collect=_collect_fail_unless_note(),
    )
    async with session_factory() as session:
        src = await SourceRepository(session).get(source_id)
        assert src.status == "collection_failed"
        # 메모 첨부 재큐(단건 호출) — raw_text 갱신 + summarizing 전이
        retry = await SourceService(session).queue_collection(
            source_id, note="복붙한 원문 메모: 세 가지 함의"
        )
        await session.commit()
        retry_task_id = retry.ai_task.id
        refreshed = await SourceRepository(session).get(source_id)
        assert refreshed.raw_text == "복붙한 원문 메모: 세 가지 함의"
        assert retry.ai_task.retry_of_task_id == first_task

    done = await execute_source_summary(
        retry_task_id,
        source_id,
        client=FakeClient(result_text=json.dumps(VALID_SUMMARY)),
        session_factory=session_factory,
        collect=_collect_fail_unless_note(),
    )
    assert done.status == "succeeded"
    async with session_factory() as session:
        src = await SourceRepository(session).get(source_id)
        assert src.status == "summarized"
        assert src.summary_payload == VALID_SUMMARY


async def test_queue_collection_note_too_long_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)
        await SourceRepository(session).set_status(source_id, "collection_failed")
        await session.commit()
        with pytest.raises(ManualNoteTooLongError):
            await SourceService(session).queue_collection(source_id, note="x" * 2001)


# ---------------------------------------------------------------------------
# 라우트 자동 트리거 (fake client + test factory를 app.state에 주입)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 요약 피드백 세션 resume 재요약 (PLAN-005-T-016)
# ---------------------------------------------------------------------------


VALID_SUMMARY_V2 = {
    "title": "Graph RAG 실전 설계 (개정)",
    "summary": "피드백을 반영해 더 짧게 다듬은 요약.",
    "keywords": ["graph-rag"],
    "source_type": "article",
    "body_markdown": "## 개정 정리\n피드백을 반영해 근거를 더 촘촘히 옮겼다.",
}


async def _summarize_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str = "okk-sess-1",
) -> uuid.UUID:
    """source를 최초 요약해 summarized로 만들고 그 source_id를 반환한다(v1 task는 session 보유)."""
    async with session_factory() as session:
        source_id = await _new_source(session)
        result = await SourceService(session).start_summary(source_id)
        await session.commit()
        task_id = result.ai_task.id
    done = await execute_source_summary(
        task_id,
        source_id,
        client=SessionFakeClient(result_text=json.dumps(VALID_SUMMARY), session_id=session_id),
        session_factory=session_factory,
        collect=_collect_ok,
    )
    assert done.status == "succeeded"
    return source_id


async def test_summary_feedback_wires_resume_session_to_submit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _summarize_once(session_factory, session_id="sess-v1")

    # 피드백 큐잉: 직전 요약 task의 session이 options.resume에 실린다.
    async with session_factory() as session:
        result = await SourceService(session).submit_summary_feedback(
            source_id, feedback="더 짧게 요약해줘"
        )
        await session.commit()
        feedback_task_id = result.ai_task.id
        assert result.source.status == "summarizing"
        assert result.ai_task.options["resume"] == {
            "mode": "session",
            "session_id": "sess-v1",
        }
        assert result.ai_task.retry_of_task_id is not None  # v1 task에 링크
        assert result.ai_task.payload["feedback"] == "더 짧게 요약해줘"

    # 실행: submit에 resume=session이 그대로 전달되고, 원문을 재수집하지 않는다.
    client = SessionFakeClient(result_text=json.dumps(VALID_SUMMARY_V2), session_id="sess-v2")
    done = await execute_source_summary(
        feedback_task_id,
        source_id,
        client=client,
        session_factory=session_factory,
        collect=_collect_forbidden,  # 호출되면 AssertionError
    )
    assert done.status == "succeeded"
    submitted = client.requests[0]
    assert submitted.options["resume"] == {"mode": "session", "session_id": "sess-v1"}
    # 피드백만 조립 — 원문 본문/조각 블록이 아니라 피드백이 프롬프트에 담긴다.
    assert "더 짧게 요약해줘" in submitted.prompt
    assert "사용자 피드백" in submitted.prompt


async def test_summary_feedback_versions_v2_and_preserves_v1(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _summarize_once(session_factory, session_id="sess-v1")

    async with session_factory() as session:
        result = await SourceService(session).submit_summary_feedback(
            source_id, feedback="키워드를 줄여줘"
        )
        await session.commit()
        feedback_task_id = result.ai_task.id

    done = await execute_source_summary(
        feedback_task_id,
        source_id,
        client=SessionFakeClient(result_text=json.dumps(VALID_SUMMARY_V2), session_id="sess-v2"),
        session_factory=session_factory,
        collect=_collect_forbidden,
    )
    assert done.status == "succeeded"

    async with session_factory() as session:
        repo = SourceRepository(session)
        source = await repo.get(source_id)
        assert source.status == "summarized"
        # summary_payload(FE 미러)는 active v2. 버전 이력은 별도 테이블에 immutable 박제.
        assert source.summary_payload == VALID_SUMMARY_V2

        revisions = await repo.list_summary_revisions(source_id)
        assert [r.version for r in revisions] == [1, 2]
        v1, v2 = revisions
        # v1은 덮어쓰이지 않고 superseded(read-only)로 보존, payload 그대로.
        assert v1.status == "superseded"
        assert v1.payload == VALID_SUMMARY
        assert v1.parent_revision_id is None
        # v2는 active(reviewable)이고 v1을 parent로 참조, active 포인터가 v2를 가리킨다.
        assert v2.status == "reviewable"
        assert v2.payload == VALID_SUMMARY_V2
        assert v2.parent_revision_id == v1.id
        assert source.active_summary_revision_id == v2.id
        # 각 버전은 자기 실행 세션을 same-format으로 박제한다(v1=sess-v1, v2=sess-v2).
        assert v1.open_kknaks_session_id == "sess-v1"
        assert v2.open_kknaks_session_id == "sess-v2"


async def test_summary_feedback_rejected_when_not_summarized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from axkg.services.sources import SummaryFeedbackNotAllowedError

    async with session_factory() as session:
        source_id = await _new_source(session)  # received
        await session.commit()
        with pytest.raises(SummaryFeedbackNotAllowedError):
            await SourceService(session).submit_summary_feedback(
                source_id, feedback="아직 요약 안 됨"
            )


async def test_summary_feedback_empty_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from axkg.services.sources import EmptyFeedbackError

    source_id = await _summarize_once(session_factory)
    async with session_factory() as session:
        with pytest.raises(EmptyFeedbackError):
            await SourceService(session).submit_summary_feedback(source_id, feedback="   ")


async def test_summary_feedback_no_previous_session_runs_without_resume(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # summarized인데 직전 succeeded task에 session이 없으면 실세션 resume 없이(새 세션) 재요약한다.
    # 전역 기본 resume=True(T-012)가 bare로 스냅샷될 수 있으나, 실세션 dict가 아니므로
    # is_resume_session=False → builder가 full 컨텍스트로 재조립한다(T-008 가드).
    from axkg.services.ai.resolution import is_resume_session

    source_id = await _summarize_once(session_factory, session_id="")
    async with session_factory() as session:
        result = await SourceService(session).submit_summary_feedback(
            source_id, feedback="다시 요약"
        )
        await session.commit()
        assert not is_resume_session(result.ai_task.options)


async def test_summary_feedback_route_transitions_summarizing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # summarized source에 피드백 POST → summarizing.
    source_id = await _summarize_once(session_factory)
    headers = await _auth_headers(client)
    res = await client.post(
        f"/sources/{source_id}/summary-feedback",
        json={"feedback": "더 짧게"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "summarizing"


async def test_summary_feedback_route_rejects_non_summarized(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)  # received
        await session.commit()
    headers = await _auth_headers(client)
    res = await client.post(
        f"/sources/{source_id}/summary-feedback", json={"feedback": "x"}, headers=headers
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "SUMMARY_FEEDBACK_NOT_ALLOWED"


async def test_summary_feedback_route_rejects_empty_feedback(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # min_length=1 → 빈 문자열은 pydantic 422.
    source_id = await _summarize_once(session_factory)
    headers = await _auth_headers(client)
    res = await client.post(
        f"/sources/{source_id}/summary-feedback", json={"feedback": ""}, headers=headers
    )
    assert res.status_code == 422


async def test_classify_route_creates_gate(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # [분류] 트리거 — WP3 Phase 1: summarized source에 분류 게이트를 생성한다(과거 501 스텁 교체).
    # client(open-kknaks) 미구성이라 background 실행은 붙지 않고 게이트/queued task만 남는다.
    source_id = await _summarize_once(session_factory)
    headers = await _auth_headers(client)
    res = await client.post(f"/sources/{source_id}/classification-gates", headers=headers)
    assert res.status_code == 201
    body = res.json()
    assert body["gate_kind"] == "classification"
    assert body["status"] == "generating"
    assert body["active_revision"]["version"] == 1


async def test_classify_route_rejects_non_summarized(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _new_source(session)  # received
        await session.commit()
    headers = await _auth_headers(client)
    res = await client.post(f"/sources/{source_id}/classification-gates", headers=headers)
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "CLASSIFICATION_NOT_ALLOWED"


async def test_manual_route_triggers_summary_when_client_present(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """client가 구성되면 manual 입력이 동기로 요약을 트리거한다(summarizing + queued task).

    background 실행은 실제 collect_source(네트워크)를 쓰므로 라우트 경로에서 fake 주입이
    불가하다 — 여기선 동기 트리거 효과만 검증하고, 성공/실패 경로는 execute_source_summary
    직접 테스트가 커버한다.
    """
    from axkg.core.database import get_session
    from axkg.main import app

    async def override_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session
    app.state.open_kknaks_client = FakeClient(result_text=json.dumps(VALID_SUMMARY))
    # background가 실제 DB/네트워크를 건드리지 않도록 즉시 반환하는 no-op runner로 대체.
    import axkg.api.routes.sources as sources_route

    scheduled: list[tuple] = []

    async def _noop_execute(*args, **kwargs):
        scheduled.append((args, kwargs))

    original = sources_route.execute_source_summary
    sources_route.execute_source_summary = _noop_execute
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            login = await ac.post(
                "/auth/login",
                json={"email": "kknaks@medisolveai.com", "password": "1234"},
            )
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            res = await ac.post(
                "/sources/manual",
                json={"source_url": "https://example.com/triggered"},
                headers=headers,
            )
            assert res.status_code == 201
            assert res.json()["status"] == "summarizing"
            source_id = res.json()["id"]

            tasks = (
                await ac.get(f"/sources/{source_id}/ai-tasks", headers=headers)
            ).json()["ai_tasks"]
            assert len(tasks) == 1
            assert tasks[0]["task_type"] == "collect_source_summary"
            assert tasks[0]["status"] == "queued"
            # background 실행이 스케줄됐다
            assert len(scheduled) == 1
    finally:
        sources_route.execute_source_summary = original
        app.dependency_overrides.clear()
        app.state.open_kknaks_client = None
        if hasattr(app.state, "session_factory"):
            delattr(app.state, "session_factory")
