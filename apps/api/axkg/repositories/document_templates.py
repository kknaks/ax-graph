"""document_templates / versions repository (AXKG-SPEC-010). 실행측은 활성 버전 로드만."""
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import TemplateVersionDTO
from axkg.models import DocumentTemplate, DocumentTemplateVersion


class DocumentTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_version(self, template_key: str) -> TemplateVersionDTO | None:
        """template_key의 활성 버전. 템플릿이 없거나 active_version_id가 비면 None."""
        stmt = (
            sa.select(DocumentTemplate, DocumentTemplateVersion)
            .join(
                DocumentTemplateVersion,
                DocumentTemplateVersion.id == DocumentTemplate.active_version_id,
            )
            .where(DocumentTemplate.key == template_key)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        template, version = row
        return TemplateVersionDTO(
            id=version.id,
            template_id=template.id,
            template_key=template.key,
            version=version.version,
            body=version.body,
        )
