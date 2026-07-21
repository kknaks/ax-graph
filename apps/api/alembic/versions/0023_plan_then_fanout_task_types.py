"""step 23: plan-then-fanout task type/handler enum 확장 (AXKG-DEC-008 / WORK-012).

project 문서화 생성을 단일 task에서 plan-then-fanout으로 전환하며 신규 task type/handler를 더한다:
- ai_tasks.task_type CHECK: +plan_project, +generate_feature_spec
- ai_task_definitions.handler_kind CHECK: +plan_project, +feature_spec

신규 컬럼·데이터 마이그레이션은 없다(값 목록 확장만). 외부 계약(SPEC-014)·apply 경로는 불변.
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_TASK_TYPE_NEW = (
    "collect_source_summary",
    "generate_classification_gate",
    "regenerate_classification_gate",
    "generate_documentation_gate",
    "regenerate_documentation_gate",
    "graph_rag_chat",
    "plan_project",
    "generate_feature_spec",
)
_TASK_TYPE_OLD = (
    "collect_source_summary",
    "generate_classification_gate",
    "regenerate_classification_gate",
    "generate_documentation_gate",
    "regenerate_documentation_gate",
    "graph_rag_chat",
)
_HANDLER_NEW = (
    "source_summary",
    "classification_gate",
    "documentation_gate",
    "graph_rag_chat",
    "plan_project",
    "feature_spec",
)
_HANDLER_OLD = (
    "source_summary",
    "classification_gate",
    "documentation_gate",
    "graph_rag_chat",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return "{} in ({})".format(column, ", ".join(f"'{v}'" for v in values))


def upgrade() -> None:
    op.drop_constraint("ck_ai_tasks_task_type", "ai_tasks", type_="check")
    op.create_check_constraint(
        "ck_ai_tasks_task_type", "ai_tasks", _in("task_type", _TASK_TYPE_NEW)
    )
    op.drop_constraint(
        "ck_ai_task_definitions_handler_kind", "ai_task_definitions", type_="check"
    )
    op.create_check_constraint(
        "ck_ai_task_definitions_handler_kind",
        "ai_task_definitions",
        _in("handler_kind", _HANDLER_NEW),
    )


def downgrade() -> None:
    op.drop_constraint("ck_ai_tasks_task_type", "ai_tasks", type_="check")
    op.create_check_constraint(
        "ck_ai_tasks_task_type", "ai_tasks", _in("task_type", _TASK_TYPE_OLD)
    )
    op.drop_constraint(
        "ck_ai_task_definitions_handler_kind", "ai_task_definitions", type_="check"
    )
    op.create_check_constraint(
        "ck_ai_task_definitions_handler_kind",
        "ai_task_definitions",
        _in("handler_kind", _HANDLER_OLD),
    )
