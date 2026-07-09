"""graph 라우트 (AXKG-SPEC-005 · SPEC-006). 계약은 스펙 API Contract를 따른다.

- GET  /graph/documents                          : 문서 그래프 노드/엣지 (type=source 기본 제외)
- GET  /graph/documents/{id}/neighborhood        : 선택 노드 depth 이내 서브그래프
- POST /graph/search                             : keyword+edge distance retriever
- POST /graph/rebuild                            : cache 전체 재빌드(읽기 전용, Markdown 안 씀)
- GET  /graph/chats                              : 내 채팅 세션 목록 (SPEC-006, owner)
- POST /graph/chats                              : 새 채팅 + 첫 질문 run 생성 (queued)
- GET  /graph/chats/{chat_id}                    : 채팅 메시지 이력
- POST /graph/chats/{chat_id}/messages           : 기존 채팅에 질문 + 새 run 생성 (queued)
- GET  /graph/chats/{chat_id}/runs/{run_id}      : 응답 생성 run 폴링

retriever(POST /graph/search)는 chat(④)·문서화 게이트(③)가 공유하는 컴포넌트다.
채팅 run의 AI 실행(Graph RAG)은 Phase 2(T-012) 소관 — 이 라우터는 lifecycle·폴링 골격까지다.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.core.database import get_session
from axkg.core.security import get_current_user
from axkg.dto.auth import UserDTO
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.schemas.chat import (
    ChatDetailResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatRunResponse,
    ChatSessionListResponse,
    ChatSessionSummary,
    ChatStartRequest,
    ChatStartResponse,
)
from axkg.schemas.graph import (
    GraphDocumentsResponse,
    GraphRebuildResponse,
    GraphSearchRequest,
    GraphSearchResponse,
)
from axkg.services.chat import (
    ChatService,
    ChatSessionNotFoundError,
    EmptyQuestionError,
    NodeNotFoundError,
)
from axkg.services.documents import DocumentNotFoundError, DocumentService
from axkg.services.graph import GraphService
from axkg.services.graph_chat_execution import execute_graph_chat
from axkg.storage.markdown_root import MarkdownRoot

router = APIRouter(prefix="/graph", tags=["graph"])


def _graph(session: AsyncSession) -> GraphService:
    return GraphService(session, root=MarkdownRoot(settings.axkg_markdown_root))


def _open_kknaks_client(request: Request) -> OpenKknaksClient | None:
    """앱 수명에 바인딩된 open-kknaks client (미구성 시 None → chat 실행 트리거 생략)."""
    return getattr(request.app.state, "open_kknaks_client", None)


def _chat_session_factory(request: Request):
    """background chat 실행이 쓸 session factory (미설정 시 runner 기본값 사용)."""
    return getattr(request.app.state, "session_factory", None)


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


@router.get("/documents", response_model=GraphDocumentsResponse)
async def graph_documents(
    session: AsyncSession = Depends(get_session),
) -> GraphDocumentsResponse:
    view = await _graph(session).graph_documents()
    return GraphDocumentsResponse.from_view(view)


@router.get(
    "/documents/{document_id}/neighborhood", response_model=GraphDocumentsResponse
)
async def graph_neighborhood(
    document_id: uuid.UUID,
    depth: int = Query(default=1, ge=1, le=3),
    session: AsyncSession = Depends(get_session),
) -> GraphDocumentsResponse:
    try:
        await DocumentService(session).get_document(document_id)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DOCUMENT_NOT_FOUND",
                "message": f"문서 없음: {document_id}",
            },
        )
    view = await _graph(session).neighborhood(document_id, depth=depth)
    return GraphDocumentsResponse.from_view(view)


@router.post("/search", response_model=GraphSearchResponse)
async def graph_search(
    body: GraphSearchRequest,
    session: AsyncSession = Depends(get_session),
) -> GraphSearchResponse:
    """keyword + edge distance retriever. selected_stem이 있으면 그 노드 neighborhood 우선."""
    graph = _graph(session)
    kwargs: dict = {"selected_stem": body.selected_stem}
    if body.top_n is not None:
        kwargs["top_n"] = body.top_n
    result = await graph.retrieve(body.query, **kwargs)
    return GraphSearchResponse.from_result(result)


@router.post("/rebuild", response_model=GraphRebuildResponse)
async def graph_rebuild(
    session: AsyncSession = Depends(get_session),
) -> GraphRebuildResponse:
    """documents/document_edges cache 전체 재빌드 (SPEC-005 POST /graph/rebuild).

    Markdown을 읽기만 한다(DEC-002). request session에서 동기로 수행하고 커밋은 DI가 한다.
    """
    stats = await _graph(session).rebuild_all()
    return GraphRebuildResponse.from_stats(stats)


# ---------------------------------------------------------------------------
# Graph Chat (AXKG-SPEC-006) — owner 스코프. run은 queued로 생성, 실행은 Phase 2(T-012).
# ---------------------------------------------------------------------------


def _chat_session_not_found(chat_id: uuid.UUID) -> HTTPException:
    # 타 유저 세션 접근도 여기로 온다(존재 은닉 → 404, owner 스코프).
    return _error(404, "CHAT_SESSION_NOT_FOUND", f"채팅 세션 없음: {chat_id}")


async def _trigger_chat_execution(
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession,
    run_id: uuid.UUID,
) -> None:
    """queued chat run의 Graph RAG 실행을 background로 연결한다(open-kknaks 구성 시).

    sources.py의 요약 배선과 동일 구조: background task는 get_session yield-teardown 커밋보다
    먼저 실행되므로, 여기서 명시적으로 커밋해 background(별도 session)가 run을 볼 수 있게 한다.
    """
    client = _open_kknaks_client(request)
    if client is None:
        return
    await session.commit()
    background.add_task(
        execute_graph_chat,
        run_id,
        client=client,
        session_factory=_chat_session_factory(request),
    )


@router.get("/chats", response_model=ChatSessionListResponse)
async def list_chats(
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatSessionListResponse:
    sessions = await ChatService(session).list_sessions(user.id)
    return ChatSessionListResponse(
        chats=[ChatSessionSummary.from_dto(s) for s in sessions]
    )


@router.post("/chats", response_model=ChatStartResponse, status_code=201)
async def create_chat(
    body: ChatStartRequest,
    request: Request,
    background: BackgroundTasks,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatStartResponse:
    """새 채팅 세션 + 첫 사용자 메시지(seq=1) + queued run (SPEC-006 POST /graph/chats).

    open-kknaks 구성 시 run의 Graph RAG 실행을 background로 트리거한다(폴링으로 결과 수신).
    미구성 시엔 queued로 남긴다(FE가 폴링 중 queued를 관측).
    """
    try:
        chat, message, run = await ChatService(session).start_chat(
            user_id=user.id,
            question=body.question,
            selected_node_id=body.selected_node_id,
            filters=body.filters,
        )
    except EmptyQuestionError:
        raise _error(422, "EMPTY_QUESTION", "질문을 입력해 주세요.")
    except NodeNotFoundError:
        raise _error(404, "NODE_NOT_FOUND", "선택한 문서를 찾지 못했습니다.")
    await _trigger_chat_execution(request, background, session, run.id)
    return ChatStartResponse(
        chat_id=chat.id,
        run_id=run.id,
        status=run.status,
        user_message_id=message.id,
    )


@router.get("/chats/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(
    chat_id: uuid.UUID,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatDetailResponse:
    try:
        chat, messages = await ChatService(session).get_session_detail(user.id, chat_id)
    except ChatSessionNotFoundError:
        raise _chat_session_not_found(chat_id)
    return ChatDetailResponse.from_dto(chat, messages)


@router.post(
    "/chats/{chat_id}/messages", response_model=ChatMessageResponse, status_code=201
)
async def add_chat_message(
    chat_id: uuid.UUID,
    body: ChatMessageRequest,
    request: Request,
    background: BackgroundTasks,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatMessageResponse:
    """기존 채팅에 질문 추가 + 새 queued run (SPEC-006 POST /graph/chats/{id}/messages)."""
    try:
        message, run = await ChatService(session).add_message(
            user_id=user.id,
            session_id=chat_id,
            question=body.question,
            selected_node_id=body.selected_node_id,
            filters=body.filters,
        )
    except ChatSessionNotFoundError:
        raise _chat_session_not_found(chat_id)
    except EmptyQuestionError:
        raise _error(422, "EMPTY_QUESTION", "질문을 입력해 주세요.")
    except NodeNotFoundError:
        raise _error(404, "NODE_NOT_FOUND", "선택한 문서를 찾지 못했습니다.")
    await _trigger_chat_execution(request, background, session, run.id)
    return ChatMessageResponse(
        run_id=run.id, status=run.status, user_message_id=message.id
    )


@router.get("/chats/{chat_id}/runs/{run_id}", response_model=ChatRunResponse)
async def get_chat_run(
    chat_id: uuid.UUID,
    run_id: uuid.UUID,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatRunResponse:
    """응답 생성 run 폴링. 성공 run은 result_payload에서 answer/evidence를 조립해 반환한다.

    - succeeded + assistant_message_id: answer/evidence_documents/evidence_edges/used_paths/
      confidence/missing_context/suggested_actions를 run.result_payload에서 채워 준다.
    - succeeded + error_code=INSUFFICIENT_GRAPH_CONTEXT: 단정 answer 없이 missing_context로 표면화.
    - failed: error_code/error_message. queued/running: status만(FE가 폴링 지속).
    """
    try:
        run, assistant_message = await ChatService(session).get_run_detail(
            user.id, chat_id, run_id
        )
    except ChatSessionNotFoundError:
        raise _chat_session_not_found(chat_id)
    return ChatRunResponse.from_dto(run, assistant_message=assistant_message)
