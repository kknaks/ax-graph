"""open-kknaks 실 바인딩 — RedisBroker + AgentClient (AXKG-SPEC-007). WP1 Phase 3.

확정 방향(admin 조사): HTTP가 아니라 **Redis broker 직결**이다. ax-graph는 api(producer)와
worker(`ClaudeWorker`, consumer)가 같은 Redis(`namespace=axkg`) + queue를 공유한다
(`apps/worker/run.py`). api는 producer로서 `AgentClient(RedisBroker)`를 쓴다.

매핑 (AXKG-SPEC-007 open-kknaks Task Mapping ↔ 실제 `AgentClient`):

| ABC(OpenKknaksClient) | AgentClient / Task |
|---|---|
| `submit_task(request)` | `client.submit(prompt, provider, model, options, provider_options, metadata, queue, max_retries)` → task_id |
| `get_task_status(id)`  | `client.status(id)` → pending/running/done/failed/cancelled/retrying |
| `wait_result(id)`      | `client.result(id, timeout=)` → `Task` (XREAD BLOCK, 폴링 아님) |
| 결과 `Task.result`         | `OpenKknaksTaskResult.result_text` |
| 결과 `Task.result_session_id` | `.session_id` (AXKG-SPEC-002 재생성 resume 원천) |
| 결과 `Task.status`         | terminal status(done/failed/cancelled) |
| 결과 `Task.error`          | `.error` |

open-kknaks 패키지(`open-kknaks==2.0.2`)는 apps/api/pyproject.toml에 추가돼 있다.
`redis.asyncio` 연결은 broker.connect() 시점에만 일어나므로 import는 부작용이 없다.
"""
from __future__ import annotations

from open_kknaks.broker.redis import RedisBroker
from open_kknaks.client import AgentClient

from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)

# api producer가 worker와 공유하는 큐. worker run.py 의 QUEUES 기본값과 일치시킨다.
DEFAULT_QUEUE = "default"

# terminal 로 취급하는 open-kknaks status.
_TERMINAL = {"done", "failed", "cancelled"}


class RedisOpenKknaksClient(OpenKknaksClient):
    """RedisBroker 위의 AgentClient를 AXKG의 OpenKknaksClient ABC로 감싼다."""

    def __init__(self, client: AgentClient, *, queue: str = DEFAULT_QUEUE) -> None:
        self._client = client
        self._queue = queue

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        """AgentClient.submit로 enqueue하고 task id를 반환한다.

        options.timeout_sec 등 실행 파라미터는 worker(TimeoutMiddleware/adapter)가 소비한다.
        max_retries는 여기서 0으로 둔다 — 재시도는 AXKG가 retry_of_task_id 새 row로 소유한다
        (SPEC-002/011). broker 레벨 자동 재시도와 이중이 되지 않게 한다.
        """
        return await self._client.submit(
            request.prompt,
            context=request.context,
            queue=self._queue,
            provider=request.provider,
            model=request.model,
            options=request.options,
            provider_options=request.provider_options,
            metadata=request.metadata,
            max_retries=0,
        )

    async def get_task_status(self, task_id: str) -> str | None:
        return await self._client.status(task_id)

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        """terminal까지 대기(XREAD BLOCK)하고 결과를 AXKG DTO로 변환한다.

        - task를 못 찾으면(None) submit 자체 유실로 보고 failed로 표면화한다.
        - timeout 이후에도 terminal이 아니면 cancelled가 아닌 failed로 처리한다
          (파이프라인이 OPEN_KKNAKS_TASK_FAILED로 매핑).
        """
        timeout = timeout_sec if timeout_sec is not None else 600.0
        task = await self._client.result(task_id, timeout=timeout)
        if task is None:
            return OpenKknaksTaskResult(
                task_id=task_id,
                status="failed",
                error="open-kknaks task를 찾을 수 없음(제출 유실 또는 만료)",
            )
        status = task.status if task.status in _TERMINAL else "failed"
        error = task.error
        if status == "failed" and task.status not in _TERMINAL:
            error = error or f"timeout {timeout}s 내 미완료 (last status={task.status})"
        return OpenKknaksTaskResult(
            task_id=task.id,
            status=status,  # type: ignore[arg-type]
            result_text=task.result,
            session_id=task.result_session_id,
            error=error,
        )


async def create_redis_open_kknaks_client(
    redis_url: str, *, namespace: str = "axkg", queue: str = DEFAULT_QUEUE
) -> tuple[RedisOpenKknaksClient, RedisBroker]:
    """broker를 연결하고 client를 만든다. broker는 호출측이 close 생명주기를 소유한다."""
    broker = RedisBroker(url=redis_url, namespace=namespace)
    await broker.connect()
    return RedisOpenKknaksClient(AgentClient(broker), queue=queue), broker
