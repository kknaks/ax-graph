"""projects 라우트 (AXKG-SPEC-014 §4, WP11 Phase 5). "프로젝트 추가" 수동 스캐폴드 + corp 트리.

- GET  /projects:slug-preview?name=  : 회사명 → slug 미리보기 + 충돌 여부 (U-1)
- POST /projects                     : 회사 프로젝트 스캐폴드 생성/합류/신규 분기 (U-1/U-2)
- GET  /projects                     : 회사 프로젝트 목록(트리 루트) (U-3)
- GET  /projects/{corp}              : 한 corp의 origin/baseline/spec 트리 (U-3)

**수동·독립 스캐폴딩**이다 — 업로드/분류가 프로젝트를 자동 생성하지 않는다(AXKG-DEC-007 D2:
회사 경계는 사람이 통제). admin 전용(main.py `_ADMIN_ROUTERS`로 require_admin 등록).
스캐폴드는 origin/baseline/spec 3층 디렉토리만 만든다 — 폴더별 map.md 자동 재생성은 후속 WP.
"""
from fastapi import APIRouter, HTTPException

from axkg.config import settings as app_settings
from axkg.schemas.projects import (
    CreateProjectRequest,
    CreateProjectResponse,
    ProjectListResponse,
    ProjectSummary,
    ProjectTreeResponse,
    SlugPreviewResponse,
)
from axkg.services.project_scaffold import (
    EmptyCorpNameError,
    InvalidOnConflictError,
    ProjectNotFoundError,
    SlugConflictError,
    create_scaffold,
    list_project_corps,
    read_project_tree,
    slug_preview,
)
from axkg.storage.markdown_root import MarkdownRoot

router = APIRouter(tags=["projects"])


def _root() -> MarkdownRoot:
    return MarkdownRoot(app_settings.axkg_markdown_root)


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


@router.get("/projects:slug-preview", response_model=SlugPreviewResponse)
def preview_slug(name: str) -> SlugPreviewResponse:
    try:
        result = slug_preview(_root(), name)
    except EmptyCorpNameError:
        raise _error(400, "EMPTY_CORP_NAME", "회사명을 입력해 주세요.")
    return SlugPreviewResponse(**result)


@router.post("/projects", response_model=CreateProjectResponse, status_code=201)
def create_project(body: CreateProjectRequest) -> CreateProjectResponse:
    try:
        result = create_scaffold(_root(), body.name, on_conflict=body.on_conflict)
    except EmptyCorpNameError:
        raise _error(400, "EMPTY_CORP_NAME", "회사명을 입력해 주세요.")
    except SlugConflictError as exc:
        raise _error(
            409,
            "SLUG_CONFLICT",
            f"이미 '{exc.slug}' 프로젝트가 있습니다. 합류/새 프로젝트를 선택해 주세요.",
        )
    except InvalidOnConflictError:
        raise _error(400, "INVALID_ON_CONFLICT", "처리 방식을 다시 선택해 주세요.")
    return CreateProjectResponse(**result)


@router.get("/projects", response_model=ProjectListResponse)
def list_projects() -> ProjectListResponse:
    corps = list_project_corps(_root())
    return ProjectListResponse(projects=[ProjectSummary(corp=c) for c in corps])


@router.get("/projects/{corp}", response_model=ProjectTreeResponse)
def get_project(corp: str) -> ProjectTreeResponse:
    try:
        tree = read_project_tree(_root(), corp)
    except ProjectNotFoundError:
        raise _error(404, "PROJECT_NOT_FOUND", "대상 프로젝트를 찾을 수 없습니다.")
    return ProjectTreeResponse(**tree)
