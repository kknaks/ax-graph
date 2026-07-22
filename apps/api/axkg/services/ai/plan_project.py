"""plan-then-fanout ① — plan_project context builder (AXKG-DEC-008 / WORK-012 P1).

handler_kind=`plan_project`. docx 원문 + 요약 → **원본요약(main) + 기능목록(plan)** 산출.
plan = `[{seq, feature_name, filename_candidate, summary}]` × N이 곧 fan-out 발주서다.
무거운 기능정의서 본문은 여기서 만들지 않는다(그건 ② generate_feature_spec).

- 입력 블록: 요약 payload + docx 원문(source.raw_text, 텍스트 추출본) + intake 메모(요약 컨텍스트).
- 템플릿: `project_source_summary`(원본요약 뼈대, AXKG-SPEC-010) — select_template_key로 선택.
- handle_result: 검증 통과 출력(document_draft=원본요약 + plan)을 **revision payload에 보관**한다
  (`plan_output`). 게이트/ revision 상태는 여기서 바꾸지 않는다 — fan-in 오케스트레이터가
  기능 task 발주·조립·상태 전이를 담당한다(gate는 generating 유지).
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO
from axkg.dto.source import SourceDTO
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.context import ContextBuilder, ContextBuildError
from axkg.services.project_scaffold import corp_feature_specs

CORP_KEY = "corp"

HANDLER_KIND = "plan_project"
PLAN_TEMPLATE_KEY = "project_source_summary"
# revision.payload에 plan 산출을 담는 키(fan-in 오케스트레이터가 읽는다).
PLAN_OUTPUT_KEY = "plan_output"

# docx 원문 주입 상한(문자). 요약 stage 수집 상한과 정합(단일 실행 컨텍스트 유지).
_SOURCE_TEXT_CAP = 60_000


class PlanProjectContextBuilder(ContextBuilder):
    """plan 산출 데이터 블록 공급 + plan 출력 revision 보관."""

    def __init__(self, session: AsyncSession) -> None:
        self._sources = SourceRepository(session)
        self._gates = GateRepository(session)
        self._docs = DocumentRepository(session)

    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        if task.source_id is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", "plan task에 source_id가 없습니다.")
        source = await self._sources.get(task.source_id)
        if source is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", f"source 없음: {task.source_id}")

        blocks: list[AssembledBlockDTO] = [self._summary_block(source)]
        note = (source.metadata or {}).get("intake_note")
        if note:
            blocks.append(
                AssembledBlockDTO(
                    kind="data",
                    label="intake_note",
                    text="[인박스 메모] 회사명 등 원문 밖 힌트:\n" + str(note),
                )
            )
        blocks.append(self._source_text_block(source))
        # 회사 내부 기능 dedup(AXKG-SPEC-014/DEC-007): 같은 corp에 이미 있는 기능정의서를
        # 주입해, 새 요구 중 기존 기능과 같은 것은 그 stem을 재사용하도록 유도한다(신규 중복 방지).
        existing_block = await self._existing_features_block(task.payload.get(CORP_KEY))
        if existing_block is not None:
            blocks.append(existing_block)
        return blocks

    async def _existing_features_block(
        self, corp: str | None
    ) -> AssembledBlockDTO | None:
        if not corp:
            return None
        existing = corp_feature_specs(await self._docs.list_all(), corp)
        if not existing:
            return None
        listed = [
            {"filename_candidate": v["stem"], "feature_name": v["title"]}
            for v in existing.values()
        ]
        return AssembledBlockDTO(
            kind="data",
            label="existing_corp_features",
            text=(
                "[이 회사에 이미 있는 기능(같은 corp)] 아래는 이 회사 프로젝트에 이미 존재하는 "
                "기능정의서 목록이다. 새 요구를 기능으로 분해할 때, **기존 기능과 같은 기능이면 그 "
                "filename_candidate(stem)를 그대로 재사용**하라(새 stem을 만들지 마라 — 시스템이 그 "
                "기존 문서를 업그레이드한다). 기존에 없는 새 기능만 새 stem을 만든다. 부서가 달라도 "
                "같은 기능이면 하나로 본다(기능 카탈로그, 부서 무관).\n"
                + json.dumps(listed, ensure_ascii=False, indent=2)
            ),
        )

    def select_template_key(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> str | None:
        return PLAN_TEMPLATE_KEY

    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        """plan 산출(원본요약 + plan)을 revision payload에 보관한다(상태 전이는 오케스트레이터)."""
        if task.revision_id is None:
            raise ContextBuildError("GATE_CONTEXT_MISSING", "plan task에 revision_id가 없습니다.")
        revision = await self._gates.get_revision(task.revision_id)
        if revision is None:
            raise ContextBuildError("REVISION_NOT_FOUND", f"revision 없음: {task.revision_id}")
        payload = dict(revision.payload or {})
        payload[PLAN_OUTPUT_KEY] = output
        await self._gates.update_revision(
            task.revision_id,
            payload=payload,
            open_kknaks_session_id=task.open_kknaks_session_id,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _summary_block(source: SourceDTO) -> AssembledBlockDTO:
        payload = {
            "source_url": source.source_url,
            "summary": source.summary_payload or {},
        }
        return AssembledBlockDTO(
            kind="data",
            label="summary_payload",
            text="[요약 payload]\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        )

    @staticmethod
    def _source_text_block(source: SourceDTO) -> AssembledBlockDTO:
        """docx 원문(텍스트 추출본, source.raw_text). 기능 분해의 1차 근거."""
        text = (source.raw_text or "")[:_SOURCE_TEXT_CAP]
        return AssembledBlockDTO(
            kind="data",
            label="source_text",
            text="[원문(docx 텍스트 추출본)]\n" + text,
        )
