"""Core Enums — TEXT + CHECK constraint 값 목록 (database README "Core Enums" SSOT)."""

SOURCE_STATUS = (
    "received",
    "summarizing",
    "summarized",
    "collection_failed",
    "ignored",
    "documented",
    "archived",
    "deleted",
)
SOURCE_CHANNEL = ("slack", "manual")
DESTINATION_TYPE = ("project", "area", "resource", "archive")
GATE_KIND = ("classification", "documentation")
APPROVAL_GATE_STATUS = (
    "not_started",
    "generating",
    "review_pending",
    "feedback_pending",
    "regenerating",
    "approved",
    "failed",
    "cancelled",
)
APPROVAL_REVISION_STATUS = (
    "drafting",
    "reviewable",
    "approved",
    "superseded",
    "rejected",
    "failed",
)
AI_TASK_STATUS = ("queued", "running", "succeeded", "failed", "cancelled")
APPLY_PLAN_STATUS = ("pending", "valid", "invalid", "applying", "applied", "failed")
APPLY_PLAN_VALIDATION_STATUS = ("pending", "valid", "invalid")
FILE_ACTION_TYPE = ("create_markdown", "patch_markdown", "update_frontmatter")
DOCUMENT_TYPE = (
    "reference",
    "permanent",
    "concept",
    "baseline",
    "decision",
    "spec",
    "work",
    "source",
)
EDGE_TYPE = ("assoc", "lineage")
EDGE_SOURCE_SYNTAX = ("wikilink", "up")
PROVIDER = ("claude", "codex")
CHAT_SESSION_STATUS = ("active", "archived", "deleted")
CHAT_MESSAGE_ROLE = ("user", "assistant", "system")
CHAT_RUN_STATUS = ("queued", "running", "succeeded", "failed", "cancelled")
AI_HANDLER_KIND = (
    "source_summary",
    "classification_gate",
    "documentation_gate",
    "graph_rag_chat",
)
# ai_tasks.task_type SSOT는 AXKG-SPEC-011 Stage Execution Contract 표.
AI_TASK_TYPE = (
    "collect_source_summary",
    "generate_classification_gate",
    "regenerate_classification_gate",
    "generate_documentation_gate",
    "regenerate_documentation_gate",
    "graph_rag_chat",
)
GATE_FEEDBACK_STATUS = ("submitted", "consumed", "cancelled")
DRAFT_TYPE = ("main_document", "derived_suggestion")
DRAFT_CHANGE_KIND = ("create", "modify")


def check_in(column: str, values: tuple[str, ...]) -> str:
    """CHECK constraint SQL 조각 생성: ``col in ('a','b')`` (NULL은 통과)."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} in ({quoted})"
