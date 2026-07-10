"""AXKG FastAPI 엔트리포인트.

라우터 소유 스펙은 40-architecture/system README의 API Surface를 따른다.

인증 (AXKG-SPEC-008):
- auth 외 모든 라우터에 Bearer 검증 dependency를 기본 적용한다.
- 제외: `/health`, `/integrations/*`, `POST /api/v1/slack/commands` — Slack intake는
  Slack signing secret 검증 소관(AXKG-SPEC-003)이라 Bearer dependency를 걸지 않는다.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from axkg.api.routes import (
    auth,
    sources,
    integrations,
    slack,
    approval_gates,
    documentation_gates,
    documents,
    graph,
    settings,
    prompts,
    templates,
    users,
)
from axkg.config import settings as app_settings
from axkg.core.security import get_current_auth, require_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    """open-kknaks Redis broker/client 생명주기 (AXKG-SPEC-007, WP1 Phase 3).

    `AXKG_REDIS_URL`이 설정된 경우에만 producer client를 연결한다. 미설정(테스트/오프라인)
    이면 `app.state.open_kknaks_client=None` — 요약 자동 트리거는 조용히 생략된다.
    worker(`apps/worker`)가 같은 Redis(namespace=axkg)의 consumer다.
    """
    client = None
    broker = None
    if app_settings.axkg_redis_url:
        # 지연 import — open-kknaks 미설치 환경에서 앱 임포트가 깨지지 않게.
        from axkg.integrations.redis_open_kknaks import create_redis_open_kknaks_client

        client, broker = await create_redis_open_kknaks_client(
            app_settings.axkg_redis_url, namespace="axkg"
        )
    app.state.open_kknaks_client = client
    app.state.open_kknaks_broker = broker
    # Slack 봇 아웃바운드 client (AXKG-SPEC-003 S-1). 토큰 미설정이면 None → 앵커/회신 생략.
    from axkg.integrations.slack import SlackBotClient, SlackIdempotencyStore

    app.state.slack_bot_client = (
        SlackBotClient(app_settings.axkg_slack_bot_token)
        if app_settings.axkg_slack_bot_token
        else None
    )
    # 슬래시 더블서밋 차단용 in-memory 멱등 집합.
    app.state.slack_idempotency = SlackIdempotencyStore()
    # background 요약 실행용 factory (runner 기본값과 동일하나 명시 주입으로 테스트 가능).
    from axkg.core.database import get_session_factory

    app.state.session_factory = get_session_factory()
    # graph cache startup scan (AXKG-SPEC-005 WP2): document root의 변경분만 증분 rebuild.
    # best-effort — root/DB 미준비(로컬/오프라인)여도 startup을 막지 않는다(POST /graph/rebuild로 수동 가능).
    import logging

    from axkg.storage.markdown_root import MarkdownRoot

    if MarkdownRoot(app_settings.axkg_markdown_root).root.is_dir():
        try:
            from axkg.workers.graph_rebuild import run_startup_scan

            await run_startup_scan(session_factory=app.state.session_factory)
        except Exception:  # noqa: BLE001 — startup은 캐시 스캔 실패로 죽지 않는다.
            logging.getLogger("axkg.main").warning(
                "graph startup scan skipped (root/DB not ready)", exc_info=True
            )
    try:
        yield
    finally:
        if broker is not None:
            await broker.close()
        if app.state.slack_bot_client is not None:
            await app.state.slack_bot_client.aclose()


app = FastAPI(title="AX Knowledge Graph API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in app_settings.axkg_cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
# Slack 서명 검증 소관 — Bearer 제외 (AXKG-SPEC-008 예외).
app.include_router(integrations.router)
# POST /api/v1/slack/commands — Slack 등록 Request URL 문자 일치, signing secret 보호.
app.include_router(slack.router)

# AXKG-SPEC-008 Access Boundary Matrix — BE 라우트 authz(실제 방어선).
# admin 전용: 소스 inbox/수집, 분류②·문서화③ 승인 게이트, 설정, 유저 관리.
# staff+admin(로그인만): 그래프 시각화 + 채팅④, 문서(그래프 노드) 열람.
_ADMIN_ROUTERS = (
    sources.router,
    approval_gates.router,
    documentation_gates.router,
    settings.router,
    prompts.router,
    templates.router,
    users.router,
)
_AUTHENTICATED_ROUTERS = (
    documents.router,
    graph.router,
)
for _router in _ADMIN_ROUTERS:
    app.include_router(_router, dependencies=[Depends(require_admin)])
for _router in _AUTHENTICATED_ROUTERS:
    app.include_router(_router, dependencies=[Depends(get_current_auth)])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
