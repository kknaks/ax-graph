"""요약 스테이지 ① context builder (AXKG-SPEC-011 S-1 / SPEC-012 / SPEC-003). WP1 Phase 3.

handler_kind=`source_summary`. 파이프라인(pipeline.py)에 등록되어 실행된다.

- 입력: source URL + `SourceMaterial`(AXKG-SPEC-012 `collect_source(url)`)을 **런타임 데이터
  블록으로만** 공급한다. 요약 "방법" 지침(`source-summary-guide.md`)은 worker 실행 workspace의
  프로젝트 context가 담당한다 — api는 파일로 로드하지 않는다(PLAN-005-T-008 실행 모델 재설계).
- 수집 실패(`CollectionError`)는 `ContextBuildError`로 변환 → 파이프라인이 task 실패로
  보존(SPEC-011 Case Matrix). source는 오케스트레이터가 `collection_failed`로 표면화한다.
- 출력(`title`/`summary`/`keywords`/`source_type`)이 스키마 검증을 통과하면 `handle_result`가
  `sources.summary_payload`에 저장하고 source를 `summarized`로 전이한다.
- 긴 원문은 chunk로 나눠 한 번의 실행에서 각 chunk를 요약·병합하도록 블록을 구성한다
  (SPEC-011 Implementation Rules: chunk 요약 병합). content_text는 수집 계층에서 이미
  `MAX_CONTENT_LENGTH`로 상한이 잡혀 있어 단일 실행 컨텍스트에 담긴다.
- 원문 전문은 application log에 남기지 않는다(SPEC-012 Security And Limits).
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO
from axkg.dto.source_material import SourceMaterial
from axkg.integrations.source_collection import CollectionError, collect_source
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.context import ContextBuilder, ContextBuildError

HANDLER_KIND = "source_summary"

# 단일 실행 컨텍스트에 담는 chunk 한 조각의 최대 길이(문자). 초과 원문은 여러 chunk
# 블록으로 나눠 한 번의 요약 실행에서 병합하도록 지시한다. 수집 상한(200_000)보다 작다.
MAX_CHUNK_CHARS = 60_000

# collect_source(url, *, user_note=...)이 반환하는 SourceMaterial 수집 실패의 실행측 코드
# 통로. CollectionError.code(AXKG-SPEC-012 Failure Contract)를 그대로 실어 표면화한다.
# user_note는 원문 수집 실패 시 메모로 요약하는 최종 fallback 입력(PLAN-005-T-013).
CollectFn = Callable[..., Awaitable[SourceMaterial]]


# ---------------------------------------------------------------------------
# chunk 유틸 (SPEC-011 Implementation Rules: 긴 원문 chunk 요약 병합)
# ---------------------------------------------------------------------------


def chunk_content(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """원문을 max_chars 이하 조각으로 나눈다. 문단 경계를 우선 보존한다.

    한 문단이 max_chars를 넘으면 그 문단만 강제로 잘라 나눈다. 빈 입력은 [""].
    """
    if not text:
        return [""]
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        piece = para if not current else f"{current}\n\n{para}"
        if len(piece) <= max_chars:
            current = piece
            continue
        if current:
            chunks.append(current)
            current = ""
        # 단일 문단이 상한을 넘으면 하드 분할.
        while len(para) > max_chars:
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        current = para
    if current:
        chunks.append(current)
    return chunks


def merge_chunk_summaries(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """chunk별 요약 payload를 하나로 병합한다 (동일 output_schema).

    - title: 첫 chunk의 title
    - summary: chunk 요약을 순서대로 이어붙임
    - body_markdown: chunk별 장문 정리본을 원문 순서대로 "\n\n"로 이어붙임(빈 값 스킵)
    - keywords: 순서 보존 중복 제거 후 최대 10개(스키마 상한)
    - source_type: 최빈값(동률이면 첫 등장)
    빈 목록은 빈 요약 payload를 만들지 않고 호출측이 검증하도록 그대로 둔다.
    """
    if not payloads:
        return {}
    if len(payloads) == 1:
        return dict(payloads[0])

    keywords: list[str] = []
    for payload in payloads:
        for kw in payload.get("keywords", []):
            if kw not in keywords:
                keywords.append(kw)

    counts: dict[str, int] = {}
    for payload in payloads:
        st = payload.get("source_type")
        if st:
            counts[st] = counts.get(st, 0) + 1
    source_type = max(counts, key=lambda k: counts[k]) if counts else "unknown"

    return {
        "title": payloads[0].get("title", ""),
        "summary": "\n\n".join(
            p.get("summary", "") for p in payloads if p.get("summary")
        ),
        "body_markdown": "\n\n".join(
            p.get("body_markdown", "") for p in payloads if p.get("body_markdown")
        ),
        "keywords": keywords[:10],
        "source_type": source_type,
    }


# ---------------------------------------------------------------------------
# context builder
# ---------------------------------------------------------------------------


class SourceSummaryContextBuilder(ContextBuilder):
    """요약 스테이지 데이터 블록 공급 + summary_payload 소비.

    session 바인딩 handler다. 파이프라인 실행 1회마다 그 실행의 session으로 생성한다
    (registry 자체는 앱 수명이 아니라 실행 수명). `collect`는 테스트에서 fake를 주입한다.

    이 builder는 **런타임 데이터(SourceMaterial 원문)만** 블록으로 공급한다. 요약 "방법"
    지침은 worker 실행 workspace의 프로젝트 context(`source-summary-guide.md`)가 담당하므로
    api가 파일로 로드해 프롬프트에 조립하지 않는다(PLAN-005-T-008 실행 모델 재설계).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        collect: CollectFn = collect_source,
    ) -> None:
        self._sources = SourceRepository(session)
        self._collect = collect
        # 실행 중 관찰용: build_data_blocks가 chunk 수/수집 방식을 남긴다.
        self.last_material: SourceMaterial | None = None
        self.last_chunk_count: int = 0

    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        if task.source_id is None:
            raise ContextBuildError(
                "SOURCE_NOT_FOUND", "요약 task에 source_id가 없습니다."
            )

        # 피드백 재요약(PLAN-005-T-016): 세션 resume 실행이라 원문 컨텍스트가 이미 세션에
        # 있다. 원문을 다시 수집·재조립하지 않고(토큰 절약) 피드백만 블록으로 공급한다.
        feedback = task.payload.get("feedback")
        if feedback:
            return [self._feedback_block(str(feedback))]
        source = await self._sources.get(task.source_id)
        if source is None:
            raise ContextBuildError(
                "SOURCE_NOT_FOUND", f"source 없음: {task.source_id}"
            )

        # 원문 수집 (AXKG-SPEC-012). 수집 실패는 Failure Contract code 그대로 표면화.
        # 저장된 메모(raw_text)를 user_note로 주입 — 원문 수집이 모두 실패하면 메모로
        # 요약하는 최종 fallback이 된다(PLAN-005-T-013). 메모 없으면 collection_failed.
        try:
            material = await self._collect(source.source_url, user_note=source.raw_text)
        except CollectionError as exc:
            raise ContextBuildError(exc.code, exc.message) from exc
        self.last_material = material

        blocks: list[AssembledBlockDTO] = [
            AssembledBlockDTO(
                kind="data",
                label="source",
                text=self._render_source_block(source.source_url, material),
            ),
        ]

        chunks = chunk_content(material.content_text, MAX_CHUNK_CHARS)
        self.last_chunk_count = len(chunks)
        if len(chunks) == 1:
            blocks.append(
                AssembledBlockDTO(
                    kind="data",
                    label="content",
                    text=f"[원문 본문 · {material.content_format}]\n{chunks[0]}",
                )
            )
        else:
            blocks.append(
                AssembledBlockDTO(
                    kind="data",
                    label="content_chunked",
                    text=(
                        f"원문이 길어 {len(chunks)}개 조각으로 나뉜다. 각 조각을 요약한 뒤 "
                        "하나의 일관된 요약으로 병합하라. 조각에 없는 내용을 추측해 채우지 않는다."
                    ),
                )
            )
            for i, chunk in enumerate(chunks, start=1):
                blocks.append(
                    AssembledBlockDTO(
                        kind="data",
                        label=f"content_chunk_{i}",
                        text=f"[원문 조각 {i}/{len(chunks)} · {material.content_format}]\n{chunk}",
                    )
                )
        return blocks

    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        """스키마 검증 통과 요약 payload를 새 버전으로 박제하고 source를 summarized로 전이한다.

        게이트 revision과 same-format으로 요약 draft 버전을 남긴다(SPEC-002/003 C, T-012):
        직전 active 버전은 superseded로 보존되고 이 실행이 새 active 버전이 된다. 이 실행 task의
        `open_kknaks_session_id`(resume 원천)와 task_id를 버전에 함께 박제한다.
        """
        if task.source_id is None:
            return
        await self._sources.set_summary(
            task.source_id,
            output,
            ai_task_id=task.id,
            open_kknaks_session_id=task.open_kknaks_session_id,
        )

    @staticmethod
    def _feedback_block(feedback: str) -> AssembledBlockDTO:
        """피드백 재요약(resume) 입력 블록 — 원문 재전송 없이 개정 지시만 담는다."""
        return AssembledBlockDTO(
            kind="data",
            label="feedback",
            text=(
                "이전 요약에 대한 사용자 피드백이다. 이 세션은 원문과 직전 요약 컨텍스트를 "
                "이미 보유하고 있으니 원문을 다시 요청·재수집하지 말고, 아래 피드백을 반영해 "
                "요약을 개정하라. 출력 JSON 스키마는 직전과 동일하게 유지한다.\n\n"
                f"[사용자 피드백]\n{feedback}"
            ),
        )

    @staticmethod
    def _render_source_block(source_url: str, material: SourceMaterial) -> str:
        """SourceMaterial 정체성/보조 metadata를 요약 입력용으로 직렬화(원문 본문 제외)."""
        meta = {
            "source_url": source_url,
            "canonical_url": material.canonical_url,
            "adapter": material.adapter,
            "content_format": material.content_format,
            "title": material.title,
            "author": material.author,
            "published_at": material.published_at,
            "duration_seconds": material.duration_seconds,
            "page_kind": material.metadata.get("page_kind"),
            "description": material.metadata.get("description"),
        }
        meta = {k: v for k, v in meta.items() if v is not None}
        return "[SourceMaterial 메타]\n" + json.dumps(meta, ensure_ascii=False, indent=2)
