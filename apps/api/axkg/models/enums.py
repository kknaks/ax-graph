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
SOURCE_CHANNEL = ("slack", "manual", "chat", "upload")
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
# 요약 draft 버전(source_summary_revisions.status). 게이트 revision과 same-format 박제이되,
# 요약 초안에는 승인/잠금 개념이 없어(SPEC-002/003) reviewable(active)·superseded 두 상태뿐이다.
SUMMARY_REVISION_STATUS = ("reviewable", "superseded")
# 확정 문서 lifecycle(documents.status, SPEC-004 Document Lifecycle / SPEC-005 / DEC-005 D).
# current=최신 유효본, superseded=옛 버전 박제 보존(그래프 기본 노출 제외).
DOCUMENT_STATUS = ("current", "superseded")
# concept→permanent stale 배지(document_stale_marks.status, SPEC-004 DEC-005 E).
# active=영향 가능성 표시 유지 / dismissed=해제(배지 제거 또는 재생성 승인 반영).
STALE_MARK_STATUS = ("active", "dismissed")
AI_TASK_STATUS = ("queued", "running", "succeeded", "failed", "cancelled")
APPLY_PLAN_STATUS = ("pending", "valid", "invalid", "applying", "applied", "failed")
APPLY_PLAN_VALIDATION_STATUS = ("pending", "valid", "invalid")
FILE_ACTION_TYPE = ("create_markdown", "overwrite_markdown")
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
