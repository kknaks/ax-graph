"""승인된 apply_plan 검증·적용. 유일한 Markdown/DB writer (AXKG-SPEC-004). WP3 Phase 3.

문서화 게이트 `승인` 시 호출되어, 승인된 revision의 documentation.v1 초안+파생지식+apply_plan을
검증하고 실행한다:
- **검증**(생성 경로 거부): path allowlist(root 안), 깨진 wikilink(본문 `[[ ]]`/`up` resolve 실패),
  duplicate stem, up-without-body. 하나라도 걸리면 apply하지 않고 에러코드 표면화(SPEC-004 Case Matrix).
- **db_actions derive**: Phase 2가 빈 배열로 둔 db_actions를 **executor가 정본으로** 만든다
  (AI는 DB 저작 안 함, SPEC-004 §5): main create_document + 파생지식별 create/update +
  update_source(documented) + update_gate(approved).
- **실행**: file_actions(create_markdown=신규 full write / patch·update=수정) → 각 문서
  `GraphService.rebuild_document`(WP2, index+엣지 반영) → source `summarized→documented` →
  revision/gate approved → apply_plans applied.
- **멱등**: 이미 approved 게이트는 approve 진입에서 거부되고, write_new는 동일 내용이면 통과한다.

범위 제외(seam): 재분류 재오픈(Phase 4), FE. LLM 호출 없음(순수 실행).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.gate import ApprovalGateDTO, ApprovalGateRevisionDTO
from axkg.repositories.apply_plans import ApplyPlanRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.documents import DocumentService, stem_from_path
from axkg.services.graph import GraphService
from axkg.storage.markdown_parser import parse_markdown
from axkg.storage.markdown_root import DocumentExistsError, MarkdownRoot

logger = logging.getLogger("axkg.apply_executor")


@dataclass(frozen=True)
class ApplyError:
    error_code: str
    target: str | None = None


class ApplyValidationError(Exception):
    """apply_plan 검증 실패 — apply하지 않고 거부한다(SPEC-004 Case Matrix)."""

    def __init__(self, errors: list[ApplyError]) -> None:
        codes = ", ".join(e.error_code for e in errors)
        super().__init__(f"apply plan invalid: {codes}")
        self.errors = errors

    @property
    def primary_code(self) -> str:
        return self.errors[0].error_code if self.errors else "APPLY_PLAN_INVALID"


@dataclass
class ApplyResult:
    written_paths: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    db_actions: list[dict] = field(default_factory=list)


def _derive_db_actions(
    form: dict, *, source_id: uuid.UUID, gate_id: uuid.UUID
) -> list[dict]:
    """apply_plan.db_actions를 executor가 정본으로 derive한다(AI 출력에 의존하지 않음)."""
    draft = form.get("document_draft") or {}
    actions: list[dict] = [
        {
            "action_type": "create_document",
            "role": "main_document",
            "target_path": draft.get("target_path"),
            "document_type": draft.get("document_type"),
        }
    ]
    for suggestion in form.get("derived_suggestions") or []:
        change_kind = suggestion.get("change_kind")
        actions.append(
            {
                "action_type": (
                    "create_document" if change_kind == "create" else "update_document"
                ),
                "role": "derived_suggestion",
                "suggestion_type": suggestion.get("suggestion_type"),
                "change_kind": change_kind,
                "target_path": suggestion.get("target_path"),
                "target_document_id": suggestion.get("target_document_id"),
            }
        )
    actions.append(
        {"action_type": "update_source_status", "source_id": str(source_id), "status": "documented"}
    )
    actions.append(
        {"action_type": "update_gate_status", "gate_id": str(gate_id), "status": "approved"}
    )
    return actions


class ApplyExecutor:
    """문서화 게이트 승인 시 apply_plan을 검증·실행하는 유일한 writer."""

    def __init__(self, session: AsyncSession, root: MarkdownRoot) -> None:
        self._session = session
        self._root = root
        self._documents = DocumentService(session)
        self._graph = GraphService(session, root=root)
        self._sources = SourceRepository(session)
        self._gates = GateRepository(session)
        self._plans = ApplyPlanRepository(session)

    async def apply(
        self, gate: ApprovalGateDTO, revision: ApprovalGateRevisionDTO
    ) -> ApplyResult:
        """revision의 apply_plan을 재검증하고 실행한다(파일+index+엣지+source+게이트).

        검증 실패면 apply_plans에 invalid 기록 후 `ApplyValidationError`. 성공하면 확정
        문서를 markdown_root에 쓰고 인덱싱·엣지 rebuild한 뒤 source documented, 게이트 approved.
        """
        form = revision.payload.get("form") or {}
        draft = form.get("document_draft") or {}
        derived = form.get("derived_suggestions") or []
        source_id = gate.source_id

        db_actions = _derive_db_actions(form, source_id=source_id, gate_id=gate.id)
        file_actions = form.get("apply_plan", {}).get("file_actions") or []

        errors = await self._validate(draft, derived)
        if errors:
            await self._plans.upsert(
                gate_revision_id=revision.id,
                status="failed",
                validation_status="invalid",
                db_actions=db_actions,
                file_actions=file_actions,
                validation_errors=[{"error_code": e.error_code, "target": e.target} for e in errors],
            )
            raise ApplyValidationError(errors)

        await self._plans.upsert(
            gate_revision_id=revision.id,
            status="applying",
            validation_status="valid",
            db_actions=db_actions,
            file_actions=file_actions,
            validation_errors=[],
        )

        result = ApplyResult(db_actions=db_actions)
        # 1) 파일 쓰기 — 파생(신규/수정) 먼저, main은 마지막(리졸브 안정).
        for suggestion in derived:
            self._apply_suggestion(suggestion, result)
        try:
            self._root.write_new(draft["target_path"], draft["markdown_full"])
        except DocumentExistsError:
            # 검증에서 duplicate stem을 걸러도, index 밖 파일이 있을 수 있다(외부 편집).
            await self._plans.upsert(
                gate_revision_id=revision.id,
                status="failed",
                validation_status="invalid",
                db_actions=db_actions,
                file_actions=file_actions,
                validation_errors=[{"error_code": "DUPLICATE_STEM", "target": draft["target_path"]}],
            )
            raise ApplyValidationError([ApplyError("DUPLICATE_STEM", draft["target_path"])])
        result.written_paths.append(draft["target_path"])

        # 2) index + 증분 엣지 rebuild (WP2). 파일을 다 쓴 뒤 rebuild해 상호 링크가 resolve된다.
        for path in result.written_paths:
            await self._graph.rebuild_document(path)

        # 3) db_actions 정본 실행: source documented, revision/gate approved.
        await self._sources.mark_documented(source_id)
        await self._gates.update_revision(revision.id, status="approved", approved=True)
        await self._gates.update_gate(
            gate.id, status="approved", approved_revision_id=revision.id
        )
        await self._plans.upsert(
            gate_revision_id=revision.id,
            status="applied",
            validation_status="valid",
            db_actions=db_actions,
            file_actions=file_actions,
            validation_errors=[],
            applied=True,
        )
        logger.info(
            "apply executed gate=%s revision=%s paths=%s",
            gate.id,
            revision.id,
            result.written_paths,
        )
        return result

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _apply_suggestion(self, suggestion: dict, result: ApplyResult) -> None:
        """파생지식 file_action 실행. 내용(draft_markdown) 없으면 skip 기록."""
        target_path = suggestion.get("target_path")
        content = suggestion.get("draft_markdown")
        change_kind = suggestion.get("change_kind")
        if not target_path or not content:
            result.skipped.append(
                {"target_path": target_path, "reason": "no_draft_markdown"}
            )
            return
        if change_kind == "create":
            self._root.write_new(target_path, content)
        else:
            self._root.overwrite(target_path, content)
        result.written_paths.append(target_path)

    async def _validate(self, draft: dict, derived: list[dict]) -> list[ApplyError]:
        """생성 경로 거부 검증: path allowlist / duplicate stem / 깨진 wikilink / up-without-body."""
        errors: list[ApplyError] = []
        target_path = draft.get("target_path")
        markdown_full = draft.get("markdown_full")
        if not target_path or not markdown_full:
            return [ApplyError("DRAFT_NOT_READY", target_path)]

        # 1) path allowlist (main + 파생 create/modify 모두 root 안)
        paths = [target_path] + [
            s.get("target_path") for s in derived if s.get("target_path")
        ]
        for path in paths:
            if not path or not self._root.is_within(path):
                errors.append(ApplyError("PATH_NOT_ALLOWED", path))

        resolver = await self._documents.build_resolver()

        # 이 apply가 새로 만드는 stem들 — 초안 본문의 자기/상호 링크는 유효로 본다.
        plan_stems = {stem_from_path(target_path)}
        for suggestion in derived:
            if suggestion.get("change_kind") == "create" and suggestion.get("target_path"):
                plan_stems.add(stem_from_path(suggestion["target_path"]))

        # 2) duplicate stem (main 문서 stem이 index에 이미 다른 path로 존재)
        main_stem = stem_from_path(target_path)
        existing = resolver.resolve(main_stem)
        if existing is not None and existing.path != target_path:
            errors.append(ApplyError("DUPLICATE_STEM", main_stem))

        # 3) 깨진 wikilink / up-without-body — main 초안 본문 기준(SPEC-005 생성 경로 거부)
        parsed = parse_markdown(markdown_full)
        body_targets = {link.target for link in parsed.wikilinks}
        for link in parsed.wikilinks:
            if resolver.resolve(link.target) is None and link.target not in plan_stems:
                errors.append(ApplyError("BROKEN_WIKILINK", link.target))
        for up in parsed.up:
            if up not in body_targets:
                errors.append(ApplyError("UP_WITHOUT_BODY_LINK", up))
            elif resolver.resolve(up) is None and up not in plan_stems:
                errors.append(ApplyError("BROKEN_WIKILINK", up))
        return errors
