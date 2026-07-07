"""open-kknaks task API client. provider credential은 여기(서버)까지만 (AXKG-SPEC-007). WP0 Phase 5.

open-kknaks의 확정 계약은 Python client(OKK-SPEC-003 AgentClient: submit/status/
result)와 Task 모델(OKK-SPEC-001)이고, AXKG가 붙을 원격 바인딩(HTTP 등)은 아직
코드로 확정되지 않았다. 그래서 여기서는 **최소 인터페이스만** 추상 클래스로 고정한다:

- task 생성(submit) / 상태 조회(status) / 결과 대기(result_text + session_id 반환)
- 필드 매핑은 AXKG-SPEC-007 "open-kknaks Task Mapping" 표를 따른다
  (prompt/context/provider/model/options/provider_options).

실제 바인딩은 `HttpOpenKknaksClient`에 TODO로 남긴다. 테스트는 fake 구현을 쓴다.
"""
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

# OKK-SPEC-001 terminal status: done / failed / cancelled
OpenKknaksTerminalStatus = Literal["done", "failed", "cancelled"]


class OpenKknaksTaskRequest(BaseModel):
    """open-kknaks Task 생성 입력 (AXKG-SPEC-007 매핑 표의 AX측 스냅샷)."""

    prompt: str
    context: str | None = None
    provider: str = "claude"
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenKknaksTaskResult(BaseModel):
    """terminal 상태의 open-kknaks task 결과 (OKK-SPEC-001 Task/TaskResult 발췌)."""

    task_id: str
    status: OpenKknaksTerminalStatus
    result_text: str | None = None
    # provider native session id (Claude session id / Codex thread id).
    # AXKG-SPEC-002 재생성 resume의 원천이다.
    session_id: str | None = None
    error: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class OpenKknaksClient(ABC):
    """AXKG가 의존하는 open-kknaks 최소 인터페이스."""

    @abstractmethod
    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        """task를 생성(enqueue)하고 open-kknaks task id를 반환한다."""

    @abstractmethod
    async def get_task_status(self, task_id: str) -> str | None:
        """저장된 task status(pending/running/done/failed/cancelled/retrying) 또는 None."""

    @abstractmethod
    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        """terminal까지 대기하고 결과(result_text + session_id)를 반환한다."""

    async def run_task(self, request: OpenKknaksTaskRequest) -> OpenKknaksTaskResult:
        """submit → terminal 대기 편의 경로. 파이프라인 스켈레톤의 기본 사용면."""
        task_id = await self.submit_task(request)
        timeout = request.options.get("timeout_sec")
        return await self.wait_result(task_id, timeout_sec=timeout)


class HttpOpenKknaksClient(OpenKknaksClient):
    """`AXKG_OPEN_KKNAKS_BASE_URL` 대상 실제 바인딩 자리.

    TODO(도메인 WP / open-kknaks 계약 확정 후):
    - OKK-SPEC-003 AgentClient의 원격 표면(HTTP 또는 broker 직결)이 코드로 확정되면
      submit/status/result를 바인딩한다.
    - 응답의 `result` → result_text, `result_session_id` → session_id 매핑.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        raise NotImplementedError("open-kknaks HTTP 바인딩 미확정 (OKK-SPEC-003 참고)")

    async def get_task_status(self, task_id: str) -> str | None:
        raise NotImplementedError("open-kknaks HTTP 바인딩 미확정 (OKK-SPEC-003 참고)")

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        raise NotImplementedError("open-kknaks HTTP 바인딩 미확정 (OKK-SPEC-003 참고)")
