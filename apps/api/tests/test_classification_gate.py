"""AXKG-SPEC-001/002 ② 분류 게이트 배선 테스트 (WP3 Phase 1).

커버:
- GateService.create_classification_gate: summarized→분류 게이트 생성(gate generating, revision v1
  drafting, queued task), source.status는 summarized 유지(파생 라벨만 변화)
- ClassificationGateContextBuilder + execute_classification_gate:
  - 성공: envelope 저장 + revision reviewable + gate review_pending + session id 저장
  - 스키마 불일치: revision failed + gate failed(부분 소비 금지)
- feedback: review_pending→feedback_pending, FEEDBACK_TOO_SHORT
- regenerate: v2 drafting + resume 세션 배선 + feedback consume; 실행 성공 시 v2 reviewable,
  v1 superseded (SPEC-002 §5 버전 규칙)
- approve: resource→destination 확정 + 문서화 게이트 생성(generating, WP3 Phase 2 — 초안 task
  큐잉), archive→source archived(문서화 게이트 없음); GATE_ALREADY_APPROVED / STALE_GATE_VERSION
- retry: failed gate + 마지막 task failed일 때만 새 revision + 새 ai_task(retry_of), gate generating
- 파생 Inbox 라벨(classify_pending/regenerating/approved)
- 라우트: POST/GET 계약(approve/feedback/regenerate, GET /sources/{id}/gates)

fake open-kknaks client로 네트워크/redis 없이 검증한다(요약 테스트 패턴).
"""
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.dto.ai import AiTaskDTO
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models.base import utcnow
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.classification_gate import ClassificationGateContextBuilder
from axkg.services.classification_gate_execution import execute_classification_gate
from axkg.services.gates import (
    FeedbackTooShortError,
    GateAlreadyApprovedError,
    GateRetryNotAllowedError,
    GateService,
    StaleGateVersionError,
    derive_inbox_label,
)

VALID_SUMMARY = {
    "title": "Graph RAG 실전 설계",
    "summary": "문서 그래프를 검색 컨텍스트로 삼는 RAG 설계 자료 요약.",
    "keywords": ["graph-rag", "retriever"],
    "source_type": "article",
}

VALID_CLASSIFICATION = {
    "destination_type": "resource",
    "destination_reason": "외부 자료를 참고용 reference note로 보존할 가치가 있다. 재사용 가능.",
    "suggested_title": "Graph RAG 실전 설계 노트",
    "suggested_tags": ["graph-rag", "retriever"],
    "source_summary": "문서 그래프를 검색 context로 삼는 RAG 설계 자료.",
    "confidence": 0.86,
}

VALID_CLASSIFICATION_V2 = {
    **VALID_CLASSIFICATION,
    "destination_type": "area",
    "destination_reason": "지속 관리할 AI 전환 역량 영역으로 재분류한다. 사례 축적 대상.",
    "confidence": 0.78,
}

ARCHIVE_CLASSIFICATION = {
    **VALID_CLASSIFICATION,
    "destination_type": "archive",
    "destination_reason": "현재 범위 밖 자료라 보관만 한다.",
}


class ClassifyFakeClient(OpenKknaksClient):
    """제출 request와 반환 session_id를 관찰 가능한 fake."""

    def __init__(
        self, *, result_text: str, status: str = "done", session_id: str = "okk-sess-c1"
    ) -> None:
        self._result_text = result_text
        self._status = status
        self._session_id = session_id
        self.requests: list[OpenKknaksTaskRequest] = []

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        self.requests.append(request)
        return "okk-c-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return self._status

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(
            task_id=task_id,
            status=self._status,  # type: ignore[arg-type]
            result_text=self._result_text,
            session_id=self._session_id,
        )


async def _summarized_source(
    session: AsyncSession, url: str = "https://example.com/a"
) -> uuid.UUID:
    """summary_payload를 담은 summarized source를 만든다(분류 전제)."""
    repo = SourceRepository(session)
    src = await repo.create(
        source_url=url,
        normalized_url=url,
        source_channel="manual",
        submitted_by=None,
        submitted_at=utcnow(),
        raw_text=None,
    )
    await repo.set_summary(src.id, VALID_SUMMARY)
    return src.id


async def _create_and_execute(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    result_text: str,
    session_id: str = "okk-sess-c1",
    url: str = "https://example.com/a",
) -> uuid.UUID:
    """분류 게이트 생성 + 실행까지 한 번에. source_id를 반환한다."""
    async with session_factory() as session:
        source_id = await _summarized_source(session, url)
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        task_id, gate_id, revision_id = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
    client = ClassifyFakeClient(result_text=result_text, session_id=session_id)
    done = await execute_classification_gate(
        task_id, gate_id, revision_id, client=client, session_factory=session_factory
    )
    assert done.status == "succeeded"
    return source_id


async def _classification_gate(
    session: AsyncSession, source_id: uuid.UUID
):
    return await GateRepository(session).get_gate_by_source_and_kind(
        source_id, "classification"
    )


async def _auth_headers(ac: AsyncClient) -> dict[str, str]:
    login = await ac.post(
        "/auth/login", json={"email": "kknaks@medisolveai.com", "password": "1234"}
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


# ---------------------------------------------------------------------------
# 파생 라벨 유닛
# ---------------------------------------------------------------------------


def test_derive_inbox_label_mapping() -> None:
    assert derive_inbox_label("summarized", "generating") == "classify_pending"
    assert derive_inbox_label("summarized", "review_pending") == "classify_pending"
    assert derive_inbox_label("summarized", "feedback_pending") == "classify_pending"
    assert derive_inbox_label("summarized", "regenerating") == "classify_regenerating"
    assert derive_inbox_label("summarized", "approved") == "classify_approved"
    # 매핑 밖: 게이트 없음/failed/summarized 아님 → None(임의 라벨 발명 금지)
    assert derive_inbox_label("summarized", None) is None
    assert derive_inbox_label("summarized", "failed") is None
    assert derive_inbox_label("received", "generating") is None
    assert derive_inbox_label("archived", "approved") is None


# ---------------------------------------------------------------------------
# 생성
# ---------------------------------------------------------------------------


async def test_create_classification_gate_transitions_and_enqueues(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _summarized_source(session)
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()

        assert result.gate.gate_kind == "classification"
        assert result.gate.status == "generating"
        assert result.gate.active_revision_id == result.revision.id
        assert result.gate.last_ai_task_id == result.ai_task.id
        assert result.revision.version == 1
        assert result.revision.status == "drafting"
        assert result.revision.ai_task_id == result.ai_task.id
        assert result.ai_task.status == "queued"
        assert result.ai_task.task_type == "generate_classification_gate"
        assert result.ai_task.gate_id == result.gate.id
        assert result.ai_task.revision_id == result.revision.id
        # source.status는 분류 내내 summarized 유지(파생 라벨만 변화, SPEC-001 매핑표)
        source = await SourceRepository(session).get(source_id)
        assert source.status == "summarized"


async def test_create_rejected_when_not_summarized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from axkg.services.gates import SourceNotSummarizedError

    async with session_factory() as session:
        src = await SourceRepository(session).create(
            source_url="https://example.com/x",
            normalized_url="https://example.com/x",
            source_channel="manual",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text=None,
        )  # received
        with pytest.raises(SourceNotSummarizedError):
            await GateService(session).create_classification_gate(src.id)


# ---------------------------------------------------------------------------
# 실행 (성공/실패)
# ---------------------------------------------------------------------------


async def test_execute_success_stores_envelope_and_review_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory,
        result_text=json.dumps(VALID_CLASSIFICATION),
        session_id="okk-sess-v1",
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        assert gate.status == "review_pending"
        revisions = await GateRepository(session).list_revisions_by_gate(gate.id)
        assert len(revisions) == 1
        rev = revisions[0]
        assert rev.status == "reviewable"
        assert rev.open_kknaks_session_id == "okk-sess-v1"
        # 공통 envelope(classification.v1) — form에 destination, summary 카드 정보
        assert rev.payload["schema_version"] == "classification.v1"
        assert rev.payload["gate_kind"] == "classification"
        assert rev.payload["form"]["destination_type"] == "resource"
        assert rev.payload["form"]["destination_reason"]
        assert rev.payload["summary"]["source_url"] == "https://example.com/a"
        # source는 summarized 유지
        source = await SourceRepository(session).get(source_id)
        assert source.status == "summarized"


async def test_execute_no_graph_context_in_prompt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # ② 분류는 요약 payload만 입력한다 — 그래프/연결 후보 컨텍스트 없음(SPEC-001 §5).
    async with session_factory() as session:
        source_id = await _summarized_source(session)
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        task_id, gate_id, revision_id = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
    client = ClassifyFakeClient(result_text=json.dumps(VALID_CLASSIFICATION))
    await execute_classification_gate(
        task_id, gate_id, revision_id, client=client, session_factory=session_factory
    )
    prompt = client.requests[0].prompt
    assert "요약" in prompt  # 요약 payload가 입력됨
    assert "JSON Schema" in prompt  # output contract 조립됨
    # 연결/그래프 컨텍스트 데이터 블록이 조립되지 않는다(문서화 게이트 ③ 소관)
    assert "연결 후보" not in prompt
    assert "documents index" not in prompt
    # 데이터 블록은 요약 payload 하나뿐(그래프/index 스냅샷 블록 없음)
    async with session_factory() as session:
        task = await AiTaskRepository(session).get(task_id)
    data_labels = [
        b["label"]
        for b in task.payload["assembled_input"]["blocks"]
        if b["kind"] == "data"
    ]
    assert data_labels == ["summary_payload"]


async def test_execute_schema_mismatch_marks_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _summarized_source(session)
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        task_id, gate_id, revision_id = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
    # destination_type만 — required(destination_reason/suggested_title/…) 누락
    client = ClassifyFakeClient(result_text=json.dumps({"destination_type": "resource"}))
    done = await execute_classification_gate(
        task_id, gate_id, revision_id, client=client, session_factory=session_factory
    )
    assert done.status == "failed"
    assert done.error_code == "OUTPUT_SCHEMA_MISMATCH"
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        assert gate.status == "failed"
        rev = (await GateRepository(session).list_revisions_by_gate(gate.id))[0]
        assert rev.status == "failed"
        assert rev.payload.get("form") == {}  # 부분 소비 금지


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


async def test_feedback_transitions_to_feedback_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        result = await GateService(session).submit_feedback(
            gate.id, body="이건 도구가 아니라 사례로 분류해줘"
        )
        await session.commit()
        assert result.gate.status == "feedback_pending"
        assert result.feedback.status == "submitted"
        assert result.feedback.target_revision_id == gate.active_revision_id


async def test_feedback_too_short_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        with pytest.raises(FeedbackTooShortError):
            await GateService(session).submit_feedback(gate.id, body="짧음")


async def test_feedback_rejected_when_approved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        await GateService(session).approve(gate.id)
        await session.commit()
        with pytest.raises(GateAlreadyApprovedError):
            await GateService(session).submit_feedback(
                gate.id, body="승인 후에는 못 바꿈 확인용"
            )


# ---------------------------------------------------------------------------
# regenerate (v2 + resume + supersede)
# ---------------------------------------------------------------------------


async def test_regenerate_wires_resume_and_supersedes_v1(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory,
        result_text=json.dumps(VALID_CLASSIFICATION),
        session_id="okk-sess-v1",
    )
    # 피드백 → 재생성 큐잉
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        v1_id = gate.active_revision_id
        await GateService(session).submit_feedback(
            gate.id, body="지속 관리 영역(area)으로 재분류해줘"
        )
        await session.commit()
        result = await GateService(session).regenerate(gate.id)
        await session.commit()
        assert result.gate.status == "regenerating"
        assert result.revision.version == 2
        assert result.revision.parent_revision_id == v1_id
        assert result.ai_task.task_type == "regenerate_classification_gate"
        # resume 세션이 v1 session으로 배선된다(SPEC-002 Session Rule)
        assert result.ai_task.options["resume"] == {
            "mode": "session",
            "session_id": "okk-sess-v1",
        }
        assert result.ai_task.payload["feedback"].startswith("지속 관리")
        task_id, gate_id, revision_id = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
        # 피드백은 consume됨
        assert (
            await GateRepository(session).get_latest_submitted_feedback(gate.id)
        ) is None

    # v2 실행: 재생성 submit에 resume 전달, 원문 재전송 없이 피드백만
    client = ClassifyFakeClient(
        result_text=json.dumps(VALID_CLASSIFICATION_V2), session_id="okk-sess-v2"
    )
    done = await execute_classification_gate(
        task_id, gate_id, revision_id, client=client, session_factory=session_factory
    )
    assert done.status == "succeeded"
    assert client.requests[0].options["resume"] == {
        "mode": "session",
        "session_id": "okk-sess-v1",
    }
    assert "사용자 피드백" in client.requests[0].prompt

    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        assert gate.status == "review_pending"
        assert gate.active_revision_id == revision_id
        revisions = {r.version: r for r in await GateRepository(session).list_revisions_by_gate(gate.id)}
        assert revisions[1].status == "superseded"  # v1 read-only 보존
        assert revisions[2].status == "reviewable"
        assert revisions[2].payload["form"]["destination_type"] == "area"


# ---------------------------------------------------------------------------
# 형제 reviewable supersede sweep (PLAN-009-T-039, SPEC-002 §5/§7 OQ)
# ---------------------------------------------------------------------------


def _fake_task(
    *, source_id: uuid.UUID, gate_id: uuid.UUID, revision_id: uuid.UUID
) -> AiTaskDTO:
    """handle_result가 읽는 최소 필드만 담은 실행 task DTO(재생성 완료 시뮬레이션)."""
    return AiTaskDTO(
        id=uuid.uuid4(),
        task_type="regenerate_classification_gate",
        status="running",
        provider="claude",
        source_id=source_id,
        gate_id=gate_id,
        revision_id=revision_id,
        open_kknaks_session_id="okk-sess-x",
        queued_at=utcnow(),
    )


async def test_handle_result_sweeps_parallel_reviewable_siblings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # v1 reviewable 상태에서 v2·v3가 v1을 부모로 병렬 생성(빠른 연속 재생성)됐다 가정.
    source_id = await _create_and_execute(
        session_factory,
        result_text=json.dumps(VALID_CLASSIFICATION),
        session_id="okk-sess-v1",
    )
    async with session_factory() as session:
        gates = GateRepository(session)
        gate = await _classification_gate(session, source_id)
        gate_id, v1_id = gate.id, gate.active_revision_id
        v2 = await gates.create_revision(
            gate_id=gate_id,
            version=await gates.next_version(gate_id),
            status="drafting",
            payload={},
            form_schema_version="classification.v1",
            parent_revision_id=v1_id,
        )
        v3 = await gates.create_revision(
            gate_id=gate_id,
            version=await gates.next_version(gate_id),
            status="drafting",
            payload={},
            form_schema_version="classification.v1",
            parent_revision_id=v1_id,
        )
        await session.commit()
        v2_id, v3_id = v2.id, v3.id

    # v2 완료 → v1 superseded, v2 reviewable
    async with session_factory() as session:
        await ClassificationGateContextBuilder(session).handle_result(
            _fake_task(source_id=source_id, gate_id=gate_id, revision_id=v2_id),
            VALID_CLASSIFICATION_V2,
        )
        await session.commit()
    # v3 완료 → v2 superseded, v3 reviewable (parent 단건 supersede라면 v2가 잔존했을 것)
    async with session_factory() as session:
        await ClassificationGateContextBuilder(session).handle_result(
            _fake_task(source_id=source_id, gate_id=gate_id, revision_id=v3_id),
            VALID_CLASSIFICATION_V2,
        )
        await session.commit()

    async with session_factory() as session:
        gates = GateRepository(session)
        revs = {r.id: r for r in await gates.list_revisions_by_gate(gate_id)}
        assert revs[v1_id].status == "superseded"
        assert revs[v2_id].status == "superseded"
        assert revs[v3_id].status == "reviewable"
        # 최신 하나만 reviewable
        reviewable = await gates.list_reviewable_revisions_by_gate(gate_id)
        assert [r.id for r in reviewable] == [v3_id]
        # dangling(reviewable/approved/superseded 밖 상태) 0
        assert all(
            r.status in {"reviewable", "approved", "superseded"} for r in revs.values()
        )


async def test_approve_supersedes_leftover_reviewable_sibling(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 승인 안전망: active 승인 시 병렬 누적된 형제 reviewable이 전부 superseded 돼야 한다.
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gates = GateRepository(session)
        gate = await _classification_gate(session, source_id)
        gate_id, active_id = gate.id, gate.active_revision_id
        sibling = await gates.create_revision(
            gate_id=gate_id,
            version=await gates.next_version(gate_id),
            status="reviewable",
            payload={
                "schema_version": "classification.v1",
                "gate_kind": "classification",
                "source_id": str(source_id),
                "form": {"destination_type": "resource"},
                "warnings": [],
            },
            form_schema_version="classification.v1",
            parent_revision_id=active_id,
        )
        await session.commit()
        sibling_id = sibling.id

    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    async with session_factory() as session:
        gates = GateRepository(session)
        revs = {r.id: r for r in await gates.list_revisions_by_gate(gate_id)}
        assert revs[active_id].status == "approved"
        assert revs[sibling_id].status == "superseded"
        # approved 1 + dangling(reviewable 잔존) 0
        assert sum(1 for r in revs.values() if r.status == "approved") == 1
        assert await gates.list_reviewable_revisions_by_gate(gate_id) == []


# ---------------------------------------------------------------------------
# approve (destination 확정 + 문서화 컨테이너 / archive 종료)
# ---------------------------------------------------------------------------


async def test_approve_resource_confirms_destination_and_creates_doc_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        result = await GateService(session).approve(gate.id)
        await session.commit()
        assert result.gate.status == "approved"
        assert result.gate.approved_revision_id == gate.active_revision_id
        assert result.destination_type == "resource"
        assert result.archived is False
        # Phase 2: 문서화 게이트 생성(generating) + 첫 revision(drafting) + generate task 큐잉
        assert result.documentation_gate is not None
        assert result.documentation_gate.status == "generating"
        assert result.documentation_gate.active_revision_id is not None
        assert result.documentation_task is not None
        assert result.documentation_task.ai_task.task_type == "generate_documentation_gate"
        assert result.documentation_task.ai_task.payload.get("destination_type") == "resource"
        doc_revisions = await GateRepository(session).list_revisions_by_gate(
            result.documentation_gate.id
        )
        assert [r.status for r in doc_revisions] == ["drafting"]
        # active revision approved(immutable), source destination 확정, summarized 유지
        rev = await GateRepository(session).get_revision(gate.active_revision_id)
        assert rev.status == "approved"
        assert rev.approved_at is not None
        source = await SourceRepository(session).get(source_id)
        assert source.status == "summarized"
        assert source.destination_type == "resource"
        assert source.approved_classification_gate_id == gate.id


async def test_approve_archive_ends_source_without_doc_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(ARCHIVE_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        result = await GateService(session).approve(gate.id)
        await session.commit()
        assert result.destination_type == "archive"
        assert result.archived is True
        assert result.documentation_gate is None
        source = await SourceRepository(session).get(source_id)
        assert source.status == "archived"
        assert source.visible_in_inbox is False
        assert source.destination_type == "archive"
        # 문서화 게이트가 생기지 않았다
        gates = await GateRepository(session).list_gates_by_source(source_id)
        assert [g.gate_kind for g in gates] == ["classification"]


async def test_approve_already_approved_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        await GateService(session).approve(gate.id)
        await session.commit()
        with pytest.raises(GateAlreadyApprovedError):
            await GateService(session).approve(gate.id)


async def test_approve_stale_revision_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        with pytest.raises(StaleGateVersionError):
            await GateService(session).approve(
                gate.id, expected_revision_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# retry (실패 후 재실행)
# ---------------------------------------------------------------------------


async def test_retry_after_failure_makes_new_task_and_revision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 최초 생성 실패(파싱 실패) → gate failed
    async with session_factory() as session:
        source_id = await _summarized_source(session)
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        task_id, gate_id, revision_id = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
    await execute_classification_gate(
        task_id,
        gate_id,
        revision_id,
        client=ClassifyFakeClient(result_text="not-json"),
        session_factory=session_factory,
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        assert gate.status == "failed"
        # 재시도: 새 revision + 새 ai_task(retry_of), gate generating
        retry = await GateService(session).retry(gate.id)
        await session.commit()
        assert retry.gate.status == "generating"
        assert retry.revision.version == 2
        assert retry.ai_task.retry_of_task_id == task_id
        assert retry.ai_task.task_type == "generate_classification_gate"
        retry_task_id, retry_rev_id = retry.ai_task.id, retry.revision.id
        # 이전 실패 revision은 감사 이력 보존
        revisions = {r.version: r for r in await GateRepository(session).list_revisions_by_gate(gate.id)}
        assert revisions[1].status == "failed"

    done = await execute_classification_gate(
        retry_task_id,
        gate_id,
        retry_rev_id,
        client=ClassifyFakeClient(result_text=json.dumps(VALID_CLASSIFICATION)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded"
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        assert gate.status == "review_pending"


async def test_retry_not_allowed_when_not_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)  # review_pending
        with pytest.raises(GateRetryNotAllowedError):
            await GateService(session).retry(gate.id)


# ---------------------------------------------------------------------------
# 라우트 계약
# ---------------------------------------------------------------------------


async def test_get_source_gates_lists_revisions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    headers = await _auth_headers(client)
    res = await client.get(f"/sources/{source_id}/gates", headers=headers)
    assert res.status_code == 200
    gates = res.json()["gates"]
    assert len(gates) == 1
    assert gates[0]["gate_kind"] == "classification"
    assert gates[0]["status"] == "review_pending"
    assert len(gates[0]["revisions"]) == 1
    assert gates[0]["revisions"][0]["status"] == "reviewable"


async def test_source_detail_exposes_inbox_label(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    headers = await _auth_headers(client)
    res = await client.get(f"/sources/{source_id}", headers=headers)
    assert res.status_code == 200
    # review_pending 분류 게이트 → classify_pending 파생 라벨
    assert res.json()["inbox_label"] == "classify_pending"


async def test_route_approve_and_feedback_flow(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        gate_id = gate.id
    headers = await _auth_headers(client)

    # 피드백 저장(client 미구성이라 AI 실행 없음)
    fb = await client.post(
        f"/gates/{gate_id}/feedback",
        json={"body": "이건 area로 재분류해줘 부탁해요"},
        headers=headers,
    )
    assert fb.status_code == 200
    assert fb.json()["status"] == "feedback_pending"

    # 너무 짧은 피드백 → FEEDBACK_TOO_SHORT
    short = await client.post(
        f"/gates/{gate_id}/feedback", json={"body": "짧"}, headers=headers
    )
    assert short.status_code == 400
    assert short.json()["detail"]["error_code"] == "FEEDBACK_TOO_SHORT"


async def test_route_approve_confirms_destination(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION)
    )
    async with session_factory() as session:
        gate = await _classification_gate(session, source_id)
        gate_id = gate.id
    headers = await _auth_headers(client)
    res = await client.post(f"/gates/{gate_id}/approve", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "approved"

    # 승인 후 재승인 → GATE_ALREADY_APPROVED
    again = await client.post(f"/gates/{gate_id}/approve", headers=headers)
    assert again.status_code == 409
    assert again.json()["detail"]["error_code"] == "GATE_ALREADY_APPROVED"

    # source destination 확정 확인
    detail = await client.get(f"/sources/{source_id}", headers=headers)
    assert detail.json()["destination_type"] == "resource"
    assert detail.json()["inbox_label"] == "classify_approved"


async def test_route_gate_not_found(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = await _auth_headers(client)
    res = await client.post(f"/gates/{uuid.uuid4()}/approve", headers=headers)
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "GATE_NOT_FOUND"


# ---------------------------------------------------------------------------
# resume 잠복 버그 (PLAN-010-T-008): bare resume=true + 세션 유실 → full 컨텍스트
# ---------------------------------------------------------------------------


def _feedback_task(source_id: uuid.UUID, options: dict) -> AiTaskDTO:
    return AiTaskDTO(
        id=uuid.uuid4(),
        task_type="regenerate_classification_gate",
        status="queued",
        provider="claude",
        queued_at=utcnow(),
        source_id=source_id,
        options=options,
        payload={
            "feedback": "area로 재분류해줘",
            "prior_payload": {"destination_type": "resource"},
        },
    )


async def test_classification_feedback_bare_resume_rebuilds_full_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # bare resume=true + 세션 없음: 요약 + 이전 payload + 피드백 full 조립(feedback-only 아님).
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION), session_id="s1"
    )
    async with session_factory() as session:
        builder = ClassificationGateContextBuilder(session)
        blocks = await builder.build_data_blocks(
            _feedback_task(source_id, {"resume": True}), None
        )
        labels = [b.label for b in blocks]
        assert labels == ["summary_payload", "prior_classification", "feedback"]


async def test_classification_feedback_real_session_stays_feedback_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_and_execute(
        session_factory, result_text=json.dumps(VALID_CLASSIFICATION), session_id="s1"
    )
    async with session_factory() as session:
        builder = ClassificationGateContextBuilder(session)
        blocks = await builder.build_data_blocks(
            _feedback_task(
                source_id, {"resume": {"mode": "session", "session_id": "s1"}}
            ),
            None,
        )
        assert [b.label for b in blocks] == ["feedback"]
