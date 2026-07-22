"""AXKG-WORK-011 — 기업 프로젝트 팬아웃 (docx→origin/baseline/spec, create-only). WP11 BE.

커버:
- Phase 2: docx 텍스트 추출 어댑터(docx_text) + 업로드 정규화 + intake 메모 동반 + origin staging
- Phase 3: projects/{corp}/{baseline,spec}/ 경로 조립 + wrap_documentation_output corp 팬아웃
- Phase 4: corp 바인딩(메모→기존 corp 매칭) + 게이트 apply 팬아웃(create-only) + origin finalize
- Phase 5: "프로젝트 추가" 수동 스캐폴드 API(slug 미리보기·충돌 분기·트리·admin 전용)

v1 범위: 기능정의서는 항상 create_feature_spec 신규 생성. dedup·supplement·map.md 재생성 제외.
"""
import io
import uuid
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.dto.source import SourceDTO
from axkg.integrations.source_collection.docx_text import (
    DOCX_ADAPTER,
    DOCX_FORMAT,
    DocxExtractError,
    extract_docx_text,
)
from axkg.models.base import utcnow
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.documentation_gate import wrap_documentation_output
from axkg.services.ai.source_summary import (
    INTAKE_NOTE_KEY,
    SourceSummaryContextBuilder,
    build_upload_material,
)
from axkg.services import project_scaffold as ps
from axkg.services.gates import GateService
from axkg.services.sources import SourceService
from axkg.storage.markdown_root import MarkdownRoot
from axkg.workers.apply_executor import ApplyExecutor

ADMIN_EMAIL = "kknaks@medisolveai.com"
STAFF_EMAIL = "dr.jinlee@kakao.com"
SEED_PASSWORD = "1234"


def make_docx(paragraphs: list[str]) -> bytes:
    """테스트용 최소 docx(OOXML zip) — word/document.xml에 문단 텍스트만 담는다."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    document_xml = (
        f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    ).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buf.getvalue()


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _headers(client: AsyncClient, email: str = ADMIN_EMAIL) -> dict[str, str]:
    res = await client.post("/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


# ---------------------------------------------------------------------------
# Phase 2 — docx 텍스트 추출
# ---------------------------------------------------------------------------


def test_extract_docx_text_paragraphs() -> None:
    content = make_docx(["요구 1: 부서 공유 캘린더", "요구 2: 병원 리뷰 관리"])
    assert extract_docx_text(content) == "요구 1: 부서 공유 캘린더\n요구 2: 병원 리뷰 관리"


def test_extract_docx_text_empty() -> None:
    assert extract_docx_text(make_docx([])) == ""


def test_extract_docx_text_corrupt_raises() -> None:
    with pytest.raises(DocxExtractError):
        extract_docx_text(b"not a zip at all")
    # zip이지만 document.xml이 없으면 거부.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other.xml", b"<x/>")
    with pytest.raises(DocxExtractError):
        extract_docx_text(buf.getvalue())


def test_build_upload_material_docx_uses_docx_adapter() -> None:
    md = build_upload_material("hello", filename="note.md")
    assert md.adapter == "upload" and md.content_format == "markdown"
    docx = build_upload_material("requirements", filename="req.docx")
    assert docx.adapter == DOCX_ADAPTER and docx.content_format == DOCX_FORMAT


def test_intake_note_block_injected_when_present() -> None:
    block = SourceSummaryContextBuilder._intake_note_block({INTAKE_NOTE_KEY: "더에스씨"})
    assert block is not None and "더에스씨" in block.text
    assert SourceSummaryContextBuilder._intake_note_block({}) is None


# ---------------------------------------------------------------------------
# Phase 2 — 업로드 docx + 메모 + origin staging (서비스)
# ---------------------------------------------------------------------------


async def test_upload_docx_extracts_text_note_and_stages_origin(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    docx = make_docx(["부서 공유 캘린더 요구", "병원 리뷰 관리 요구"])
    async with session_factory() as s:
        service = SourceService(s)
        source = await service.create_upload(
            filename="the-sc-req.docx",
            content=docx,
            submitted_by=None,
            note="더에스씨",
            markdown_root=root,
        )
        await s.commit()
    # 본문 텍스트만 raw_text로 추출됨
    assert source.raw_text == "부서 공유 캘린더 요구\n병원 리뷰 관리 요구"
    assert source.original_filename == "the-sc-req.docx"
    # 메모가 metadata에 저장됨(요약 컨텍스트로 동반될 값)
    assert source.metadata[INTAKE_NOTE_KEY] == "더에스씨"
    # origin 첨부 원본이 staging에 raw로 보관됨
    origin = source.metadata["origin"]
    assert origin["filename"] == "the-sc-req.docx"
    assert root.exists(origin["staged_rel"])
    assert root.read_bytes(origin["staged_rel"]) == docx


async def test_upload_docx_accepted_via_route(
    client: AsyncClient, markdown_root: Path
) -> None:
    headers = await _headers(client)
    docx = make_docx(["요구사항 본문"])
    res = await client.post(
        "/sources/upload",
        files={"file": ("req.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"note": "Acme Corp"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["source_channel"] == "upload"
    assert body["raw_text"] == "요구사항 본문"


async def test_upload_corrupt_docx_rejected(
    client: AsyncClient, markdown_root: Path
) -> None:
    headers = await _headers(client)
    res = await client.post(
        "/sources/upload",
        files={"file": ("bad.docx", b"not a real docx", "application/octet-stream")},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "UNSUPPORTED_UPLOAD_TYPE"


# ---------------------------------------------------------------------------
# Phase 3 — 경로 조립 + wrap_documentation_output 팬아웃
# ---------------------------------------------------------------------------


def test_project_path_helpers() -> None:
    assert ps.project_baseline_path("the-sc", "sum.md") == "projects/the-sc/baseline/sum.md"
    assert ps.project_spec_path("the-sc", "cal.md") == "projects/the-sc/spec/cal.md"
    assert ps.origin_final_path("the-sc", "a/b/req.docx") == "projects/the-sc/origin/req.docx"
    assert ps.corp_from_path("projects/the-sc/baseline/x.md") == "the-sc"
    assert ps.corp_from_path("resources/x.md") is None
    # corp/파일명 없으면 빈 문자열(executor 안전망행)
    assert ps.project_spec_path("", "x.md") == ""


def _dummy_source() -> SourceDTO:
    return SourceDTO(
        id=uuid.uuid4(),
        source_channel="upload",
        submitted_at=utcnow(),
        status="summarized",
        summary_payload={"title": "더에스씨 요구", "summary": "요약"},
        created_at=utcnow(),
        updated_at=utcnow(),
    )


def test_documentation_schema_accepts_feature_spec_suggestion() -> None:
    """seeded documentation_gate output_schema가 create_feature_spec 파생을 통과시킨다.

    pipeline이 jsonschema로 AI 출력을 엄격 검증하므로, enum에 create_feature_spec이 없으면
    라이브 팬아웃이 OUTPUT_SCHEMA_MISMATCH로 막힌다(WP11 Phase 4 enum 배선).
    """
    import jsonschema

    from axkg.seeds import PROMPT_SEEDS

    schema = next(p for p in PROMPT_SEEDS if p["key"] == "documentation_gate")["output_schema"]
    output = {
        "document_draft": {
            "filename_candidate": "the-sc-source-summary.md",
            "markdown_full": "---\ntype: baseline\n---\n# x\n## 기능 목록\n- [[cal]]\n",
        },
        "derived_suggestions": [
            {
                "suggestion_type": "create_feature_spec",
                "filename_candidate": "cal.md",
                "draft_markdown": "---\ntype: feature_spec\n---\n# 캘린더\n",
                "link_reason": "요구 1항목",
            }
        ],
    }
    jsonschema.validate(output, schema)  # 예외 없이 통과해야 한다


def test_wrap_documentation_output_project_fanout_paths() -> None:
    output = {
        "document_draft": {
            "filename_candidate": "the-sc-source-summary.md",
            "markdown_full": "---\ntype: baseline\ntitle: 더에스씨 원본요약\n---\n\n# 더에스씨 원본요약\n\n## 기능 목록\n- [[shared-calendar]]\n",
        },
        "derived_suggestions": [
            {
                "suggestion_type": "create_feature_spec",
                "filename_candidate": "shared-calendar.md",
                "draft_markdown": "---\ntype: feature_spec\n---\n# 공유 캘린더\n",
                "link_reason": "요구 1항목",
            }
        ],
    }
    env = wrap_documentation_output(_dummy_source(), "project", output, corp="the-sc")
    form = env["form"]
    assert form["document_draft"]["target_path"] == "projects/the-sc/baseline/the-sc-source-summary.md"
    assert form["document_draft"]["document_type"] == "baseline"
    derived = form["derived_suggestions"][0]
    assert derived["change_kind"] == "create"
    assert derived["target_path"] == "projects/the-sc/spec/shared-calendar.md"


def test_wrap_documentation_output_no_corp_falls_back_flat() -> None:
    output = {
        "document_draft": {
            "filename_candidate": "sum.md",
            "markdown_full": "---\ntype: baseline\n---\n# x\n",
        },
        "derived_suggestions": [],
    }
    env = wrap_documentation_output(_dummy_source(), "project", output, corp=None)
    # corp 미바인딩 → 팬아웃 없이 flat projects/ (v1 skip 동작)
    assert env["form"]["document_draft"]["target_path"] == "projects/sum.md"


# ---------------------------------------------------------------------------
# Phase 4 — corp 바인딩 + 게이트 apply 팬아웃 + origin finalize
# ---------------------------------------------------------------------------


def test_resolve_corp_matches_existing_only() -> None:
    corps = ["the-sc", "acme"]
    assert ps.resolve_corp("the-sc", corps) == "the-sc"
    assert ps.resolve_corp("the-sc 신규 요구", corps) == "the-sc"
    assert ps.resolve_corp("더에스씨", ["더에스씨"]) == "더에스씨"
    # 매칭 프로젝트 없으면 None(자동 생성 금지)
    assert ps.resolve_corp("unknown-co", corps) is None
    assert ps.resolve_corp("", corps) is None


async def test_documentation_extra_payload_binds_corp(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    ps.create_scaffold(root, "the-sc")  # 수동 선행 스캐폴드
    async with session_factory() as s:
        src = await SourceRepository(s).create(
            source_url=None,
            normalized_url=None,
            source_channel="upload",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text="요구 본문",
            metadata={INTAKE_NOTE_KEY: "the-sc"},
        )
        gate_service = GateService(s)
        extra = gate_service._documentation_extra_payload("project", src)
        # WORK-013: project는 sub-type(requirement 기본)도 함께 실린다.
        assert extra == {
            "destination_type": "project",
            "corp": "the-sc",
            "project_subtype": "requirement",
        }
        # 매칭 프로젝트 없는 회사명이면 corp 미바인딩(팬아웃 skip)
        src2 = SourceDTO(**{**src.model_dump(), "metadata": {INTAKE_NOTE_KEY: "no-such-co"}})
        assert gate_service._documentation_extra_payload("project", src2) == {
            "destination_type": "project",
            "project_subtype": "requirement",
        }
        # project가 아니면 corp 로직 자체를 타지 않는다
        assert gate_service._documentation_extra_payload("resource", src) == {
            "destination_type": "resource"
        }


async def test_apply_project_fanout_create_only_and_origin(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    ps.create_scaffold(root, "the-sc")
    # origin 첨부 원본을 staging에 미리 둔다(업로드 단계 모사)
    docx = make_docx(["요구 본문"])
    staged_rel = ps.origin_staging_path("tok-1", "the-sc-req.docx")
    root.write_bytes(staged_rel, docx)

    main_md = (
        "---\ntype: baseline\ntitle: 더에스씨 원본요약\n---\n\n"
        "# 더에스씨 원본요약\n\n## 기능 목록\n- [[shared-calendar]] — 공유 캘린더\n"
    )
    feature_md = (
        "---\ntype: feature_spec\ntitle: 공유 캘린더\nup: [the-sc-source-summary]\n---\n\n"
        "# 공유 캘린더\n\n## 8. 연결\n- [[the-sc-source-summary]] — 원본요약\n"
    )
    output = {
        "document_draft": {
            "filename_candidate": "the-sc-source-summary.md",
            "markdown_full": main_md,
        },
        "derived_suggestions": [
            {
                "suggestion_type": "create_feature_spec",
                "filename_candidate": "shared-calendar.md",
                "draft_markdown": feature_md,
                "link_reason": "요구 1항목=1장",
            }
        ],
    }

    async with session_factory() as s:
        repo = SourceRepository(s)
        src = await repo.create(
            source_url=None,
            normalized_url=None,
            source_channel="upload",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text="요구 본문",
            metadata={
                INTAKE_NOTE_KEY: "the-sc",
                "origin": {"filename": "the-sc-req.docx", "staged_rel": staged_rel},
            },
        )
        await repo.set_summary(src.id, {"title": "더에스씨 원본요약", "summary": "요약"})
        cls_gate = await GateRepository(s).create_gate(
            source_id=src.id, gate_kind="classification", status="approved"
        )
        await repo.set_classification_destination(
            src.id, destination_type="project", gate_id=cls_gate.id, archived=False
        )
        envelope = wrap_documentation_output(src, "project", output, corp="the-sc")
        gate = await GateRepository(s).create_gate(
            source_id=src.id, gate_kind="documentation", status="review_pending"
        )
        revision = await GateRepository(s).create_revision(
            gate_id=gate.id,
            version=1,
            status="reviewable",
            payload=envelope,
            form_schema_version="documentation.v1",
        )
        await s.commit()
        gate_id, revision_id, source_id = gate.id, revision.id, src.id

    async with session_factory() as s:
        gate = await GateRepository(s).get_gate(gate_id)
        revision = await GateRepository(s).get_revision(revision_id)
        await ApplyExecutor(s, root).apply(gate, revision)
        await s.commit()

    # 팬아웃: baseline 1장 + spec 1장(신규 생성) 파일이 회사 프로젝트 3층에 쓰였다
    assert (markdown_root / "projects/the-sc/baseline/the-sc-source-summary.md").is_file()
    assert (markdown_root / "projects/the-sc/spec/shared-calendar.md").is_file()
    # origin 원본이 staging→projects/the-sc/origin/으로 finalize됐다(그래프 노드 아님)
    assert (markdown_root / "projects/the-sc/origin/the-sc-req.docx").read_bytes() == docx
    assert not root.exists(staged_rel)  # staging 정리됨

    async with session_factory() as s:
        docs = DocumentRepository(s)
        baseline = await docs.get_by_stem("the-sc-source-summary")
        feature = await docs.get_by_stem("shared-calendar")
        assert baseline is not None and baseline.document_type == "baseline"
        # 기능정의서는 feature_spec 타입으로 신규 문서화(create-only)
        assert feature is not None and feature.document_type == "feature_spec"
        # source documented
        src = await SourceRepository(s).get(source_id)
        assert src.status == "documented"


# ---------------------------------------------------------------------------
# Phase 5 — "프로젝트 추가" 수동 스캐폴드 API
# ---------------------------------------------------------------------------


async def test_slug_preview_route(client: AsyncClient, markdown_root: Path) -> None:
    headers = await _headers(client)
    res = await client.get("/projects:slug-preview", params={"name": "The SC"}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"slug": "the-sc", "conflict": False}


async def test_slug_preview_empty_name(client: AsyncClient, markdown_root: Path) -> None:
    headers = await _headers(client)
    res = await client.get("/projects:slug-preview", params={"name": "  "}, headers=headers)
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "EMPTY_CORP_NAME"


async def test_create_project_scaffold_and_tree(
    client: AsyncClient, markdown_root: Path
) -> None:
    headers = await _headers(client)
    res = await client.post("/projects", json={"name": "The SC"}, headers=headers)
    assert res.status_code == 201, res.text
    # WORK-013: 회사 루트 {corp}.md 경로도 반환된다.
    assert res.json() == {
        "slug": "the-sc",
        "created": True,
        "merged": False,
        "root_path": "projects/the-sc/the-sc.md",
    }
    # 4층 디렉토리(context 포함) + 회사 루트 문서 생성
    for sub in ("origin", "baseline", "spec", "context"):
        assert (markdown_root / f"projects/the-sc/{sub}").is_dir()
    assert (markdown_root / "projects/the-sc/the-sc.md").is_file()
    # 목록·트리 조회
    listing = await client.get("/projects", headers=headers)
    assert listing.json() == {"projects": [{"corp": "the-sc"}]}
    tree = await client.get("/projects/the-sc", headers=headers)
    assert tree.status_code == 200
    assert tree.json() == {
        "corp": "the-sc",
        "folders": {"origin": [], "baseline": [], "spec": [], "context": []},
    }


async def test_create_project_conflict_branches(
    client: AsyncClient, markdown_root: Path
) -> None:
    headers = await _headers(client)
    await client.post("/projects", json={"name": "The SC"}, headers=headers)
    # 충돌 + on_conflict 미지정 → 409 SLUG_CONFLICT
    conflict = await client.post("/projects", json={"name": "The SC"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "SLUG_CONFLICT"
    # merge → 기존 합류
    merged = await client.post(
        "/projects", json={"name": "The SC", "on_conflict": "merge"}, headers=headers
    )
    # merge는 기존 회사 루트를 보존한다 → root_path=None(새로 쓰지 않음).
    assert merged.json() == {
        "slug": "the-sc",
        "created": False,
        "merged": True,
        "root_path": None,
    }
    # create_new → suffix 신규
    new = await client.post(
        "/projects", json={"name": "The SC", "on_conflict": "create_new"}, headers=headers
    )
    assert new.json()["slug"] == "the-sc-2"


async def test_project_not_found_tree(client: AsyncClient, markdown_root: Path) -> None:
    headers = await _headers(client)
    res = await client.get("/projects/nope", headers=headers)
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "PROJECT_NOT_FOUND"


async def test_projects_admin_only(client: AsyncClient, markdown_root: Path) -> None:
    staff = await _headers(client, STAFF_EMAIL)
    res = await client.post("/projects", json={"name": "The SC"}, headers=staff)
    assert res.status_code == 403
