"""AXKG FastAPI 엔트리포인트.

라우터 소유 스펙은 40-architecture/system README의 API Surface를 따른다.

인증 (AXKG-SPEC-008):
- auth 외 모든 라우터에 Bearer 검증 dependency를 기본 적용한다.
- 제외: `/health`, `/integrations/*` — Slack intake는 Slack signing secret
  검증 소관(AXKG-SPEC-003, WP1에서 구현)이라 Bearer dependency를 걸지 않는다.
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from axkg.api.routes import (
    auth,
    sources,
    integrations,
    approval_gates,
    documentation_gates,
    documents,
    graph,
    settings,
    prompts,
    templates,
)
from axkg.config import settings as app_settings
from axkg.core.security import get_current_auth

app = FastAPI(title="AX Knowledge Graph API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in app_settings.axkg_cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
# Slack 서명 검증 소관 — Bearer 제외 (AXKG-SPEC-008 예외).
app.include_router(integrations.router)

_PROTECTED_ROUTERS = (
    sources.router,
    approval_gates.router,
    documentation_gates.router,
    documents.router,
    graph.router,
    settings.router,
    prompts.router,
    templates.router,
)
for _router in _PROTECTED_ROUTERS:
    app.include_router(_router, dependencies=[Depends(get_current_auth)])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
