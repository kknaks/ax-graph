"""분류/문서화 게이트 lifecycle, feedback, revision 승인 (AXKG-SPEC-001/002/004). WP3 Phase 1.

이 Phase는 **분류 게이트(②)**를 실물로 만든다. 상태 기계는 AXKG-SPEC-002 §4/§5가 SSOT다:
게이트 생성 → review_pending → approved, 피드백 → regenerate(v2) → v1 superseded, 승인 immutable,
실패 → retry. 3층 상태(gate.status 사용자 표시 / revision.status 제안 버전 / ai_task.status
실행)를 섞지 않는다.

task 큐잉만 여기서(SourceService와 동일하게 AiTaskRepository + resolve_execution_config 직접
사용) 하고, open-kknaks 실행은 오케스트레이터(classification_gate_execution)가 background로 돈다.

Phase 2(WP3): 분류 승인 시 문서화 게이트를 **생성(generating) + 초안 task 큐잉**하고
(regenerate/retry도 gate_kind로 분기), 실행은 오케스트레이터(documentation_gate_execution)가
background로 돈다. 범위 제외: Apply Executor(Phase 3 — 승인→파일 확정·`documented` 전이),
재분류 재오픈(Phase 4). 문서화 게이트 approve→apply는 아직 하지 않는다(초안 생성·검토·재생성까지).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDTO
from axkg.dto.gate import (
    ApprovalGateDTO,
    ApprovalGateRevisionDTO,
    GateFeedbackDTO,
)
from axkg.repositories.ai_task_definitions import AiTaskDefinitionRepository
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.settings import SettingRepository
from axkg.repositories.sources import SourceRepository
from axkg.repositories.stale import StaleMarkRepository
from axkg.config import settings
from axkg.services.ai.classification_gate import empty_classification_payload
from axkg.services.ai.documentation_gate import empty_documentation_payload
from axkg.services.ai.resolution import resolve_execution_config
from axkg.services.ai.feature_spec import PLAN_ITEM_KEY
from axkg.services.ai.plan_project import PLAN_OUTPUT_KEY
from axkg.services.ai.source_summary import INTAKE_NOTE_KEY
from axkg.services.plan_fanout_execution import (
    FEATURE_TASK_TYPE,
    _latest_by_seq,
    compute_fanout_progress,
)
from axkg.services.project_scaffold import (
    SUBTYPE_CONTEXT,
    list_project_corps,
    resolve_corp,
    resolve_project_subtype,
)
from axkg.services.summary_archive import write_summary_archive
from axkg.storage.markdown_root import MarkdownRoot
from axkg.workers.apply_executor import ApplyExecutor, ApplyValidationError

GATE_KIND_CLASSIFICATION = "classification"
GATE_KIND_DOCUMENTATION = "documentation"
GENERATE_TASK = "generate_classification_gate"
REGENERATE_TASK = "regenerate_classification_gate"
GENERATE_DOC_TASK = "generate_documentation_gate"
REGENERATE_DOC_TASK = "regenerate_documentation_gate"
# plan-then-fanout (AXKG-DEC-008/WORK-012): project 문서화는 단일 task 대신 plan_project로
# 시작한다(→ fan-out 기능 task → fan-in 조립). generate/regenerate 모두 plan_project를 쓴다.
PLAN_PROJECT_TASK = "plan_project"
FEATURE_SPEC_TASK = "generate_feature_spec"
CLASSIFICATION_FORM_VERSION = "classification.v1"
DOCUMENTATION_FORM_VERSION = "documentation.v1"
AI_PROVIDER_SETTINGS_KEY = "ai_provider"

FEEDBACK_MIN_LENGTH = 10
FEEDBACK_MAX_LENGTH = 4000

# stale 재생성 주입 전문 cap(문자). 문서당 소형 컨텍스트 유지(SPEC-004 §E-3) — 초과 시 truncated.
_STALE_MARKDOWN_CAP = 8000

# 승인 destination이 문서화 게이트로 이어지지 않는 종료 목적지(AXKG-SPEC-001 U-3).
ARCHIVE_DESTINATION = "archive"
# 회사 프로젝트 팬아웃 destination(AXKG-SPEC-014, WP11). corp 바인딩 대상.
PROJECT_DESTINATION = "project"

# 분류 파생 라벨(Inbox 큐 라벨) 매핑 — AXKG-SPEC-001 §Verification 매핑표가 SSOT.
# DB에 저장하지 않는 파생값이다(sources.status + 분류 게이트 상태 조합).
_CLASSIFY_PENDING_GATE_STATUSES = ("generating", "review_pending", "feedback_pending")


# 문서화 게이트 표시 상태(파생) 매핑 — AXKG-SPEC-004 State/Lifecycle 표가 SSOT.
# 저장 SSOT는 공통 approval_gates.status. 표시 라벨은 새 저장 상태를 만들지 않는다.
_DOCUMENTATION_STATUS_LABELS = {
    "not_started": "draft_generating",
    "generating": "draft_generating",
    "regenerating": "draft_generating",
    "review_pending": "draft_ready",
    "feedback_pending": "feedback_submitted",
    "failed": "failed",
    "cancelled": "reclassification_requested",
    "approved": "approved",
}


def derive_documentation_status(gate_status: str) -> str | None:
    """문서화 게이트 저장 status → UI 표시 상태(파생, AXKG-SPEC-004 매핑표)."""
    return _DOCUMENTATION_STATUS_LABELS.get(gate_status)


def derive_inbox_label(
    source_status: str, classification_gate_status: str | None
) -> str | None:
    """summarized source + 분류 게이트 상태 → Inbox 큐 라벨(AXKG-SPEC-001 매핑표).

    매핑되지 않는 조합(게이트 없음/failed/not_started/cancelled, summarized 아님)은 None —
    임의 라벨을 발명하지 않는다. 문서화 라벨(doc_*)은 Phase 2 소관이라 여기서 만들지 않는다.
    """
    if source_status != "summarized" or classification_gate_status is None:
        return None
    if classification_gate_status in _CLASSIFY_PENDING_GATE_STATUSES:
        return "classify_pending"
    if classification_gate_status == "regenerating":
        return "classify_regenerating"
    if classification_gate_status == "approved":
        return "classify_approved"
    return None


# ---------------------------------------------------------------------------
# 에러 (Case Matrix — AXKG-SPEC-002/001)
# ---------------------------------------------------------------------------


class GateNotFoundError(Exception):
    def __init__(self, gate_id: uuid.UUID) -> None:
        super().__init__(f"approval_gate not found: {gate_id}")
        self.gate_id = gate_id


class SourceNotSummarizedError(Exception):
    """summarized가 아닌 source에 분류 게이트 생성 (Case Matrix: CLASSIFICATION_NOT_ALLOWED)."""

    def __init__(self, source_id: uuid.UUID, status: str) -> None:
        super().__init__(f"classification not allowed: source {source_id} status={status}")
        self.source_id = source_id
        self.status = status


class FeedbackTooShortError(Exception):
    """피드백 길이 부족 (Case Matrix: FEEDBACK_TOO_SHORT)."""


class GateAlreadyApprovedError(Exception):
    """승인된 게이트 수정 시도 (Case Matrix: GATE_ALREADY_APPROVED)."""

    def __init__(self, gate_id: uuid.UUID) -> None:
        super().__init__(f"gate already approved: {gate_id}")
        self.gate_id = gate_id


class StaleGateVersionError(Exception):
    """오래된 버전 승인 시도 / active revision이 승인 가능 상태가 아님 (Case Matrix: STALE_GATE_VERSION)."""


class GateRetryNotAllowedError(Exception):
    """재시도 불가 상태 (Case Matrix: RETRY_NOT_ALLOWED)."""

    def __init__(self, gate_id: uuid.UUID, status: str) -> None:
        super().__init__(f"retry not allowed: gate {gate_id} status={status}")
        self.gate_id = gate_id
        self.status = status


class FeatureRetryNotAllowedError(Exception):
    """기능 재시도 불가 — 대상 seq 기능 task가 없거나 failed가 아님 (plan-then-fanout, WORK-012)."""

    def __init__(self, gate_id: uuid.UUID, seq: int) -> None:
        super().__init__(f"feature retry not allowed: gate {gate_id} seq={seq}")
        self.gate_id = gate_id
        self.seq = seq


class DraftMarkdownNotFoundError(Exception):
    """초안 markdown 전문 없음 (Case Matrix: DRAFT_MARKDOWN_NOT_FOUND)."""

    def __init__(self, source_id: uuid.UUID, draft_version: int) -> None:
        super().__init__(
            f"draft markdown not found: source {source_id} v{draft_version}"
        )
        self.source_id = source_id
        self.draft_version = draft_version


class NotThisDestinationReasonMissingError(Exception):
    """"이 destination이 아님" 피드백에 이유 누락 (Case Matrix: MISSING_NOT_THIS_DESTINATION_REASON)."""


class ReclassificationNotAllowedError(Exception):
    """재분류 재오픈 불가 상태: 대상이 문서화 게이트가 아니거나 분류 게이트가 approved가 아님.

    (SPEC-004 Validation: 대상 게이트가 문서화 게이트이고 그 source의 분류 게이트가 approved.
    전용 Case Matrix 코드는 없어 RECLASSIFICATION_NOT_ALLOWED로 표면화 — 리포트 OQ 참조.)
    """

    def __init__(self, gate_id: uuid.UUID, reason: str) -> None:
        super().__init__(f"reclassification not allowed: gate {gate_id} ({reason})")
        self.gate_id = gate_id
        self.reason = reason


class StaleDocumentNotFoundError(Exception):
    """stale 재생성 대상 문서 없음 (Case Matrix: DOCUMENT_NOT_FOUND)."""

    def __init__(self, document_id: uuid.UUID) -> None:
        super().__init__(f"document not found: {document_id}")
        self.document_id = document_id


class StaleRegenerationNotAllowedError(Exception):
    """stale 재생성 불가: 대상이 permanent가 아니거나 producing source/문서화 게이트가 없다.

    (SPEC-004 §E: 재생성 게이트는 그 permanent의 producing source 기준 문서화 게이트
    재문서화 경로를 재사용한다. 전용 Case Matrix 코드는 없어 STALE_REGENERATION_NOT_ALLOWED로
    표면화 — 리포트 OQ 참조.)
    """

    def __init__(self, document_id: uuid.UUID, reason: str) -> None:
        super().__init__(f"stale regeneration not allowed: doc {document_id} ({reason})")
        self.document_id = document_id
        self.reason = reason


# ---------------------------------------------------------------------------
# 결과 컨테이너
# ---------------------------------------------------------------------------


class GateTaskResult:
    """게이트 + 대상 revision + queued ai_task (생성/재생성/재시도 공통)."""

    def __init__(
        self,
        gate: ApprovalGateDTO,
        revision: ApprovalGateRevisionDTO,
        ai_task: AiTaskDTO,
    ) -> None:
        self.gate = gate
        self.revision = revision
        self.ai_task = ai_task


class FeedbackResult:
    def __init__(self, gate: ApprovalGateDTO, feedback: GateFeedbackDTO) -> None:
        self.gate = gate
        self.feedback = feedback


class ApproveResult:
    """분류 승인 결과 — 확정 destination + (해당 시) 생성·큐잉된 문서화 게이트.

    documentation_task는 문서화 초안 생성을 위해 큐잉된 task(+게이트/revision)다. 라우트가
    이걸 background(execute_documentation_gate)로 스케줄링한다(WP3 Phase 2). archive면 None.
    """

    def __init__(
        self,
        gate: ApprovalGateDTO,
        *,
        destination_type: str,
        archived: bool,
        documentation_gate: ApprovalGateDTO | None,
        documentation_task: "GateTaskResult | None" = None,
    ) -> None:
        self.gate = gate
        self.destination_type = destination_type
        self.archived = archived
        self.documentation_gate = documentation_gate
        self.documentation_task = documentation_task


class ReclassificationResult:
    """재분류 재오픈 결과 — cancelled된 문서화 게이트 + 재오픈·재생성 큐잉된 분류 게이트.

    classification_task는 분류 게이트를 다시 regenerating으로 만들고 재분류 이유를 반영한 v2
    revision + regenerate_classification_gate task를 큐잉한 것이다. 라우트가 이걸
    background(execute_classification_gate)로 스케줄링한다(regenerate 경로 재사용).
    """

    def __init__(
        self,
        *,
        documentation_gate: ApprovalGateDTO,
        classification_task: "GateTaskResult",
    ) -> None:
        self.documentation_gate = documentation_gate
        self.classification_task = classification_task


class DocumentationGateView:
    """문서화 게이트 조회 뷰(AXKG-SPEC-004 Data Contract) — ApprovalGate(documentation) 파생.

    status는 저장 status가 아니라 표시 상태(파생 라벨)다. destination_type은 source 확정값.
    """

    def __init__(
        self,
        gate: ApprovalGateDTO,
        *,
        source_id: uuid.UUID,
        destination_type: str | None,
        display_status: str | None,
        active_revision: ApprovalGateRevisionDTO | None,
    ) -> None:
        self.gate = gate
        self.source_id = source_id
        self.destination_type = destination_type
        self.display_status = display_status
        self.active_revision = active_revision


class GateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._gates = GateRepository(session)
        self._sources = SourceRepository(session)
        self._tasks = AiTaskRepository(session)
        self._definitions = AiTaskDefinitionRepository(session)
        self._settings = SettingRepository(session)
        self._docs = DocumentRepository(session)
        self._stale = StaleMarkRepository(session)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    async def get_gate(self, gate_id: uuid.UUID) -> ApprovalGateDTO:
        gate = await self._gates.get_gate(gate_id)
        if gate is None:
            raise GateNotFoundError(gate_id)
        return gate

    async def derive_inbox_labels(self, sources: list) -> dict[uuid.UUID, str | None]:
        """source 목록의 Inbox 큐 라벨을 분류 게이트 상태와 조합해 파생 계산한다(batch).

        DB에 저장하지 않는 파생값(AXKG-SPEC-001 매핑표). 게이트가 없는 source는 None.
        """
        ids = [s.id for s in sources]
        gates = await self._gates.list_gates_by_sources_and_kind(
            ids, GATE_KIND_CLASSIFICATION
        )
        by_source = {g.source_id: g.status for g in gates}
        return {
            s.id: derive_inbox_label(s.status, by_source.get(s.id)) for s in sources
        }

    async def get_active_revision(
        self, gate: ApprovalGateDTO
    ) -> ApprovalGateRevisionDTO | None:
        if gate.active_revision_id is None:
            return None
        return await self._gates.get_revision(gate.active_revision_id)

    async def list_gates(
        self, source_id: uuid.UUID
    ) -> list[tuple[ApprovalGateDTO, list[ApprovalGateRevisionDTO]]]:
        """source의 게이트 + 각 게이트 revision 목록(버전 badge용)."""
        gates = await self._gates.list_gates_by_source(source_id)
        result: list[tuple[ApprovalGateDTO, list[ApprovalGateRevisionDTO]]] = []
        for gate in gates:
            revisions = await self._gates.list_revisions_by_gate(gate.id)
            result.append((gate, revisions))
        return result

    # ------------------------------------------------------------------
    # 문서화 게이트 조회 뷰 (GET /documentation-gates)
    # ------------------------------------------------------------------

    async def list_documentation_gates(self) -> list[DocumentationGateView]:
        """project/area/resource 승인 source의 문서화 게이트 목록(조회 전용 뷰)."""
        gates = await self._gates.list_gates_by_kind(GATE_KIND_DOCUMENTATION)
        views: list[DocumentationGateView] = []
        for gate in gates:
            source = await self._sources.get(gate.source_id)
            active = await self.get_active_revision(gate)
            views.append(
                DocumentationGateView(
                    gate,
                    source_id=gate.source_id,
                    destination_type=source.destination_type if source else None,
                    display_status=derive_documentation_status(gate.status),
                    active_revision=active,
                )
            )
        return views

    async def get_documentation_draft_markdown(
        self, source_id: uuid.UUID, draft_version: int
    ) -> str:
        """초안 `.md` 전문 조회(document_draft.markdown_full). 없으면 DRAFT_MARKDOWN_NOT_FOUND."""
        gate = await self._gates.get_gate_by_source_and_kind(
            source_id, GATE_KIND_DOCUMENTATION
        )
        if gate is None:
            raise DraftMarkdownNotFoundError(source_id, draft_version)
        for revision in await self._gates.list_revisions_by_gate(gate.id):
            if revision.version != draft_version:
                continue
            form = revision.payload.get("form") or {}
            markdown = (form.get("document_draft") or {}).get("markdown_full")
            if markdown:
                return markdown
            raise DraftMarkdownNotFoundError(source_id, draft_version)
        raise DraftMarkdownNotFoundError(source_id, draft_version)

    # ------------------------------------------------------------------
    # 분류 게이트 생성 (POST /sources/{id}/classification-gates)
    # ------------------------------------------------------------------

    async def create_classification_gate(
        self, source_id: uuid.UUID
    ) -> GateTaskResult:
        """summarized source에 분류 게이트 + 첫 revision 생성 + generate task 큐잉.

        source.status는 `summarized` 그대로 둔다(파생 라벨만 바뀜, SPEC-001 매핑표). 이미
        분류 게이트가 있고 승인됐으면 GATE_ALREADY_APPROVED, 그 외에는 다음 버전 revision을
        새로 만들어 재생성한다.
        """
        source = await self._sources.get(source_id)
        if source is None:
            raise GateNotFoundError(source_id)
        if source.status != "summarized":
            raise SourceNotSummarizedError(source_id, source.status)

        # 요약 확정 지점(정정 모델 첫째 md 생성, PLAN-009-T-014): [분류]로 넘기는 이 순간에
        # active summary 버전을 요약 보관 md로 확정 생성한다(보관용 side-output, 그래프 무관).
        await self._write_summary_archive(source)

        gate = await self._gates.get_gate_by_source_and_kind(
            source_id, GATE_KIND_CLASSIFICATION
        )
        if gate is None:
            gate = await self._gates.create_gate(
                source_id=source_id,
                gate_kind=GATE_KIND_CLASSIFICATION,
                status="not_started",
            )
        elif gate.status == "approved":
            raise GateAlreadyApprovedError(gate.id)

        version = await self._gates.next_version(gate.id)
        revision = await self._gates.create_revision(
            gate_id=gate.id,
            version=version,
            status="drafting",
            payload=empty_classification_payload(source),
            form_schema_version="classification.v1",
        )
        task = await self._enqueue_task(
            GENERATE_TASK,
            source_id=source_id,
            gate_id=gate.id,
            revision_id=revision.id,
        )
        revision = await self._gates.update_revision(revision.id, ai_task_id=task.id)
        gate = await self._gates.update_gate(
            gate.id,
            status="generating",
            active_revision_id=revision.id,
            last_ai_task_id=task.id,
        )
        return GateTaskResult(gate, revision, task)

    # ------------------------------------------------------------------
    # feedback (POST /gates/{id}/feedback)
    # ------------------------------------------------------------------

    async def submit_feedback(
        self, gate_id: uuid.UUID, *, body: str
    ) -> FeedbackResult:
        """피드백 저장 + gate review_pending→feedback_pending. 승인된 게이트는 거부."""
        gate = await self.get_gate(gate_id)
        if gate.status == "approved":
            raise GateAlreadyApprovedError(gate_id)

        text = (body or "").strip()
        if len(text) < FEEDBACK_MIN_LENGTH or len(text) > FEEDBACK_MAX_LENGTH:
            raise FeedbackTooShortError

        target_revision_id = gate.active_revision_id
        if target_revision_id is None:
            # 검토할 active revision이 없으면 피드백 대상이 없다(재시도로 다시 생성해야 함).
            raise StaleGateVersionError
        feedback = await self._gates.create_feedback(
            gate_id=gate_id,
            target_revision_id=target_revision_id,
            body=text,
        )
        gate = await self._gates.update_gate(gate_id, status="feedback_pending")
        return FeedbackResult(gate, feedback)

    # ------------------------------------------------------------------
    # 재분류 재오픈 ("이 destination이 아님", POST /gates/{doc_id}/feedback 확장)
    # ------------------------------------------------------------------

    async def request_reclassification(
        self, doc_gate_id: uuid.UUID, *, reason: str
    ) -> ReclassificationResult:
        """문서화 게이트 "이 destination이 아님" 피드백 → 분류 게이트 재오픈 (SPEC-002 §5 / SPEC-004 S-3).

        원자적 전이(한 트랜잭션):
        - 분류 게이트: status `approved → regenerating`(유일 예외 전이), `approved_revision_id` 해제.
        - 기존 approved 분류 revision: 내용 불변으로 `superseded` 마킹.
        - source: `destination_type`·`approved_classification_gate_id` 리셋(null).
        - 문서화 게이트: `cancelled`(표시 상태 reclassification_requested).
        - 재분류 이유를 담은 새 분류 revision(v_next) 생성 + `regenerate_classification_gate`
          task 큐잉(regenerate 경로 재사용 — 이유를 feedback/context로 전달, resume 세션 승계).

        거부:
        - 이유 누락 → MISSING_NOT_THIS_DESTINATION_REASON.
        - 대상이 문서화 게이트가 아님 / 분류 게이트가 approved 아님 → RECLASSIFICATION_NOT_ALLOWED.
        - 이미 승인(apply 완료)된 문서화 게이트 → GATE_ALREADY_APPROVED.
        """
        doc_gate = await self.get_gate(doc_gate_id)
        if doc_gate.gate_kind != GATE_KIND_DOCUMENTATION:
            raise ReclassificationNotAllowedError(doc_gate_id, "not_documentation_gate")
        if doc_gate.status == "approved":
            raise GateAlreadyApprovedError(doc_gate_id)

        text = (reason or "").strip()
        if not text:
            raise NotThisDestinationReasonMissingError

        cls_gate = await self._gates.get_gate_by_source_and_kind(
            doc_gate.source_id, GATE_KIND_CLASSIFICATION
        )
        if (
            cls_gate is None
            or cls_gate.status != "approved"
            or cls_gate.approved_revision_id is None
        ):
            raise ReclassificationNotAllowedError(doc_gate_id, "classification_not_approved")
        approved_rev = await self._gates.get_revision(cls_gate.approved_revision_id)
        if approved_rev is None:
            raise ReclassificationNotAllowedError(doc_gate_id, "classification_not_approved")

        source = await self._require_source(cls_gate.source_id)

        # 재분류 이유를 분류 게이트 feedback으로 감사 기록(대상=기존 approved revision).
        feedback = await self._gates.create_feedback(
            gate_id=cls_gate.id,
            target_revision_id=approved_rev.id,
            body=text,
            payload={
                "kind": "not_this_destination",
                "not_this_destination_reason": text,
                "documentation_gate_id": str(doc_gate_id),
            },
        )

        # 기존 approved 분류 revision: 내용 불변으로 superseded 마킹(payload 수정 금지).
        await self._gates.update_revision(approved_rev.id, status="superseded")

        # source destination 확정 리셋.
        await self._sources.reset_classification(cls_gate.source_id)

        # 문서화 게이트 cancelled(감사 이력 보존, 표시 상태 reclassification_requested).
        doc_gate = await self._gates.update_gate(doc_gate_id, status="cancelled")

        # 재분류 이유를 담은 새 분류 revision(v_next) + regenerate task(regenerate 경로 재사용).
        resume_session = await self._resolve_resume_session(approved_rev)
        version = await self._gates.next_version(cls_gate.id)
        revision = await self._gates.create_revision(
            gate_id=cls_gate.id,
            version=version,
            status="drafting",
            payload=empty_classification_payload(source),
            form_schema_version=CLASSIFICATION_FORM_VERSION,
            parent_revision_id=approved_rev.id,
            feedback_id=feedback.id,
        )
        task = await self._enqueue_task(
            REGENERATE_TASK,
            source_id=cls_gate.source_id,
            gate_id=cls_gate.id,
            revision_id=revision.id,
            feedback=text,
            prior_payload=approved_rev.payload,
            resume_session=resume_session,
            resume_of_task_id=approved_rev.ai_task_id,
            payload_kind="classification",
            extra_payload={"reclassification": True},
        )
        revision = await self._gates.update_revision(revision.id, ai_task_id=task.id)
        await self._gates.consume_feedback(feedback.id)
        cls_gate = await self._gates.update_gate(
            cls_gate.id,
            status="regenerating",
            active_revision_id=revision.id,
            last_ai_task_id=task.id,
            clear_approved_revision=True,
        )
        return ReclassificationResult(
            documentation_gate=doc_gate,
            classification_task=GateTaskResult(cls_gate, revision, task),
        )

    # ------------------------------------------------------------------
    # regenerate (POST /gates/{id}/regenerate)
    # ------------------------------------------------------------------

    async def regenerate(self, gate_id: uuid.UUID) -> GateTaskResult:
        """제출된 feedback을 consume하고 새 revision v(n+1) + regenerate task를 큐잉한다.

        resume 세션은 open-kknaks Session Rule 순서로 계산(target revision session →
        그 revision의 ai_task session → 둘 다 없으면 stateless). gate feedback_pending→regenerating.
        """
        gate = await self.get_gate(gate_id)
        if gate.status == "approved":
            raise GateAlreadyApprovedError(gate_id)

        feedback = await self._gates.get_latest_submitted_feedback(gate_id)
        if feedback is None:
            # 재생성하려면 소비할 피드백이 필요하다(피드백 없이 온 재생성은 최신 재확인 필요).
            raise StaleGateVersionError
        target_revision = await self._gates.get_revision(feedback.target_revision_id)
        if target_revision is None:
            raise StaleGateVersionError

        source = await self._require_source(gate.source_id)
        spec = self._gate_kind_spec(gate.gate_kind, source)
        resume_session = await self._resolve_resume_session(target_revision)
        version = await self._gates.next_version(gate_id)
        revision = await self._gates.create_revision(
            gate_id=gate_id,
            version=version,
            status="drafting",
            payload=spec["empty_payload"],
            form_schema_version=spec["form_schema_version"],
            parent_revision_id=target_revision.id,
            feedback_id=feedback.id,
        )
        task = await self._enqueue_task(
            spec["regenerate"],
            source_id=gate.source_id,
            gate_id=gate_id,
            revision_id=revision.id,
            feedback=feedback.body,
            prior_payload=target_revision.payload,
            resume_session=resume_session,
            resume_of_task_id=target_revision.ai_task_id,
            payload_kind=spec["payload_kind"],
            extra_payload=spec["extra_payload"],
        )
        revision = await self._gates.update_revision(revision.id, ai_task_id=task.id)
        await self._gates.consume_feedback(feedback.id)
        gate = await self._gates.update_gate(
            gate_id,
            status="regenerating",
            active_revision_id=revision.id,
            last_ai_task_id=task.id,
        )
        return GateTaskResult(gate, revision, task)

    # ------------------------------------------------------------------
    # stale 재생성 게이트 오픈 (POST /documents/{id}/regenerate, SPEC-004 §E)
    # ------------------------------------------------------------------

    async def open_stale_regeneration(
        self, document_id: uuid.UUID
    ) -> GateTaskResult:
        """stale permanent의 재생성 게이트를 열고 재생성 task를 큐잉한다(SPEC-004 §E-3/E-4).

        그 permanent의 producing source 기준 문서화 게이트의 재문서화 경로(v++)를 재사용한다:
        새 revision(v_next) + `regenerate_documentation_gate` task. task payload에 stale 주입
        (대상 permanent 전문 + 바뀐 concept 전문 + 변경 요지, E-3 3입력)을 실어 context builder가
        재생성 초안을 만들게 한다. 이후 리뷰/피드백/승인은 기존 게이트 계약 그대로다.

        1 문서 = 1 재생성 게이트. 일괄 판단/일괄 실행 없음(E-3/E-4). 반영은 자동이 아니라
        사용자 승인(approve→Apply Executor)이 하며, 승인 apply가 stale을 해제한다.
        """
        doc = await self._docs.get(document_id)
        if doc is None:
            raise StaleDocumentNotFoundError(document_id)
        if doc.document_type != "permanent":
            raise StaleRegenerationNotAllowedError(document_id, "not_permanent")
        if doc.source_id is None:
            raise StaleRegenerationNotAllowedError(document_id, "no_producing_source")

        doc_gate = await self._gates.get_gate_by_source_and_kind(
            doc.source_id, GATE_KIND_DOCUMENTATION
        )
        if doc_gate is None:
            raise StaleRegenerationNotAllowedError(document_id, "no_documentation_gate")

        source = await self._require_source(doc.source_id)
        destination_type = source.destination_type or "area"
        stale_injection = await self._build_stale_injection(doc)

        parent_id = doc_gate.approved_revision_id or doc_gate.active_revision_id
        version = await self._gates.next_version(doc_gate.id)
        revision = await self._gates.create_revision(
            gate_id=doc_gate.id,
            version=version,
            status="drafting",
            payload=empty_documentation_payload(source, destination_type),
            form_schema_version=DOCUMENTATION_FORM_VERSION,
            parent_revision_id=parent_id,
        )
        task = await self._enqueue_task(
            REGENERATE_DOC_TASK,
            source_id=doc.source_id,
            gate_id=doc_gate.id,
            revision_id=revision.id,
            payload_kind="documentation",
            extra_payload={
                "destination_type": destination_type,
                "stale_regeneration": stale_injection,
            },
        )
        revision = await self._gates.update_revision(revision.id, ai_task_id=task.id)
        doc_gate = await self._gates.update_gate(
            doc_gate.id,
            status="regenerating",
            active_revision_id=revision.id,
            last_ai_task_id=task.id,
        )
        # 재생성 시작 → source를 완료 탭에서 꺼내 승인 탭으로 재노출한다(확정 UX, T-017).
        # documented는 visible_in_inbox=false + FE inTab이 승인 탭에서 하드 제외하므로, 최초
        # 문서화 리뷰와 동일한 상태(summarized + visible)로 되돌린다 — 분류 게이트는 approved
        # 그대로라 inbox_label=classify_approved가 파생돼 승인 탭에 걸린다(새 상태/라벨 발명 없음).
        # v2 승인 시 기존 _approve_documentation→mark_documented가 다시 documented로 되돌린다.
        await self._sources.set_status(doc.source_id, "summarized")
        return GateTaskResult(doc_gate, revision, task)

    async def _build_stale_injection(self, doc) -> dict:
        """E-3 입력 계약: 대상 permanent 전문 + 바뀐 concept 전문 + 변경 요지(문서당 3입력)."""
        root = MarkdownRoot(settings.axkg_markdown_root)
        target_markdown = self._read_capped(root, doc.path)
        changed_concepts: list[dict] = []
        for mark in await self._stale.list_active_for_document(doc.id):
            concept_path = mark.concept_path
            if concept_path is None:
                concept = await self._docs.get_by_stem(mark.concept_stem)
                concept_path = concept.path if concept is not None else None
            changed_concepts.append(
                {
                    "stem": mark.concept_stem,
                    "path": concept_path,
                    "change_summary": mark.change_summary,
                    "markdown": (
                        self._read_capped(root, concept_path) if concept_path else ""
                    ),
                }
            )
        return {
            "target_document": {
                "path": doc.path,
                "title": doc.title,
                "markdown": target_markdown,
            },
            "changed_concepts": changed_concepts,
        }

    @staticmethod
    def _read_capped(root: MarkdownRoot, path: str) -> str:
        if not path or not root.exists(path):
            return ""
        try:
            text = root.read_text(path)
        except OSError:
            return ""
        if len(text) > _STALE_MARKDOWN_CAP:
            return text[:_STALE_MARKDOWN_CAP] + "\n… (truncated)"
        return text

    # ------------------------------------------------------------------
    # approve (POST /gates/{id}/approve)
    # ------------------------------------------------------------------

    async def approve(
        self, gate_id: uuid.UUID, *, expected_revision_id: uuid.UUID | None = None
    ) -> ApproveResult:
        """최신 active revision(reviewable)을 승인하고 분류 부수효과를 적용한다.

        - active revision이 아닌 오래된 버전 승인은 STALE_GATE_VERSION.
        - 이미 승인된 게이트는 GATE_ALREADY_APPROVED.
        - active revision reviewable→approved, gate review_pending→approved,
          approved_revision_id 설정(gate당 1개, immutable).
        - destination 확정: source.destination_type·approved_classification_gate_id.
          archive → source archived(종료). project/area/resource → 문서화 게이트 컨테이너만 생성.
        """
        gate = await self.get_gate(gate_id)
        if gate.status == "approved":
            raise GateAlreadyApprovedError(gate_id)
        active_id = gate.active_revision_id
        if active_id is None:
            raise StaleGateVersionError
        if expected_revision_id is not None and expected_revision_id != active_id:
            raise StaleGateVersionError

        revision = await self._gates.get_revision(active_id)
        if revision is None or revision.status != "reviewable":
            raise StaleGateVersionError

        # 문서화 게이트 승인은 Apply Executor로 위임한다(WP3 Phase 3): 초안 확정 write +
        # index + 엣지 rebuild + source documented + 게이트/revision approved.
        if gate.gate_kind == GATE_KIND_DOCUMENTATION:
            return await self._approve_documentation(gate, revision)

        destination_type = (revision.payload.get("form") or {}).get("destination_type")
        if not destination_type:
            raise StaleGateVersionError

        await self._gates.update_revision(active_id, status="approved", approved=True)
        # 승인 안전망: 병렬 누적된 형제 reviewable이 남아 있으면 전부 superseded (dangling
        # 방지, SPEC-002 §5/§7 OQ). handle_result sweep으로 이미 정리됐으면 no-op.
        await self._gates.supersede_other_reviewable_revisions(
            gate_id, keep_revision_id=active_id
        )
        gate = await self._gates.update_gate(
            gate_id, status="approved", approved_revision_id=active_id
        )

        archived = destination_type == ARCHIVE_DESTINATION
        await self._sources.set_classification_destination(
            gate.source_id,
            destination_type=destination_type,
            gate_id=gate_id,
            archived=archived,
        )

        documentation_gate: ApprovalGateDTO | None = None
        documentation_task: GateTaskResult | None = None
        if not archived:
            # Phase 2: 문서화 게이트를 생성(generating)하고 초안 생성 task를 큐잉한다.
            # (SPEC-004 "초안은 분류 승인 시 함께 생성" — 별도 수동 트리거 없음.)
            source = await self._require_source(gate.source_id)
            documentation_gate = await self._gates.get_gate_by_source_and_kind(
                gate.source_id, GATE_KIND_DOCUMENTATION
            )
            if documentation_gate is None:
                documentation_gate = await self._gates.create_gate(
                    source_id=gate.source_id,
                    gate_kind=GATE_KIND_DOCUMENTATION,
                    status="not_started",
                )
            documentation_task = await self._start_documentation_gate(
                documentation_gate, source, destination_type
            )
            documentation_gate = documentation_task.gate
        return ApproveResult(
            gate,
            destination_type=destination_type,
            archived=archived,
            documentation_gate=documentation_gate,
            documentation_task=documentation_task,
        )

    async def _start_documentation_gate(
        self, gate: ApprovalGateDTO, source, destination_type: str
    ) -> GateTaskResult:
        """문서화 게이트 첫 revision(drafting) + 생성 task 큐잉 → gate generating.

        destination_type을 task.payload에 실어 보내 context builder가 destination→template을
        선택하게 한다. **project는 plan-then-fanout**(AXKG-DEC-008): 단일 문서화 task 대신
        plan_project task로 시작해 이후 기능 task 병렬 발주·fan-in 조립으로 이어진다(오케스트레이터
        `execute_plan_then_fanout`). resource/area는 종전 단일 generate_documentation_gate.
        """
        version = await self._gates.next_version(gate.id)
        revision = await self._gates.create_revision(
            gate_id=gate.id,
            version=version,
            status="drafting",
            payload=empty_documentation_payload(source, destination_type),
            form_schema_version=DOCUMENTATION_FORM_VERSION,
        )
        # project 요구사항 → plan-then-fanout(plan_project). project context(WORK-013) 및
        # 비-project → 단일 generate_documentation_gate(context는 단일 문서, 팬아웃 없음).
        is_requirement_fanout = (
            destination_type == PROJECT_DESTINATION
            and not self._is_context_project(destination_type, source)
        )
        task_type = PLAN_PROJECT_TASK if is_requirement_fanout else GENERATE_DOC_TASK
        task = await self._enqueue_task(
            task_type,
            source_id=source.id,
            gate_id=gate.id,
            revision_id=revision.id,
            payload_kind="documentation",
            extra_payload=self._documentation_extra_payload(destination_type, source),
        )
        revision = await self._gates.update_revision(revision.id, ai_task_id=task.id)
        gate = await self._gates.update_gate(
            gate.id,
            status="generating",
            active_revision_id=revision.id,
            last_ai_task_id=task.id,
        )
        return GateTaskResult(gate, revision, task)

    # ------------------------------------------------------------------
    # retry (POST /gates/{id}/retry)
    # ------------------------------------------------------------------

    async def retry(self, gate_id: uuid.UUID) -> GateTaskResult:
        """failed gate + 마지막 ai_task failed일 때만 재시도. 새 revision + 새 ai_task.

        기존 failed task/revision은 감사 이력으로 보존한다. 재생성 맥락(feedback 연결)이면
        gate→regenerating, 최초 생성 맥락이면 gate→generating.
        """
        gate = await self.get_gate(gate_id)
        if gate.status != "failed" or gate.last_ai_task_id is None:
            raise GateRetryNotAllowedError(gate_id, gate.status)
        failed_task = await self._tasks.get(gate.last_ai_task_id)
        if failed_task is None or failed_task.status != "failed":
            raise GateRetryNotAllowedError(gate_id, gate.status)

        # 실패한 revision을 참조해 재생성 맥락을 이어간다(parent/feedback/resume 승계).
        failed_revision = (
            await self._gates.get_revision(failed_task.revision_id)
            if failed_task.revision_id
            else None
        )
        is_regenerate = failed_task.task_type in (REGENERATE_TASK, REGENERATE_DOC_TASK)
        source = await self._require_source(gate.source_id)
        spec = self._gate_kind_spec(gate.gate_kind, source)
        version = await self._gates.next_version(gate_id)
        parent_revision_id = (
            failed_revision.parent_revision_id if failed_revision else None
        )
        feedback_id = failed_revision.feedback_id if failed_revision else None
        revision = await self._gates.create_revision(
            gate_id=gate_id,
            version=version,
            status="drafting",
            payload=spec["empty_payload"],
            form_schema_version=spec["form_schema_version"],
            parent_revision_id=parent_revision_id,
            feedback_id=feedback_id,
        )

        resume_session = None
        feedback_body = None
        prior_payload = None
        if is_regenerate and parent_revision_id is not None:
            parent = await self._gates.get_revision(parent_revision_id)
            if parent is not None:
                resume_session = await self._resolve_resume_session(parent)
                prior_payload = parent.payload
            feedback_body = failed_task.payload.get("feedback")

        task = await self._enqueue_task(
            failed_task.task_type,
            source_id=gate.source_id,
            gate_id=gate_id,
            revision_id=revision.id,
            retry_of_task_id=failed_task.id,
            retry_count=failed_task.retry_count + 1,
            feedback=feedback_body,
            prior_payload=prior_payload,
            resume_session=resume_session,
            resume_of_task_id=parent_revision_id,
            payload_kind=spec["payload_kind"],
            extra_payload=spec["extra_payload"],
        )
        revision = await self._gates.update_revision(revision.id, ai_task_id=task.id)
        gate = await self._gates.update_gate(
            gate_id,
            status="regenerating" if is_regenerate else "generating",
            active_revision_id=revision.id,
            last_ai_task_id=task.id,
        )
        return GateTaskResult(gate, revision, task)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _require_source(self, source_id: uuid.UUID):
        source = await self._sources.get(source_id)
        if source is None:
            raise GateNotFoundError(source_id)
        return source

    def _documentation_extra_payload(self, destination_type: str, source) -> dict:
        """문서화 task payload extra: destination_type + (project면) corp 바인딩 (WP11 Phase 4).

        분류 project 확정 시 intake 메모(sources.metadata[intake_note])의 회사명을 기존
        `projects/{corp}/`에 매칭해 corp를 payload에 싣는다 → context builder가 팬아웃 경로
        (baseline/·spec/)를 조립한다. 매칭 프로젝트가 없으면 corp를 싣지 않아 팬아웃하지 않는다
        (프로젝트 선행 생성 전제 — 자동 생성 금지, AXKG-DEC-007). MarkdownRoot 미마운트여도
        조용히 skip한다(corp 없이 flat).
        """
        extra: dict = {"destination_type": destination_type}
        if destination_type != PROJECT_DESTINATION:
            return extra
        memo = (source.metadata or {}).get(INTAKE_NOTE_KEY)
        try:
            corps = list_project_corps(MarkdownRoot(settings.axkg_markdown_root))
        except OSError:
            corps = []
        corp = resolve_corp(memo, corps)
        if corp:
            extra["corp"] = corp
        # project 하위 sub-type(WORK-013 P2): 메모 성격 힌트로 requirement/context 판정.
        # context → 단일 context 문서 경로, requirement → 기존 plan-then-fanout.
        extra["project_subtype"] = resolve_project_subtype(memo)
        return extra

    def _is_context_project(self, destination_type: str, source) -> bool:
        """project + context sub-type인지(단일 문서 경로 라우팅용, WORK-013)."""
        if destination_type != PROJECT_DESTINATION:
            return False
        memo = (source.metadata or {}).get(INTAKE_NOTE_KEY)
        return resolve_project_subtype(memo) == SUBTYPE_CONTEXT

    # ------------------------------------------------------------------
    # plan-then-fanout — 진행률 + 기능 단위 재시도 (AXKG-DEC-008/WORK-012)
    # ------------------------------------------------------------------

    async def get_fanout_progress(self, gate_id: uuid.UUID) -> dict | None:
        """project 문서화 게이트의 기능 생성 진행률(N개 중 M완료·부분 실패). plan 없으면 None.

        상태 노출용(P4) — UI는 후속. plan_output(revision) + 기능 task 상태로 파생 계산한다.
        """
        gate = await self.get_gate(gate_id)
        revision = await self.get_active_revision(gate)
        if revision is None:
            return None
        plan_output = (revision.payload or {}).get(PLAN_OUTPUT_KEY)
        if not plan_output:
            return None
        plan = plan_output.get("plan") or []
        feature_tasks = await self._tasks.list_by_gate(gate_id, FEATURE_TASK_TYPE)
        return compute_fanout_progress(plan, _latest_by_seq(feature_tasks))

    async def retry_feature(self, gate_id: uuid.UUID, seq: int) -> GateTaskResult:
        """실패한 기능정의서(seq) 하나만 재시도 큐잉한다(11개 통째 재생성 아님).

        대상 seq의 최신 기능 task가 failed일 때만 허용한다. 실패 task는 불변 보존하고
        retry_of_task_id로 연결된 새 queued task를 만든다(plan_item·corp payload 승계). 실행은
        오케스트레이터 `execute_feature_retry`가 background로 돈다(끝나면 revision 재조립).
        """
        gate = await self.get_gate(gate_id)
        if gate.status == "approved":
            raise GateAlreadyApprovedError(gate_id)
        revision = await self.get_active_revision(gate)
        if revision is None:
            raise FeatureRetryNotAllowedError(gate_id, seq)
        feature_tasks = await self._tasks.list_by_gate(gate_id, FEATURE_TASK_TYPE)
        latest = _latest_by_seq(feature_tasks)
        target = latest.get(int(seq))
        if target is None or target.status != "failed":
            raise FeatureRetryNotAllowedError(gate_id, seq)

        definition = await self._definitions.get_by_key(FEATURE_TASK_TYPE)
        if definition is None or not definition.enabled:
            raise LookupError(f"ai_task_definition missing: {FEATURE_TASK_TYPE}")
        global_settings = await self._settings.get_value(AI_PROVIDER_SETTINGS_KEY)
        config = resolve_execution_config(global_settings, definition)
        # 실패 task payload에서 실행 재료만 승계(plan_item/stem/corp) — snapshot 잡음은 뺀다.
        prior = target.payload or {}
        payload = {
            "kind": "feature_spec",
            PLAN_ITEM_KEY: prior.get(PLAN_ITEM_KEY),
            "source_summary_stem": prior.get("source_summary_stem"),
            "corp": prior.get("corp"),
            "destination_type": "project",
        }
        task = await self._tasks.create(
            task_type=FEATURE_TASK_TYPE,
            task_definition_id=definition.id,
            provider=config.provider,
            model=config.model,
            options=config.options,
            provider_options=config.provider_options,
            source_id=target.source_id,
            gate_id=gate_id,
            revision_id=revision.id,
            retry_of_task_id=target.id,
            retry_count=target.retry_count + 1,
            payload=payload,
        )
        gate = await self._gates.update_gate(gate_id, status="generating")
        return GateTaskResult(gate, revision, task)

    async def _write_summary_archive(self, source) -> None:
        """요약 확정 시 active summary 버전을 요약 보관 md로 확정 생성한다(PLAN-009-T-014).

        active summary revision이 없으면(백필 전 데이터) 조용히 건너뛴다 — DB가 SoT다.
        markdown root 미provision(테스트/미마운트)이면 writer가 스스로 skip한다.
        """
        active = await self._sources.get_active_summary_revision(source.id)
        if active is None:
            return
        write_summary_archive(
            MarkdownRoot(settings.axkg_markdown_root), source, active
        )

    async def _approve_documentation(
        self, gate: ApprovalGateDTO, revision: ApprovalGateRevisionDTO
    ) -> ApproveResult:
        """문서화 게이트 승인 → Apply Executor 실행(초안 확정 + documented, WP3 Phase 3).

        검증 실패(경로/깨진 링크/duplicate)는 apply하지 않고 `ApplyValidationError`로 표면화한다
        (라우트가 Case Matrix 에러코드로 매핑). 성공하면 revision/gate approved + source documented.
        """
        executor = ApplyExecutor(
            self._session, MarkdownRoot(settings.axkg_markdown_root)
        )
        await executor.apply(gate, revision)
        gate = await self.get_gate(gate.id)
        source = await self._require_source(gate.source_id)
        return ApproveResult(
            gate,
            destination_type=source.destination_type or "",
            archived=False,
            documentation_gate=gate,
            documentation_task=None,
        )

    def _gate_kind_spec(self, gate_kind: str, source) -> dict:
        """gate_kind별 재생성/재시도 조립 스펙(task type·form 버전·빈 payload·payload kind).

        documentation은 destination_type을 payload에 실어(template 선택용) 보낸다. 분류는
        Phase 1과 동일하게 유지한다(회귀 방지).
        """
        if gate_kind == GATE_KIND_DOCUMENTATION:
            destination_type = source.destination_type or "resource"
            # project 요구사항은 plan-then-fanout(AXKG-DEC-008): 재생성/재시도도 plan_project로
            # 시작해 다시 fan-out·fan-in한다. project context(WORK-013)·resource/area는 종전 단일
            # generate/regenerate_documentation_gate.
            is_fanout = destination_type == PROJECT_DESTINATION and not (
                self._is_context_project(destination_type, source)
            )
            return {
                "generate": PLAN_PROJECT_TASK if is_fanout else GENERATE_DOC_TASK,
                "regenerate": PLAN_PROJECT_TASK if is_fanout else REGENERATE_DOC_TASK,
                "form_schema_version": DOCUMENTATION_FORM_VERSION,
                "empty_payload": empty_documentation_payload(source, destination_type),
                "payload_kind": "documentation",
                "extra_payload": self._documentation_extra_payload(
                    destination_type, source
                ),
            }
        return {
            "generate": GENERATE_TASK,
            "regenerate": REGENERATE_TASK,
            "form_schema_version": CLASSIFICATION_FORM_VERSION,
            "empty_payload": empty_classification_payload(source),
            "payload_kind": "classification",
            "extra_payload": {},
        }

    async def _resolve_resume_session(
        self, target_revision: ApprovalGateRevisionDTO
    ) -> str | None:
        """AXKG-SPEC-002 open-kknaks Session Rule: revision session → ai_task session → None."""
        if target_revision.open_kknaks_session_id:
            return target_revision.open_kknaks_session_id
        if target_revision.ai_task_id is not None:
            task = await self._tasks.get(target_revision.ai_task_id)
            if task is not None:
                return task.open_kknaks_session_id
        return None

    async def _enqueue_task(
        self,
        task_type: str,
        *,
        source_id: uuid.UUID,
        gate_id: uuid.UUID,
        revision_id: uuid.UUID,
        retry_of_task_id: uuid.UUID | None = None,
        retry_count: int = 0,
        feedback: str | None = None,
        prior_payload: dict | None = None,
        resume_session: str | None = None,
        resume_of_task_id: uuid.UUID | None = None,
        payload_kind: str = "classification",
        extra_payload: dict | None = None,
    ) -> AiTaskDTO:
        """게이트 ai_task 큐잉(SourceService 미러링) — 실행 설정은 생성 시점 스냅샷.

        재생성/재시도(feedback 있음)면 resume 세션을 options.resume에 배선하고 payload에
        feedback·이전 payload(stateless fallback용)를 남긴다(AXKG-SPEC-011 Resume Wiring).
        `extra_payload`(예: 문서화 destination_type)는 항상 payload에 병합한다 — context
        builder가 template 선택 등에 쓴다.
        """
        definition = await self._definitions.get_by_key(task_type)
        if definition is None or not definition.enabled:
            raise LookupError(f"ai_task_definition missing: {task_type}")
        global_settings = await self._settings.get_value(AI_PROVIDER_SETTINGS_KEY)
        config = resolve_execution_config(global_settings, definition)

        options = dict(config.options)
        payload: dict = {}
        if feedback is not None:
            payload["kind"] = f"{payload_kind}_feedback"
            payload["feedback"] = feedback
            payload["prior_payload"] = prior_payload or {}
            payload["resume_of_task_id"] = (
                str(resume_of_task_id) if resume_of_task_id else None
            )
            if resume_session:
                # open-kknaks claude executor 계약: options.resume={mode:session, session_id}.
                options["resume"] = {"mode": "session", "session_id": resume_session}
        else:
            payload["kind"] = payload_kind
        if extra_payload:
            payload.update(extra_payload)

        return await self._tasks.create(
            task_type=task_type,
            task_definition_id=definition.id,
            provider=config.provider,
            model=config.model,
            options=options,
            provider_options=config.provider_options,
            source_id=source_id,
            gate_id=gate_id,
            revision_id=revision_id,
            retry_of_task_id=retry_of_task_id,
            retry_count=retry_count,
            payload=payload,
        )
