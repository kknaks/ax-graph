"""문서 경로 매핑·조립 SSOT (AXKG-SPEC-004, PLAN-009-T-040).

AI는 파일명(create)/대상 stem(supplement)만 내고 **디렉토리는 시스템이 결정**한다.
경로 조립(wrap_documentation_output)과 안전망 검증(apply_executor)이 같은 매핑을 공유하도록
여기에 단일 정의를 둔다 — 중복 정의 금지.
"""
from __future__ import annotations

from pathlib import PurePosixPath

# main 초안 document_type → 허용 디렉토리 (AXKG-SPEC-005, DEC-005).
MAIN_DIR_BY_TYPE = {
    "reference": "resources/",
    "permanent": "permanent/",
    "baseline": "projects/",
}
# 파생 create suggestion_type → 허용 디렉토리 (Derived Knowledge Apply Matrix, SPEC-004).
# create_feature_spec(회사 프로젝트 팬아웃 기능정의서, WP11)는 projects/ 하위(구체 경로는
# projects/{corp}/spec/ — corp는 시스템이 조립, project_scaffold.project_spec_path)로 검증한다.
DERIVED_DIR_BY_TYPE = {
    "create_new_concept": "permanent/concepts/",
    "create_project_baseline": "projects/",
    "create_feature_spec": "projects/",
}


def normalize_filename(candidate: str | None) -> str:
    """AI filename_candidate → 파일명 stem+`.md`로 정규화한다.

    디렉토리 성분(AI가 실수로 붙인 `areas/`·`concepts/` 등)을 떼고 `.md`를 보장한다.
    빈 값/비어있는 stem이면 ""를 돌려준다(조립 측이 빈 경로로 처리 → executor 안전망행).
    """
    if not candidate:
        return ""
    name = PurePosixPath(candidate.strip()).name  # 디렉토리 성분 제거
    if name.lower().endswith(".md"):
        name = name[:-3]
    name = name.strip()
    return f"{name}.md" if name else ""


def assemble_main_path(document_type: str | None, filename_candidate: str | None) -> str:
    """main 초안 경로 = 타입 디렉토리 + 정규화된 파일명. 매핑/파일명 없으면 ""."""
    directory = MAIN_DIR_BY_TYPE.get(document_type or "")
    filename = normalize_filename(filename_candidate)
    return directory + filename if directory and filename else ""


def assemble_derived_create_path(
    suggestion_type: str | None, filename_candidate: str | None
) -> str:
    """파생 create 경로 = suggestion_type 디렉토리 + 정규화된 파일명. 없으면 ""."""
    directory = DERIVED_DIR_BY_TYPE.get(suggestion_type or "")
    filename = normalize_filename(filename_candidate)
    return directory + filename if directory and filename else ""
