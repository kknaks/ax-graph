"""handler_kind별 context builder 인터페이스 + registry (AXKG-SPEC-011).

- ContextBuilder는 조립의 **데이터 블록**만 공급한다. 프롬프트/템플릿/output
  contract 프레임은 assembly(코드 소유)가 쌓는다.
- 실제 스테이지 구현체(source_summary/classification_gate/documentation_gate/
  graph_rag_chat)는 각 도메인 WP 소관이다. 여기에는 인터페이스와 테스트/검증용
  더미 handler만 둔다.
- handler 코드는 동적이지 않다: registry에 명시 등록된 handler_kind만 실행된다
  (SPEC-011 Implementation Rules — 설정에서 임의 코드 실행 불가).
"""
from abc import ABC, abstractmethod
from typing import Any

from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO


class UnknownHandlerKindError(Exception):
    """registry에 등록되지 않은 handler_kind 실행 시도."""

    def __init__(self, handler_kind: str) -> None:
        super().__init__(f"unregistered handler_kind: {handler_kind}")
        self.handler_kind = handler_kind


class ContextBuildError(Exception):
    """데이터 블록 준비 단계(예: 원문 수집)의 실패 — 실행측 코드로 매핑한다.

    파이프라인은 이 예외를 인프라 오류가 아니라 task 실패(error_code)로 흡수한다.
    요약 스테이지의 수집 실패(AXKG-SPEC-012 Failure Contract → SPEC-011 Case Matrix
    `CONTENT_FETCH_FAILED` 등)를 `ai_tasks.status=failed`로 보존하기 위한 통로다.
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message


class ContextBuilder(ABC):
    """스테이지별 입력 데이터 블록 공급 + 검증 통과한 출력의 소비 인터페이스."""

    @abstractmethod
    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        """handler가 주입할 데이터 블록들(source 데이터, 연결 후보 컨텍스트 등).

        문서초안(③) 구현체는 retriever top-N + documents index 스냅샷 2단을
        항상 포함해야 한다(AXKG-DEC-005) — 도메인 WP 소관.
        """

    def select_template_key(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> str | None:
        """조립에 쓸 템플릿 key. 기본은 definition.template_key.

        documentation_gate 구현체는 destination→template key 매핑
        (resource→reference, area→permanent, project→project_baseline,
        AXKG-SPEC-010)을 여기서 적용한다 — 도메인 WP 소관.
        """
        return definition.template_key

    @abstractmethod
    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        """파싱·스키마 검증을 **통과한** 출력의 소비 지점.

        검증 실패 출력은 여기로 오지 않는다(부분 소비 금지, SPEC-011 Validation).
        스테이지별 결과 저장(summary_payload / revision / run)은 도메인 WP 소관.
        """


class ContextBuilderRegistry:
    """handler_kind → ContextBuilder 명시 등록 registry."""

    def __init__(self) -> None:
        self._builders: dict[str, ContextBuilder] = {}

    def register(self, handler_kind: str, builder: ContextBuilder) -> None:
        self._builders[handler_kind] = builder

    def get(self, handler_kind: str) -> ContextBuilder:
        builder = self._builders.get(handler_kind)
        if builder is None:
            raise UnknownHandlerKindError(handler_kind)
        return builder


class DummyContextBuilder(ContextBuilder):
    """테스트/파이프라인 검증용 더미 handler.

    고정 데이터 블록을 공급하고, 검증 통과한 출력을 results에 쌓는다.
    실제 스테이지 handler가 아니며 프로덕션 registry에 등록하지 않는다.
    """

    def __init__(
        self,
        data_blocks: list[AssembledBlockDTO] | None = None,
        template_key: str | None = None,
    ) -> None:
        self._data_blocks = data_blocks or [
            AssembledBlockDTO(
                kind="data",
                label="dummy_source",
                text="더미 입력 데이터: 파이프라인 골격 검증용 블록이다.",
            )
        ]
        self._template_key = template_key
        self.results: list[tuple[AiTaskDTO, dict[str, Any]]] = []

    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        return list(self._data_blocks)

    def select_template_key(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> str | None:
        return self._template_key or definition.template_key

    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        self.results.append((task, output))
