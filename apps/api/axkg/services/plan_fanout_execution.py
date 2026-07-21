"""plan-then-fanout 오케스트레이션 (AXKG-DEC-008 / WORK-012 P1~P4).

project 문서화 생성을 3단계로 실행한다(단일 task 타임아웃/거대출력 파싱실패 해소):

  ① plan_project task 실행 → 원본요약 + 기능목록(plan) 산출(revision.payload에 보관).
  ② plan 각 기능마다 generate_feature_spec task를 **병렬** 발주·실행(기능별 격리·재시도).
  ③ N개 기능정의서 draft를 fan-in해 문서화 게이트 revision(main=원본요약 + derived=기능 N)으로
     조립 → gate review_pending. 승인·apply는 기존 apply_executor(main+derived 팬아웃) 재사용.

부분 실패 정책(AXKG-DEC-008 OQ 확정, v1): **한 기능 task 실패는 그 기능만 실패 표시하고
나머지로 게이트를 조립·진행한다**(전체 보류 아님). 실패 기능은 기능 단위로 재시도 가능
(`retry_feature`) — 11개 통째 재생성이 아니다. 게이트 revision "완결성"은 "모든 기능 task가
terminal(succeeded/failed)에 도달"로 정의하며, 성공분 derived + 실패분 목록으로 조립한다.

외부 계약(원본요약 + 기능정의서 N, main+derived, origin·corp·경로 3층)은 불변 —
`wrap_documentation_output`/apply_executor를 그대로 재사용한다(AXKG-SPEC-014/004).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.core.database import get_session_factory
from axkg.dto.ai import AiTaskDTO
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai import AiExecutionService, ContextBuilderRegistry
from axkg.services.ai.documentation_gate import wrap_documentation_output
from axkg.services.ai.feature_spec import (
    FEATURE_RESULT_KEY,
    PLAN_ITEM_KEY,
    SOURCE_SUMMARY_STEM_KEY,
    FeatureSpecContextBuilder,
)
from axkg.services.ai.feature_spec import HANDLER_KIND as FEATURE_HANDLER
from axkg.services.ai.plan_project import (
    PLAN_OUTPUT_KEY,
    PlanProjectContextBuilder,
)
from axkg.services.ai.plan_project import HANDLER_KIND as PLAN_HANDLER
from axkg.services.document_paths import normalize_filename
from axkg.services.qmd import build_qmd_client
from axkg.storage.markdown_root import MarkdownRoot

logger = logging.getLogger("axkg.plan_fanout_execution")

PLAN_TASK_TYPE = "plan_project"
FEATURE_TASK_TYPE = "generate_feature_spec"
CORP_KEY = "corp"
# 기능 task 병렬 상한(worker concurrency). 너무 크면 open-kknaks/모델에 부담이라 보수적으로.
FANOUT_CONCURRENCY = 5


def _qmd():
    return build_qmd_client(
        mcp_url=settings.axkg_qmd_mcp_url,
        rerank_default=settings.axkg_qmd_rerank_default,
    )


async def execute_plan_then_fanout(
    plan_task_id: uuid.UUID,
    gate_id: uuid.UUID,
    revision_id: uuid.UUID,
    *,
    client: OpenKknaksClient,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    root: MarkdownRoot | None = None,
    concurrency: int = FANOUT_CONCURRENCY,
) -> None:
    """plan → fan-out(병렬) → fan-in 조립을 한 오케스트레이션으로 실행한다.

    plan 실패면 게이트를 failed로 표면화하고 종료(기능 발주 없음). plan 성공이면 기능 task를
    발주·병렬 실행한 뒤, 전 기능이 terminal에 도달하면 revision을 조립해 gate review_pending.
    """
    factory = session_factory or get_session_factory()
    the_root = root or MarkdownRoot(settings.axkg_markdown_root)

    # ── ① plan 실행 + 기능 task 발주 ──────────────────────────────────
    async with factory() as session:
        registry = ContextBuilderRegistry()
        registry.register(PLAN_HANDLER, PlanProjectContextBuilder(session))
        service = AiExecutionService(session, client=client, registry=registry)
        plan_done = await service.execute_task(plan_task_id)
        if plan_done.status != "succeeded":
            await _surface_gate_failed(
                session, gate_id, revision_id,
                error_code=plan_done.error_code or "PLAN_FAILED",
            )
            await session.commit()
            logger.warning("plan_project failed gate=%s task=%s", gate_id, plan_task_id)
            return
        feature_task_ids = await _spawn_feature_tasks(
            service, session, plan_done, gate_id, revision_id
        )
        await session.commit()

    # ── ② 기능 task 병렬 실행(기능별 격리) ────────────────────────────
    if feature_task_ids:
        sem = asyncio.Semaphore(max(1, concurrency))

        async def _run(tid: uuid.UUID) -> None:
            async with sem:
                await _execute_feature_task(
                    tid, client=client, session_factory=factory, root=the_root
                )

        await asyncio.gather(*[_run(t) for t in feature_task_ids], return_exceptions=True)

    # ── ③ fan-in 조립 → gate review_pending ───────────────────────────
    async with factory() as session:
        await finalize_fanout(session, gate_id, revision_id, root=the_root)
        await session.commit()


async def _spawn_feature_tasks(
    service: AiExecutionService,
    session: AsyncSession,
    plan_task: AiTaskDTO,
    gate_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> list[uuid.UUID]:
    """plan의 각 기능 → generate_feature_spec task(queued) 발주. corp·요약 stem을 실어 보낸다."""
    gates = GateRepository(session)
    revision = await gates.get_revision(revision_id)
    plan_output = (revision.payload or {}).get(PLAN_OUTPUT_KEY) if revision else None
    if not plan_output:
        return []
    plan = plan_output.get("plan") or []
    main_draft = plan_output.get("document_draft") or {}
    summary_stem = PurePosixPath(
        normalize_filename(main_draft.get("filename_candidate"))
    ).stem
    corp = plan_task.payload.get(CORP_KEY)

    # corp·요약 stem을 revision에 보관(fan-in·재시도가 재사용).
    payload = dict(revision.payload or {})
    payload[CORP_KEY] = corp
    payload[SOURCE_SUMMARY_STEM_KEY] = summary_stem
    await gates.update_revision(revision_id, payload=payload)

    task_ids: list[uuid.UUID] = []
    for item in plan:
        task = await service.create_task(
            FEATURE_TASK_TYPE,
            source_id=plan_task.source_id,
            gate_id=gate_id,
            revision_id=revision_id,
            payload={
                "kind": "feature_spec",
                PLAN_ITEM_KEY: item,
                SOURCE_SUMMARY_STEM_KEY: summary_stem,
                CORP_KEY: corp,
                "destination_type": "project",
            },
        )
        task_ids.append(task.id)
    return task_ids


async def _execute_feature_task(
    task_id: uuid.UUID,
    *,
    client: OpenKknaksClient,
    session_factory: async_sessionmaker[AsyncSession],
    root: MarkdownRoot,
) -> AiTaskDTO:
    """기능 task 하나를 자체 session에서 실행한다. 실패는 task에만 남긴다(gate 미표면화·격리)."""
    async with session_factory() as session:
        registry = ContextBuilderRegistry()
        registry.register(
            FEATURE_HANDLER,
            FeatureSpecContextBuilder(session, root=root, qmd=_qmd()),
        )
        service = AiExecutionService(session, client=client, registry=registry)
        done = await service.execute_task(task_id)
        await session.commit()
        return done


def _latest_by_seq(feature_tasks: list[AiTaskDTO]) -> dict[int, AiTaskDTO]:
    """seq별 최신 task(재시도 포함) — queued_at·retry_count 순으로 뒤가 최신."""
    latest: dict[int, AiTaskDTO] = {}
    for task in feature_tasks:  # list_by_gate가 queued_at asc 정렬 → 순회 끝이 최신
        seq = (task.payload.get(PLAN_ITEM_KEY) or {}).get("seq")
        if seq is None:
            continue
        latest[int(seq)] = task
    return latest


def _feature_stem(filename_candidate: str | None) -> str:
    """plan filename_candidate → 파일명 stem(원본요약 `[[stem]]`·spec 경로의 stem)."""
    return PurePosixPath(normalize_filename(filename_candidate)).stem


def _prune_failed_feature_links(markdown: str, failed_stems: set[str]) -> str:
    """원본요약 본문에서 실패/미완 기능 stem을 가리키는 `[[ ]]` 불릿 줄을 제거한다.

    부분 실패 시 그 기능은 spec 문서가 없어 apply에서 BROKEN_WIKILINK가 되므로, 조립 시점의
    원본요약에서 해당 링크 줄만 뺀다(원본 plan_output은 보존 — 재시도 성공 시 되살아남).
    """
    if not failed_stems:
        return markdown
    kept: list[str] = []
    for line in markdown.splitlines():
        if any(f"[[{s}]]" in line or f"[[{s}|" in line for s in failed_stems):
            continue
        kept.append(line)
    return "\n".join(kept)


def compute_fanout_progress(plan: list[dict], latest: dict[int, AiTaskDTO]) -> dict:
    """N개 중 M개 완료 진행률(부분 실패 포함) — P4 상태 노출용(UI는 후속)."""
    total = len(plan)
    completed = failed = running = 0
    failed_items: list[dict] = []
    for item in plan:
        seq = int(item.get("seq"))
        task = latest.get(seq)
        status = task.status if task else "queued"
        if status == "succeeded":
            completed += 1
        elif status == "failed":
            failed += 1
            failed_items.append({"seq": seq, "feature_name": item.get("feature_name")})
        else:
            running += 1
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "running": running,
        "failed_features": failed_items,
        "status": "complete" if running == 0 else "generating",
    }


async def finalize_fanout(
    session: AsyncSession,
    gate_id: uuid.UUID,
    revision_id: uuid.UUID,
    *,
    root: MarkdownRoot,
) -> bool:
    """전 기능 task가 terminal이면 revision을 main+derived로 조립하고 gate review_pending.

    아직 실행 중인 기능 task가 있으면 조립하지 않고 False(배리어 미완). 조립 시 성공 기능만
    derived로 담고, 실패 기능은 progress.failed_features로 표시한다(부분 진행). 이미 승인된
    게이트는 건드리지 않는다.
    """
    gates = GateRepository(session)
    tasks_repo = AiTaskRepository(session)
    sources = SourceRepository(session)

    gate = await gates.get_gate(gate_id)
    revision = await gates.get_revision(revision_id)
    if gate is None or revision is None or gate.status == "approved":
        return False
    plan_output = (revision.payload or {}).get(PLAN_OUTPUT_KEY)
    if not plan_output:
        return False
    plan = plan_output.get("plan") or []
    corp = (revision.payload or {}).get(CORP_KEY)

    feature_tasks = await tasks_repo.list_by_gate(gate_id, FEATURE_TASK_TYPE)
    latest = _latest_by_seq(feature_tasks)

    # 배리어: 하나라도 아직 queued/running이면 조립하지 않는다.
    for item in plan:
        task = latest.get(int(item.get("seq")))
        if task is not None and task.status not in ("succeeded", "failed"):
            return False

    derived: list[dict] = []
    failed_stems: set[str] = set()
    for item in plan:
        task = latest.get(int(item.get("seq")))
        stem = _feature_stem(item.get("filename_candidate"))
        result = (task.payload.get(FEATURE_RESULT_KEY) or {}) if task else {}
        draft = result.get("document_draft") or {}
        succeeded = (
            task is not None
            and task.status == "succeeded"
            and draft.get("markdown_full")
            and draft.get("filename_candidate")
        )
        if not succeeded:
            # 부분 실패: 이 기능은 spec을 안 만든다 → 원본요약이 그 stem을 링크하면 apply에서
            # BROKEN_WIKILINK가 되므로 아래에서 원본요약 `## 기능 목록` 링크를 제거한다.
            if stem:
                failed_stems.add(stem)
            continue
        derived.append(
            {
                "suggestion_type": "create_feature_spec",
                "filename_candidate": draft["filename_candidate"],
                "draft_markdown": draft["markdown_full"],
                "link_reason": item.get("summary") or "요구 1항목=1장(기능정의서)",
            }
        )

    source = await sources.get(gate.source_id)
    # 원본요약(main)은 plan_output 원본에서 복사해, 이번에 실패/미완인 기능 링크만 제거한다.
    # (plan_output은 revision에 원본 그대로 유지 — 재시도 성공 시 재조립에서 그 링크가 되살아난다.)
    main_draft = dict(plan_output.get("document_draft") or {})
    main_draft["markdown_full"] = _prune_failed_feature_links(
        main_draft.get("markdown_full", ""), failed_stems
    )
    output = {
        "document_draft": main_draft,
        "derived_suggestions": derived,
    }
    envelope = wrap_documentation_output(source, "project", output, corp=corp)
    progress = compute_fanout_progress(plan, latest)
    envelope["form"]["fanout"] = progress
    # fan-in·재시도가 재사용할 재료를 revision에 유지(plan_output·corp).
    envelope[PLAN_OUTPUT_KEY] = plan_output
    envelope[CORP_KEY] = corp

    await gates.update_revision(revision_id, status="reviewable", payload=envelope)
    await gates.update_gate(
        gate_id, status="review_pending", active_revision_id=revision_id
    )
    logger.info(
        "fanout finalized gate=%s total=%s completed=%s failed=%s",
        gate_id, progress["total"], progress["completed"], progress["failed"],
    )
    return True


async def execute_feature_retry(
    retry_task_id: uuid.UUID,
    gate_id: uuid.UUID,
    revision_id: uuid.UUID,
    *,
    client: OpenKknaksClient,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    root: MarkdownRoot | None = None,
) -> None:
    """실패한 기능 하나를 재실행하고 revision을 다시 조립한다(기능 단위 재시도)."""
    factory = session_factory or get_session_factory()
    the_root = root or MarkdownRoot(settings.axkg_markdown_root)
    await _execute_feature_task(
        retry_task_id, client=client, session_factory=factory, root=the_root
    )
    async with factory() as session:
        await finalize_fanout(session, gate_id, revision_id, root=the_root)
        await session.commit()


async def _surface_gate_failed(
    session: AsyncSession,
    gate_id: uuid.UUID,
    revision_id: uuid.UUID,
    *,
    error_code: str,
) -> None:
    """plan 실패 시 revision/gate를 failed로 표면화(감사 이력 보존)."""
    gates = GateRepository(session)
    revision = await gates.get_revision(revision_id)
    if revision is not None and revision.status == "drafting":
        await gates.update_revision(revision_id, status="failed")
    gate = await gates.get_gate(gate_id)
    if gate is not None and gate.status != "failed":
        await gates.update_gate(gate_id, status="failed")
