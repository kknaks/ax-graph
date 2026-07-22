"""projects API 스키마 (AXKG-SPEC-014 §4, WP11 Phase 5). "프로젝트 추가"(수동 스캐폴드)·트리."""
from pydantic import BaseModel


class SlugPreviewResponse(BaseModel):
    slug: str
    conflict: bool


class CreateProjectRequest(BaseModel):
    name: str
    # 충돌 시에만 필수: "merge"(합류) | "create_new"(suffix 신규).
    on_conflict: str | None = None
    # 회사 간략정보 (WORK-013 P1) — 회사 루트 {corp}.md에 반영. 선택 입력.
    domain: str | None = None
    intro: str | None = None


class CreateProjectResponse(BaseModel):
    slug: str
    created: bool = False
    merged: bool = False
    # 회사 루트 문서 경로(새로 쓴 경우). 이미 있으면 None (WORK-013).
    root_path: str | None = None


class ProjectSummary(BaseModel):
    corp: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]


class ProjectFolders(BaseModel):
    origin: list[str]
    baseline: list[str]
    spec: list[str]
    # 회사 배경지식 단일 문서 층 (WORK-013). 구형 프로젝트는 빈 목록.
    context: list[str] = []


class ProjectTreeResponse(BaseModel):
    corp: str
    folders: ProjectFolders
