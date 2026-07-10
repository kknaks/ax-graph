"""요약 확정 시 요약 보관 md 생성 (PLAN-009-T-014, 정정 모델 첫째 md 생성 지점).

요약 카드에서 [분류]로 넘어가는 순간(=요약 확정)이 트리거다. 그 source의 active summary
revision(T-012 `sources.active_summary_revision_id`) payload를 `data/documents/summaries/{stem}.md`
보관용 md로 확정 생성한다.

경계(seam):
- **보관용 only**: 그래프 노드/엣지/인덱스/retriever/`/graph/documents`/index_snapshot에 절대 안
  들어간다. `summaries/`는 `MarkdownRoot.iter_markdown` 스캔에서 제외돼 index/rebuild에 잡히지 않는다.
- downstream(분류/문서화)은 여전히 DB `summary_payload`/active revision을 읽는다 — 이 md는 side-output.
- 재확정(재피드백 후 다시 [분류])은 같은 stem md를 overwrite한다. 히스토리는 DB
  `source_summary_revisions`에 박제돼 있으므로 md는 현재 active 버전 하나다.
"""
from __future__ import annotations

import re

import yaml

from axkg.dto.source import SourceDTO, SourceSummaryRevisionDTO
from axkg.storage.markdown_root import SUMMARIES_SUBDIR, MarkdownRoot


def slugify(title: str) -> str:
    """요약 title을 파일 stem으로 정규화. 유니코드 letter/digit는 보존, 그 외는 하이픈.

    한글 제목도 stem으로 그대로 쓴다(Obsidian stem 규칙과 정합). 빈 결과는 `summary`.
    """
    text = (title or "").strip().lower()
    text = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-_")
    return text or "summary"


def build_summary_markdown(
    source: SourceDTO, revision: SourceSummaryRevisionDTO
) -> str:
    """active summary revision payload → 보관용 요약 md 전문(frontmatter + body_markdown).

    frontmatter: type/title/source_url/tags(keywords)/summarized_at. 본문은 payload의
    `body_markdown`(없으면 `summary` fallback).
    """
    payload = revision.payload or {}
    title = str(payload.get("title") or source.source_url)
    keywords = [str(k) for k in (payload.get("keywords") or [])]
    body = str(payload.get("body_markdown") or payload.get("summary") or "").rstrip()

    front: dict[str, object] = {
        "type": "summary",
        "title": title,
        "source_url": source.source_url,
        "tags": keywords,
        "summarized_at": revision.created_at.isoformat(),
    }
    front_yaml = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{front_yaml}\n---\n\n{body}\n"


def summary_archive_path(revision: SourceSummaryRevisionDTO) -> str:
    """active summary 버전의 보관 md 상대 경로 (`summaries/{title-slug}.md`)."""
    payload = revision.payload or {}
    stem = slugify(str(payload.get("title") or ""))
    return f"{SUMMARIES_SUBDIR}/{stem}.md"


def write_summary_archive(
    root: MarkdownRoot,
    source: SourceDTO,
    revision: SourceSummaryRevisionDTO,
) -> str | None:
    """요약 확정 → 보관 md write(overwrite, 멱등). 반환은 쓴 상대 경로, root 미provision이면 None.

    markdown root(문서 store)가 아직 없으면(미마운트/테스트) 보관 md를 건너뛴다 — DB active
    revision이 SoT이므로 side-output 생략은 무해하다(요약 트리거의 graceful degradation과 동일).
    """
    if not root.root.is_dir():
        return None
    rel = summary_archive_path(revision)
    markdown = build_summary_markdown(source, revision)
    return root.overwrite(rel, markdown)
