"""신규 개념 발굴 stale 배지 backfill (SPEC-004 §E-8/E-9, WORK-014). 멱등·삭제 없음.

E-8(신규 개념 retriever 발굴) 배포 **이전에 인입된 기존 concept**들은 관련 문서(permanent 종합
노트·feature_spec 기능정의서)를 소급 발굴한 적이 없다. 이 스크립트가 기존 concept 전수(또는
`--stem`으로 한 개)를 대상으로 발굴 트리거를 1회 소급 실행해 그간 누락된 stale 배지를 채운다.

발굴·마킹 로직은 apply 시점 신규 개념 마킹과 **동일한 코어**(`ApplyExecutor.
discover_related_and_mark`)를 재사용한다 — corp 경계 + score 임계 + top-N 상한. 멱등:
`document_stale_marks`는 (document_id, concept_stem) upsert라 다시 돌려도 중복 배지를 만들지 않는다.
반영은 여전히 수동(배지 → 사용자 재생성 게이트 승인, E-3~E-6) — 이 스크립트는 배지만 채운다.

CLI(앱 컨텍스트 — DB 세션·MarkdownRoot·GraphService 재사용):
    python -m axkg.scripts.backfill_stale_new_concepts [--stem <concept-stem>] [--dry-run]
서버(docker):
    docker exec axkg-api python -m axkg.scripts.backfill_stale_new_concepts --dry-run
    docker exec axkg-api python -m axkg.scripts.backfill_stale_new_concepts --stem 음성-인식-stt
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.repositories.documents import DocumentRepository
from axkg.storage.markdown_root import MarkdownRoot
from axkg.workers.apply_executor import ApplyExecutor

_CONCEPT_TYPE = "concept"
_QUERY_BODY_CAP = 2_000


@dataclass
class ConceptResult:
    stem: str
    marked: int = 0  # 이 개념이 stale 배지를 붙인 대상 문서 수


@dataclass
class BackfillReport:
    dry_run: bool
    concepts_total: int = 0
    results: list[ConceptResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = f"[backfill-stale-new-concepts{' DRY-RUN' if self.dry_run else ''}]"
        total_marks = sum(r.marked for r in self.results)
        touched = [r for r in self.results if r.marked > 0]
        lines = [
            head,
            f"  개념: 총 {self.concepts_total}개 스캔 / 배지 발생 {len(touched)}개 개념 / "
            f"stale 배지 {'예정' if self.dry_run else '생성'} {total_marks}개",
        ]
        for r in sorted(touched, key=lambda x: -x.marked):
            lines.append(f"    [[{r.stem}]] → 관련 문서 {r.marked}개")
        if self.errors:
            lines.append("  errors: " + "; ".join(self.errors))
        return "\n".join(lines)


async def backfill_stale_new_concepts(
    session: AsyncSession,
    root: MarkdownRoot,
    *,
    stem: str | None = None,
    dry_run: bool = False,
) -> BackfillReport:
    """기존 concept를 소급 발굴해 관련 문서에 stale 배지를 붙인다(멱등).

    dry_run이면 세션을 커밋하지 않으므로(호출측이 rollback), 무엇을 마킹할지 카운트만 보인다.
    """
    docs_repo = DocumentRepository(session)
    executor = ApplyExecutor(session, root)

    all_docs = await docs_repo.list_all()
    concepts = [
        d
        for d in all_docs
        if d.document_type == _CONCEPT_TYPE
        and d.status == "current"
        and (stem is None or d.stem == stem)
    ]
    report = BackfillReport(dry_run=dry_run, concepts_total=len(concepts))
    for concept in concepts:
        body = _read(root, concept.path)
        query = ApplyExecutor._new_concept_query(concept.title, body)
        try:
            marked = await executor.discover_related_and_mark(
                concept, query, triggering_revision_id=None
            )
        except Exception as exc:  # noqa: BLE001 — 개념 하나 실패가 전체를 막지 않는다.
            report.errors.append(f"{concept.stem}: {exc}")
            continue
        report.results.append(ConceptResult(stem=concept.stem, marked=marked))
    return report


def _read(root: MarkdownRoot, path: str) -> str:
    if not path or not root.exists(path):
        return ""
    try:
        return root.read_text(path)[:_QUERY_BODY_CAP]
    except OSError:
        return ""


async def _amain(argv: list[str] | None = None) -> BackfillReport:
    parser = argparse.ArgumentParser(
        prog="python -m axkg.scripts.backfill_stale_new_concepts",
        description="신규 개념 발굴 stale 배지 backfill (WORK-014, 멱등·삭제 없음).",
    )
    parser.add_argument(
        "--stem", default=None,
        help="한 개념만 대상으로 소급(예: 음성-인식-stt). 없으면 전 concept 스캔.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="마킹을 커밋하지 않고 무엇을 붙일지 카운트만 출력한다(프로덕션 실행 전 확인용).",
    )
    args = parser.parse_args(argv)

    from axkg.core.database import get_engine, get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        report = await backfill_stale_new_concepts(
            session,
            MarkdownRoot(settings.axkg_markdown_root),
            stem=args.stem,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()
    await get_engine().dispose()
    print(report.render())
    return report


if __name__ == "__main__":
    asyncio.run(_amain())
