"""AXKG-SPEC-011 AI 실행 골격 테스트 — fake open-kknaks client + 더미 handler.

시나리오:
(a) 정상 경로: 해석→조립→실행→성공 + 스냅샷(prompt_version_id/payload) 검증
(b) JSON 파싱 실패 → failed + OUTPUT_PARSE_FAILED
(c) output_schema 불일치 → failed + OUTPUT_SCHEMA_MISMATCH + 필드 미소비
(d) 활성 프롬프트 없음 → 코드 fallback으로 성공 + version id null + payload 기록
(e) retry → 새 row + retry_of_task_id, 실패 task 불변
+ 템플릿 조립/fallback, SPEC-007 병합 순서, SPEC-002 resume session 헬퍼

더미 handler는 seed된 handler_kind(source_summary/documentation_gate) 아래에
등록한다 — handler_kind/task_type CHECK 제약의 SSOT는 스펙 표라서 테스트 전용
enum 값을 추가하지 않는다.
"""
import json
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.dto.ai import AiTaskDefinitionDTO
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models import Prompt
from axkg.repositories.ai_task_definitions import AiTaskDefinitionRepository
from axkg.repositories.settings import SettingRepository
from axkg.services.ai import (
    AiExecutionService,
    ContextBuilderRegistry,
    DummyContextBuilder,
    resolve_execution_config,
)
from axkg.services.ai.fallbacks import (
    FALLBACK_PROMPT_TEXT,
    PROMPT_FALLBACK_USED,
    RETRIEVER_FALLBACK_USED,
    TEMPLATE_FALLBACK_USED,
)
from axkg.services.ai.pipeline import extract_json_object, strip_code_fences

VALID_SUMMARY_OUTPUT = {
    "title": "Graph RAG 실전 설계",
    "summary": "문서 그래프를 검색 컨텍스트로 삼는 RAG 설계 자료 요약.",
    "keywords": ["graph-rag", "retriever"],
    "source_type": "article",
    "body_markdown": "## 배경\n문서 그래프를 검색 컨텍스트로 삼는다.",
}

VALID_DOCUMENTATION_OUTPUT = {
    "document_draft": {
        "filename_candidate": "2026-07-07-graph-rag.md",
        "markdown_full": "---\ntype: reference\n---\n# Graph RAG\n",
    },
    "derived_suggestions": [],
}


class FakeOpenKknaksClient(OpenKknaksClient):
    """submit/wait를 즉시 응답하는 fake. 요청 스냅샷을 기록한다."""

    def __init__(
        self,
        *,
        result_text: str | None = None,
        status: str = "done",
        session_id: str | None = "okk-sess-1",
        error: str | None = None,
    ) -> None:
        self._result_text = result_text
        self._status = status
        self._session_id = session_id
        self._error = error
        self.requests: list[OpenKknaksTaskRequest] = []

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        self.requests.append(request)
        return "okk-task-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return self._status

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(
            task_id=task_id,
            status=self._status,
            result_text=self._result_text,
            session_id=self._session_id,
            error=self._error,
        )


def make_service(
    session: AsyncSession,
    client: OpenKknaksClient,
    dummy: DummyContextBuilder,
    handler_kind: str = "source_summary",
) -> AiExecutionService:
    registry = ContextBuilderRegistry()
    registry.register(handler_kind, dummy)
    return AiExecutionService(session, client=client, registry=registry)


async def active_prompt_version_id(session: AsyncSession, key: str) -> uuid.UUID | None:
    prompt = await session.scalar(sa.select(Prompt).where(Prompt.key == key))
    assert prompt is not None
    return prompt.active_version_id


# ---------------------------------------------------------------------------
# (a) 정상 경로
# ---------------------------------------------------------------------------


async def test_execute_success_snapshots_and_consumes_output(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text=json.dumps(VALID_SUMMARY_OUTPUT))
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        assert task.status == "queued"
        # SPEC-007 MVP 기본값이 생성 시점에 스냅샷된다
        assert task.provider == "claude"
        assert task.options["timeout_sec"] == 300
        # 전역 기본 max_turns=20 (collect_source_summary는 definition override 없음, T-012)
        assert task.provider_options == {"max_turns": 20, "effort": "medium"}

        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        assert done.error_code is None
        # 성공 실행은 사용한 prompt_version_id를 스냅샷한다
        assert done.prompt_version_id == await active_prompt_version_id(
            session, "source_summary"
        )
        assert done.template_version_id is None
        # open-kknaks task/session id 저장
        assert done.open_kknaks_task_id == "okk-task-1"
        assert done.open_kknaks_session_id == "okk-sess-1"
        # payload에 조립 입력 스냅샷 + fallback 없음
        kinds = [b["kind"] for b in done.payload["assembled_input"]["blocks"]]
        assert kinds == ["prompt", "data", "output_contract"]
        assert done.payload["fallbacks"] == []
        # 블록 조립: 프롬프트(지시) → 데이터 블록 → 출력 계약 순으로 쌓인다
        sent = client.requests[0]
        assert sent.provider == "claude"
        assert "수집 비서" in sent.prompt  # 활성 프롬프트(지시)
        assert "더미 입력 데이터" in sent.prompt  # handler 데이터 블록
        assert "JSON Schema" in sent.prompt  # 코드 고정 output contract 프레임
        assert "{{" not in sent.prompt  # 변수 치환 아님
        # 검증 통과 출력이 handler로 전달된다
        assert dummy.results == [(done, VALID_SUMMARY_OUTPUT)]


# ---------------------------------------------------------------------------
# (b) JSON 파싱 실패
# ---------------------------------------------------------------------------


async def test_output_parse_failure_marks_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text="죄송합니다, JSON이 아닙니다.")
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        failed = await service.execute_task(task.id)
        await session.commit()

        assert failed.status == "failed"
        assert failed.error_code == "OUTPUT_PARSE_FAILED"
        assert failed.error_message
        assert dummy.results == []  # 어떤 필드도 소비하지 않는다
        # 실패 task도 요청/조립 스냅샷은 payload에 보존된다 (SPEC-002)
        assert "assembled_input" in failed.payload


def test_strip_code_fences_variants() -> None:
    # ```json … ``` (agentic claude가 흔히 내는 형태) → 내부 JSON만
    fenced = '```json\n{"a": 1}\n```'
    assert strip_code_fences(fenced) == '{"a": 1}'
    # 언어 태그 없는 펜스도 벗긴다
    assert strip_code_fences("```\n{\"a\": 1}\n```") == '{"a": 1}'
    # 펜스가 없으면 원문 그대로 (내부 백틱은 건드리지 않음)
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'
    assert strip_code_fences('{"md": "a ``` b"}') == '{"md": "a ``` b"}'


async def test_fenced_json_output_parses_and_consumes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """```json 펜스로 감싼 출력도 파싱·소비된다 (agentic 실행 출력 정규화)."""
    async with session_factory() as session:
        fenced = "```json\n" + json.dumps(VALID_SUMMARY_OUTPUT) + "\n```"
        client = FakeOpenKknaksClient(result_text=fenced)
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        assert dummy.results == [(done, VALID_SUMMARY_OUTPUT)]


def test_extract_json_object_variants() -> None:
    # 프리앰블(해설 문장) + 유효 JSON → 객체 경계만 추출 (PLAN-009-T-026 갭1 실측)
    preamble = 'Now producing the classification output as pure JSON.\n\n{"a": 1}'
    assert extract_json_object(preamble) == '{"a": 1}'
    # 후미 텍스트도 제거
    assert extract_json_object('{"a": 1}\n\n이상입니다.') == '{"a": 1}'
    # 프리앰블 + 후미 동시
    assert extract_json_object('설명\n{"a": 1}\n끝') == '{"a": 1}'
    # 순수 JSON은 그대로
    assert extract_json_object('{"a": 1}') == '{"a": 1}'
    # 중괄호가 없으면 원문 그대로 (뒤에서 파싱 실패로 표면화)
    assert extract_json_object("JSON이 아닙니다") == "JSON이 아닙니다"
    # 내부 조작 없음 — 첫 { ~ 마지막 } 경계만, 내부 문자열은 손대지 않음
    assert extract_json_object('x {"md": "a } b"} y') == '{"md": "a } b"}'


async def test_preamble_json_output_parses_and_consumes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """JSON 앞 프리앰블 해설 문장이 붙어도 파싱·소비된다 (PLAN-009-T-026 갭1)."""
    async with session_factory() as session:
        preamble = (
            "Now producing the classification output as pure JSON.\n\n"
            + json.dumps(VALID_SUMMARY_OUTPUT)
        )
        client = FakeOpenKknaksClient(result_text=preamble)
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        assert dummy.results == [(done, VALID_SUMMARY_OUTPUT)]


async def test_fence_plus_preamble_combo_parses_and_consumes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """코드펜스 + 프리앰블 조합도 정규화된다 (strip_fences → extract → parse)."""
    async with session_factory() as session:
        combo = (
            "해설을 붙입니다:\n```json\n"
            + json.dumps(VALID_SUMMARY_OUTPUT)
            + "\n```\n감사합니다."
        )
        client = FakeOpenKknaksClient(result_text=combo)
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        assert dummy.results == [(done, VALID_SUMMARY_OUTPUT)]


async def test_preamble_with_invalid_json_still_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """경계 추출 후에도 무효 JSON이면 OUTPUT_PARSE_FAILED (강제복구 금지)."""
    async with session_factory() as session:
        # 중괄호는 있으나 내부가 깨진 JSON — 추출은 되지만 파싱은 실패해야 한다
        client = FakeOpenKknaksClient(result_text="설명 {이건: 유효한, JSON이, 아니다,,} 끝")
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        failed = await service.execute_task(task.id)
        await session.commit()

        assert failed.status == "failed"
        assert failed.error_code == "OUTPUT_PARSE_FAILED"
        assert dummy.results == []


async def test_literal_control_char_in_string_parses_and_consumes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """JSON 문자열 안 리터럴 개행/탭(미이스케이프)도 파싱·소비된다 (strict=False, T-029 실측)."""
    async with session_factory() as session:
        # body_markdown 값 안에 진짜 개행/탭 문자가 그대로 들어간 raw JSON — strict 파싱은
        # "Invalid control character"로 실패하지만 strict=False는 허용한다(해석 유일·조작 없음).
        raw = (
            '{"title": "T", "summary": "S", "keywords": ["k"], '
            '"source_type": "article", '
            '"body_markdown": "## 배경\n리터럴 개행이\t문자열 안에 있다."}'
        )
        expected = {
            "title": "T",
            "summary": "S",
            "keywords": ["k"],
            "source_type": "article",
            "body_markdown": "## 배경\n리터럴 개행이\t문자열 안에 있다.",
        }
        client = FakeOpenKknaksClient(result_text=raw)
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        assert dummy.results == [(done, expected)]


async def test_unescaped_quote_still_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """미이스케이프 큰따옴표는 strict=False로도 결정적 해석 불가 → OUTPUT_PARSE_FAILED."""
    async with session_factory() as session:
        # title 값 안의 "hi"가 이스케이프되지 않아 delimiter 파싱이 깨진다(제어문자 문제 아님).
        raw = (
            '{"title": "he said "hi" today", "summary": "S", "keywords": ["k"], '
            '"source_type": "article", "body_markdown": "b"}'
        )
        client = FakeOpenKknaksClient(result_text=raw)
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        failed = await service.execute_task(task.id)
        await session.commit()

        assert failed.status == "failed"
        assert failed.error_code == "OUTPUT_PARSE_FAILED"
        assert dummy.results == []


# ---------------------------------------------------------------------------
# (c) 스키마 불일치 — 필드 미소비
# ---------------------------------------------------------------------------


async def test_output_schema_mismatch_marks_failed_without_consuming(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        # title만 있고 required(summary/keywords/source_type) 누락
        client = FakeOpenKknaksClient(result_text=json.dumps({"title": "T"}))
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        failed = await service.execute_task(task.id)
        await session.commit()

        assert failed.status == "failed"
        assert failed.error_code == "OUTPUT_SCHEMA_MISMATCH"
        assert dummy.results == []  # 부분 소비 금지


# ---------------------------------------------------------------------------
# (d) 활성 프롬프트 없음 → 코드 fallback
# ---------------------------------------------------------------------------


async def test_prompt_fallback_keeps_pipeline_running(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(
            sa.update(Prompt)
            .where(Prompt.key == "source_summary")
            .values(active_version_id=None)
        )
        client = FakeOpenKknaksClient(result_text=json.dumps(VALID_SUMMARY_OUTPUT))
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        # fallback 실행: 버전 id는 null, payload에 관찰 가능하게 기록
        assert done.prompt_version_id is None
        assert PROMPT_FALLBACK_USED in done.payload["fallbacks"]
        assert FALLBACK_PROMPT_TEXT.split(".")[0] in client.requests[0].prompt
        assert dummy.results  # fallback schema로 검증 통과 → 소비


# ---------------------------------------------------------------------------
# 템플릿 조립 (documentation_gate류) + 템플릿 fallback
# ---------------------------------------------------------------------------


async def test_documentation_gate_assembles_template_block(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text=json.dumps(VALID_DOCUMENTATION_OUTPUT))
        dummy = DummyContextBuilder(template_key="reference")
        service = make_service(session, client, dummy, handler_kind="documentation_gate")

        task = await service.create_task("generate_documentation_gate")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        assert done.prompt_version_id is not None
        assert done.template_version_id is not None  # ③은 템플릿 버전도 스냅샷
        kinds = [b["kind"] for b in done.payload["assembled_input"]["blocks"]]
        assert kinds == ["prompt", "template_frame", "data", "output_contract"]
        # 코드 고정 프레임 문구 + 활성 템플릿 body가 함께 조립된다
        assert "템플릿 뼈대" in client.requests[0].prompt
        assert "type: reference" in client.requests[0].prompt


async def test_template_fallback_records_and_continues(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text=json.dumps(VALID_DOCUMENTATION_OUTPUT))
        dummy = DummyContextBuilder(template_key="no-such-template")
        service = make_service(session, client, dummy, handler_kind="documentation_gate")

        task = await service.create_task("generate_documentation_gate")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"
        assert done.template_version_id is None
        assert TEMPLATE_FALLBACK_USED in done.payload["fallbacks"]


async def test_retriever_fallback_recorded_in_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """retriever가 qmd 장애로 폴백하면 RETRIEVER_FALLBACK_USED가 payload에 관찰 기록된다(C-5).

    빌더의 retriever_fallback_used 플래그를 파이프라인이 getattr로 수집하는 배선을 검증한다.
    """
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text=json.dumps(VALID_SUMMARY_OUTPUT))
        dummy = DummyContextBuilder()
        dummy.retriever_fallback_used = True  # qmd 사이드카 장애 시 빌더가 세우는 플래그
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        await session.commit()

        assert done.status == "succeeded"  # 폴백은 실패 아님 — 실행은 계속된다
        assert RETRIEVER_FALLBACK_USED in done.payload["fallbacks"]


# ---------------------------------------------------------------------------
# (e) retry 체인 — 실패 task 불변, 새 row
# ---------------------------------------------------------------------------


async def test_retry_creates_new_row_and_preserves_failed_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text="not-json")
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        failed = await service.execute_task(task.id)
        assert failed.status == "failed"

        retry = await service.retry_task(failed.id)
        await session.commit()

        assert retry.id != failed.id
        assert retry.status == "queued"
        assert retry.retry_of_task_id == failed.id
        assert retry.retry_count == failed.retry_count + 1 == 1
        # 원 task 불변
        original = await service.get_retry_chain(retry.id)
        assert [t.id for t in original] == [failed.id, retry.id]
        assert original[0].status == "failed"
        assert original[0].error_code == "OUTPUT_PARSE_FAILED"


async def test_retry_not_allowed_for_non_failed_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text=json.dumps(VALID_SUMMARY_OUTPUT))
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        assert done.status == "succeeded"

        import pytest

        from axkg.services.ai import RetryNotAllowedError

        with pytest.raises(RetryNotAllowedError):
            await service.retry_task(done.id)


# ---------------------------------------------------------------------------
# SPEC-007 병합 순서 (global → definition defaults → task_overrides)
# ---------------------------------------------------------------------------


def test_resolution_merge_order() -> None:
    definition = AiTaskDefinitionDTO(
        id=uuid.uuid4(),
        key="graph_rag_chat",
        display_name="그래프 채팅",
        handler_kind="graph_rag_chat",
        prompt_key="graph_rag_chat",
        default_model="def-model",
        default_options={"timeout_sec": 400},
        default_provider_options={"effort": "low"},
    )
    global_settings = {
        "provider": "codex",
        "model": "global-model",
        "options": {"timeout_sec": 350, "resume": False},
        "provider_options": {"max_turns": 5},
        "task_overrides": {
            "graph_rag_chat": {
                "options": {"resume": True, "timeout_sec": 600},
                "provider_options": {"max_turns": 6, "effort": "high"},
            }
        },
    }
    config = resolve_execution_config(global_settings, definition)
    assert config.provider == "codex"  # definition.default_provider 없음 → global
    assert config.model == "def-model"  # override.model 없음 → definition default
    assert config.options == {"timeout_sec": 600, "resume": True}  # override 최우선
    assert config.provider_options == {"max_turns": 6, "effort": "high"}


def test_resolution_defaults_without_settings() -> None:
    definition = AiTaskDefinitionDTO(
        id=uuid.uuid4(),
        key="collect_source_summary",
        display_name="소스 요약 수집",
        handler_kind="source_summary",
        prompt_key="source_summary",
    )
    config = resolve_execution_config(None, definition)
    assert config.provider == "claude"
    assert config.model is None
    assert config.options == {"timeout_sec": 300, "resume": True}
    assert config.provider_options == {"max_turns": 20, "effort": "medium"}


async def test_seed_global_max_turns_20_and_graph_rag_chat_override_6(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SPEC-007 정합: 전역 기본 max_turns=20(T-012), graph_rag_chat definition만 override 6.

    이 태스크의 핵심 검증 지점 — 시드된 전역 설정 + definition default_provider_options를
    실제로 병합했을 때 chat만 6, 다른 stage(예: source_summary)는 전역 20을 받는다.
    """
    async with session_factory() as session:
        global_settings = await SettingRepository(session).get_value("ai_provider")
        assert global_settings["provider_options"]["max_turns"] == 20

        defs = AiTaskDefinitionRepository(session)
        summary_def = await defs.get_by_key("collect_source_summary")
        chat_def = await defs.get_by_key("graph_rag_chat")
        assert summary_def is not None and chat_def is not None

        summary_cfg = resolve_execution_config(global_settings, summary_def)
        chat_cfg = resolve_execution_config(global_settings, chat_def)

        # source_summary는 definition override 없음 → 전역 20, effort medium 유지
        assert summary_cfg.provider_options == {"max_turns": 20, "effort": "medium"}
        # graph_rag_chat만 definition default_provider_options로 6, effort medium 유지
        assert chat_cfg.provider_options == {"max_turns": 6, "effort": "medium"}


async def test_seed_task_overrides_pin_sonnet_model_for_all_tasks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """PLAN-010-T-011: 시드된 task_overrides가 실행 6개 task 전부 model=claude-sonnet-4-6로.

    글로벌 model 비움(=CLI 디폴트 대형 모델)에 의존하지 않게 각 task에 Sonnet을 명시한다.
    provider는 claude 그대로, definition 레벨 provider_options(문서화 12/chat 6)는 무변경.
    """
    async with session_factory() as session:
        global_settings = await SettingRepository(session).get_value("ai_provider")
        assert global_settings["model"] is None  # 글로벌은 여전히 비움
        defs = AiTaskDefinitionRepository(session)

        expected_keys = [
            "collect_source_summary",
            "generate_classification_gate",
            "regenerate_classification_gate",
            "generate_documentation_gate",
            "regenerate_documentation_gate",
            "graph_rag_chat",
        ]
        for key in expected_keys:
            definition = await defs.get_by_key(key)
            assert definition is not None, key
            cfg = resolve_execution_config(global_settings, definition)
            assert cfg.model == "claude-sonnet-4-6", key
            assert cfg.provider == "claude", key  # provider는 글로벌 claude 그대로

        # definition 레벨 provider_options override는 model 오버라이드와 독립적으로 보존된다.
        doc_def = await defs.get_by_key("generate_documentation_gate")
        chat_def = await defs.get_by_key("graph_rag_chat")
        assert resolve_execution_config(global_settings, doc_def).provider_options[
            "max_turns"
        ] == 12
        assert resolve_execution_config(global_settings, chat_def).provider_options[
            "max_turns"
        ] == 6


async def test_seed_global_defaults_reflect_operational_values(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """PLAN-010-T-012: 시드된 글로벌 기본값이 운영값(resume True / max_turns 20)으로 태어난다.

    bare resume=True는 T-008 실세션 가드(is_resume_session) 덕에 무해 — override 없는 task의
    resolved options에 resume=True가 실려도 실세션 dict가 아니므로 feedback-only가 되지 않는다.
    """
    from axkg.services.ai.resolution import is_resume_session

    async with session_factory() as session:
        global_settings = await SettingRepository(session).get_value("ai_provider")
        assert global_settings["options"] == {"timeout_sec": 300, "resume": True}
        assert global_settings["provider_options"] == {"max_turns": 20, "effort": "medium"}

        summary_def = await AiTaskDefinitionRepository(session).get_by_key(
            "collect_source_summary"
        )
        cfg = resolve_execution_config(global_settings, summary_def)
        assert cfg.options["resume"] is True  # 전역 bare true 스냅샷
        assert is_resume_session(cfg.options) is False  # 실세션 아님 → 무해(T-008)


# ---------------------------------------------------------------------------
# SPEC-002 resume session 후보 헬퍼
# ---------------------------------------------------------------------------


async def test_resolve_resume_session_candidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        client = FakeOpenKknaksClient(result_text=json.dumps(VALID_SUMMARY_OUTPUT))
        dummy = DummyContextBuilder()
        service = make_service(session, client, dummy)

        task = await service.create_task("collect_source_summary")
        done = await service.execute_task(task.id)
        await session.commit()

        # 1) target revision session이 있으면 그것을 쓴다
        assert (
            await service.resolve_resume_session(
                target_revision_session_id="rev-sess", original_task_id=done.id
            )
            == "rev-sess"
        )
        # 2) 없으면 원 task의 open_kknaks_session_id
        assert (
            await service.resolve_resume_session(original_task_id=done.id)
            == "okk-sess-1"
        )
        # 3) 둘 다 없으면 stateless(None)
        assert await service.resolve_resume_session() is None
