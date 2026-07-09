"""documentation-gates API 응답 (AXKG-SPEC-004 조회 전용 뷰).

DocumentationGate는 독립 리소스가 아니라 ApprovalGate(gate_kind=documentation)의 조회 뷰다
(액션은 공통 게이트 API `/gates/{id}/*`를 쓴다). FE(Phase 4)가 이 계약을 소비한다.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel

from axkg.schemas.gates import RevisionResponse
from axkg.services.gates import DocumentationGateView


class DocumentationGateResponse(BaseModel):
    gate_id: uuid.UUID
    source_id: uuid.UUID
    gate_kind: str
    destination_type: str | None = None
    # 표시 상태(파생): draft_generating/draft_ready/feedback_submitted/failed/
    # reclassification_requested/approved. 저장 SSOT는 공통 approval_gates.status.
    status: str | None = None
    active_revision_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    active_revision: RevisionResponse | None = None

    @classmethod
    def from_view(cls, view: DocumentationGateView) -> "DocumentationGateResponse":
        return cls(
            gate_id=view.gate.id,
            source_id=view.source_id,
            gate_kind=view.gate.gate_kind,
            destination_type=view.destination_type,
            status=view.display_status,
            active_revision_id=view.gate.active_revision_id,
            created_at=view.gate.created_at,
            updated_at=view.gate.updated_at,
            active_revision=(
                RevisionResponse.from_dto(view.active_revision)
                if view.active_revision is not None
                else None
            ),
        )


class DocumentationGateListResponse(BaseModel):
    documentation_gates: list[DocumentationGateResponse]


class DraftMarkdownResponse(BaseModel):
    """초안 `.md` 전문 (document_draft.markdown_full)."""

    source_id: uuid.UUID
    draft_version: int
    markdown: str
