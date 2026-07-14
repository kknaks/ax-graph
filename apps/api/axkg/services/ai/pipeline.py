"""AI 실행 파이프라인 (AXKG-SPEC-011).

경로: ai_task 생성(queued, 설정 스냅샷) → definition 해석 → 프롬프트/템플릿
로드(실패 시 코드 fallback) → 블록 조립 → ai_tasks 조립 스냅샷 → open-kknaks
실행(running) → open_kknaks_task_id/session_id 저장 → 출력 JSON 파싱
(OUTPUT_PARSE_FAILED) → output_schema 검증(OUTPUT_SCHEMA_MISMATCH) → 성공 시
handler.handle_result로 전달. 검증 실패 출력은 어떤 필드도 소비하지 않는다.

재시도: 실패 task는 불변, retry_of_task_id로 새 row (AXKG-SPEC-002).
"""
import json
import re
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
from axkg.services.ai.context import ContextBuildError, ContextBuilderRegistry
from axkg.services.ai.resolution import resolve_execution_config

AI_PROVIDER_SETTINGS_KEY = "ai_provider"

# Case Matrix (AXKG-SPEC-011) + 실행측 실패 코드
ERROR_OUTPUT_PARSE_FAILED = "OUTPUT_PARSE_FAILED"
ERROR_OUTPUT_SCHEMA_MISMATCH = "OUTPUT_SCHEMA_MISMATCH"
# open-kknaks 전달 자체가 실패 (SPEC-007 Case Matrix)
ERROR_AI_TASK_SUBMIT_FAILED = "AI_TASK_SUBMIT_FAILED"
# open-kknaks task가 terminal failed/cancelled로 끝남 (SPEC-011 Case Matrix 밖 — 실행측 코드)
ERROR_OPEN_KKNAKS_TASK_FAILED = "OPEN_KKNAKS_TASK_FAILED"

# 출력 앞뒤를 감싼 마크다운 코드펜스(```json … ```)를 벗겨낸다. claude가 프로젝트
# context를 읽는 agentic 실행에서 JSON을 펜스로 감싸 내는 경우가 있어(출력 계약은
# "JSON 하나로만"이지만 모델이 종종 펜스를 덧댐), 파싱 전에 정규화한다. 펜스가 없으면
# 원문을 그대로 돌려준다.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)


def strip_code_fences(text: str) -> str:
    """선행/후행 마크다운 코드펜스를 제거한다(내부 JSON은 건드리지 않음)."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text


def extract_json_object(text: str) -> str:
    """첫 '{'부터 마지막 '}'까지를 결정적으로 추출한다.

    claude가 agentic 실행에서 JSON 앞뒤에 해설 문장(프리앰블/후미)을 덧붙여 내는
    경우가 있어(출력 계약은 "JSON 하나로만"이지만 모델이 종종 어긴다), 파싱 전에
    바깥 텍스트를 걷어낸다. 경계 추출만 하고 내부 문자열 복구/이스케이프 보정 같은
    강제복구는 하지 않는다 — '{'나 '}'가 없거나 순서가 어긋나면 원문을 그대로 돌려주고
    파싱은 뒤에서 OUTPUT_PARSE_FAILED로 표면화된다.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


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
        options_overrides: dict[str, Any] | None = None,
    ) -> AiTaskDTO:
        """queued ai_task 생성. 실행 설정은 생성 시점에 해석·스냅샷한다.

        SPEC-007: 설정 변경은 기존 queued/running task에 소급 적용하지 않는다 —
        그래서 provider/model/options/provider_options는 생성 시점 값으로 고정된다.

        `options_overrides`는 해석된 config.options 위에 얹는 실행측 오버레이다 —
        세션 resume(`{"resume": {"mode": "session", "session_id": ...}}`, SPEC-002)처럼
        도메인 WP가 스냅샷 시점에 주입해야 하는 옵션에만 쓴다.
        """
        definition = await self._resolve_definition(task_type)
        global_settings = await self._settings.get_value(AI_PROVIDER_SETTINGS_KEY)
        config = resolve_execution_config(global_settings, definition)
        options = config.options
        if options_overrides:
            options = {**config.options, **options_overrides}
        return await self._tasks.create(
            task_type=task_type,
            task_definition_id=definition.id,
            provider=config.provider,
            model=config.model,
            options=options,
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
        #    데이터 준비(수집 등) 실패는 인프라 오류가 아니라 task 실패로 보존한다
        #    (SPEC-011 Case Matrix: CONTENT_FETCH_FAILED → source collection_failed).
        try:
            data_blocks = await builder.build_data_blocks(task, definition)
        except ContextBuildError as exc:
            return await self._tasks.mark_failed(
                task_id, error_code=exc.error_code, error_message=exc.message
            )
        # retriever가 qmd 사이드카 장애로 keyword+edge 폴백했으면 관찰 기록(③④ 공통, C-5).
        if getattr(builder, "retriever_fallback_used", False):
            fallback_codes.append(fallbacks.RETRIEVER_FALLBACK_USED)
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
        # 정규화 순서: 코드펜스 제거 → 프리앰블/후미 제거 → json parse.
        # strict=False: 문자열 내부 리터럴 제어문자(개행·탭 등)를 허용하는 stdlib 표준 관대
        # 모드. 장문 body_markdown 요약에서 claude가 미이스케이프 개행을 자주 내보내는데
        # (T-029 실측), JSON 문자열의 리터럴 제어문자는 "이스케이프됐어야 할 문자"로 해석이
        # 유일해 내용 조작이 없다(강제복구 아님). 미이스케이프 큰따옴표류는 여전히 실패한다.
        try:
            normalized = extract_json_object(strip_code_fences(result.result_text or ""))
            output = json.loads(normalized, strict=False)
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
