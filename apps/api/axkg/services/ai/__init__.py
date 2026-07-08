"""AI task 생성·retry 체인·open-kknaks 매핑, task definition 해석 → 3자 조립 → fallback (AXKG-SPEC-011). WP0 Phase 5.

모듈 구성:
- resolution: SPEC-007 병합 순서로 provider/model/options/provider_options 해석
- fallbacks: 활성 프롬프트/템플릿 로드 실패 시 코드 내장 fallback 상수
- context: handler_kind별 ContextBuilder 인터페이스 + registry (+ 더미 handler)
- assembly: 블록 조립 — 변수 치환 없음, 코드 고정 프레임으로 블록을 쌓는다
- pipeline: 생성(queued) → 해석/조립 → 스냅샷 → 실행(running) → 출력 파싱·검증
"""
from axkg.services.ai.assembly import assemble_input
from axkg.services.ai.context import (
    ContextBuilder,
    ContextBuildError,
    ContextBuilderRegistry,
    DummyContextBuilder,
    UnknownHandlerKindError,
)
from axkg.services.ai.pipeline import (
    AiExecutionService,
    RetryNotAllowedError,
    TaskDefinitionNotFoundError,
)
from axkg.services.ai.resolution import resolve_execution_config

__all__ = [
    "AiExecutionService",
    "ContextBuilder",
    "ContextBuildError",
    "ContextBuilderRegistry",
    "DummyContextBuilder",
    "RetryNotAllowedError",
    "TaskDefinitionNotFoundError",
    "UnknownHandlerKindError",
    "assemble_input",
    "resolve_execution_config",
]
