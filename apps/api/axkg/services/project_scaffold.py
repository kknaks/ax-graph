"""회사 프로젝트 팬아웃 경로·slug·스캐폴드·origin 보관 (AXKG-SPEC-014, AXKG-DEC-007). WP11.

회사 프로젝트는 `projects/{corp}/`의 3층(origin·baseline·spec)이다:
- `origin/`  — 첨부 docx **원본 raw**(바인드 마운트, 그래프 노드 아님)
- `baseline/`— 원본요약(`project_source_summary`, main, document_type=baseline)
- `spec/`    — 기능정의서(`project_feature_spec`, 파생, document_type=feature_spec)

경로 디렉토리는 **시스템이 조립**한다(AI는 파일명 stem만, SPEC-004 §4). 이 모듈이 경로
조립(문서화 게이트 wrap)·안전망 검증(apply_executor)·스캐폴드 생성(프로젝트 추가 API)의
단일 SSOT다 — 중복 정의 금지.

v1(WP11) 범위: 스캐폴드는 **수동·독립 생성**(업로드/분류가 프로젝트를 자동 생성하지 않는다),
기능정의서는 항상 신규 생성(create-only, dedup·map.md 재생성은 후속 WP).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

PROJECTS_DIR = "projects"
ORIGIN = "origin"
BASELINE = "baseline"
SPEC = "spec"
# 회사 배경지식(조직·업무 플로우 등) 단일 문서 층 (AXKG-DEC-009/WORK-013).
CONTEXT = "context"
CORP_SUBDIRS = (ORIGIN, BASELINE, SPEC, CONTEXT)
# 회사 루트/context document_type (AXKG-DEC-009 — 신규 타입 기본).
COMPANY_DOCUMENT_TYPE = "company"
CONTEXT_DOCUMENT_TYPE = "context"
# project 하위 sub-type (AXKG-DEC-009 D2).
SUBTYPE_REQUIREMENT = "requirement"
SUBTYPE_CONTEXT = "context"
# origin 첨부 원본 업로드 시 임시 보관(corp 미확정 단계). corp 매칭·게이트 승인 시 finalize된다.
# `.`으로 시작해 corp 목록·트리에서 자연 제외되고, *.docx라 iter_markdown(=*.md) 스캔에도 안 든다.
ORIGIN_STAGING_DIR = f"{PROJECTS_DIR}/.origin-staging"


def slugify(name: str) -> str:
    """회사명 → URL-safe slug(소문자·하이픈). 한글 음절은 보존한다(로마자 변환 없음).

    "더에스씨"처럼 로마자 대응(the-sc)은 사용자가 정하는 몫이라 여기서 음역하지 않는다 —
    시스템은 정규화만 한다(공백·구두점→하이픈, 소문자화, 허용문자 외 제거). 결과가 비면 ""
    (호출측이 EMPTY_CORP_NAME 처리).
    """
    text = unicodedata.normalize("NFKC", name or "").strip().lower()
    # 공백·언더스코어·점·슬래시를 하이픈으로.
    text = re.sub(r"[\s_./\\]+", "-", text)
    # 허용문자: 소문자 영숫자, 한글 음절, 하이픈. 그 외 제거.
    text = re.sub(r"[^a-z0-9가-힣-]", "", text)
    # 하이픈 축약·양끝 정리.
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def corp_dir(corp: str) -> str:
    return f"{PROJECTS_DIR}/{corp}"


def corp_subdir(corp: str, sub: str) -> str:
    return f"{PROJECTS_DIR}/{corp}/{sub}"


def project_baseline_path(corp: str, filename: str) -> str:
    """원본요약(main) 경로 = projects/{corp}/baseline/{stem}.md. corp/파일명 없으면 ""."""
    if not corp or not filename:
        return ""
    return f"{corp_subdir(corp, BASELINE)}/{filename}"


def project_spec_path(corp: str, filename: str) -> str:
    """기능정의서(파생) 경로 = projects/{corp}/spec/{stem}.md. corp/파일명 없으면 ""."""
    if not corp or not filename:
        return ""
    return f"{corp_subdir(corp, SPEC)}/{filename}"


def project_context_path(corp: str, filename: str) -> str:
    """회사 context 단일 문서 경로 = projects/{corp}/context/{stem}.md (WORK-013). 없으면 ""."""
    if not corp or not filename:
        return ""
    return f"{corp_subdir(corp, CONTEXT)}/{filename}"


def company_root_path(corp: str) -> str:
    """회사 루트 앵커 경로 = projects/{corp}/{corp}.md (WORK-013). corp의 stem은 corp 자체."""
    if not corp:
        return ""
    return f"{corp_dir(corp)}/{corp}.md"


def origin_final_path(corp: str, filename: str) -> str:
    """origin 첨부 원본 경로 = projects/{corp}/origin/{원본파일명}. corp/파일명 없으면 ""."""
    name = PurePosixPath((filename or "").strip()).name
    if not corp or not name:
        return ""
    return f"{corp_subdir(corp, ORIGIN)}/{name}"


def origin_staging_path(source_id: str, filename: str) -> str:
    """corp 확정 전 origin 임시 보관 경로. 원본 확장자를 보존한다(비-md)."""
    suffix = PurePosixPath((filename or "").strip()).suffix or ".bin"
    return f"{ORIGIN_STAGING_DIR}/{source_id}{suffix}"


def corp_from_path(path: str | None) -> str | None:
    """projects/{corp}/{origin|baseline|spec}/... 경로에서 corp를 뽑는다. 아니면 None."""
    if not path:
        return None
    parts = PurePosixPath(path).parts
    if len(parts) >= 3 and parts[0] == PROJECTS_DIR and parts[2] in CORP_SUBDIRS:
        return parts[1]
    return None


def is_corp_project_dir(root, corp: str) -> bool:
    """corp가 실재하는 회사 프로젝트 스캐폴드인지 — baseline/·spec/ 하위가 모두 있어야 True.

    origin만 있고 baseline/spec이 없는 상태(예: origin staging 잔재)는 프로젝트로 보지 않는다.
    `root`는 MarkdownRoot(중복 import 회피로 duck-typed).
    """
    if not corp or corp.startswith("."):
        return False
    return root.is_dir(corp_subdir(corp, BASELINE)) and root.is_dir(corp_subdir(corp, SPEC))


def list_project_corps(root) -> list[str]:
    """projects/ 바로 아래의 회사 프로젝트 corp slug 목록(정렬). staging(.) 항목은 제외한다."""
    names = root.list_child_names(PROJECTS_DIR)
    return [name for name in names if is_corp_project_dir(root, name)]


class EmptyCorpNameError(Exception):
    """회사명 trim/slugify 후 빈 값 (AXKG-SPEC-014 EMPTY_CORP_NAME)."""


class SlugConflictError(Exception):
    """slug가 기존 corp와 충돌 + on_conflict 미지정 (AXKG-SPEC-014 SLUG_CONFLICT, 409)."""

    def __init__(self, slug: str) -> None:
        super().__init__(f"slug conflict: {slug}")
        self.slug = slug


class InvalidOnConflictError(Exception):
    """on_conflict 값이 merge/create_new가 아님 (AXKG-SPEC-014 INVALID_ON_CONFLICT)."""


class ProjectNotFoundError(Exception):
    """대상 corp 프로젝트 스캐폴드 부재 (AXKG-SPEC-014 PROJECT_NOT_FOUND, 404)."""

    def __init__(self, corp: str) -> None:
        super().__init__(f"project not found: {corp}")
        self.corp = corp


_ON_CONFLICT_MERGE = "merge"
_ON_CONFLICT_CREATE_NEW = "create_new"


def _ensure_corp_dirs(root, corp: str) -> None:
    """corp 프로젝트의 origin/baseline/spec 디렉토리를 만든다(멱등).

    v1은 map.md 스캐폴드/재생성을 만들지 않는다(후속 WP — SPEC-014 설계 계약은 유지).
    """
    for sub in CORP_SUBDIRS:
        root.mkdirs(corp_subdir(corp, sub))


def _next_free_suffix_slug(root, slug: str) -> str:
    """slug-2, slug-3 … 중 아직 corp 프로젝트로 존재하지 않는 첫 slug (충돌 신규 분기)."""
    n = 2
    while True:
        candidate = f"{slug}-{n}"
        if not is_corp_project_dir(root, candidate):
            return candidate
        n += 1


def slug_preview(root, name: str) -> dict:
    """회사명 → {slug, conflict}. 빈 slug는 EmptyCorpNameError (AXKG-SPEC-014 U-1)."""
    slug = slugify(name)
    if not slug:
        raise EmptyCorpNameError
    return {"slug": slug, "conflict": is_corp_project_dir(root, slug)}


def company_root_markdown(slug: str, name: str, *, domain: str | None = None,
                          intro: str | None = None) -> str:
    """회사 루트 앵커 `{corp}.md` 본문 (WORK-013). document_type=company, stem={slug}.

    회사당 1개의 안정적 앵커(요구 docx가 늘어도 불변). 모든 산출(baseline·context)이 `up:`으로
    이 문서(stem={slug})에 수렴한다(AXKG-DEC-009 D3). display 회사명은 alias로 둬 `[[회사명]]`도
    resolve된다.
    """
    display = (name or "").strip() or slug
    intro_line = (intro or "").strip() or "회사 배경 정보."
    domain_line = (domain or "").strip() or "-"
    return (
        "---\n"
        f"type: {COMPANY_DOCUMENT_TYPE}\n"
        f"title: {display}\n"
        f"aliases: [{display}]\n"
        "tags: []\n"
        "up: []\n"
        "---\n\n"
        f"# {display}\n\n"
        f"{intro_line}\n\n"
        f"- 도메인: {domain_line}\n\n"
        "## 회사 요약\n\n"
        "<!-- 이 회사의 요구사항(baseline/spec)과 배경지식(context)이 모두 이 루트로 수렴한다. -->\n"
    )


def _write_company_root(root, slug: str, name: str, domain: str | None,
                        intro: str | None) -> str | None:
    """회사 루트 문서를 없을 때만 쓴다(멱등, 기존 앵커 보존). 쓴 경우 rel 경로, 이미 있으면 None."""
    rel = company_root_path(slug)
    if root.exists(rel):
        return None
    root.write_new(rel, company_root_markdown(slug, name, domain=domain, intro=intro))
    return rel


def create_scaffold(root, name: str, on_conflict: str | None = None, *,
                    domain: str | None = None, intro: str | None = None) -> dict:
    """회사 프로젝트 스캐폴드 + **회사 루트 앵커 `{corp}.md`** 를 생성한다(WORK-013, DEC-009 D1).

    - 빈 회사명 → EmptyCorpNameError.
    - 충돌 없음 → projects/{slug}/{origin,baseline,spec,context}/ + {slug}.md 생성, {slug, created}.
    - 충돌 + on_conflict 미지정 → SlugConflictError(409, 사용자 결정 요구 분기).
    - 충돌 + merge → 기존 corp에 합류(디렉토리 멱등, 루트는 기존 보존), {slug, merged}.
    - 충돌 + create_new → {slug}-2 등 suffix 신규 생성 + 루트, {slug: newslug, created}.
    - on_conflict가 merge/create_new 외 값 → InvalidOnConflictError.

    반환 dict에 `root_path`(새로 쓴 회사 루트 rel 경로, 있으면)를 실어 라우트가 인덱싱하게 한다.
    업로드/분류와 별개인 수동 작업이다(AXKG-DEC-007 D2 회사 경계는 사람이 통제).
    """
    slug = slugify(name)
    if not slug:
        raise EmptyCorpNameError
    conflict = is_corp_project_dir(root, slug)
    if not conflict:
        _ensure_corp_dirs(root, slug)
        root_path = _write_company_root(root, slug, name, domain, intro)
        return {"slug": slug, "created": True, "root_path": root_path}
    if on_conflict is None:
        raise SlugConflictError(slug)
    if on_conflict == _ON_CONFLICT_MERGE:
        _ensure_corp_dirs(root, slug)
        root_path = _write_company_root(root, slug, name, domain, intro)  # 없을 때만
        return {"slug": slug, "merged": True, "root_path": root_path}
    if on_conflict == _ON_CONFLICT_CREATE_NEW:
        new_slug = _next_free_suffix_slug(root, slug)
        _ensure_corp_dirs(root, new_slug)
        root_path = _write_company_root(root, new_slug, name, domain, intro)
        return {"slug": new_slug, "created": True, "root_path": root_path}
    raise InvalidOnConflictError


# project 하위 sub-type 판정 — 메모 성격 힌트 우선 (AXKG-DEC-009 D2). 아래 힌트가 메모에 있으면
# context, 없으면 requirement(안전 폴백 — DEC-009 OQ 확정: 오분류 시 팬아웃 누락<노이즈).
_CONTEXT_MEMO_HINTS = (
    "context", "컨텍스트", "회사 정보", "회사정보", "회사 소개", "회사소개",
    "배경지식", "배경 지식", "배경 정보", "배경정보", "조직도", "조직 정보", "조직도야",
    "업무 플로우", "업무플로우", "워크플로우", "업무 흐름", "휴가", "vacation",
)


def resolve_project_subtype(memo: str | None) -> str:
    """intake 메모의 성격 힌트로 requirement/context를 판정한다(AXKG-DEC-009 D2, WORK-013 P2).

    메모 성격 힌트를 **우선 신호**로 쓴다(예: "SC 회사 정보야" → context). 힌트가 없으면
    안전 폴백 **requirement**(기존 팬아웃 경로) — 오분류 비용상 context를 기능으로 쪼개는 노이즈
    보다 요구를 팬아웃 누락하는 게 크다는 판단(DEC-009 OQ 확정). 내용 기반 AI 판단은 후속.
    """
    text = (memo or "").lower()
    if any(hint in text for hint in _CONTEXT_MEMO_HINTS):
        return SUBTYPE_CONTEXT
    return SUBTYPE_REQUIREMENT


def _list_md_stems(root, corp: str, sub: str) -> list[str]:
    """corp/{sub} 하위 항목 목록. origin은 원본 파일명 그대로, baseline/spec은 .md만."""
    names = root.list_child_names(corp_subdir(corp, sub))
    if sub == ORIGIN:
        return names
    return [n for n in names if n.lower().endswith(".md")]


def read_project_tree(root, corp: str) -> dict:
    """corp 프로젝트의 origin/baseline/spec 3층 트리(항목명 목록). 부재 시 ProjectNotFoundError.

    본문 렌더/열람 경계는 AXKG-SPEC-013 소관 — 여기서는 목록만 조립한다(AXKG-SPEC-014 U-3).
    """
    if not is_corp_project_dir(root, corp):
        raise ProjectNotFoundError(corp)
    return {
        "corp": corp,
        "folders": {sub: _list_md_stems(root, corp, sub) for sub in CORP_SUBDIRS},
    }


def resolve_corp(memo: str | None, corps: list[str]) -> str | None:
    """intake 메모(회사명) → 기존 corp 매칭. 없으면 None(팬아웃 skip, v1 범위 밖).

    v1 단순 규약(AXKG-DEC-007: 회사 경계는 사람이 통제 — 자동 추론/생성 금지):
    1) 메모를 slugify한 값이 기존 corp와 정확히 일치하면 그 corp.
    2) 아니면, 기존 corp slug가 slugify(메모)의 토큰(하이픈 분해)으로 나타나면 그 corp
       (가장 긴 corp 우선 — 더 구체적인 회사명 우선).
    매칭이 없으면 None — 프로젝트 선행 생성 전제이며 자동 생성하지 않는다.
    """
    if not memo or not corps:
        return None
    memo_slug = slugify(memo)
    if not memo_slug:
        return None
    if memo_slug in corps:
        return memo_slug
    tokens = set(memo_slug.split("-"))
    matches = [c for c in corps if c in memo_slug or set(c.split("-")) <= tokens]
    if not matches:
        return None
    return max(matches, key=len)
