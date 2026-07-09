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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO
from axkg.dto.source import SourceDTO
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.context import ContextBuilder, ContextBuildError
from axkg.services.graph import GraphService
from axkg.storage.markdown_parser import split_frontmatter
from axkg.storage.markdown_root import MarkdownRoot

HANDLER_KIND = "documentation_gate"
FORM_SCHEMA_VERSION = "documentation.v1"
APPLY_PLAN_SCHEMA_VERSION = "apply_plan.v1"

# destination → 활성 템플릿 key (AXKG-SPEC-010) / 초안 document_type (AXKG-SPEC-005, DEC-005).
DESTINATION_TEMPLATE_KEY = {
    "resource": "reference",
    "area": "permanent",
    "project": "project_baseline",
}
DESTINATION_DOCUMENT_TYPE = {
    "resource": "reference",
    "area": "permanent",
    "project": "baseline",
}
# 파생지식 change_kind → 기본 file_action (Derived Knowledge Apply Matrix, SPEC-004).
_DEFAULT_FILE_ACTION = {"create": "create_markdown", "modify": "patch_markdown"}
_MODIFY_SUGGESTION = "supplement_existing_concept"

# 초안 body preview 길이(문자). frontmatter는 전량 preview.
_BODY_PREVIEW_LEN = 600
_RETRIEVER_TOP_N = 8


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


def _normalize_derived(suggestion: dict[str, Any]) -> dict[str, Any]:
    """AI derived_suggestion을 SPEC-004 Data Contract 형태로 정규화한다.

    change_kind는 suggestion_type에서 파생(supplement→modify, create_*→create).
    file_action 미지정이면 change_kind 기본값. modify는 target_document_id/diff_preview,
    create는 target_path/draft_markdown을 함께 싣는다(있으면 그대로, 없으면 None).
    """
    suggestion_type = suggestion.get("suggestion_type")
    change_kind = "modify" if suggestion_type == _MODIFY_SUGGESTION else "create"
    file_action = suggestion.get("file_action") or _DEFAULT_FILE_ACTION[change_kind]
    return {
        "suggestion_type": suggestion_type,
        "change_kind": change_kind,
        "target_path": suggestion.get("target_path"),
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
    source: SourceDTO, destination_type: str, output: dict[str, Any]
) -> dict[str, Any]:
    """스키마 통과 출력을 documentation.v1 공통 envelope로 감싼다(SPEC-002/004)."""
    raw_draft = output.get("document_draft") or {}
    markdown_full = raw_draft.get("markdown_full", "")
    _, body = split_frontmatter(markdown_full)
    frontmatter_preview = markdown_full[: len(markdown_full) - len(body)].strip()
    document_type = DESTINATION_DOCUMENT_TYPE.get(destination_type, "reference")
    document_draft = {
        "document_type": document_type,
        "target_path": raw_draft.get("target_path"),
        "filename_candidate": raw_draft.get("filename_candidate"),
        "markdown_full": markdown_full,
        "frontmatter_preview": frontmatter_preview,
        "body_preview": body.strip()[:_BODY_PREVIEW_LEN],
        "links": raw_draft.get("links", []),
    }
    derived = [_normalize_derived(s) for s in output.get("derived_suggestions", [])]
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

    def __init__(self, session: AsyncSession, *, root: MarkdownRoot | None = None) -> None:
        self._sources = SourceRepository(session)
        self._gates = GateRepository(session)
        self._graph = GraphService(
            session, root=root or MarkdownRoot(settings.axkg_markdown_root)
        )

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
        connection_block = await self._connection_candidates_block(source)

        feedback = task.payload.get("feedback")
        if feedback:
            resume = task.options.get("resume")
            if resume:
                # 세션 resume: 원문/요약/컨텍스트 재전송 없이 feedback만(토큰 절약). 단, 연결
                # 후보 컨텍스트는 그래프가 갱신됐을 수 있어 항상 다시 공급한다(SPEC-011).
                return [connection_block, self._feedback_block(str(feedback))]
            prior_payload = task.payload.get("prior_payload")
            return [
                self._summary_data_block(source, destination_type),
                self._prior_payload_block(prior_payload),
                connection_block,
                self._feedback_block(str(feedback)),
            ]

        # 최초 생성: 요약 + 승인 분류 결과 + 연결 후보 2단 컨텍스트.
        return [
            self._summary_data_block(source, destination_type),
            await self._classification_block(source, destination_type),
            connection_block,
        ]

    def select_template_key(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> str | None:
        """destination→template key 매핑 (SPEC-010). payload의 destination_type 사용."""
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
        envelope = wrap_documentation_output(source, destination_type, output)
        # 새 버전이 reviewable이 되면 직전 active revision(parent)은 superseded (SPEC-002 §5).
        if revision.parent_revision_id is not None:
            prior = await self._gates.get_revision(revision.parent_revision_id)
            if prior is not None and prior.status == "reviewable":
                await self._gates.update_revision(prior.id, status="superseded")

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
        context = {
            "related_documents": [
                {
                    "stem": d.stem,
                    "title": d.title,
                    "document_type": d.document_type,
                    "snippet": d.snippet,
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
                "target은 생성하지 않는다.\n"
                + json.dumps(context, ensure_ascii=False, indent=2)
            ),
        )

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
