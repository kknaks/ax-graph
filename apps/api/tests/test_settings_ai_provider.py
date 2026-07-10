"""AXKG-SPEC-007 AI Provider 설정 API 테스트 (WP5 Phase 1).

커버:
- GET 기본값(설정 없을 때 claude) / seeded GET / PUT 저장 후 GET 반영
- PUT task-override: 등록+enabled key 수락, 미등록·disabled key 거부
- DELETE task-override 제거
- validation: unsupported provider / timeout·max_turns·effort 범위 밖 거부(에러코드 정확)
- health 조회 형태(claude/codex status)
- 비소급: 기존 queued ai_task snapshot이 설정 변경 후에도 불변
- owner 스코프/미인증 401
"""
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models import AiTaskDefinition, Setting
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.services.ai import ContextBuilderRegistry
from axkg.services.ai.pipeline import AiExecutionService
from axkg.services.settings import SettingsService

SEED_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"


class _DummyClient(OpenKknaksClient):
    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        return "okk-x"

    async def get_task_status(self, task_id: str) -> str | None:
        return "done"

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(task_id=task_id, status="done")


async def _auth(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


# ---------------------------------------------------------------------------
# 조회 / 저장
# ---------------------------------------------------------------------------


async def test_get_default_when_no_setting_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # ai_provider row를 지우면 서비스는 SPEC-007 MVP 기본값(claude)을 돌려준다.
    async with session_factory() as session:
        await session.execute(sa.delete(Setting).where(Setting.key == "ai_provider"))
        await session.commit()
        value = await SettingsService(session).get_ai_provider()
        assert value["provider"] == "claude"
        assert value["model"] is None
        assert value.get("updated_at") is None


async def test_get_seeded_ai_provider(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.get("/settings/ai-provider", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "claude"
    assert body["options"]["timeout_sec"] == 300
    assert body["provider_options"]["effort"] == "medium"
    # PLAN-010-T-011: 실행 6개 task 전부 model=claude-sonnet-4-6 오버라이드 시드.
    assert body["task_overrides"] == {
        "collect_source_summary": {"model": "claude-sonnet-4-6"},
        "generate_classification_gate": {"model": "claude-sonnet-4-6"},
        "regenerate_classification_gate": {"model": "claude-sonnet-4-6"},
        "generate_documentation_gate": {"model": "claude-sonnet-4-6"},
        "regenerate_documentation_gate": {"model": "claude-sonnet-4-6"},
        "graph_rag_chat": {"model": "claude-sonnet-4-6"},
    }


async def test_put_then_get_reflects(client: AsyncClient) -> None:
    headers = await _auth(client)
    put = await client.put(
        "/settings/ai-provider",
        json={
            "provider": "codex",
            "model": "gpt-5",
            "options": {"timeout_sec": 600, "resume": True},
            "provider_options": {"max_turns": 10, "effort": "high"},
        },
        headers=headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["provider"] == "codex"
    assert put.json()["updated_at"] is not None

    got = (await client.get("/settings/ai-provider", headers=headers)).json()
    assert got["provider"] == "codex"
    assert got["model"] == "gpt-5"
    assert got["options"]["timeout_sec"] == 600
    assert got["provider_options"]["max_turns"] == 10


async def test_put_preserves_task_overrides(client: AsyncClient) -> None:
    headers = await _auth(client)
    # 먼저 override를 심고
    await client.put(
        "/settings/ai-provider/task-overrides/graph_rag_chat",
        json={"provider_options": {"max_turns": 8}},
        headers=headers,
    )
    # 전역 PUT은 task_overrides를 보존해야 한다.
    put = await client.put(
        "/settings/ai-provider",
        json={"provider": "claude", "options": {}, "provider_options": {}},
        headers=headers,
    )
    assert put.status_code == 200
    assert "graph_rag_chat" in put.json()["task_overrides"]


# ---------------------------------------------------------------------------
# task override CRUD
# ---------------------------------------------------------------------------


async def test_put_task_override_accepts_enabled_key(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.put(
        "/settings/ai-provider/task-overrides/graph_rag_chat",
        json={
            "model": "claude-x",
            "options": {"timeout_sec": 600, "resume": True},
            "provider_options": {"max_turns": 6, "effort": "high"},
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    override = res.json()["task_overrides"]["graph_rag_chat"]
    assert override["model"] == "claude-x"
    assert override["options"]["timeout_sec"] == 600
    assert override["provider_options"]["effort"] == "high"


async def test_put_task_override_rejects_unknown_key(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.put(
        "/settings/ai-provider/task-overrides/not_a_real_task",
        json={"provider_options": {"max_turns": 5}},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "UNKNOWN_TASK_DEFINITION"


async def test_put_task_override_rejects_disabled_key(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # 등록됐지만 enabled=false인 definition은 override 대상이 아니다.
    async with session_factory() as session:
        await session.execute(
            sa.update(AiTaskDefinition)
            .where(AiTaskDefinition.key == "graph_rag_chat")
            .values(enabled=False)
        )
        await session.commit()
    headers = await _auth(client)
    res = await client.put(
        "/settings/ai-provider/task-overrides/graph_rag_chat",
        json={"provider_options": {"max_turns": 5}},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "UNKNOWN_TASK_DEFINITION"


async def test_delete_task_override_removes(client: AsyncClient) -> None:
    headers = await _auth(client)
    await client.put(
        "/settings/ai-provider/task-overrides/graph_rag_chat",
        json={"provider_options": {"max_turns": 8}},
        headers=headers,
    )
    res = await client.delete(
        "/settings/ai-provider/task-overrides/graph_rag_chat", headers=headers
    )
    assert res.status_code == 200
    assert "graph_rag_chat" not in res.json()["task_overrides"]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


async def test_unsupported_provider_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.put(
        "/settings/ai-provider",
        json={"provider": "gemini", "options": {}, "provider_options": {}},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "UNSUPPORTED_PROVIDER"


async def test_timeout_out_of_range_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.put(
        "/settings/ai-provider",
        json={"provider": "claude", "options": {"timeout_sec": 5}, "provider_options": {}},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "INVALID_EXECUTION_LIMIT"


async def test_max_turns_out_of_range_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.put(
        "/settings/ai-provider",
        json={
            "provider": "claude",
            "options": {},
            "provider_options": {"max_turns": 99},
        },
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "INVALID_EXECUTION_LIMIT"


async def test_invalid_effort_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.put(
        "/settings/ai-provider",
        json={
            "provider": "claude",
            "options": {},
            "provider_options": {"effort": "extreme"},
        },
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "INVALID_EXECUTION_LIMIT"


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


async def test_health_returns_provider_statuses(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.get("/settings/ai-provider/health", headers=headers)
    assert res.status_code == 200
    providers = {p["provider"]: p for p in res.json()["providers"]}
    assert set(providers) == {"claude", "codex"}
    # seed 기본 provider(claude)는 available, 나머지는 unknown.
    assert providers["claude"]["status"] == "available"
    assert providers["codex"]["status"] == "unknown"


# ---------------------------------------------------------------------------
# 비소급 (설정 변경이 기존 queued task snapshot에 소급되지 않음)
# ---------------------------------------------------------------------------


async def test_settings_change_not_retroactive_to_existing_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 1) 현재 설정(claude)으로 task 생성 → snapshot 고정.
    async with session_factory() as session:
        service = AiExecutionService(
            session, client=_DummyClient(), registry=ContextBuilderRegistry()
        )
        task = await service.create_task("graph_rag_chat")
        await session.commit()
        task_id = task.id
        original_provider = task.provider
        original_options = dict(task.options)

    # 2) 전역 설정을 codex + 다른 limits로 바꾼다.
    async with session_factory() as session:
        await SettingsService(session).put_ai_provider(
            provider="codex",
            model="gpt-5",
            options={"timeout_sec": 600, "resume": True},
            provider_options={"max_turns": 12, "effort": "high"},
        )
        await session.commit()

    # 3) 기존 queued task snapshot은 그대로여야 한다(소급 없음).
    async with session_factory() as session:
        reloaded = await AiTaskRepository(session).get(task_id)
        assert reloaded.status == "queued"
        assert reloaded.provider == original_provider
        assert reloaded.options == original_options


# ---------------------------------------------------------------------------
# 문서화 실행 옵션 시드 정합 (PLAN-009-T-035, 2026-07-09 라이브 실측)
# ---------------------------------------------------------------------------


async def test_documentation_gate_seed_execution_options(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # seed가 문서화③ 2건에 max_turns 12 / timeout_sec 600을 SSOT로 심어야 한다
    # (DB 리셋 후에도 라이브 실측 값이 증발하지 않도록).
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(AiTaskDefinition).where(
                    AiTaskDefinition.key.in_(
                        ["generate_documentation_gate", "regenerate_documentation_gate"]
                    )
                )
            )
        ).scalars().all()
    by_key = {d.key: d for d in rows}
    assert set(by_key) == {
        "generate_documentation_gate",
        "regenerate_documentation_gate",
    }
    for definition in by_key.values():
        assert definition.default_provider_options == {"max_turns": 12}
        assert definition.default_options == {"timeout_sec": 600}


async def test_documentation_gate_resolved_config_reflects_seed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # definition 기본값이 실행 설정 해석에 병합돼 실제 queued task 스냅샷에 반영되는지 확인.
    async with session_factory() as session:
        service = AiExecutionService(
            session, client=_DummyClient(), registry=ContextBuilderRegistry()
        )
        doc_task = await service.create_task("generate_documentation_gate")
        # 전역 기본값(max_turns 20 / timeout_sec 300, T-012)은 그대로 — 문서화 정의만 override.
        summary_task = await service.create_task("collect_source_summary")
        await session.commit()

    assert doc_task.provider_options["max_turns"] == 12
    assert doc_task.options["timeout_sec"] == 600
    assert summary_task.provider_options["max_turns"] == 20
    assert summary_task.options["timeout_sec"] == 300


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/settings/ai-provider")).status_code == 401
    assert (
        await client.put(
            "/settings/ai-provider",
            json={"provider": "claude", "options": {}, "provider_options": {}},
        )
    ).status_code == 401
