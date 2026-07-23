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
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.gate import ApprovalGateDTO, ApprovalGateRevisionDTO
from axkg.repositories.apply_plans import ApplyPlanRepository
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.repositories.stale import StaleMarkRepository
from axkg.services.document_paths import DERIVED_DIR_BY_TYPE as _DERIVED_DIR_BY_TYPE
from axkg.services.document_paths import MAIN_DIR_BY_TYPE as _MAIN_DIR_BY_TYPE
from axkg.services.documents import DocumentService, stem_from_path
from axkg.services.project_scaffold import (
    corp_feature_specs,
    corp_from_path,
    origin_final_path,
)
from axkg.services.graph import GraphService
from axkg.services.stem_conflict import (
    disambiguate_stem,
    remap_stem_refs,
    rewrite_wikilinks,
)
from axkg.storage.markdown_parser import parse_markdown, split_frontmatter
from axkg.storage.markdown_root import DocumentExistsError, MarkdownRoot

logger = logging.getLogger("axkg.apply_executor")

# 회사 프로젝트 팬아웃 파생 기능정의서 suggestion_type (plan_fanout_execution과 동일 계약).
_CREATE_FEATURE_SPEC = "create_feature_spec"
_SUPPLEMENT_FEATURE = "supplement_existing_feature"
# 기존 기능정의서 병합 보존 시 붙는 섹션 헤더 — 재해결 supplement가 기존 전문을 덧붙일 때 사용.
_MERGE_SECTION_HEADER = "## 이전 정의(병합 보존)"

# 경로 컨벤션 (PLAN-009-T-016): 허용 디렉토리 밖이면 PATH_NOT_ALLOWED 거부(안전망).
# 디렉토리 매핑 SSOT는 services/document_paths.py — wrap(조립)과 여기(검증)가 공유한다
# (PLAN-009-T-040). main은 초안 document_type, 파생은 suggestion_type 기준. modify는 기존 경로.


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
    form: dict,
    *,
    source_id: uuid.UUID,
    gate_id: uuid.UUID,
    version: int = 1,
    supersede_path: str | None = None,
) -> list[dict]:
    """apply_plan.db_actions를 executor가 정본으로 derive한다(AI 출력에 의존하지 않음).

    재문서화면 main create_document에 `version`을 싣고, 경로가 바뀌면 옛 문서를 내리는
    `supersede_document` action을 함께 남긴다(SPEC-004 Document Lifecycle, T-012).
    """
    draft = form.get("document_draft") or {}
    actions: list[dict] = [
        {
            "action_type": "create_document",
            "role": "main_document",
            "target_path": draft.get("target_path"),
            "document_type": draft.get("document_type"),
            "version": version,
        }
    ]
    if supersede_path is not None:
        actions.append(
            {
                "action_type": "supersede_document",
                "role": "main_document",
                "target_path": supersede_path,
            }
        )
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
        self._doc_repo = DocumentRepository(session)
        self._stale = StaleMarkRepository(session)

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

        # 문서 lifecycle 판단 (SPEC-004 Document Lifecycle, T-012): 같은 source 계보의 현재
        # main 문서가 있으면 재문서화다 — 같은 경로면 덮어쓰기(버전++), 경로가 바뀌면 옛 문서
        # supersede + 새 문서 current.
        prior_main = await self._doc_repo.get_current_main_by_source(source_id)

        # 충돌 재해결 pass (회사 프로젝트 팬아웃, TOCTOU 해소): spawn 시점에 정한 create/경로가
        # 승인 지연 사이 라이브 DB 변화로 무효화됐을 수 있다. _validate 직전에 main/파생을
        # 라이브 resolver 기준으로 재작성해 DUPLICATE_STEM/DocumentExistsError를 애초에 흡수한다
        # (해소 가능한 팬아웃 충돌은 하드페일하지 않는다). 비프로젝트 apply는 no-op.
        await self._reresolve_conflicts(draft, derived, source_id=source_id)
        target_path = draft.get("target_path")

        same_path = prior_main is not None and prior_main.path == target_path
        path_changed = prior_main is not None and prior_main.path != target_path
        new_version = (prior_main.version + 1) if prior_main is not None else 1
        supersede_path = prior_main.path if path_changed else None

        db_actions = _derive_db_actions(
            form,
            source_id=source_id,
            gate_id=gate.id,
            version=new_version,
            supersede_path=supersede_path,
        )
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
        if same_path:
            # 같은 경로 재문서화(피드백 후 재승인, 동일 destination): 덮어쓰기. 옛 버전 본문은
            # DB 게이트 revision과 documents.version 이력에 박제돼 있어 파일 덮어쓰기가 안전하다.
            self._root.overwrite(target_path, draft["markdown_full"])
        else:
            try:
                self._root.write_new(target_path, draft["markdown_full"])
            except DocumentExistsError:
                # 검증에서 duplicate stem을 걸러도, index 밖 파일이 있을 수 있다(외부 편집).
                await self._plans.upsert(
                    gate_revision_id=revision.id,
                    status="failed",
                    validation_status="invalid",
                    db_actions=db_actions,
                    file_actions=file_actions,
                    validation_errors=[{"error_code": "DUPLICATE_STEM", "target": target_path}],
                )
                raise ApplyValidationError([ApplyError("DUPLICATE_STEM", target_path)])
        result.written_paths.append(target_path)

        # 2) index + 증분 엣지 rebuild (WP2). 파일을 다 쓴 뒤 rebuild해 상호 링크가 resolve된다.
        for path in result.written_paths:
            await self._graph.rebuild_document(path)

        # 3a) 파생 문서 lifecycle 스탬프 (SPEC-004 D, T-027): create=version 1 /
        #     supplement(overwrite)=version++. rebuild upsert는 version을 건드리지 않으므로
        #     인덱스에 남은 직전 version을 읽어 modify면 +1 한다. skip된 파생은 스탬프 안 함.
        await self._stamp_derived_lifecycle(derived, revision_id=revision.id, source_id=source_id)

        # 3b) concept→permanent stale 연쇄 감지 (SPEC-004 §E, T-030): supplement(modify) 파생이
        #     적용·버전 스탬프된 직후, 그 concept를 [[ ]]로 참조하는 permanent에 stale 배지를
        #     붙인다(backlink 쿼리, AI 없음). 마킹만 — 어떤 자동 실행도 트리거하지 않는다.
        await self._mark_stale_from_supplements(derived, revision_id=revision.id)

        # 3) main 문서 lifecycle 스탬프: current + version + producing revision/source 링크.
        #    경로가 바뀌었으면 옛 문서를 superseded로 내리고 옛 .md를 제거한다(박제는 DB가 보유).
        main_doc = await self._doc_repo.set_main_lifecycle(
            path=target_path,
            version=new_version,
            producing_revision_id=revision.id,
            source_id=source_id,
        )
        if path_changed and prior_main is not None:
            await self._doc_repo.supersede_document(prior_main.id)
            self._root.remove(prior_main.path)
            await self._stale.dismiss_document(prior_main.id)
        # permanent(종합 노트) 재문서화 apply는 그 문서의 stale 배지를 해제한다(SPEC-004 §E,
        # "재생성 승인 적용 시 해당 stale 해제"). concept 개정 재반영이 apply된 것으로 본다.
        if main_doc.document_type == "permanent":
            await self._stale.dismiss_document(main_doc.id)

        # 3c) 회사 프로젝트 팬아웃 origin 보관(WP11 Phase 4): main이 projects/{corp}/baseline/이면
        #     staging에 둔 첨부 docx 원본을 projects/{corp}/origin/으로 finalize한다(그래프 노드
        #     아님, best-effort). corp/origin 정보가 없으면 no-op.
        await self._finalize_project_origin(source_id, target_path)

        # 4) db_actions 정본 실행: source documented, revision/gate approved.
        await self._sources.mark_documented(source_id)
        await self._gates.update_revision(revision.id, status="approved", approved=True)
        # 승인 안전망: 병렬 누적된 형제 reviewable을 전부 superseded (dangling 방지,
        # SPEC-002 §5/§7 OQ). handle_result sweep이 이미 정리했으면 no-op.
        await self._gates.supersede_other_reviewable_revisions(
            gate.id, keep_revision_id=revision.id
        )
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
            skipped=result.skipped,
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

    async def _reresolve_conflicts(
        self,
        draft: dict,
        derived: list[dict],
        *,
        source_id: uuid.UUID,
    ) -> None:
        """apply 시점 라이브 DB로 stem 충돌을 재해결한다(회사 프로젝트 팬아웃만, in-place).

        spawn 시점 dedup/disambiguate(plan_fanout_execution)와 **동일 규칙**을 라이브 인덱스에
        다시 적용한다 — 승인 지연 사이 다른 소스가 같은 stem을 만들어 spawn 배정이 무효화되는
        TOCTOU를 흡수한다. 규칙:

        1) 파생 create `feature_spec` stem이 라이브 인덱스에 이미 존재:
           - **같은 corp current feature_spec** → create→modify(supplement)로 전환(공통기능
             합치기, 기존 경로에 병합 업그레이드).
           - 그 외 타입/다른 corp(concept 등) → feature stem disambiguate 후 create 유지
             (기존 문서 절대 불변, concept-supplement 가드 무침범).
        2) main(baseline/context) stem이 **다른 소스**의 문서와 충돌 → distinctive stem으로
           disambiguate(같은 소스 재문서화 `same_path`는 건드리지 않는다).
        3) 링크 전파: main stem이 바뀌면 파생 spec의 up:/본문 링크를, 파생 stem이 바뀌면
           원본요약 `## 기능 목록` 링크를 새 stem으로 재작성한다.

        비프로젝트(corp 미바인딩) apply는 no-op — 종전 검증/에러 경로 그대로.
        """
        main_path = draft.get("target_path")
        corp = corp_from_path(main_path)
        if not corp:
            return

        resolver = await self._documents.build_resolver()
        all_docs = await self._doc_repo.list_all()
        corp_specs = corp_feature_specs(all_docs, corp)
        taken = {d.stem for d in all_docs}

        main_stem_remap: dict[str, str] = {}
        feature_stem_remap: dict[str, str] = {}

        # 1) main(baseline/context) stem 충돌 — 다른 소스 문서와 겹치면 distinctive stem으로 회피.
        #    같은 소스 재문서화(같은 source_id로 이미 인덱싱된 문서)는 자기 자신이므로 건드리지 않는다.
        main_stem = stem_from_path(main_path)
        existing_main = resolver.resolve(main_stem)
        own_main = existing_main is not None and existing_main.source_id == source_id
        if existing_main is not None and not own_main:
            new_main_stem = disambiguate_stem(main_stem, corp, taken)
            taken.add(new_main_stem)
            new_main_path = str(PurePosixPath(main_path).with_name(f"{new_main_stem}.md"))
            draft["target_path"] = new_main_path
            draft["filename_candidate"] = f"{new_main_stem}.md"
            main_stem_remap[main_stem] = new_main_stem
        else:
            taken.add(main_stem)

        # 2) 파생 create feature_spec stem 충돌.
        for suggestion in derived:
            if (
                suggestion.get("change_kind") != "create"
                or suggestion.get("suggestion_type") != _CREATE_FEATURE_SPEC
            ):
                continue
            path = suggestion.get("target_path")
            if not path:
                continue
            stem = stem_from_path(path)
            existing = resolver.resolve(stem)
            if existing is None:
                taken.add(stem)
                continue
            same_corp_feature = corp_specs.get(stem)
            if same_corp_feature is not None:
                # 같은 corp current feature_spec → create를 supplement(modify)로 전환(합치기).
                # 기존 전문을 로드해 병합 업그레이드하고, 대상 경로를 기존 경로로 맞춘다.
                target = same_corp_feature["path"]
                suggestion["suggestion_type"] = _SUPPLEMENT_FEATURE
                suggestion["change_kind"] = "modify"
                suggestion["file_action"] = "overwrite_markdown"
                suggestion["target_path"] = target
                suggestion["target_document_id"] = str(existing.id)
                suggestion["draft_markdown"] = self._merge_feature_supplement(
                    target, suggestion.get("draft_markdown")
                )
                suggestion.setdefault(
                    "diff_preview", f"기존 기능정의서 '{stem}'에 새 요구 반영(apply 재해결 합치기)."
                )
                taken.add(stem)
            else:
                # concept/reference/permanent/company/context 또는 다른 corp/superseded feature와
                # 충돌 → 그 문서는 절대 안 건드리고 feature stem을 disambiguate해 create 유지.
                new_stem = disambiguate_stem(stem, corp, taken)
                taken.add(new_stem)
                new_path = str(PurePosixPath(path).with_name(f"{new_stem}.md"))
                suggestion["target_path"] = new_path
                suggestion["filename_candidate"] = f"{new_stem}.md"
                feature_stem_remap[stem] = new_stem

        # 3) 링크 전파.
        if feature_stem_remap and draft.get("markdown_full"):
            # 원본요약 `## 기능 목록`의 [[old]] → [[final]] (disambiguate된 파생 create 반영).
            draft["markdown_full"] = rewrite_wikilinks(
                draft["markdown_full"], feature_stem_remap
            )
        if main_stem_remap:
            # 파생 spec의 up:[old-summary]·본문 [[old-summary]] → 새 원본요약 stem.
            for suggestion in derived:
                content = suggestion.get("draft_markdown")
                if content:
                    suggestion["draft_markdown"] = remap_stem_refs(content, main_stem_remap)

    def _merge_feature_supplement(
        self, existing_path: str, new_draft: str | None
    ) -> str:
        """기능 supplement 재해결 병합: 새 draft(현행 완전 spec)에 기존 전문 본문을 보존 덧붙인다.

        TOCTOU 재해결에서 create로 생성됐던 draft는 기존 전문을 반영하지 못했으므로(생성 시점엔
        기존 문서가 없었다), 정보 손실을 막기 위해 기존 문서 본문을 `## 이전 정의(병합 보존)`
        섹션으로 append한다(이미 포함돼 있으면 그대로). 옛 버전 자체는 documents.version 이력에
        박제되고, 여기서는 파일 본문에 이전 정의를 남겨 병합 성격을 유지한다. LLM 블렌드가 아닌
        기계적 병합이다(executor는 LLM 미호출)."""
        new_draft = new_draft or ""
        try:
            existing = (
                self._root.read_text(existing_path)
                if self._root.exists(existing_path)
                else ""
            )
        except OSError:
            existing = ""
        if not existing.strip():
            return new_draft
        _, existing_body = split_frontmatter(existing)
        existing_body = existing_body.strip()
        if not existing_body or existing_body in new_draft:
            return new_draft
        return (
            new_draft.rstrip()
            + f"\n\n{_MERGE_SECTION_HEADER}\n\n"
            + existing_body
            + "\n"
        )

    async def _stamp_derived_lifecycle(
        self,
        derived: list[dict],
        *,
        revision_id: uuid.UUID,
        source_id: uuid.UUID,
    ) -> None:
        """파생 문서(concept/baseline)에 버전 lifecycle을 스탬프한다(SPEC-004 D).

        create=version 1(신규 row 기본값 그대로) / modify(supplement overwrite)=직전 version+1.
        내용(draft_markdown) 없이 skip된 파생, 또는 rebuild가 인덱스를 못 만든 파생은 건너뛴다.
        옛 버전 본문 박제는 게이트 revision payload가 이미 보유 — 별도 스냅샷 없음.
        """
        for suggestion in derived:
            path = suggestion.get("target_path")
            if not path or not suggestion.get("draft_markdown"):
                continue
            current = await self._doc_repo.get_by_path(path)
            if current is None:
                continue
            version = (
                current.version + 1
                if suggestion.get("change_kind") == "modify"
                else current.version
            )
            await self._doc_repo.set_derived_lifecycle(
                path=path,
                version=version,
                producing_revision_id=revision_id,
                source_id=source_id,
            )

    async def _mark_stale_from_supplements(
        self, derived: list[dict], *, revision_id: uuid.UUID
    ) -> None:
        """supplement(modify) 파생으로 개정된 concept를 참조하는 permanent에 stale 배지를 붙인다.

        감지 = backlink 쿼리(document_edges)로 그 concept를 가리키는 문서 중 type=permanent만
        (reference·비참조 문서 미마킹). 배지에는 변경 요지(유발 suggestion의 diff_preview)를
        동봉한다(E-2). 내용 없이 skip된 supplement는 마킹하지 않는다(적용된 것만).
        """
        # supplement_existing_concept는 항상 modify(개념 성장 경로) — change_kind 누락 payload에도
        # 견고하도록 suggestion_type을 1차 기준으로 삼는다. 내용 없이 skip된 것은 제외(적용된 것만).
        supplements = [
            s
            for s in derived
            if s.get("suggestion_type") == "supplement_existing_concept"
            and s.get("change_kind") != "create"
            and s.get("target_path")
            and s.get("draft_markdown")
        ]
        if not supplements:
            return
        docs_by_id = {d.id: d for d in await self._doc_repo.list_all()}
        for suggestion in supplements:
            concept = await self._doc_repo.get_by_path(suggestion["target_path"])
            if concept is None or concept.document_type != "concept":
                continue
            change_summary = suggestion.get("diff_preview") or suggestion.get("summary")
            marked: set[uuid.UUID] = set()
            for edge in await self._doc_repo.list_edges_to_document(concept.id):
                referrer = docs_by_id.get(edge.from_document_id)
                if (
                    referrer is None
                    or referrer.document_type != "permanent"
                    or referrer.status != "current"
                    or referrer.id in marked
                ):
                    continue
                marked.add(referrer.id)
                await self._stale.mark(
                    document_id=referrer.id,
                    concept_stem=concept.stem,
                    concept_path=concept.path,
                    change_summary=change_summary,
                    triggering_revision_id=revision_id,
                )

    async def _finalize_project_origin(
        self, source_id: uuid.UUID, main_path: str | None
    ) -> None:
        """staging에 둔 첨부 docx 원본을 projects/{corp}/origin/으로 옮긴다(WP11 Phase 4).

        corp는 main(원본요약) 경로 projects/{corp}/baseline/…에서 뽑는다. source.metadata의
        origin staging 정보(staged_rel·filename)가 있고 staged 파일이 실재하면 origin 최종
        경로로 복사하고 staging을 제거한다. origin은 그래프 노드가 아니라 바인드 마운트 raw
        파일이다(documents 테이블/인덱스 미편입). 감사용 부가물이라 실패해도 apply를 막지 않는다.
        """
        corp = corp_from_path(main_path)
        if not corp:
            return
        source = await self._sources.get(source_id)
        origin = (source.metadata or {}).get("origin") if source is not None else None
        if not origin:
            return
        staged_rel = origin.get("staged_rel")
        filename = origin.get("filename")
        if not staged_rel or not filename or not self._root.exists(staged_rel):
            return
        dest = origin_final_path(corp, filename)
        if not dest:
            return
        try:
            self._root.write_bytes(dest, self._root.read_bytes(staged_rel))
            self._root.remove(staged_rel)
        except OSError:
            logger.warning("origin finalize failed source=%s corp=%s", source_id, corp)

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
        """생성 경로 거부 검증: 경로 컨벤션 + path allowlist / duplicate stem / 깨진 wikilink /
        up-without-body — main 초안과 파생 draft_markdown 모두."""
        errors: list[ApplyError] = []
        target_path = draft.get("target_path")
        markdown_full = draft.get("markdown_full")
        if not target_path or not markdown_full:
            return [ApplyError("DRAFT_NOT_READY", target_path)]

        resolver = await self._documents.build_resolver()

        # 1) 경로 검증 (root 안 + 컨벤션 디렉토리, PLAN-009-T-016).
        self._check_main_path(draft, errors)
        for suggestion in derived:
            self._check_derived_path(suggestion, resolver, errors)
            self._check_supplement_target(suggestion, resolver, errors)

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

        # 3) 깨진 wikilink / up-without-body — main 초안 + 파생 draft_markdown 모두(SPEC-005).
        self._check_body_links(markdown_full, resolver, plan_stems, errors)
        for suggestion in derived:
            content = suggestion.get("draft_markdown")
            if content:
                self._check_body_links(content, resolver, plan_stems, errors)
        return errors

    def _check_main_path(self, draft: dict, errors: list[ApplyError]) -> None:
        """main 초안 경로: root 안 + document_type별 허용 디렉토리."""
        path = draft.get("target_path")
        if not path or not self._root.is_within(path):
            errors.append(ApplyError("PATH_NOT_ALLOWED", path))
            return
        required = _MAIN_DIR_BY_TYPE.get(draft.get("document_type"))
        if required is not None and not path.startswith(required):
            errors.append(ApplyError("PATH_NOT_ALLOWED", path))

    def _check_supplement_target(
        self, suggestion: dict, resolver, errors: list[ApplyError]
    ) -> None:
        """supplement 대상은 concept만 허용한다 (PLAN-009-T-036).

        `supplement_existing_concept`가 reference/permanent/baseline을 보충 대상으로 고르면
        시맨틱 위반 — reference는 "출처 기록, 거의 고정" 정체성이고, concept 성장/stale 메커니즘을
        우회한다. index에서 대상을 resolve해 document_type≠concept이면 거부한다. resolve 실패는
        `_check_derived_path`가 PATH_NOT_ALLOWED로 이미 거른다(여기선 이중 표면화하지 않는다).
        """
        if suggestion.get("suggestion_type") != "supplement_existing_concept":
            return
        path = suggestion.get("target_path")
        if not path:
            return
        existing = resolver.resolve(stem_from_path(path))
        if existing is not None and existing.document_type != "concept":
            errors.append(ApplyError("SUPPLEMENT_TARGET_NOT_CONCEPT", path))

    def _check_derived_path(
        self, suggestion: dict, resolver, errors: list[ApplyError]
    ) -> None:
        """파생 경로: create는 suggestion_type별 디렉토리, modify는 index 실존 경로(신규 경로 금지)."""
        path = suggestion.get("target_path")
        if not path or not self._root.is_within(path):
            errors.append(ApplyError("PATH_NOT_ALLOWED", path))
            return
        if suggestion.get("change_kind") == "modify":
            # modify 대상은 index에 실존하는 문서의 기존 경로여야 한다.
            existing = resolver.resolve(stem_from_path(path))
            if existing is None or existing.path != path:
                errors.append(ApplyError("PATH_NOT_ALLOWED", path))
            return
        required = _DERIVED_DIR_BY_TYPE.get(suggestion.get("suggestion_type"))
        if required is not None and not path.startswith(required):
            errors.append(ApplyError("PATH_NOT_ALLOWED", path))

    @staticmethod
    def _check_body_links(
        markdown: str, resolver, plan_stems: set[str], errors: list[ApplyError]
    ) -> None:
        """본문 `[[ ]]`/`up:` 링크 검증(초안·파생 공통): 스냅샷/plan 밖 target 거부."""
        parsed = parse_markdown(markdown)
        body_targets = {link.target for link in parsed.wikilinks}
        for link in parsed.wikilinks:
            if resolver.resolve(link.target) is None and link.target not in plan_stems:
                errors.append(ApplyError("BROKEN_WIKILINK", link.target))
        for up in parsed.up:
            if up not in body_targets:
                errors.append(ApplyError("UP_WITHOUT_BODY_LINK", up))
            elif resolver.resolve(up) is None and up not in plan_stems:
                errors.append(ApplyError("BROKEN_WIKILINK", up))
