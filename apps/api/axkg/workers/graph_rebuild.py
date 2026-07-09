"""documents/document_edges 캐시 재빌드. 트리거: startup scan / 증분 / POST /graph/rebuild (AXKG-SPEC-005). WP2.

rebuild는 Markdown을 **읽기만** 한다 — cache는 언제든 Markdown에서 재빌드 가능(DEC-002).
자체 session에서 도는 오케스트레이터(요약 execution 패턴)이며, api 요청 핸들러가
`POST /graph/rebuild`로 전체 rebuild를, 앱 startup이 scan을 스케줄링한다.

트리거 3종:
- **전체 rebuild**(`run_full_rebuild`): 인덱스+엣지 전부 재구성. POST /graph/rebuild.
- **증분**(`run_document_rebuild`): 문서 1개 단위. 파일 없으면 인덱스에서 제거 + inbound heal.
- **startup scan**(`run_startup_scan`): content_hash 비교로 **변경분만** 증분 rebuild하고,
  디스크에서 사라진 문서를 제거한다(외부 편집 반영).
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.core.database import get_session_factory
from axkg.repositories.documents import DocumentRepository
from axkg.services.graph import GraphService, RebuildStats
from axkg.storage.markdown_root import MarkdownRoot, content_hash

logger = logging.getLogger("axkg.graph_rebuild")


def _root(root: MarkdownRoot | None) -> MarkdownRoot:
    return root or MarkdownRoot(settings.axkg_markdown_root)


async def run_full_rebuild(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    root: MarkdownRoot | None = None,
) -> RebuildStats:
    """document root 전체를 재인덱싱하고 엣지를 재구성한 뒤 commit 한다."""
    factory = session_factory or get_session_factory()
    resolved_root = _root(root)
    async with factory() as session:
        stats = await GraphService(session, root=resolved_root).rebuild_all()
        await session.commit()
    logger.info(
        "graph full rebuild: indexed=%d removed=%d edges=%d broken=%d",
        stats.indexed,
        stats.removed,
        stats.edges,
        stats.broken_edges,
    )
    return stats


async def run_document_rebuild(
    path: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    root: MarkdownRoot | None = None,
) -> RebuildStats:
    """단일 문서 증분 rebuild(Apply Executor 증분 훅 · 외부 편집 반영)."""
    factory = session_factory or get_session_factory()
    resolved_root = _root(root)
    async with factory() as session:
        stats = await GraphService(session, root=resolved_root).rebuild_document(path)
        await session.commit()
    return stats


async def run_startup_scan(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    root: MarkdownRoot | None = None,
) -> RebuildStats:
    """앱 startup 스캔 — content_hash가 바뀐(또는 새) 문서만 증분 rebuild + 삭제 반영.

    변경분만 손대되, 삭제·이름변경으로 stem이 생기거나 사라지는 경우 증분 rebuild의
    inbound heal / break가 백링크 엣지를 갱신한다.
    """
    factory = session_factory or get_session_factory()
    resolved_root = _root(root)
    total = RebuildStats()
    async with factory() as session:
        service = GraphService(session, root=resolved_root)
        repo = DocumentRepository(session)
        indexed = {doc.path: doc.content_hash for doc in await repo.list_all()}
        on_disk = set(resolved_root.iter_markdown())

        changed: list[str] = []
        for rel in on_disk:
            current = content_hash(resolved_root.read_text(rel))
            if indexed.get(rel) != current:
                changed.append(rel)
        removed = [path for path in indexed if path not in on_disk]

        for rel in changed:
            stats = await service.rebuild_document(rel)
            _accumulate(total, stats)
        for path in removed:
            stats = await service.rebuild_document(path)  # 파일 없음 → 제거 경로
            _accumulate(total, stats)
        await session.commit()
    logger.info(
        "graph startup scan: changed=%d removed=%d edges=%d",
        len(changed),
        len(removed),
        total.edges,
    )
    return total


def _accumulate(total: RebuildStats, stats: RebuildStats) -> None:
    total.indexed += stats.indexed
    total.removed += stats.removed
    total.edges += stats.edges
    total.broken_edges += stats.broken_edges
    total.skipped.extend(stats.skipped)
    total.duplicate_stems.extend(stats.duplicate_stems)
    total.invalid_documents.extend(stats.invalid_documents)
