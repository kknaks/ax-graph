"""AXKG-SPEC-002 §5 / SPEC-004 S-3 재분류 재오픈 테스트 (WP3 Phase 4).

문서화 게이트(③)의 "이 destination이 아님" 피드백이 승인된 분류 게이트(②)를 재오픈하는 흐름.

커버:
- request_reclassification 원자적 전이(5가지):
  - 분류 게이트 approved→regenerating + approved_revision_id 해제(유일 예외 전이)
  - 기존 approved 분류 revision superseded(내용 불변)
  - source destination_type·approved_classification_gate_id 리셋
  - 문서화 게이트 cancelled(표시 상태 reclassification_requested)
  - 재분류 이유를 담은 새 분류 revision(v_next) + regenerate_classification_gate task 큐잉
- 재생성 실행(regenerate 경로 재사용) → 다른 destination v2 reviewable, 문서화 게이트 재생성
- 이유 누락 거부(MISSING_NOT_THIS_DESTINATION_REASON)
- 분류 미승인/문서화 게이트 아님 거부(RECLASSIFICATION_NOT_ALLOWED)
- 라우트: POST /gates/{doc_id}/feedback (not_this_destination) 계약

fake open-kknaks client로 네트워크/redis 없이 검증한다(분류/문서화 테스트 패턴).
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models.base import utcnow
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.classification_gate_execution import execute_classification_gate
from axkg.services.documentation_gate_execution import execute_documentation_gate
from axkg.services.gates import (
    GateService,
    NotThisDestinationReasonMissingError,
    ReclassificationNotAllowedError,
    derive_documentation_status,
)

VALID_SUMMARY = {
    "title": "Graph RAG 실전 설계",
    "summary": "문서 그래프를 검색 컨텍스트로 삼는 RAG 설계 자료 요약.",
    "keywords": ["graph-rag", "retriever"],
    "source_type": "article",
}

RESOURCE_CLASSIFICATION = {
    "destination_type": "resource",
    "destination_reason": "외부 자료를 참고용 reference note로 보존할 가치가 있다. 재사용 가능.",
    "suggested_title": "Graph RAG 실전 설계 노트",
    "suggested_tags": ["graph-rag", "retriever"],
    "source_summary": "문서 그래프를 검색 context로 삼는 RAG 설계 자료.",
    "confidence": 0.86,
}

# 재분류 후 분류기가 다른 destination(area)을 추천한 v2.
AREA_CLASSIFICATION = {
    **RESOURCE_CLASSIFICATION,
    "destination_type": "area",
    "destination_reason": "지속 관리할 AI 전환 역량 영역으로 재분류한다. 사례 축적 대상.",
    "confidence": 0.79,
}

DRAFT_MARKDOWN = (
    "---\ntype: reference\ntitle: Graph RAG 실전 설계 노트\n---\n\n# Graph RAG 실전 설계 노트\n"
)

VALID_DOCUMENTATION = {
    "document_draft": {
        "filename_candidate": "graph-rag-practical-design.md",
        "target_path": "reference/graph-rag-practical-design.md",
        "markdown_full": DRAFT_MARKDOWN,
        "links": [],
    },
    "derived_suggestions": [],
}

RECLASSIFY_REASON = "이 자료는 참고 reference가 아니라 지속 관리 area로 봐야 해. destination이 아님."


class FakeClient(OpenKknaksClient):
    """제출 request와 반환 session_id를 관찰 가능한 fake."""

    def __init__(
        self, *, result_text: str, status: str = "done", session_id: str = "okk-r-1"
    ) -> None:
        self._result_text = result_text
        self._status = status
        self._session_id = session_id
        self.requests: list[OpenKknaksTaskRequest] = []

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        self.requests.append(request)
        return "okk-r-task-1"

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
    session: AsyncSession, url: str = "https://example.com/reopen"
) -> uuid.UUID:
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


async def _to_documentation_ready(
    session_factory: async_sessionmaker[AsyncSession],
    url: str = "https://example.com/reopen",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """summarized → 분류 생성·실행·승인(resource) → 문서화 초안 실행까지.

    returns (source_id, classification_gate_id, documentation_gate_id). 이 시점에
    분류 게이트=approved, 문서화 게이트=review_pending(draft_ready).
    """
    async with session_factory() as session:
        source_id = await _summarized_source(session, url)
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        cls_task, cls_gate, cls_rev = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
    await execute_classification_gate(
        cls_task,
        cls_gate,
        cls_rev,
        client=FakeClient(result_text=json.dumps(RESOURCE_CLASSIFICATION), session_id="okk-cls-v1"),
        session_factory=session_factory,
    )
    async with session_factory() as session:
        gate = await GateRepository(session).get_gate_by_source_and_kind(
            source_id, "classification"
        )
        approve = await GateService(session).approve(gate.id)
        await session.commit()
        doc = approve.documentation_task
        doc_task, doc_gate, doc_rev = doc.ai_task.id, doc.gate.id, doc.revision.id
        cls_gate_id = gate.id
    await execute_documentation_gate(
        doc_task,
        doc_gate,
        doc_rev,
        client=FakeClient(result_text=json.dumps(VALID_DOCUMENTATION), session_id="okk-doc-v1"),
        session_factory=session_factory,
    )
    return source_id, cls_gate_id, doc_gate


async def _auth_headers(ac: AsyncClient) -> dict[str, str]:
    login = await ac.post(
        "/auth/login", json={"email": "kknaks@medisolveai.com", "password": "1234"}
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


# ---------------------------------------------------------------------------
# 표시 상태 파생 유닛 (cancelled → reclassification_requested)
# ---------------------------------------------------------------------------


def test_cancelled_documentation_status_is_reclassification_requested() -> None:
    assert derive_documentation_status("cancelled") == "reclassification_requested"


# ---------------------------------------------------------------------------
# 재오픈 전이 (SPEC-002 §5 — 5가지)
# ---------------------------------------------------------------------------


async def test_reclassification_reopens_all_transitions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, cls_gate_id, doc_gate_id = await _to_documentation_ready(session_factory)
    async with session_factory() as session:
        repo = GateRepository(session)
        cls_gate = await repo.get_gate(cls_gate_id)
        approved_rev_id = cls_gate.approved_revision_id
        assert cls_gate.status == "approved"
        assert approved_rev_id is not None

        reopen = await GateService(session).request_reclassification(
            doc_gate_id, reason=RECLASSIFY_REASON
        )
        await session.commit()

        cls_task = reopen.classification_task
        # (1) 분류 게이트: approved → regenerating + approved_revision_id 해제
        assert cls_task.gate.status == "regenerating"
        assert cls_task.gate.approved_revision_id is None
        assert cls_task.gate.active_revision_id == cls_task.revision.id
        # (2) 기존 approved 분류 revision: superseded (내용 불변)
        old = await repo.get_revision(approved_rev_id)
        assert old.status == "superseded"
        assert old.payload["form"]["destination_type"] == "resource"  # payload 불변
        # (5) 재분류 이유를 담은 새 분류 revision(v2) + regenerate task 큐잉
        assert cls_task.revision.version == 2
        assert cls_task.revision.status == "drafting"
        assert cls_task.revision.parent_revision_id == approved_rev_id
        assert cls_task.revision.feedback_id is not None
        assert cls_task.ai_task.task_type == "regenerate_classification_gate"
        assert cls_task.ai_task.payload["feedback"] == RECLASSIFY_REASON
        assert cls_task.ai_task.payload["reclassification"] is True
        # resume 세션이 기존 approved revision session으로 배선됨(SPEC-002 Session Rule)
        assert cls_task.ai_task.options["resume"] == {
            "mode": "session",
            "session_id": "okk-cls-v1",
        }
        # (4) 문서화 게이트: cancelled (표시 상태 reclassification_requested)
        assert reopen.documentation_gate.status == "cancelled"
        assert derive_documentation_status(reopen.documentation_gate.status) == (
            "reclassification_requested"
        )
        # (3) source: destination 확정 리셋, summarized 유지
        source = await SourceRepository(session).get(source_id)
        assert source.destination_type is None
        assert source.approved_classification_gate_id is None
        assert source.status == "summarized"

        # 재분류 이유가 분류 게이트 feedback으로 감사 기록됨(consumed)
        fb = await repo.get_revision(cls_task.revision.id)
        assert fb.feedback_id is not None


async def test_reclassification_regenerates_new_destination(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, cls_gate_id, doc_gate_id = await _to_documentation_ready(session_factory)
    async with session_factory() as session:
        reopen = await GateService(session).request_reclassification(
            doc_gate_id, reason=RECLASSIFY_REASON
        )
        await session.commit()
        task_id, gate_id, revision_id = (
            reopen.classification_task.ai_task.id,
            reopen.classification_task.gate.id,
            reopen.classification_task.revision.id,
        )
    # regenerate 경로 재사용: 분류기가 area로 재분류한 v2 실행
    client = FakeClient(result_text=json.dumps(AREA_CLASSIFICATION), session_id="okk-cls-v2")
    done = await execute_classification_gate(
        task_id, gate_id, revision_id, client=client, session_factory=session_factory
    )
    assert done.status == "succeeded"
    # 재생성 submit에 재분류 이유가 실린다
    assert "사용자 피드백" in client.requests[0].prompt
    assert client.requests[0].options["resume"] == {
        "mode": "session",
        "session_id": "okk-cls-v1",
    }
    async with session_factory() as session:
        repo = GateRepository(session)
        gate = await repo.get_gate(gate_id)
        assert gate.status == "review_pending"
        revisions = {r.version: r for r in await repo.list_revisions_by_gate(gate_id)}
        assert revisions[1].status == "superseded"  # 기존 approved 보존
        assert revisions[2].status == "reviewable"
        assert revisions[2].payload["form"]["destination_type"] == "area"
        # 문서화 게이트는 cancelled 그대로(재승인 시 새로 생성됨 — Phase 2 흐름)
        doc_gate = await repo.get_gate(doc_gate_id)
        assert doc_gate.status == "cancelled"


async def test_reclassification_reapprove_creates_fresh_documentation_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 재분류 → 재생성 → 재승인 시 문서화 게이트를 새로(generating) 다시 만든다(Phase 2 approve 흐름 재사용).
    source_id, cls_gate_id, doc_gate_id = await _to_documentation_ready(session_factory)
    async with session_factory() as session:
        reopen = await GateService(session).request_reclassification(
            doc_gate_id, reason=RECLASSIFY_REASON
        )
        await session.commit()
        task_id, gate_id, revision_id = (
            reopen.classification_task.ai_task.id,
            reopen.classification_task.gate.id,
            reopen.classification_task.revision.id,
        )
    await execute_classification_gate(
        task_id,
        gate_id,
        revision_id,
        client=FakeClient(result_text=json.dumps(AREA_CLASSIFICATION)),
        session_factory=session_factory,
    )
    async with session_factory() as session:
        result = await GateService(session).approve(gate_id)
        await session.commit()
        assert result.destination_type == "area"
        assert result.archived is False
        # 같은 문서화 게이트 컨테이너를 다시 generating으로(초안 task 큐잉)
        assert result.documentation_gate.id == doc_gate_id
        assert result.documentation_gate.status == "generating"
        assert result.documentation_task.ai_task.payload.get("destination_type") == "area"
        source = await SourceRepository(session).get(source_id)
        assert source.destination_type == "area"


# ---------------------------------------------------------------------------
# 거부
# ---------------------------------------------------------------------------


async def test_reclassification_reason_missing_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, doc_gate_id = await _to_documentation_ready(session_factory)
    async with session_factory() as session:
        with pytest.raises(NotThisDestinationReasonMissingError):
            await GateService(session).request_reclassification(doc_gate_id, reason="  ")


async def test_reclassification_rejected_on_classification_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 대상이 문서화 게이트가 아니면(분류 게이트 id) 거부
    _, cls_gate_id, _ = await _to_documentation_ready(session_factory)
    async with session_factory() as session:
        with pytest.raises(ReclassificationNotAllowedError):
            await GateService(session).request_reclassification(
                cls_gate_id, reason=RECLASSIFY_REASON
            )


async def test_reclassification_rejected_when_classification_not_approved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 1회 재분류 후 분류 게이트는 regenerating(approved 아님) → 재요청 거부
    _, _, doc_gate_id = await _to_documentation_ready(session_factory)
    async with session_factory() as session:
        await GateService(session).request_reclassification(
            doc_gate_id, reason=RECLASSIFY_REASON
        )
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(ReclassificationNotAllowedError):
            await GateService(session).request_reclassification(
                doc_gate_id, reason=RECLASSIFY_REASON
            )


# ---------------------------------------------------------------------------
# 라우트 계약 (POST /gates/{doc_id}/feedback, not_this_destination)
# ---------------------------------------------------------------------------


async def test_route_reclassification_flow(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, cls_gate_id, doc_gate_id = await _to_documentation_ready(
        session_factory, url="https://example.com/reopen-route"
    )
    headers = await _auth_headers(client)

    # 이유 누락 → MISSING_NOT_THIS_DESTINATION_REASON
    missing = await client.post(
        f"/gates/{doc_gate_id}/feedback",
        json={"not_this_destination": True},
        headers=headers,
    )
    assert missing.status_code == 400
    assert missing.json()["detail"]["error_code"] == "MISSING_NOT_THIS_DESTINATION_REASON"

    # 정상 재분류 → 문서화 게이트 cancelled 반환
    res = await client.post(
        f"/gates/{doc_gate_id}/feedback",
        json={
            "not_this_destination": True,
            "not_this_destination_reason": RECLASSIFY_REASON,
        },
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"

    # 분류 게이트가 재오픈됨(regenerating) — GET /sources/{id}/gates로 확인
    gates = await client.get(f"/sources/{source_id}/gates", headers=headers)
    by_kind = {g["gate_kind"]: g for g in gates.json()["gates"]}
    assert by_kind["classification"]["status"] == "regenerating"
    assert by_kind["documentation"]["status"] == "cancelled"
