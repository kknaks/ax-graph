"""회사 루트 + baseline up: 체인 backfill (WORK-013 / AXKG-DEC-009). 멱등·삭제 없음.

WORK-013(회사 루트 `{corp}.md` + up: 회사 루트 수렴) **배포 전에 생성된 기존 회사 프로젝트**는
회사 루트 문서도, baseline의 `up: [{corp}]`도 없다. 이 스크립트가 삭제·재생성 없이 **in-place**로
부족한 것만 채워 새 구조에 맞춘다:

  1) `projects/{corp}/{corp}.md`(document_type `company`)가 없으면 생성하고 그래프 노드로 인덱싱한다
     (WORK-013 routes/projects.py의 회사 루트 생성·인덱싱과 동일 경로 재사용). 이미 있으면 재인덱싱만.
  2) `projects/{corp}/baseline/`의 baseline 문서 중 `up:`에 `{corp}`가 없는 것에 `up: [{corp}]` +
     본문 `## 연결`에 `[[{corp}]]`를 추가한다(services.document_anchor 재사용, 이미 있으면 skip).
  3) 변경 문서의 인덱스+엣지를 rebuild해 `baseline → {corp}` lineage 엣지를 materialize한다.
     (feature_spec은 이미 `up: [원본요약]`이라 원본요약 backfill로 2단 체인이 자동 완성 — 확인만.)

멱등: 이미 backfill된 프로젝트에 다시 돌려도 회사 루트를 중복 생성하지 않고, baseline `up:`도
중복 추가하지 않는다. `--dry-run`은 write/인덱싱 없이 무엇을 바꿀지만 출력한다.

CLI(앱 컨텍스트 — DB 세션·MarkdownRoot·GraphService 재사용):
    python -m axkg.scripts.backfill_company_root --corp <corp> [--root-md <path>] [--dry-run]
서버(docker):
    docker exec axkg-api python -m axkg.scripts.backfill_company_root --corp sc --dry-run
    docker exec axkg-api python -m axkg.scripts.backfill_company_root --corp sc --root-md /tmp/sc.md
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.services.document_anchor import apply_document_anchor
from axkg.services.graph import GraphService
from axkg.services.project_scaffold import (
    BASELINE,
    COMPANY_DOCUMENT_TYPE,
    SPEC,
    company_root_markdown,
    company_root_path,
    corp_dir,
    corp_subdir,
)
from axkg.storage.markdown_parser import extract_wikilinks, parse_markdown
from axkg.storage.markdown_root import MarkdownRoot


@dataclass
class BackfillReport:
    """backfill 결과 요약(멱등 판단·dry-run 출력용)."""

    corp: str
    dry_run: bool
    project_found: bool = True
    root_path: str | None = None
    root_created: bool = False  # 이번에 새로 생성(또는 dry-run이면 생성 예정)
    root_already_existed: bool = False
    root_indexed: bool = False  # company 노드로 인덱싱됨(dry-run이면 예정)
    baselines_total: int = 0
    baselines_updated: list[str] = field(default_factory=list)  # up: 추가한 stem
    baselines_skipped: list[str] = field(default_factory=list)  # 이미 up:[corp] 있음
    specs_total: int = 0  # feature_spec은 건드리지 않음(확인만)
    errors: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = f"[backfill{' DRY-RUN' if self.dry_run else ''}] corp={self.corp}"
        if not self.project_found:
            return f"{head}\n  ERROR: projects/{self.corp}/ 프로젝트가 없습니다."
        verb = "생성 예정" if self.dry_run else ("생성" if self.root_created else "유지")
        lines = [
            head,
            f"  회사 루트: {self.root_path} — "
            + ("이미 있음(재인덱싱)" if self.root_already_existed else verb)
            + ("" if self.dry_run else (" · 인덱싱됨" if self.root_indexed else "")),
            f"  baseline: 총 {self.baselines_total}개 / "
            f"up:[{self.corp}] 추가 {len(self.baselines_updated)}개 / "
            f"이미 있음 {len(self.baselines_skipped)}개",
        ]
        if self.baselines_updated:
            lines.append("    " + ("추가 예정: " if self.dry_run else "추가함: ")
                         + ", ".join(self.baselines_updated))
        lines.append(f"  feature_spec: {self.specs_total}개(변경 없음 — 원본요약 up으로 2단 체인)")
        if not self.dry_run and (self.root_created or self.baselines_updated):
            lines.append(f"  엣지: baseline → [[{self.corp}]] lineage 수렴 rebuild 완료")
        if self.errors:
            lines.append("  errors: " + "; ".join(self.errors))
        return "\n".join(lines)


def _needs_up(text: str, corp: str) -> bool:
    """이 문서가 아직 up:[corp] + 본문 [[corp]]를 안 갖췄으면 True(backfill 대상)."""
    parsed = parse_markdown(text)
    has_up = corp in parsed.up
    has_link = corp in {w.target for w in extract_wikilinks(parsed.body)}
    return not (has_up and has_link)


def _md_names(root: MarkdownRoot, directory: str) -> list[str]:
    return [n for n in root.list_child_names(directory) if n.lower().endswith(".md")]


def _ensure_company_frontmatter(content: str) -> str:
    """회사 루트 내용의 frontmatter type을 company로 보장한다(그 외 내용은 보존).

    --root-md가 이미 `type: company`면 그대로, 아니면 시스템이 company로 강제한다(노드 타입 정합).
    """
    if parse_markdown(content).document_type == COMPANY_DOCUMENT_TYPE:
        return content
    return apply_document_anchor(content, document_type=COMPANY_DOCUMENT_TYPE)


async def backfill_company_root(
    session: AsyncSession,
    root: MarkdownRoot,
    corp: str,
    *,
    root_md_content: str | None = None,
    dry_run: bool = False,
) -> BackfillReport:
    """한 회사 프로젝트를 in-place backfill한다(멱등). 실제 write/index는 dry_run=False일 때만.

    session commit은 호출측 소관이다(CLI main이 commit). 삭제·재생성 없이 부족분만 추가한다.
    """
    report = BackfillReport(corp=corp, dry_run=dry_run)
    if not root.is_dir(corp_dir(corp)):
        report.project_found = False
        return report

    graph = GraphService(session, root=root)

    # 1) 회사 루트 {corp}.md — 없으면 생성, 있으면 재인덱싱(멱등).
    root_rel = company_root_path(corp)
    report.root_path = root_rel
    root_exists = root.exists(root_rel)
    report.root_already_existed = root_exists
    if not root_exists:
        content = _ensure_company_frontmatter(
            root_md_content if root_md_content is not None
            else company_root_markdown(corp, corp)
        )
        report.root_created = True
        if not dry_run:
            root.write_new(root_rel, content)
    if not dry_run:
        # rebuild는 파일을 읽어 company 노드로 인덱싱한다(신규/기존 모두 멱등 upsert).
        await graph.rebuild_document(root_rel)
        report.root_indexed = True

    # 2) baseline up:[corp] + 본문 [[corp]] 백필(이미 있으면 skip).
    baseline_dir = corp_subdir(corp, BASELINE)
    changed_rels: list[str] = []
    for name in _md_names(root, baseline_dir):
        rel = f"{baseline_dir}/{name}"
        stem = name[:-3]
        try:
            text = root.read_text(rel)
        except OSError as exc:
            report.errors.append(f"read {rel}: {exc}")
            continue
        report.baselines_total += 1
        if not _needs_up(text, corp):
            report.baselines_skipped.append(stem)
            continue
        report.baselines_updated.append(stem)
        if not dry_run:
            anchored = apply_document_anchor(
                text, document_type="baseline", up_target=corp
            )
            root.overwrite(rel, anchored)
            changed_rels.append(rel)

    # feature_spec은 이미 up:[원본요약]이라 원본요약 backfill로 2단 체인 자동 완성 — 확인만.
    report.specs_total = len(_md_names(root, corp_subdir(corp, SPEC)))

    # 3) 변경 baseline rebuild → baseline→{corp} lineage 엣지 materialize(루트는 위에서 인덱싱됨).
    if not dry_run:
        for rel in changed_rels:
            await graph.rebuild_document(rel)
    return report


async def _amain(argv: list[str] | None = None) -> BackfillReport:
    parser = argparse.ArgumentParser(
        prog="python -m axkg.scripts.backfill_company_root",
        description="회사 루트 + baseline up: 체인 backfill (WORK-013, 멱등·삭제 없음).",
    )
    parser.add_argument("--corp", required=True, help="회사 slug (예: sc)")
    parser.add_argument(
        "--root-md", default=None,
        help="회사 루트 {corp}.md로 쓸 md 파일 경로(frontmatter 포함). 없으면 최소 stub.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="write/인덱싱 없이 무엇을 만들/바꿀지만 출력한다(프로덕션 실행 전 확인용).",
    )
    args = parser.parse_args(argv)

    root_md_content: str | None = None
    if args.root_md:
        with open(args.root_md, encoding="utf-8") as fh:
            root_md_content = fh.read()

    from axkg.core.database import get_engine, get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        report = await backfill_company_root(
            session,
            MarkdownRoot(settings.axkg_markdown_root),
            args.corp,
            root_md_content=root_md_content,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            await session.commit()
    await get_engine().dispose()
    print(report.render())
    return report


if __name__ == "__main__":
    asyncio.run(_amain())
