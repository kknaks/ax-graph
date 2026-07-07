"""AI 실행 파이프라인 (AXKG-SPEC-011).

경로: ai_task 생성(queued, 설정 스냅샷) → definition 해석 → 프롬프트/템플릿
로드(실패 시 코드 fallback) → 블록 조립 → ai_tasks 조립 스냅샷 → open-kknaks
실행(running) → open_kknaks_task_id/session_id 저장 → 출력 JSON 파싱
(OUTPUT_PARSE_FAILED) → output_schema 검증(OUTPUT_SCHEMA_MISMATCH) → 성공 시
handler.handle_result로 전달. 검증 실패 출력은 어떤 필드도 소비하지 않는다.

재시도: 실패 task는 불변, retry_of_task_id로 새 row (AXKG-SPEC-002).
"""
import json
import uuid
from typing import Any

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDTO, AssembledInputDTO, PromptVersionDTO, TemplateVersionDTO
from axkg.integrations.open_kknaks import OpenKknaksClient, OpenKknaksTaskRequest
from axkg.repositories.ai_task_definitions import AiTaskDefinitionRepository
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.document_templates import DocumentTemplateRepository
from axkg.repositories.prompts import PromptRepository
from axkg.repositories.settings import SettingRepository
from axkg.services.ai import fallbacks
from axkg.services.ai.assembly import assemble_input
from axkg.services.ai.context import ContextBuilderRegistry
from axkg.services.ai.resolution import resolve_execution_config

AI_PROVIDER_SETTINGS_KEY = "ai_provider"

# Case Matrix (AXKG-SPEC-011) + 실행측 실패 코드
ERROR_OUTPUT_PARSE_FAILED = "OUTPUT_PARSE_FAILED"
ERROR_OUTPUT_SCHEMA_MISMATCH = "OUTPUT_SCHEMA_MISMATCH"
# open-kknaks 전달 자체가 실패 (SPEC-007 Case Matrix)
ERROR_AI_TASK_SUBMIT_FAILED = "AI_TASK_SUBMIT_FAILED"
# open-kknaks task가 terminal failed/cancelled로 끝남 (SPEC-011 Case Matrix 밖 — 실행측 코드)
ERROR_OPEN_KKNAKS_TASK_FAILED = "OPEN_KKNAKS_TASK_FAILED"


class TaskDefinitionNotFoundError(Exception):
    """등록되지 않았거나 비활성인 ai_task_definitions key."""

    def __init__(self, task_type: str) -> None:
        super().__init__(f"unknown or disabled ai_task_definition: {task_type}")
        self.task_type = task_type


class RetryNotAllowedError(Exception):
    """failed가 아닌 task의 retry 시도 (SPEC-002 retry 규칙)."""

    def __init__(self, task_id: uuid.UUID, status: str) -> None:
        super().__init__(f"retry not allowed: task {task_id} status={status}")
        self.task_id = task_id
        self.status = status


class AiExecutionService:
    """AI 실행 골격 서비스 — session은 repositories로만 전달한다."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        client: OpenKknaksClient,
        registry: ContextBuilderRegistry,
    ) -> None:
        self._definitions = AiTaskDefinitionRepository(session)
        self._prompts = PromptRepository(session)
        self._templates = DocumentTemplateRepository(session)
        self._settings = SettingRepository(session)
        self._tasks = AiTaskRepository(session)
        self._client = client
        self._registry = registry

    # ------------------------------------------------------------------
    # 생성 / 재시도 체인
    # ------------------------------------------------------------------

    async def create_task(
        self,
        task_type: str,
        *,
        source_id: uuid.UUID | None = None,
        gate_id: uuid.UUID | None = None,
        revision_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AiTaskDTO:
        """queued ai_task 생성. 실행 설정은 생성 시점에 해석·스냅샷한다.

        SPEC-007: 설정 변경은 기존 queued/running task에 소급 적용하지 않는다 —
        그래서 provider/model/options/provider_options는 생성 시점 값으로 고정된다.
        """
        definition = await self._resolve_definition(task_type)
        global_settings = await self._settings.get_value(AI_PROVIDER_SETTINGS_KEY)
        config = resolve_execution_config(global_settings, definition)
        return await self._tasks.create(
            task_type=task_type,
            task_definition_id=definition.id,
            provider=config.provider,
            model=config.model,
            options=config.options,
            provider_options=config.provider_options,
            source_id=source_id,
            gate_id=gate_id,
            revision_id=revision_id,
            payload=payload,
        )

    async def retry_task(self, failed_task_id: uuid.UUID) -> AiTaskDTO:
        """실패 task는 불변 보존, retry는 retry_of_task_id로 연결된 새 queued row.

        실행 설정은 다시 해석한다(재시도 시점의 설정 반영). resume session 후보도
        호출측이 `resolve_resume_session`으로 다시 계산한다(SPEC-002).
        """
        failed = await self._tasks.get(failed_task_id)
        if failed is None:
            raise LookupError(f"ai_task not found: {failed_task_id}")
        if failed.status != "failed":
            raise RetryNotAllowedError(failed_task_id, failed.status)

        definition = await self._resolve_definition(failed.task_type)
        global_settings = await self._settings.get_value(AI_PROVIDER_SETTINGS_KEY)
        config = resolve_execution_config(global_settings, definition)
        return await self._tasks.create(
            task_type=failed.task_type,
            task_definition_id=definition.id,
            provider=config.provider,
            model=config.model,
            options=config.options,
            provider_options=config.provider_options,
            source_id=failed.source_id,
            gate_id=failed.gate_id,
            revision_id=failed.revision_id,
            retry_of_task_id=failed.id,
            retry_count=failed.retry_count + 1,
        )

    async def get_retry_chain(self, task_id: uuid.UUID) -> list[AiTaskDTO]:
        return await self._tasks.get_retry_chain(task_id)

    async def resolve_resume_session(
        self,
        *,
        target_revision_session_id: str | None = None,
        original_task_id: uuid.UUID | None = None,
    ) -> str | None:
        """재생성 resume session 후보 계산 (AXKG-SPEC-002 open-kknaks Session Rule).

        1) target revision의 open_kknaks_session_id
        2) 없으면 원 task(ai_tasks.open_kknaks_session_id)
        3) 둘 다 없으면 None — stateless 재생성(컨텍스트 전체 주입은 호출측 소관).
        resume 전달 자체(options.resume 배선)는 도메인 WP 소관이다.
        """
        if target_revision_session_id:
            return target_revision_session_id
        if original_task_id is not None:
            task = await self._tasks.get(original_task_id)
            if task is not None:
                return task.open_kknaks_session_id
        return None

    # ------------------------------------------------------------------
    # 실행 파이프라인
    # ------------------------------------------------------------------

    async def execute_task(self, task_id: uuid.UUID) -> AiTaskDTO:
        """queued task를 해석→조립→스냅샷→실행→출력 처리까지 진행한다."""
        task = await self._tasks.get(task_id)
        if task is None:
            raise LookupError(f"ai_task not found: {task_id}")
        definition = await self._resolve_definition(task.task_type)
        builder = self._registry.get(definition.handler_kind)

        # 1) 프롬프트/템플릿 로드 (실패 시 코드 fallback — 파이프라인 중단 없음)
        fallback_codes: list[str] = []
        prompt_version = await self._load_active_prompt(definition.prompt_key)
        if prompt_version is not None:
            prompt_text = prompt_version.prompt_text
            output_schema = prompt_version.output_schema
            prompt_version_id = prompt_version.id
        else:
            prompt_text = fallbacks.FALLBACK_PROMPT_TEXT
            output_schema = fallbacks.FALLBACK_OUTPUT_SCHEMA
            prompt_version_id = None
            fallback_codes.append(fallbacks.PROMPT_FALLBACK_USED)

        template_body: str | None = None
        template_version_id: uuid.UUID | None = None
        template_key = builder.select_template_key(task, definition)
        if template_key is not None:
            template_version = await self._load_active_template(template_key)
            if template_version is not None:
                template_body = template_version.body
                template_version_id = template_version.id
            else:
                template_body = fallbacks.FALLBACK_TEMPLATE_BODY
                fallback_codes.append(fallbacks.TEMPLATE_FALLBACK_USED)

        # 2) 블록 조립 (변수 치환 없음 — assembly 모듈의 코드 고정 프레임)
        data_blocks = await builder.build_data_blocks(task, definition)
        assembled = assemble_input(
            prompt_text=prompt_text,
            output_schema=output_schema,
            prompt_version_id=prompt_version_id,
            data_blocks=data_blocks,
            template_body=template_body,
            template_version_id=template_version_id,
            fallback_codes=fallback_codes,
        )

        # 3) ai_tasks 스냅샷 — 조립 입력/버전/fallback 관찰 기록
        task = await self._tasks.set_assembly_snapshot(
            task_id,
            prompt_version_id=assembled.prompt_version_id,
            template_version_id=assembled.template_version_id,
            payload=self._snapshot_payload(task, assembled, template_key),
        )

        # 4) open-kknaks 실행
        task = await self._tasks.mark_running(task_id)
        request = OpenKknaksTaskRequest(
            prompt=assembled.render_prompt(),
            provider=task.provider,
            model=task.model,
            options=task.options,
            provider_options=task.provider_options,
            metadata={"axkg_task_id": str(task.id), "axkg_task_type": task.task_type},
        )
        try:
            result = await self._client.run_task(request)
        except Exception as exc:  # noqa: BLE001 — 실행 실패는 상태로 보존한다
            return await self._tasks.mark_failed(
                task_id, error_code=ERROR_AI_TASK_SUBMIT_FAILED, error_message=str(exc)
            )

        task = await self._tasks.set_open_kknaks_refs(
            task_id,
            open_kknaks_task_id=result.task_id,
            open_kknaks_session_id=result.session_id,
        )
        if result.status != "done":
            return await self._tasks.mark_failed(
                task_id,
                error_code=ERROR_OPEN_KKNAKS_TASK_FAILED,
                error_message=result.error or f"open-kknaks task {result.status}",
            )

        # 5) 출력 파싱 → 스키마 검증 → 소비 (실패 시 어떤 필드도 소비하지 않음)
        try:
            output = json.loads(result.result_text or "")
        except (json.JSONDecodeError, TypeError) as exc:
            return await self._tasks.mark_failed(
                task_id, error_code=ERROR_OUTPUT_PARSE_FAILED, error_message=str(exc)
            )
        try:
            jsonschema.validate(output, assembled.output_schema)
        except jsonschema.ValidationError as exc:
            return await self._tasks.mark_failed(
                task_id, error_code=ERROR_OUTPUT_SCHEMA_MISMATCH, error_message=exc.message
            )

        task = await self._tasks.mark_succeeded(task_id)
        await builder.handle_result(task, output)
        return task

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _resolve_definition(self, task_type: str):
        definition = await self._definitions.get_by_key(task_type)
        if definition is None or not definition.enabled:
            raise TaskDefinitionNotFoundError(task_type)
        return definition

    async def _load_active_prompt(self, prompt_key: str) -> PromptVersionDTO | None:
        """활성 프롬프트 로드. 없음/조회 에러 모두 fallback 경로(None)로 흡수."""
        try:
            return await self._prompts.get_active_version(prompt_key)
        except Exception:  # noqa: BLE001 — 로드 실패는 실행을 중단시키지 않는다 (S-4)
            return None

    async def _load_active_template(self, template_key: str) -> TemplateVersionDTO | None:
        try:
            return await self._templates.get_active_version(template_key)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _snapshot_payload(
        task: AiTaskDTO, assembled: AssembledInputDTO, template_key: str | None
    ) -> dict[str, Any]:
        """payload에 조립 입력 전체를 관찰 가능하게 스냅샷한다 (SPEC-011)."""
        payload = dict(task.payload)
        payload["assembled_input"] = {
            "blocks": [block.model_dump() for block in assembled.blocks],
            "template_key": template_key,
        }
        payload["output_schema"] = assembled.output_schema
        payload["fallbacks"] = assembled.fallback_codes
        return payload
