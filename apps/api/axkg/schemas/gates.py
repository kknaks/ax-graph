"""approval gates API 요청/응답 (AXKG-SPEC-002/001 Interface Contract).

FE(profile-fe, Phase 4)가 이 계약으로 승인 화면을 구현한다 — 응답 스키마를 스펙과 다르게
임의 발명하지 않는다. dto(내부)↔schema(API) 분리(코드 규칙).
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from axkg.dto.gate import ApprovalGateDTO, ApprovalGateRevisionDTO


class RevisionResponse(BaseModel):
    """AI 제안 버전(revision). payload는 classification.v1 envelope."""

    id: uuid.UUID
    gate_id: uuid.UUID
    version: int
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    form_schema_version: str
    parent_revision_id: uuid.UUID | None = None
    feedback_id: uuid.UUID | None = None
    ai_task_id: uuid.UUID | None = None
    created_at: datetime
    approved_at: datetime | None = None

    @classmethod
    def from_dto(cls, dto: ApprovalGateRevisionDTO) -> "RevisionResponse":
        return cls(
            id=dto.id,
            gate_id=dto.gate_id,
            version=dto.version,
            status=dto.status,
            payload=dto.payload,
            form_schema_version=dto.form_schema_version,
            parent_revision_id=dto.parent_revision_id,
            feedback_id=dto.feedback_id,
            ai_task_id=dto.ai_task_id,
            created_at=dto.created_at,
            approved_at=dto.approved_at,
        )


class GateResponse(BaseModel):
    """게이트 묶음 + (선택) active revision·revision 목록.

    FE는 status로 폴링하고 active_revision.payload로 카드를 렌더한다. revisions는
    버전 badge/비교용(목록 조회에서만 채운다).
    """

    id: uuid.UUID
    source_id: uuid.UUID
    gate_kind: str
    status: str
    active_revision_id: uuid.UUID | None = None
    approved_revision_id: uuid.UUID | None = None
    last_ai_task_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    active_revision: RevisionResponse | None = None
    revisions: list[RevisionResponse] | None = None

    @classmethod
    def from_dto(
        cls,
        dto: ApprovalGateDTO,
        *,
        active_revision: ApprovalGateRevisionDTO | None = None,
        revisions: list[ApprovalGateRevisionDTO] | None = None,
    ) -> "GateResponse":
        return cls(
            id=dto.id,
            source_id=dto.source_id,
            gate_kind=dto.gate_kind,
            status=dto.status,
            active_revision_id=dto.active_revision_id,
            approved_revision_id=dto.approved_revision_id,
            last_ai_task_id=dto.last_ai_task_id,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
            active_revision=(
                RevisionResponse.from_dto(active_revision)
                if active_revision is not None
                else None
            ),
            revisions=(
                [RevisionResponse.from_dto(r) for r in revisions]
                if revisions is not None
                else None
            ),
        )


class GateListResponse(BaseModel):
    gates: list[GateResponse]


class FeedbackRequest(BaseModel):
    """피드백 저장 입력. 길이(10~4000) 검증은 서비스가 FEEDBACK_TOO_SHORT로 신호한다.

    문서화 게이트(③)의 "이 destination이 아님" 재분류 요청(SPEC-004 U-4)은 같은 엔드포인트를
    확장한다: `not_this_destination=true` + `not_this_destination_reason`(필수)이면 서비스가
    분류 게이트 재오픈 흐름(SPEC-002 §5)으로 라우팅한다. 일반 피드백은 `body`만 쓴다.
    """

    body: str | None = None
    not_this_destination: bool = False
    not_this_destination_reason: str | None = None


class ApproveRequest(BaseModel):
    """승인 입력. revision_id를 주면 최신 active revision과 다를 때 STALE_GATE_VERSION."""

    revision_id: uuid.UUID | None = None
