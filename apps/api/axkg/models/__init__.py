"""SQLAlchemy ORM 모델. 스키마 SoT는 40-architecture/database README. WP0 Phase 3.

레이어 규칙: models는 어떤 상위 레이어도 import하지 않는다.
의존 방향: api/routes → services → repositories → models (단방향).
"""
from axkg.models.base import Base
from axkg.models.user import User, AuthToken
from axkg.models.setting import Setting
from axkg.models.source import Source
from axkg.models.prompt import Prompt, PromptVersion
from axkg.models.ai_task import AiTaskDefinition, AiTask
from axkg.models.gate import ApprovalGate, ApprovalGateRevision, GateFeedback
from axkg.models.draft import Draft, ApplyPlan
from axkg.models.document import Document, DocumentEdge
from axkg.models.chat import GraphChatSession, GraphChatMessage, GraphChatRun
from axkg.models.template import DocumentTemplate, DocumentTemplateVersion

__all__ = [
    "Base",
    "User",
    "AuthToken",
    "Setting",
    "Source",
    "Prompt",
    "PromptVersion",
    "AiTaskDefinition",
    "AiTask",
    "ApprovalGate",
    "ApprovalGateRevision",
    "GateFeedback",
    "Draft",
    "ApplyPlan",
    "Document",
    "DocumentEdge",
    "GraphChatSession",
    "GraphChatMessage",
    "GraphChatRun",
    "DocumentTemplate",
    "DocumentTemplateVersion",
]
