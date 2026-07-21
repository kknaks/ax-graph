"""projects API 스키마 (AXKG-SPEC-014 §4, WP11 Phase 5). "프로젝트 추가"(수동 스캐폴드)·트리."""
from pydantic import BaseModel


class SlugPreviewResponse(BaseModel):
    slug: str
    conflict: bool


class CreateProjectRequest(BaseModel):
    name: str
    # 충돌 시에만 필수: "merge"(합류) | "create_new"(suffix 신규).
    on_conflict: str | None = None


class CreateProjectResponse(BaseModel):
    slug: str
    created: bool = False
    merged: bool = False


class ProjectSummary(BaseModel):
    corp: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]


class ProjectFolders(BaseModel):
    origin: list[str]
    baseline: list[str]
    spec: list[str]


class ProjectTreeResponse(BaseModel):
    corp: str
    folders: ProjectFolders
