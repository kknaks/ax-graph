"""문서화 게이트 ③ context builder (AXKG-SPEC-004/005/011 §Stage). WP3 Phase 2.

handler_kind=`documentation_gate`. `ClassificationGateContextBuilder`를 미러링한다.

- 입력 블록: (1) source `summary_payload`, (2) 승인된 분류 결과(destination_type +
  destination_reason + suggested_title/tags), (3) **연결 후보 2단 컨텍스트**(retriever top-N
  관련 문서 + documents index 스냅샷, AXKG-DEC-005). 컨텍스트는 **항상 주입**한다(확정 문서가
  아직 없어 빈 결과여도 블록 형태 유지, SPEC-011). PARA 문서화 "방법" 지침은 worker workspace
  context 소관 — api가 파일로 로드하지 않는다(요약/분류와 동일 실행 모델).
- 템플릿 선택: destination→template key (`resource→reference`/`area→permanent`/
  `project→project_baseline`, SPEC-010). destination_type은 task.payload에 실려 오므로
  동기 `select_template_key`에서 바로 매핑한다(파이프라인이 template body를 로드).
- feedback 재생성: resume 세션이 컨텍스트를 보유하면 feedback 블록만, stateless면 요약+분류+
  이전 payload+feedback 인라인(SPEC-002 Session Rule 3단).
- `handle_result`: 검증 통과 출력(documentation output_schema)을 **documentation.v1 공통
  envelope**로 감싸 revision payload에 저장하고 상태를 전이한다. apply_plan은 **제안
  (validation_status=pending)**으로만 저장한다 — 실행(파일 쓰기/`documented`)은 Phase 3 executor.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO
from axkg.dto.source import SourceDTO
from axkg.repositories.document_templates import DocumentTemplateRepository
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.context import ContextBuilder, ContextBuildError
from axkg.services.ai.resolution import is_resume_session
from axkg.services.document_paths import (
    assemble_derived_create_path,
    assemble_main_path,
    normalize_filename,
)
from axkg.services.project_scaffold import (
    CONTEXT_DOCUMENT_TYPE,
    SUBTYPE_CONTEXT,
    project_baseline_path,
    project_context_path,
    project_spec_path,
)
from axkg.services.document_anchor import apply_document_anchor
from axkg.services.documents import DocumentService
from axkg.services.graph import GraphService
from axkg.services.qmd import QmdClient
from axkg.storage.markdown_parser import split_frontmatter
from axkg.storage.markdown_root import MarkdownRoot

# target_stem → 기존 문서 경로(없으면 None). modify 파생 경로 해소용(PLAN-009-T-040).
ResolvePathFn = Callable[[str], "str | None"]

HANDLER_KIND = "documentation_gate"
FORM_SCHEMA_VERSION = "documentation.v1"
APPLY_PLAN_SCHEMA_VERSION = "apply_plan.v1"

# destination → 활성 템플릿 key (AXKG-SPEC-010) / 초안 document_type (AXKG-SPEC-005, DEC-005).
# project는 회사 프로젝트 팬아웃(AXKG-SPEC-014): main=원본요약(project_source_summary,
# document_type=baseline)이고, 기능정의서(feature_spec)는 파생으로 나온다(고정 동봉 템플릿).
DESTINATION_TEMPLATE_KEY = {
    "resource": "reference",
    "area": "permanent",
    "project": "project_source_summary",
}
DESTINATION_DOCUMENT_TYPE = {
    "resource": "reference",
    "area": "permanent",
    "project": "baseline",
}
PROJECT_DESTINATION = "project"
# 파생지식 change_kind → 기본 file_action (Derived Knowledge Apply Matrix, SPEC-004).
_DEFAULT_FILE_ACTION = {"create": "create_markdown", "modify": "overwrite_markdown"}
# supplement류(modify) suggestion_type 집합. feature dedup(supplement_existing_feature)은
# 후속 WP에서 배선되지만, 정규화 로직이 두 supplement를 modify로 다루도록 여기 포함한다.
_MODIFY_SUGGESTIONS = frozenset(
    {"supplement_existing_concept", "supplement_existing_feature"}
)
_CREATE_FEATURE_SPEC = "create_feature_spec"
# 파생 concept 전용 뼈대 template key — destination 매핑이 아니라 문서화③ 조립에 고정 동봉
# (PLAN-009-T-027, Layer Taxonomy: 고정 산출 타입 md 뼈대=템플릿, SPEC-011 §4).
_CONCEPT_TEMPLATE_KEY = "concept"
# 파생 기능정의서 전용 뼈대 template key — project 팬아웃 시 concept처럼 문서화③에 고정 동봉
# 주입한다(AXKG-SPEC-010/014, WP11 Phase 3). derived_suggestions[]의 create_feature_spec가 이
# 뼈대를 따른다.
_FEATURE_SPEC_TEMPLATE_KEY = "project_feature_spec"

# 초안 body preview 길이(문자). frontmatter는 전량 preview.
_BODY_PREVIEW_LEN = 600
_RETRIEVER_TOP_N = 8
# related_documents 문서 전문 주입 길이 cap(문자). A1 modify의 재료 — 초과 시 truncated 표기.
_RELATED_DOC_MARKDOWN_CAP = 4000


def _summary_block(source: SourceDTO, destination_type: str) -> dict[str, Any]:
    payload = source.summary_payload or {}
    return {
        "title": payload.get("title", ""),
        "source_url": source.source_url,
        "source_summary": payload.get("summary", ""),
        "destination_type": destination_type,
    }


def empty_documentation_payload(
    source: SourceDTO, destination_type: str
) -> dict[str, Any]:
    """AI 결과 저장 전 placeholder envelope(payload NOT NULL 충족)."""
    return {
        "schema_version": FORM_SCHEMA_VERSION,
        "gate_kind": "documentation",
        "source_id": str(source.id),
        "summary": _summary_block(source, destination_type),
        "form": {},
        "warnings": [],
    }


def _normalize_derived(
    suggestion: dict[str, Any],
    resolve_existing_path: ResolvePathFn | None = None,
    *,
    corp: str | None = None,
) -> dict[str, Any]:
    """AI derived_suggestion을 SPEC-004 Data Contract 형태로 정규화한다.

    change_kind는 suggestion_type에서 파생(supplement*→modify, create_*→create).
    경로(target_path)는 **시스템이 조립**한다(PLAN-009-T-040, AI는 경로를 내지 않음):
    - create_feature_spec(회사 프로젝트 팬아웃, WP11): projects/{corp}/spec/{stem}.md.
    - 그 외 create: suggestion_type 디렉토리 + 정규화된 filename_candidate.
    - modify: target_stem을 resolver로 기존 경로 해소. 해소 실패면 "" — executor 안전망
      (PATH_NOT_ALLOWED)에 맡긴다(신규 에러코드 발명 금지).
    """
    suggestion_type = suggestion.get("suggestion_type")
    change_kind = "modify" if suggestion_type in _MODIFY_SUGGESTIONS else "create"
    file_action = suggestion.get("file_action") or _DEFAULT_FILE_ACTION[change_kind]
    if change_kind == "create":
        if suggestion_type == _CREATE_FEATURE_SPEC:
            # 기능정의서는 projects/{corp}/spec/에 신규 생성(create-only, v1). corp 미확정이면
            # ""로 두어 executor 안전망(PATH_NOT_ALLOWED)이 잡게 한다(무근거 경로 생성 금지).
            target_path = project_spec_path(
                corp or "", normalize_filename(suggestion.get("filename_candidate"))
            )
        else:
            target_path = assemble_derived_create_path(
                suggestion_type, suggestion.get("filename_candidate")
            )
    else:
        stem = suggestion.get("target_stem")
        target_path = ""
        if stem and resolve_existing_path is not None:
            target_path = resolve_existing_path(str(stem)) or ""
    return {
        "suggestion_type": suggestion_type,
        "change_kind": change_kind,
        "target_path": target_path,
        "file_action": file_action,
        "target_document_id": suggestion.get("target_document_id"),
        "draft_markdown": suggestion.get("draft_markdown"),
        "diff_preview": suggestion.get("diff_preview"),
        "link_reason": suggestion.get("link_reason"),
        "summary": suggestion.get("summary"),
    }


def _apply_plan(
    document_draft: dict[str, Any], derived: list[dict[str, Any]]
) -> dict[str, Any]:
    """draft + 파생지식을 apply_plan **제안**으로 변환한다(validation_status=pending).

    Phase 2는 실행하지 않는다 — file_actions는 U-5 preview용 제안이고, db_actions 실제
    구성/검증(source `documented` 전이 등)은 Phase 3 Apply Executor 소관이라 비워 둔다.
    """
    file_actions: list[dict[str, Any]] = [
        {
            "action": "create_markdown",
            "role": "main_document",
            "target_path": document_draft.get("target_path"),
            "document_type": document_draft.get("document_type"),
        }
    ]
    for item in derived:
        file_actions.append(
            {
                "action": item["file_action"],
                "role": "derived_suggestion",
                "suggestion_type": item["suggestion_type"],
                "change_kind": item["change_kind"],
                "target_path": item["target_path"],
            }
        )
    return {
        "schema_version": APPLY_PLAN_SCHEMA_VERSION,
        "validation_status": "pending",
        "db_actions": [],
        "file_actions": file_actions,
    }


def wrap_documentation_output(
    source: SourceDTO,
    destination_type: str,
    output: dict[str, Any],
    *,
    prior_main_path: str | None = None,
    resolve_existing_path: ResolvePathFn | None = None,
    corp: str | None = None,
    project_subtype: str | None = None,
) -> dict[str, Any]:
    """스키마 통과 출력을 documentation.v1 공통 envelope로 감싼다(SPEC-002/004).

    경로(target_path)는 시스템이 조립한다(PLAN-009-T-040): main은 prior main이 있으면 그
    경로 재사용(재생성 v2에서 파일명 흔들려도 경로 고정), 없으면 타입 디렉토리 + 정규화된
    filename. 조립 결과는 envelope의 기존 target_path 자리에 저장 — FE 계약 무변경.

    project 팬아웃(WP11): corp가 바인딩되면 main(원본요약)은 projects/{corp}/baseline/,
    파생 기능정의서(create_feature_spec)는 projects/{corp}/spec/로 조립된다. corp 미바인딩
    (매칭 프로젝트 없음)이면 팬아웃 없이 종전 flat 경로(projects/)로 떨어진다(v1: 팬아웃 skip).
    """
    raw_draft = output.get("document_draft") or {}
    markdown_full = raw_draft.get("markdown_full", "")
    # 회사 context 단일 문서(WORK-013 P3): document_type=context, projects/{corp}/context/ 경로,
    # up:[{corp}] + 본문 [[{corp}]] 자동 배선. 팬아웃 없음(derived 무시).
    is_context = (
        destination_type == PROJECT_DESTINATION and project_subtype == SUBTYPE_CONTEXT
    )
    if is_context:
        markdown_full = apply_document_anchor(
            markdown_full, document_type=CONTEXT_DOCUMENT_TYPE, up_target=corp or None
        )
    _, body = split_frontmatter(markdown_full)
    frontmatter_preview = markdown_full[: len(markdown_full) - len(body)].strip()
    document_type = (
        CONTEXT_DOCUMENT_TYPE
        if is_context
        else DESTINATION_DOCUMENT_TYPE.get(destination_type, "reference")
    )
    if is_context and corp:
        assembled_main = project_context_path(
            corp, normalize_filename(raw_draft.get("filename_candidate"))
        )
    elif destination_type == PROJECT_DESTINATION and corp:
        assembled_main = project_baseline_path(
            corp, normalize_filename(raw_draft.get("filename_candidate"))
        )
    else:
        assembled_main = assemble_main_path(
            document_type, raw_draft.get("filename_candidate")
        )
    target_path = prior_main_path or assembled_main
    document_draft = {
        "document_type": document_type,
        "target_path": target_path,
        "filename_candidate": raw_draft.get("filename_candidate"),
        "markdown_full": markdown_full,
        "frontmatter_preview": frontmatter_preview,
        "body_preview": body.strip()[:_BODY_PREVIEW_LEN],
        "links": raw_draft.get("links", []),
    }
    # context 단일 문서는 팬아웃하지 않는다 — 파생 제안을 무시한다(WORK-013 P3).
    derived = (
        []
        if is_context
        else [
            _normalize_derived(s, resolve_existing_path, corp=corp)
            for s in output.get("derived_suggestions", [])
        ]
    )
    return {
        "schema_version": FORM_SCHEMA_VERSION,
        "gate_kind": "documentation",
        "source_id": str(source.id),
        "summary": _summary_block(source, destination_type),
        "form": {
            "destination_type": destination_type,
            "document_draft": document_draft,
            "derived_suggestions": derived,
            "apply_plan": _apply_plan(document_draft, derived),
        },
        "warnings": output.get("warnings", []),
    }


class DocumentationGateContextBuilder(ContextBuilder):
    """문서화 스테이지 데이터 블록 공급 + revision payload 소비.

    session 바인딩 handler. 연결 후보 2단 컨텍스트(retriever + index 스냅샷)를 항상 공급한다.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        root: MarkdownRoot | None = None,
        qmd: QmdClient | None = None,
    ) -> None:
        self._sources = SourceRepository(session)
        self._gates = GateRepository(session)
        self._templates = DocumentTemplateRepository(session)
        self._root = root or MarkdownRoot(settings.axkg_markdown_root)
        self._graph = GraphService(session, root=self._root, qmd=qmd)
        self._documents = DocumentService(session)
        self._doc_repo = DocumentRepository(session)
        # qmd 사이드카 장애 폴백 관찰 플래그(pipeline이 RETRIEVER_FALLBACK_USED로 수집).
        self.retriever_fallback_used: bool = False

    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        if task.source_id is None:
            raise ContextBuildError(
                "SOURCE_NOT_FOUND", "문서화 task에 source_id가 없습니다."
            )
        source = await self._sources.get(task.source_id)
        if source is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", f"source 없음: {task.source_id}")

        destination_type = self._destination(task, source)
        is_context = self._is_context(task)
        connection_block = await self._connection_candidates_block(source)
        concept_block = await self._concept_template_block()
        # project 팬아웃(WP11): 기능정의서 파생 뼈대(project_feature_spec)를 concept처럼 고정
        # 동봉한다. context 단일 문서(WORK-013)나 비-project면 None(팬아웃 안 함).
        feature_spec_block = (
            await self._feature_spec_template_block()
            if destination_type == PROJECT_DESTINATION and not is_context
            else None
        )
        # 회사 context 단일 문서 지침(WORK-013 P3): 기능으로 쪼개지 말고 배경지식 1장으로.
        context_block = self._context_guidance_block() if is_context else None

        # stale 재생성(SPEC-004 §E-3): 사용자가 연 재생성 게이트. 입력 계약 = 대상 permanent
        # 전문 + 바뀐 concept 전문 + 변경 요지(문서당 소형 컨텍스트). 피드백 경로가 아니라
        # 전용 주입 블록으로 공급한다(출력 규율 E-6은 블록에 명시).
        stale = task.payload.get("stale_regeneration")
        if stale:
            return [
                block
                for block in [
                    self._summary_data_block(source, destination_type),
                    connection_block,
                    concept_block,
                    self._stale_injection_block(stale),
                ]
                if block is not None
            ]

        feedback = task.payload.get("feedback")
        if feedback:
            if is_resume_session(task.options):
                # 세션 resume: 원문/요약/컨텍스트·concept 뼈대 재전송 없이 feedback만(토큰 절약).
                # 단, 연결 후보 컨텍스트는 그래프가 갱신됐을 수 있어 항상 다시 공급한다(SPEC-011).
                return [connection_block, self._feedback_block(str(feedback))]
            prior_payload = task.payload.get("prior_payload")
            return [
                block
                for block in [
                    self._summary_data_block(source, destination_type),
                    self._prior_payload_block(prior_payload),
                    connection_block,
                    concept_block,
                    feature_spec_block,
                    context_block,
                    self._feedback_block(str(feedback)),
                ]
                if block is not None
            ]

        # 최초 생성: 요약 + 승인 분류 결과 + 연결 후보 2단 컨텍스트 + 파생 concept/기능정의서 뼈대.
        return [
            block
            for block in [
                self._summary_data_block(source, destination_type),
                await self._classification_block(source, destination_type),
                connection_block,
                concept_block,
                feature_spec_block,
                context_block,
            ]
            if block is not None
        ]

    def select_template_key(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> str | None:
        """destination→template key 매핑 (SPEC-010). payload의 destination_type 사용.

        회사 context 단일 문서(WORK-013)는 요약① 수준 단일 md라 reference 뼈대를 재사용한다
        (document_type은 시스템이 context로 강제, wrap/apply_document_anchor).
        """
        if self._is_context(task):
            return "reference"
        destination_type = task.payload.get("destination_type")
        if destination_type in DESTINATION_TEMPLATE_KEY:
            return DESTINATION_TEMPLATE_KEY[destination_type]
        return definition.template_key or "reference"

    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        """검증 통과 출력을 documentation.v1 envelope로 저장하고 상태를 전이한다."""
        if task.revision_id is None or task.gate_id is None:
            raise ContextBuildError(
                "GATE_CONTEXT_MISSING", "문서화 task에 gate_id/revision_id가 없습니다."
            )
        source = await self._sources.get(task.source_id) if task.source_id else None
        if source is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", "문서화 결과 저장 대상 source 없음.")
        revision = await self._gates.get_revision(task.revision_id)
        if revision is None:
            raise ContextBuildError(
                "REVISION_NOT_FOUND", f"revision 없음: {task.revision_id}"
            )

        destination_type = self._destination(task, source)
        # 경로 조립 재료(PLAN-009-T-040): main 재문서화면 prior current main 경로를 재사용하고,
        # 파생 modify는 resolver로 target_stem→기존 경로를 해소한다.
        prior_main = (
            await self._doc_repo.get_current_main_by_source(source.id)
            if source.id is not None
            else None
        )
        resolver = await self._documents.build_resolver()

        def resolve_existing_path(stem: str) -> str | None:
            existing = resolver.resolve(stem)
            return existing.path if existing is not None else None

        envelope = wrap_documentation_output(
            source,
            destination_type,
            output,
            prior_main_path=prior_main.path if prior_main is not None else None,
            resolve_existing_path=resolve_existing_path,
            corp=self._corp(task),
            project_subtype=task.payload.get("project_subtype"),
        )
        # 이 revision을 reviewable로 올리기 전에, 같은 gate의 다른 모든 reviewable 형제를
        # superseded로 sweep한다(SPEC-002 §5). 빠른 연속 재생성 병렬 완료 시 parent 단건
        # supersede로는 중간 버전이 dangling으로 잔존했다(§7 OQ). reviewable만 대상.
        await self._gates.supersede_other_reviewable_revisions(
            task.gate_id, keep_revision_id=revision.id
        )

        await self._gates.update_revision(
            revision.id,
            status="reviewable",
            payload=envelope,
            open_kknaks_session_id=task.open_kknaks_session_id,
        )
        await self._gates.update_gate(
            task.gate_id,
            status="review_pending",
            active_revision_id=revision.id,
        )

    # ------------------------------------------------------------------
    # 블록 구성
    # ------------------------------------------------------------------

    @staticmethod
    def _destination(task: AiTaskDTO, source: SourceDTO) -> str:
        """destination_type: task.payload 우선, 없으면 source 확정값."""
        return task.payload.get("destination_type") or source.destination_type or "resource"

    @staticmethod
    def _corp(task: AiTaskDTO) -> str | None:
        """회사 프로젝트 slug(corp). 분류 project 확정 시 게이트가 task.payload에 실어 보낸다
        (WP11 Phase 4 corp 바인딩). 없으면 None → 팬아웃 없이 flat 경로로 떨어진다."""
        corp = task.payload.get("corp")
        return str(corp) if corp else None

    @staticmethod
    def _is_context(task: AiTaskDTO) -> bool:
        """회사 context 단일 문서 sub-type인지(WORK-013 P2). payload.project_subtype 사용."""
        return task.payload.get("project_subtype") == SUBTYPE_CONTEXT

    @staticmethod
    def _context_guidance_block() -> AssembledBlockDTO:
        """회사 context 단일 문서 생성 지침(WORK-013 P3). 기능으로 쪼개지 않는다."""
        return AssembledBlockDTO(
            kind="data",
            label="context_guidance",
            text=(
                "[회사 context 문서 지침] 이 업로드는 요구사항이 아니라 **회사 배경지식(조직·업무 "
                "플로우 등)** 이다. 기능정의서로 쪼개지 말고, 회사를 이해하는 **단일 참고 문서 1장**"
                "(요약① 수준)으로 작성하라. document_draft 하나만 내고 파생지식(derived)은 만들지 "
                "마라. 경로/타입/회사 루트 링크는 시스템이 붙인다 — filename_candidate에 파일명 stem만 낸다."
            ),
        )

    @staticmethod
    def _summary_data_block(source: SourceDTO, destination_type: str) -> AssembledBlockDTO:
        payload = {
            "source_url": source.source_url,
            "destination_type": destination_type,
            "summary": source.summary_payload or {},
        }
        return AssembledBlockDTO(
            kind="data",
            label="summary_payload",
            text=(
                "[문서화 대상 source 요약]\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        )

    async def _feature_spec_template_block(self) -> AssembledBlockDTO | None:
        """파생 기능정의서 전용 뼈대 블록(project 팬아웃 고정 동봉, WP11 Phase 3).

        project destination에서 `create_feature_spec` 파생의 draft_markdown이 따를 골격
        (요구 배경~수용 기준·`## 8. 연결`)을 프롬프트에 함께 주입한다. 템플릿이 아직 시딩되지
        않았으면 블록을 생략한다(프롬프트 서술로도 골격 유도 가능).
        """
        template = await self._templates.get_active_version(_FEATURE_SPEC_TEMPLATE_KEY)
        if template is None:
            return None
        return AssembledBlockDTO(
            kind="template_frame",
            label="feature_spec_template",
            text=(
                "[파생 기능정의서 뼈대] project 팬아웃에서 create_feature_spec 파생의 "
                "draft_markdown은 아래 뼈대(frontmatter·섹션 구조)를 그대로 따른다. 요구 1항목=1장, "
                "요청부서·요청 이력은 넣지 않는다(기능 dedup, 부서 무관):\n\n"
                + template.body
            ),
        )

    async def _concept_template_block(self) -> AssembledBlockDTO | None:
        """파생 concept 전용 뼈대 블록(문서화③ 고정 동봉, PLAN-009-T-027).

        main 템플릿(destination→key)과 별개로, `supplement_existing_concept`/`create_new_concept`
        파생의 draft_markdown이 따를 골격(정의/맥락/근거 출처)을 프롬프트에 함께 주입한다.
        템플릿이 아직 시딩되지 않았으면 블록을 생략한다(프롬프트 서술로도 골격 유도 가능).
        """
        template = await self._templates.get_active_version(_CONCEPT_TEMPLATE_KEY)
        if template is None:
            return None
        return AssembledBlockDTO(
            kind="template_frame",
            label="concept_template",
            text=(
                "[파생 concept 뼈대] create_new_concept·supplement_existing_concept 파생의 "
                "draft_markdown은 아래 뼈대(frontmatter·섹션 구조)를 그대로 따른다:\n\n"
                + template.body
            ),
        )

    async def _classification_block(
        self, source: SourceDTO, destination_type: str
    ) -> AssembledBlockDTO:
        """승인된 분류 결과(destination_reason/suggested_title/tags)를 블록으로."""
        form: dict[str, Any] = {"destination_type": destination_type}
        gate_id = source.approved_classification_gate_id
        if gate_id is not None:
            gate = await self._gates.get_gate(gate_id)
            if gate is not None and gate.approved_revision_id is not None:
                revision = await self._gates.get_revision(gate.approved_revision_id)
                if revision is not None:
                    form = revision.payload.get("form") or form
        return AssembledBlockDTO(
            kind="data",
            label="approved_classification",
            text=(
                "[승인된 분류 결과]\n"
                + json.dumps(form, ensure_ascii=False, indent=2)
            ),
        )

    async def _connection_candidates_block(
        self, source: SourceDTO
    ) -> AssembledBlockDTO:
        """연결 후보 2단 컨텍스트: retriever top-N + documents index 스냅샷(항상 주입).

        AI는 이 스냅샷 안의 stem/alias로만 `up:`/`[[ ]]`와 target_document_id를 만든다
        (스냅샷 밖 target 금지, SPEC-005). 확정 문서가 없으면 빈 목록이지만 블록은 유지한다.
        """
        payload = source.summary_payload or {}
        query = " ".join(
            str(x)
            for x in [payload.get("title", ""), *(payload.get("keywords") or [])]
            if x
        ) or (payload.get("summary", "") or source.source_url)
        result = await self._graph.retrieve(query, top_n=_RETRIEVER_TOP_N)
        self.retriever_fallback_used = result.fallback_used
        context = {
            "retriever_mode": result.retriever_mode,
            "retriever_fallback_used": result.fallback_used,
            "related_documents": [
                {
                    "stem": d.stem,
                    "title": d.title,
                    "document_type": d.document_type,
                    "target_path": d.path,
                    "snippet": d.snippet,
                    # 문서 전문(cap) — supplement_existing_concept(modify)가 보충 반영한
                    # 수정 전문을 draft_markdown으로 쓰기 위한 재료(A1, SPEC-004).
                    "markdown": self._load_full_markdown(d.path),
                }
                for d in result.documents
            ],
            "documents_index_snapshot": [
                {
                    "stem": e.stem,
                    "title": e.title,
                    "document_type": e.document_type,
                    "aliases": list(e.aliases),
                }
                for e in result.index_snapshot
            ],
        }
        return AssembledBlockDTO(
            kind="data",
            label="connection_candidates",
            text=(
                "[연결 후보 컨텍스트] 아래 retriever 후보와 documents index 스냅샷 안의 "
                "stem/alias로만 up:/[[ ]] 연결과 target_document_id를 만든다. 목록에 없는 "
                "target은 생성하지 않는다. related_documents.markdown은 문서 전문이며, "
                "supplement_existing_concept(modify) 제안은 이 전문이 있는 문서에 대해서만, "
                "그 전문을 기준으로 수정 전문을 draft_markdown에 쓴다.\n"
                + json.dumps(context, ensure_ascii=False, indent=2)
            ),
        )

    def _load_full_markdown(self, path: str) -> str:
        """related document 전문을 cap 길이만큼 로드한다(초과 시 truncated 표기)."""
        if not path:
            return ""
        try:
            if not self._root.exists(path):
                return ""
            text = self._root.read_text(path)
        except OSError:
            return ""
        if len(text) > _RELATED_DOC_MARKDOWN_CAP:
            return text[:_RELATED_DOC_MARKDOWN_CAP] + "\n… (truncated)"
        return text

    @staticmethod
    def _prior_payload_block(prior_payload: Any) -> AssembledBlockDTO:
        return AssembledBlockDTO(
            kind="data",
            label="prior_documentation",
            text=(
                "[직전 문서화 초안(v1)]\n"
                + json.dumps(prior_payload or {}, ensure_ascii=False, indent=2)
            ),
        )

    @staticmethod
    def _stale_injection_block(stale: dict[str, Any]) -> AssembledBlockDTO:
        """stale 재생성 주입 블록(SPEC-004 §E-3 입력 + §E-6 출력 규율).

        대상 permanent 전문 + 바뀐 concept 전문 + 변경 요지를 싣고, 출력 규율(옛 전제 의존
        판단만 수정·미지적 보존, 암묵 전제도 검토)을 명시한다. 프롬프트 시드는 불변 —
        규율은 이 주입 블록으로만 전달한다.
        """
        target = stale.get("target_document") or {}
        concepts = stale.get("changed_concepts") or []
        return AssembledBlockDTO(
            kind="data",
            label="stale_regeneration",
            text=(
                "[stale 재생성 — 구성 concept 개정 반영]\n"
                "아래 종합 노트(permanent, target_document)는 그 구성 개념(concept)이 새 버전으로 "
                "개정되어 낡은 전제를 담고 있을 수 있다. changed_concepts는 바뀐 concept의 현재 "
                "전문과 변경 요지다.\n"
                "출력 규율: 옛 전제(바뀐 concept의 이전 내용)에 의존한 판단만 수정하고, 지적되지 "
                "않은 판단·서술은 그대로 보존하라. 명시 인용뿐 아니라 개념을 암묵 전제로 한 판단도 "
                "검토 대상이다. 대상 종합 노트의 목적·구조는 유지하고, 출력 JSON 스키마는 최초 "
                "생성과 동일하게 둔다. 연결은 함께 주어진 연결 후보 스냅샷 안에서만 만든다.\n\n"
                + json.dumps(
                    {"target_document": target, "changed_concepts": concepts},
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        )

    @staticmethod
    def _feedback_block(feedback: str) -> AssembledBlockDTO:
        return AssembledBlockDTO(
            kind="data",
            label="feedback",
            text=(
                "이전 문서화 초안(초안+파생지식)에 대한 사용자 피드백이다. 이 세션은 source "
                "요약·분류·초안 컨텍스트를 이미 보유하고 있으니 원문을 다시 요청하지 말고, 아래 "
                "피드백을 반영해 초안과 파생지식을 통째로 v2로 재생성하라. 연결은 함께 주어진 "
                "연결 후보 스냅샷 안에서만 만든다. 출력 JSON 스키마는 직전과 동일하게 유지한다.\n\n"
                f"[사용자 피드백]\n{feedback}"
            ),
        )
