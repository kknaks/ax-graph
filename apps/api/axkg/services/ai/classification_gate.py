"""분류 게이트 ② context builder (AXKG-SPEC-001 U-3 / SPEC-002 / SPEC-011 §Stage). WP3 Phase 1.

handler_kind=`classification_gate`. `SourceSummaryContextBuilder`를 미러링한다.

- 입력: source의 `summary_payload`만 런타임 데이터 블록으로 공급한다. **그래프 컨텍스트 없음**
  (연결 후보/retriever/index 스냅샷은 문서화 게이트 ③ 소관, AXKG-SPEC-001 §5). PARA 분류 "방법"
  지침(`para-classification.md`)은 worker 실행 workspace의 프로젝트 context 소관 — api가 파일로
  로드하지 않는다(요약 스테이지와 동일 실행 모델).
- feedback 재생성: resume 세션이 원문·요약·이전 payload 컨텍스트를 이미 보유하므로 feedback
  블록만 공급한다. resume 세션이 없으면(stateless) source 요약 + 이전 payload + feedback을
  모두 인라인한다(AXKG-SPEC-002 open-kknaks Session Rule 3단).
- `handle_result`: 스키마 통과 출력(classification.v1 form)을 공통 envelope로 감싸 대상 revision
  payload에 저장하고 revision `drafting→reviewable`, gate `generating/regenerating→review_pending`,
  직전 active revision은 `superseded`, revision·gate 포인터/세션 id를 갱신한다.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO
from axkg.dto.source import SourceDTO
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.context import ContextBuilder, ContextBuildError

HANDLER_KIND = "classification_gate"
FORM_SCHEMA_VERSION = "classification.v1"

# classification.v1 form에 담는 필드(AXKG-SPEC-002 Approval Gate Payload Schema). envelope
# 공통 필드(schema_version/gate_kind/source_id/summary/confidence/warnings)는 코드가 감싼다.
_FORM_FIELDS = (
    "destination_type",
    "destination_reason",
    "suggested_title",
    "suggested_tags",
    "source_type",
    "confidence",
)


def _summary_block(source: SourceDTO) -> dict[str, Any]:
    """envelope.summary — UI 카드 상단 요약 정보(AXKG-SPEC-002)."""
    payload = source.summary_payload or {}
    return {
        "title": payload.get("title", ""),
        "source_url": source.source_url,
        "source_summary": payload.get("summary", ""),
    }


def empty_classification_payload(source: SourceDTO) -> dict[str, Any]:
    """AI 결과 저장 전 placeholder envelope(payload NOT NULL 충족)."""
    return {
        "schema_version": FORM_SCHEMA_VERSION,
        "gate_kind": "classification",
        "source_id": str(source.id),
        "summary": _summary_block(source),
        "form": {},
        "warnings": [],
    }


def wrap_classification_output(
    source: SourceDTO, output: dict[str, Any]
) -> dict[str, Any]:
    """스키마 통과 출력을 classification.v1 공통 envelope로 감싼다(SPEC-002)."""
    form = {k: output[k] for k in _FORM_FIELDS if k in output}
    return {
        "schema_version": FORM_SCHEMA_VERSION,
        "gate_kind": "classification",
        "source_id": str(source.id),
        "summary": {
            "title": output.get("suggested_title")
            or (source.summary_payload or {}).get("title", ""),
            "source_url": source.source_url,
            "source_summary": output.get("source_summary")
            or (source.summary_payload or {}).get("summary", ""),
        },
        "form": form,
        "confidence": output.get("confidence"),
        "warnings": output.get("warnings", []),
    }


class ClassificationGateContextBuilder(ContextBuilder):
    """분류 스테이지 데이터 블록 공급 + revision payload 소비.

    session 바인딩 handler다. 실행 1회마다 그 실행의 session으로 생성한다. 그래프 컨텍스트는
    공급하지 않는다(연결은 문서화 게이트 소관).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._sources = SourceRepository(session)
        self._gates = GateRepository(session)

    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        if task.source_id is None:
            raise ContextBuildError(
                "SOURCE_NOT_FOUND", "분류 task에 source_id가 없습니다."
            )
        source = await self._sources.get(task.source_id)
        if source is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", f"source 없음: {task.source_id}")

        feedback = task.payload.get("feedback")
        if feedback:
            resume = task.options.get("resume")
            if resume:
                # 세션 resume: 원문·요약·이전 payload 재전송 없이 피드백만(토큰 절약).
                return [self._feedback_block(str(feedback))]
            # stateless fallback: source 요약 + 이전 payload + feedback 모두 인라인.
            prior_payload = task.payload.get("prior_payload")
            return [
                self._summary_data_block(source),
                self._prior_payload_block(prior_payload),
                self._feedback_block(str(feedback)),
            ]

        # 최초 생성: source 요약 payload만 데이터로 공급(그래프 컨텍스트 없음).
        return [self._summary_data_block(source)]

    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        """검증 통과 출력을 envelope로 감싸 revision에 저장하고 상태를 전이한다."""
        if task.revision_id is None or task.gate_id is None:
            raise ContextBuildError(
                "GATE_CONTEXT_MISSING", "분류 task에 gate_id/revision_id가 없습니다."
            )
        source = await self._sources.get(task.source_id) if task.source_id else None
        if source is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", "분류 결과 저장 대상 source 없음.")

        revision = await self._gates.get_revision(task.revision_id)
        if revision is None:
            raise ContextBuildError(
                "REVISION_NOT_FOUND", f"revision 없음: {task.revision_id}"
            )

        envelope = wrap_classification_output(source, output)
        # 이 revision을 reviewable로 올리기 전에, 같은 gate의 다른 모든 reviewable 형제를
        # superseded로 sweep한다(SPEC-002 §5, "최신 하나만 active/reviewable"). 빠른 연속
        # 재생성으로 v2·v3가 병렬 완료돼도 parent 단건 supersede로는 중간 버전이 잔존해
        # dangling이 생겼다(§7 OQ, 2026-07-10 라이브 실측). drafting인 이 revision 자신은
        # 아직 reviewable이 아니라 sweep 대상이 아니지만, keep으로 명시해 안전을 보장한다.
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
    def _summary_data_block(source: SourceDTO) -> AssembledBlockDTO:
        payload = {
            "source_url": source.source_url,
            "summary": source.summary_payload or {},
        }
        return AssembledBlockDTO(
            kind="data",
            label="summary_payload",
            text=(
                "[분류 대상 source 요약]\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        )

    @staticmethod
    def _prior_payload_block(prior_payload: Any) -> AssembledBlockDTO:
        return AssembledBlockDTO(
            kind="data",
            label="prior_classification",
            text=(
                "[직전 분류 제안(v1)]\n"
                + json.dumps(prior_payload or {}, ensure_ascii=False, indent=2)
            ),
        )

    @staticmethod
    def _feedback_block(feedback: str) -> AssembledBlockDTO:
        return AssembledBlockDTO(
            kind="data",
            label="feedback",
            text=(
                "이전 분류 제안에 대한 사용자 피드백이다. 이 세션은 source 요약과 직전 분류 "
                "컨텍스트를 이미 보유하고 있으니 원문을 다시 요청하지 말고, 아래 피드백을 반영해 "
                "PARA destination 분류를 개정하라. 출력 JSON 스키마는 직전과 동일하게 유지한다.\n\n"
                f"[사용자 피드백]\n{feedback}"
            ),
        )
