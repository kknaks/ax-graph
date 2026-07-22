"""plan-then-fanout ② — feature_spec context builder (AXKG-DEC-008 / WORK-012 P2).

handler_kind=`feature_spec`. plan 1개 기능 → 기능정의서 1장(document_draft). 작고 집중된
출력이라 600초로 충분하고 병렬·기능별 재시도가 된다(단일-task 타임아웃/거대출력 파싱실패 해소).

- 입력 블록: docx 원문(source.raw_text) + 이 task가 맡은 plan 항목(task.payload.plan_item) +
  원본요약 stem(up/연결용) + 연결 후보 컨텍스트(차용 링크 index 스냅샷, best-effort).
- 템플릿: `project_feature_spec`(기능정의서 뼈대, AXKG-SPEC-010) — select_template_key로 선택.
- handle_result: 검증 통과 출력(document_draft=기능정의서 1장)을 **이 task 자신의 payload**에
  보관한다(`feature_result`). fan-in 오케스트레이터가 gate의 기능 task들을 취합해 조립한다.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO
from axkg.dto.source import SourceDTO
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.context import ContextBuilder, ContextBuildError
from axkg.services.graph import GraphService
from axkg.services.qmd import QmdClient
from axkg.storage.markdown_root import MarkdownRoot

HANDLER_KIND = "feature_spec"
FEATURE_TEMPLATE_KEY = "project_feature_spec"
# task.payload에 기능 산출을 담는 키(fan-in 오케스트레이터가 읽는다).
FEATURE_RESULT_KEY = "feature_result"
PLAN_ITEM_KEY = "plan_item"
SOURCE_SUMMARY_STEM_KEY = "source_summary_stem"
# 기능 dedup(supplement) 배선용 payload 키 (AXKG-SPEC-014/DEC-007).
SUGGESTION_TYPE_KEY = "suggestion_type"
TARGET_STEM_KEY = "target_stem"
EXISTING_SPEC_MARKDOWN_KEY = "existing_spec_markdown"
SUPPLEMENT_FEATURE = "supplement_existing_feature"

_SOURCE_TEXT_CAP = 60_000
_RETRIEVER_TOP_N = 8


class FeatureSpecContextBuilder(ContextBuilder):
    """기능정의서 1장 데이터 블록 공급 + 기능 산출 task 보관."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        root: MarkdownRoot | None = None,
        qmd: QmdClient | None = None,
    ) -> None:
        self._sources = SourceRepository(session)
        self._tasks = AiTaskRepository(session)
        self._root = root or MarkdownRoot(settings.axkg_markdown_root)
        self._graph = GraphService(session, root=self._root, qmd=qmd)
        self.retriever_fallback_used: bool = False

    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        if task.source_id is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", "feature task에 source_id가 없습니다.")
        source = await self._sources.get(task.source_id)
        if source is None:
            raise ContextBuildError("SOURCE_NOT_FOUND", f"source 없음: {task.source_id}")
        plan_item = task.payload.get(PLAN_ITEM_KEY)
        if not plan_item:
            raise ContextBuildError(
                "PLAN_ITEM_MISSING", "feature task에 plan_item이 없습니다."
            )

        summary_stem = task.payload.get(SOURCE_SUMMARY_STEM_KEY)
        blocks: list[AssembledBlockDTO] = [
            self._plan_item_block(plan_item, summary_stem),
            self._source_text_block(source),
            await self._connection_block(plan_item),
        ]
        # 기능 dedup(supplement): 기존 기능정의서 전문을 주입해 병합·업그레이드를 지시한다.
        if task.payload.get(SUGGESTION_TYPE_KEY) == SUPPLEMENT_FEATURE:
            existing_md = task.payload.get(EXISTING_SPEC_MARKDOWN_KEY)
            if existing_md:
                blocks.append(self._supplement_block(existing_md))
        return blocks

    def select_template_key(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> str | None:
        return FEATURE_TEMPLATE_KEY

    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        """기능정의서 산출을 이 task 자신의 payload에 보관한다(fan-in이 취합)."""
        await self._tasks.merge_payload(task.id, {FEATURE_RESULT_KEY: output})

    # ------------------------------------------------------------------

    @staticmethod
    def _plan_item_block(plan_item: dict, summary_stem: str | None) -> AssembledBlockDTO:
        payload = {"assigned_feature": plan_item, "source_summary_stem": summary_stem}
        return AssembledBlockDTO(
            kind="data",
            label="plan_item",
            text=(
                "[이 task가 맡은 기능] 아래 한 기능에만 집중해 기능정의서 1장을 쓴다. "
                "`## 8. 연결`에는 원본요약(source_summary_stem)을 [[ ]]로 반드시 걸어라.\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        )

    @staticmethod
    def _source_text_block(source: SourceDTO) -> AssembledBlockDTO:
        text = (source.raw_text or "")[:_SOURCE_TEXT_CAP]
        return AssembledBlockDTO(
            kind="data",
            label="source_text",
            text="[원문(docx 텍스트 추출본)]\n" + text,
        )

    @staticmethod
    def _supplement_block(existing_md: str) -> AssembledBlockDTO:
        """기능 dedup — 기존 기능정의서 전문 주입 + 병합·업그레이드 규율(supplement_existing_concept 동형)."""
        return AssembledBlockDTO(
            kind="data",
            label="existing_feature_spec",
            text=(
                "[기존 기능정의서 전문 — 이 기능은 이미 존재한다] 이 회사에 이 기능정의서가 이미 "
                "있다. 아래 **기존 전문을 기준**으로, 새 docx 요구가 더한 상세(요구 배경·유저 플로우·"
                "상세 요구·수용 기준 등)를 **병합·보강한 업그레이드 전문**을 draft_markdown에 내라 "
                "(diff/patch가 아니라 수정된 전문 overwrite). **기존 내용을 보존**하고 새 요구만 "
                "합류시켜라 — 기존 서술을 함부로 삭제·축소하지 마라. frontmatter의 filename은 기존 "
                "stem을 그대로 유지하고, 더할 상세가 없으면 기존 전문을 실질적으로 유지한다.\n\n"
                + existing_md
            ),
        )

    async def _connection_block(self, plan_item: dict) -> AssembledBlockDTO:
        """차용 링크용 연결 후보(retriever index 스냅샷). best-effort — 실패해도 빈 스냅샷."""
        query = " ".join(
            str(x)
            for x in [plan_item.get("feature_name", ""), plan_item.get("summary", "")]
            if x
        )
        snapshot: list[dict] = []
        try:
            result = await self._graph.retrieve(query, top_n=_RETRIEVER_TOP_N)
            self.retriever_fallback_used = result.fallback_used
            snapshot = [
                {
                    "stem": e.stem,
                    "title": e.title,
                    "document_type": e.document_type,
                    "aliases": list(e.aliases),
                }
                for e in result.index_snapshot
            ]
        except Exception:  # noqa: BLE001 — 연결 후보는 품질 보조라 실패해도 생성은 계속.
            self.retriever_fallback_used = True
        return AssembledBlockDTO(
            kind="data",
            label="connection_candidates",
            text=(
                "[연결 후보 컨텍스트] `## 8. 연결`의 ax-graph 기존 역량 차용 링크는 아래 스냅샷 안의 "
                "stem/alias로만 만든다(스냅샷 밖 target 금지, 빈 [[ ]] 금지). 원본요약 링크는 위 "
                "plan_item의 source_summary_stem을 쓴다.\n"
                + json.dumps(snapshot, ensure_ascii=False, indent=2)
            ),
        )
