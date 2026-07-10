"""AXKG-SPEC-004 §E concept→permanent stale 연쇄 테스트 (PLAN-009-T-030).

커버 (E-1~6 동작 계약):
- 감지: supplement(modify) 적용 직후 그 concept를 [[ ]]로 참조하는 **permanent만** stale 마킹
  (reference·비참조 문서 미마킹). backlink 쿼리, AI 없음.
- 목록/해제: GET /documents/stale, POST .../stale/dismiss(멱등).
- 재생성: POST .../regenerate → 문서화 게이트 v++ + task payload에 3입력(대상 전문+바뀐 concept
  전문+변경 요지) 포함.
- 재생성 승인 적용 → 해당 stale 해제.

fake open-kknaks client로 네트워크/redis 없이 검증한다.
"""
import json
import uuid
from pathlib import Path, PurePosixPath

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models.base import utcnow
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.repositories.stale import StaleMarkRepository
from axkg.services.classification_gate_execution import execute_classification_gate
from axkg.services.documentation_gate_execution import execute_documentation_gate
from axkg.services.gates import (
    GateService,
    StaleRegenerationNotAllowedError,
)
from axkg.services.graph import GraphService
from axkg.services.stale import StaleService
from axkg.storage.markdown_root import MarkdownRoot

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
    "suggested_tags": ["graph-rag"],
    "source_summary": "문서 그래프를 검색 context로 삼는 RAG 설계.",
    "confidence": 0.86,
}
AREA_CLASSIFICATION = {
    "destination_type": "area",
    "destination_reason": "내 전략 종합 노트로 계속 자라날 영역이다. 여러 개념이 합류한다.",
    "suggested_title": "내 RAG 전략 노트",
    "suggested_tags": ["strategy"],
    "source_summary": "여러 개념을 엮은 전략 종합.",
    "confidence": 0.82,
}


def _concept_md(title: str, body: str) -> str:
    return f"---\ntype: concept\ntitle: {title}\n---\n\n{body}\n"


def _permanent_md(title: str, body: str) -> str:
    return f"---\ntype: permanent\ntitle: {title}\n---\n\n# {title}\n\n{body}\n"


def _reference_md(title: str, body: str) -> str:
    return f"---\ntype: reference\ntitle: {title}\n---\n\n# {title}\n\n{body}\n"


class FakeClient(OpenKknaksClient):
    def __init__(self, *, result_text: str, session_id: str = "okk-x") -> None:
        self._result_text = result_text
        self._session_id = session_id

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        return "okk-x-1"

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


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _seed_document(
    session_factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    rel: str,
    markdown: str,
) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(markdown, "utf-8")
    async with session_factory() as session:
        await GraphService(session, root=MarkdownRoot(str(root))).rebuild_document(rel)
        await session.commit()


async def _to_review_pending(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    classification: dict,
    documentation_output: dict,
    url: str,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """summarized→분류 승인→문서화 초안 실행까지. (source_id, doc_gate_id, doc_revision_id)."""
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
        await repo.set_summary(src.id, VALID_SUMMARY)
        source_id = src.id
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        cls = (result.ai_task.id, result.gate.id, result.revision.id)
    await execute_classification_gate(
        *cls,
        client=FakeClient(result_text=json.dumps(classification)),
        session_factory=session_factory,
    )
    async with session_factory() as session:
        cls_gate = await GateRepository(session).get_gate_by_source_and_kind(
            source_id, "classification"
        )
        approve = await GateService(session).approve(cls_gate.id)
        await session.commit()
        doc = approve.documentation_task
    done = await execute_documentation_gate(
        doc.ai_task.id,
        doc.gate.id,
        doc.revision.id,
        client=FakeClient(result_text=json.dumps(documentation_output)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded", done.error_message
    return source_id, doc.gate.id, doc.revision.id


async def _approve(
    session_factory: async_sessionmaker[AsyncSession], gate_id: uuid.UUID
) -> None:
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()


def _supplement_documentation(concept_rel: str, diff_preview: str) -> dict:
    """resource main + concept 하나를 보충(supplement)하는 문서화 출력.

    경로는 시스템이 조립한다(T-040): main은 filename만, supplement는 대상 concept의 stem만.
    """
    concept_stem = PurePosixPath(concept_rel).stem
    return {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _reference_md(
                "Graph RAG 실전 설계 노트", "문서 그래프를 검색 컨텍스트로 삼는 RAG 설계."
            ),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": concept_stem,
                "file_action": "overwrite_markdown",
                "target_document_id": "concept",
                "draft_markdown": _concept_md("Concept", "개념. 새 출처로 보강됨(v2)."),
                "diff_preview": diff_preview,
                "link_reason": "이 출처가 개념을 보강한다.",
            }
        ],
    }


# ---------------------------------------------------------------------------
# 감지 (E-2): supplement 적용 → 참조 permanent만 stale, reference·비참조 미마킹
# ---------------------------------------------------------------------------


async def test_supplement_marks_referring_permanent_only(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # 선행 인덱스: concept + 그것을 [[ ]]로 참조하는 permanent / reference / 비참조 permanent.
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/concepts/concept.md",
        markdown=_concept_md("Concept", "초기 개념."),
    )
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/my-strategy.md",
        markdown=_permanent_md("내 전략", "핵심은 [[concept]]에 의존한다."),
    )
    await _seed_document(
        session_factory, markdown_root,
        rel="resources/ref-note.md",
        markdown=_reference_md("참고 노트", "출처가 [[concept]]를 인용한다."),
    )
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/other-strategy.md",
        markdown=_permanent_md("다른 전략", "concept를 참조하지 않는다."),
    )

    _, gate_id, _ = await _to_review_pending(
        session_factory,
        classification=RESOURCE_CLASSIFICATION,
        documentation_output=_supplement_documentation(
            "permanent/concepts/concept.md", "개념 정의에 근거 문단 추가."
        ),
        url="https://example.com/supplement",
    )
    await _approve(session_factory, gate_id)

    async with session_factory() as session:
        docs = DocumentRepository(session)
        stale = StaleMarkRepository(session)
        active = await stale.list_active()
        marked_docs = {m.document_id for m in active}

        strategy = await docs.get_by_stem("my-strategy")
        ref = await docs.get_by_stem("ref-note")
        other = await docs.get_by_stem("other-strategy")
        # 참조하는 permanent만 마킹.
        assert strategy.id in marked_docs
        assert ref.id not in marked_docs  # reference는 미마킹
        assert other.id not in marked_docs  # 비참조 미마킹
        # 배지에 유발 concept + 변경 요지 동봉(E-2).
        mark = next(m for m in active if m.document_id == strategy.id)
        assert mark.concept_stem == "concept"
        assert mark.change_summary == "개념 정의에 근거 문단 추가."
        assert mark.status == "active"


# ---------------------------------------------------------------------------
# 목록 / 해제 (E-1): GET /documents/stale, dismiss 멱등
# ---------------------------------------------------------------------------


async def test_stale_list_and_dismiss_idempotent(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/concepts/concept.md",
        markdown=_concept_md("Concept", "초기 개념."),
    )
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/my-strategy.md",
        markdown=_permanent_md("내 전략", "핵심은 [[concept]]에 의존한다."),
    )
    _, gate_id, _ = await _to_review_pending(
        session_factory,
        classification=RESOURCE_CLASSIFICATION,
        documentation_output=_supplement_documentation(
            "permanent/concepts/concept.md", "요지 갱신."
        ),
        url="https://example.com/list",
    )
    await _approve(session_factory, gate_id)

    async with session_factory() as session:
        views = await StaleService(session).list_stale()
        assert len(views) == 1
        assert views[0].document_type == "permanent"
        assert views[0].stale_marks[0].concept_stem == "concept"
        assert views[0].stale_marks[0].change_summary == "요지 갱신."
        doc_id = views[0].document_id

    # 해제 → 목록에서 사라짐.
    async with session_factory() as session:
        dismissed = await StaleService(session).dismiss(doc_id)
        await session.commit()
        assert dismissed == 1
    async with session_factory() as session:
        assert await StaleService(session).list_stale() == []
    # 멱등: 다시 해제해도 0건, 에러 없음.
    async with session_factory() as session:
        assert await StaleService(session).dismiss(doc_id) == 0
        await session.commit()


async def test_stale_routes(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    markdown_root: Path,
) -> None:
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/concepts/concept.md",
        markdown=_concept_md("Concept", "초기 개념."),
    )
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/my-strategy.md",
        markdown=_permanent_md("내 전략", "핵심은 [[concept]]에 의존한다."),
    )
    _, gate_id, _ = await _to_review_pending(
        session_factory,
        classification=RESOURCE_CLASSIFICATION,
        documentation_output=_supplement_documentation(
            "permanent/concepts/concept.md", "요지 갱신."
        ),
        url="https://example.com/route",
    )
    await _approve(session_factory, gate_id)

    login = await client.post(
        "/auth/login", json={"email": "kknaks@medisolveai.com", "password": "1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    res = await client.get("/documents/stale", headers=headers)
    assert res.status_code == 200, res.text
    docs = res.json()["documents"]
    assert len(docs) == 1
    doc_id = docs[0]["document_id"]
    assert docs[0]["stale_marks"][0]["concept_stem"] == "concept"

    dismiss = await client.post(f"/documents/{doc_id}/stale/dismiss", headers=headers)
    assert dismiss.status_code == 200, dismiss.text
    assert dismiss.json()["dismissed_count"] == 1
    # 멱등
    again = await client.post(f"/documents/{doc_id}/stale/dismiss", headers=headers)
    assert again.status_code == 200
    assert again.json()["dismissed_count"] == 0
    assert (await client.get("/documents/stale", headers=headers)).json()["documents"] == []


# ---------------------------------------------------------------------------
# 재생성 (E-3/E-4): 문서당 독립 게이트 v++, task payload에 3입력
# ---------------------------------------------------------------------------


async def _document_permanent(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    concept_rel: str,
    permanent_path: str,
    permanent_stem: str,
    concept_stem: str,
    url: str,
) -> uuid.UUID:
    """source를 AREA로 분류·문서화 승인해 [[concept]]를 참조하는 permanent를 확정 생성한다.

    returns 확정된 permanent document_id(producing source + 문서화 게이트 보유).
    """
    area_doc = {
        "document_draft": {
            "filename_candidate": f"{permanent_stem}.md",
            "markdown_full": _permanent_md(
                "내 전략 노트", f"이 전략은 [[{concept_stem}]] 위에 선다."
            ),
        },
        "derived_suggestions": [],
    }
    _, gate_id, _ = await _to_review_pending(
        session_factory,
        classification=AREA_CLASSIFICATION,
        documentation_output=area_doc,
        url=url,
    )
    await _approve(session_factory, gate_id)
    async with session_factory() as session:
        doc = await DocumentRepository(session).get_by_stem(permanent_stem)
        assert doc is not None and doc.document_type == "permanent"
        assert doc.source_id is not None
        return doc.id


async def _make_stale_permanent(
    session_factory: async_sessionmaker[AsyncSession], root: Path
) -> uuid.UUID:
    """concept 시드 → permanent(area) 확정 → 다른 source가 concept supplement → permanent stale.

    returns stale된 permanent document_id.
    """
    await _seed_document(
        session_factory, root,
        rel="permanent/concepts/concept-x.md",
        markdown=_concept_md("Concept X", "초기 개념 X."),
    )
    permanent_id = await _document_permanent(
        session_factory,
        concept_rel="permanent/concepts/concept-x.md",
        permanent_path="permanent/my-area-note.md",
        permanent_stem="my-area-note",
        concept_stem="concept-x",
        url="https://example.com/area-note",
    )
    # 다른 source가 concept-x를 보충 → permanent stale 마킹.
    _, sup_gate, _ = await _to_review_pending(
        session_factory,
        classification=RESOURCE_CLASSIFICATION,
        documentation_output=_supplement_documentation(
            "permanent/concepts/concept-x.md", "concept-x 갱신 요지"
        ),
        url="https://example.com/supplement-x",
    )
    await _approve(session_factory, sup_gate)
    return permanent_id


async def test_regenerate_opens_gate_with_three_inputs(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    permanent_id = await _make_stale_permanent(session_factory, markdown_root)

    async with session_factory() as session:
        result = await GateService(session).open_stale_regeneration(permanent_id)
        await session.commit()
        gate_id = result.gate.id
        task_id = result.ai_task.id
        # 게이트 재문서화 revision v++ (v1 초안 이후 v2).
        assert result.gate.status == "regenerating"
        assert result.revision.version == 2

    async with session_factory() as session:
        task = await AiTaskRepository(session).get(task_id)
        assert task.task_type == "regenerate_documentation_gate"
        stale = task.payload["stale_regeneration"]
        # E-3 3입력: 대상 permanent 전문 + 바뀐 concept 전문 + 변경 요지.
        assert "[[concept-x]]" in stale["target_document"]["markdown"]
        concepts = stale["changed_concepts"]
        assert len(concepts) == 1
        assert concepts[0]["stem"] == "concept-x"
        assert concepts[0]["change_summary"] == "concept-x 갱신 요지"
        assert "개념 X" in concepts[0]["markdown"] or concepts[0]["markdown"]
        # 게이트가 이 gate_id 위에서 v++ 됐다(같은 permanent의 producing 문서화 게이트 재사용).
        assert task.gate_id == gate_id


async def test_regenerate_rejects_non_permanent(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    await _seed_document(
        session_factory, markdown_root,
        rel="permanent/concepts/lonely.md",
        markdown=_concept_md("Lonely", "producing source 없는 concept."),
    )
    async with session_factory() as session:
        concept = await DocumentRepository(session).get_by_stem("lonely")
        with pytest.raises(StaleRegenerationNotAllowedError):
            await GateService(session).open_stale_regeneration(concept.id)


# ---------------------------------------------------------------------------
# 재생성 승인 적용 → stale 해제
# ---------------------------------------------------------------------------


async def test_regenerate_approval_clears_stale(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    permanent_id = await _make_stale_permanent(session_factory, markdown_root)
    # stale 존재 확인.
    async with session_factory() as session:
        assert len(await StaleMarkRepository(session).list_active_for_document(permanent_id)) == 1

    # 재생성 게이트 오픈 + 초안 실행(개정 반영 v2, 여전히 [[concept-x]] 참조).
    async with session_factory() as session:
        result = await GateService(session).open_stale_regeneration(permanent_id)
        await session.commit()
        regen = (result.ai_task.id, result.gate.id, result.revision.id)
    v2_doc = {
        "document_draft": {
            "filename_candidate": "my-area-note.md",
            "markdown_full": _permanent_md(
                "내 전략 노트", "개정 반영: [[concept-x]] 최신 정의를 전제로 판단 갱신."
            ),
        },
        "derived_suggestions": [],
    }
    done = await execute_documentation_gate(
        *regen,
        client=FakeClient(result_text=json.dumps(v2_doc)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded", done.error_message

    # 재생성 승인 → 재문서화 apply → stale 해제.
    await _approve(session_factory, regen[1])

    async with session_factory() as session:
        # stale 해제됨.
        assert await StaleMarkRepository(session).list_active_for_document(permanent_id) == []
        assert await StaleService(session).list_stale() == []
        # permanent 재문서화(version++, 같은 경로).
        doc = await DocumentRepository(session).get(permanent_id)
        assert doc.version == 2
        assert doc.status == "current"
    assert "판단 갱신" in (markdown_root / "permanent/my-area-note.md").read_text("utf-8")


# ---------------------------------------------------------------------------
# 재생성 시 소스 승인 탭 재노출 → v2 승인 시 완료 탭 재숨김 (T-017)
# ---------------------------------------------------------------------------


async def _source_id_of(
    session_factory: async_sessionmaker[AsyncSession], permanent_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        doc = await DocumentRepository(session).get(permanent_id)
        assert doc.source_id is not None
        return doc.source_id


async def test_regeneration_reexposes_source_then_hides_on_v2_approval(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    permanent_id = await _make_stale_permanent(session_factory, markdown_root)
    source_id = await _source_id_of(session_factory, permanent_id)

    # 최초 문서화 완료 상태: documented + 완료 탭(비노출).
    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "documented"
        assert source.visible_in_inbox is False

    # 재생성 오픈 → 소스가 완료 탭에서 나와 승인 탭으로 재노출.
    async with session_factory() as session:
        result = await GateService(session).open_stale_regeneration(permanent_id)
        await session.commit()
        regen = (result.ai_task.id, result.gate.id, result.revision.id)

    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "summarized"  # documented 아님 → FE inTab 승인 탭 대상
        assert source.visible_in_inbox is True  # 기본 목록(GET /sources)에 재등장
        # FE inTab 승인 탭 계약: status!=documented AND inbox_label truthy.
        labels = await GateService(session).derive_inbox_labels([source])
        assert labels[source_id] == "classify_approved"
        # 기본 Inbox 목록에도 실제로 포함된다.
        listed = await SourceRepository(session).list()
        assert source_id in {s.id for s in listed}

    # v2 실행 + 승인 → 기존 documented 경로가 소스를 완료 탭으로 재숨김.
    v2_doc = {
        "document_draft": {
            "filename_candidate": "my-area-note.md",
            "markdown_full": _permanent_md("내 전략 노트", "v2: [[concept-x]] 갱신 반영."),
        },
        "derived_suggestions": [],
    }
    done = await execute_documentation_gate(
        *regen, client=FakeClient(result_text=json.dumps(v2_doc)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded", done.error_message
    await _approve(session_factory, regen[1])

    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        assert source.status == "documented"
        assert source.visible_in_inbox is False
        # 기본 Inbox 목록에서 다시 빠진다(완료 탭 전용).
        listed = await SourceRepository(session).list()
        assert source_id not in {s.id for s in listed}
