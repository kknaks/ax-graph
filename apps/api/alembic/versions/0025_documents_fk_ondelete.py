"""step 25: documents 참조 FK on_delete 정정 — 문서 삭제 시 참조 정리 (재인덱싱 FK 크래시 fix).

문서를 지울 때(permanent→resources 이동 등으로 옛 path prune) documents.id를 참조하는 FK가
NO ACTION이라 삭제가 막혀 run_startup_scan이 ForeignKeyViolation으로 크래시하고, pull 후
재인덱싱이 매번 터져 서버 DB가 옛 상태로 고착됐다(문서함 "문서 본문을 불러오지 못했습니다").
참조 성격에 맞게 on_delete를 정정한다:

- document_stale_marks.document_id → CASCADE (배지는 대상 문서 없으면 무의미)
- graph_chat_{sessions,messages,runs}.selected_document_id → SET NULL (채팅 이력 보존, 선택만 해제)

document_edges(from/to)는 rebuild_document/rebuild_all이 코드로 삭제·break하므로 불변
(to는 is_broken=true까지 세팅해야 해 SET NULL 캐스케이드로 대체 불가).
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# (constraint, table, column, ondelete)
_FKS = [
    ("fk_document_stale_marks_document_id", "document_stale_marks", "document_id", "CASCADE"),
    ("fk_graph_chat_sessions_selected_document_id", "graph_chat_sessions", "selected_document_id", "SET NULL"),
    ("fk_graph_chat_messages_selected_document_id", "graph_chat_messages", "selected_document_id", "SET NULL"),
    ("fk_graph_chat_runs_selected_document_id", "graph_chat_runs", "selected_document_id", "SET NULL"),
]


def upgrade() -> None:
    for name, table, column, ondelete in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, "documents", [column], ["id"], ondelete=ondelete)


def downgrade() -> None:
    for name, table, column, _ in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, "documents", [column], ["id"])
