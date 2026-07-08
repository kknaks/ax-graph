"""document_templates / versions repository (AXKG-SPEC-010).

- 실행측(pipeline)은 `get_active_version`으로 활성 버전만 로드한다(건드리지 않음).
- 관리 API(WP5 Phase 3)는 목록/버전/저장(새 버전+활성 포인터 이동)/롤백(포인터 이동)을 쓴다.
- 활성 여부는 `DocumentTemplateVersion` 컬럼이 아니라 `DocumentTemplate.active_version_id`
  포인터로 판별한다(버전 row는 불변 — 저장은 새 버전, 롤백은 포인터만 이동, 복사 없음).
- commit은 DI/route가 한다. T-009 Prompts repo와 대칭 구조. output_schema 없음(body만).
"""
import uuid
from typing import Any

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

    # ------------------------------------------------------------------
    # 관리 API용 조회
    # ------------------------------------------------------------------

    async def list_templates(self) -> list[dict[str, Any]]:
        """템플릿 목록 + 각 활성 버전 번호(key asc)."""
        templates = (
            await self._session.scalars(
                sa.select(DocumentTemplate).order_by(DocumentTemplate.key.asc())
            )
        ).all()
        result: list[dict[str, Any]] = []
        for template in templates:
            active = await self._active_version_row(template)
            result.append(
                {
                    "key": template.key,
                    "name": template.name,
                    "active_version": active.version if active is not None else None,
                    "updated_at": template.updated_at,
                }
            )
        return result

    async def get_template(self, key: str) -> dict[str, Any] | None:
        """단일 템플릿의 활성 버전 view. 템플릿이 없으면 None."""
        template = await self._template_row(key)
        if template is None:
            return None
        return self._active_view(template, await self._active_version_row(template))

    async def list_versions(self, key: str) -> list[dict[str, Any]] | None:
        """버전 목록(version desc, is_active 표시). 템플릿이 없으면 None."""
        template = await self._template_row(key)
        if template is None:
            return None
        versions = (
            await self._session.scalars(
                sa.select(DocumentTemplateVersion)
                .where(DocumentTemplateVersion.template_id == template.id)
                .order_by(DocumentTemplateVersion.version.desc())
            )
        ).all()
        return [self._version_view(template, v) for v in versions]

    async def get_version(self, key: str, version: int) -> dict[str, Any] | None:
        """특정 버전 view. 템플릿/버전 없으면 None."""
        template = await self._template_row(key)
        if template is None:
            return None
        row = await self._version_row(template.id, version)
        return self._version_view(template, row) if row is not None else None

    # ------------------------------------------------------------------
    # 관리 API용 변경
    # ------------------------------------------------------------------

    async def create_version(
        self,
        key: str,
        *,
        body: str,
        created_by: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """새 버전(version=max+1) 생성 + 활성 포인터 이동. 템플릿 없으면 None. 기존 버전 불변."""
        template = await self._template_row(key)
        if template is None:
            return None
        current_max = await self._session.scalar(
            sa.select(sa.func.max(DocumentTemplateVersion.version)).where(
                DocumentTemplateVersion.template_id == template.id
            )
        )
        row = DocumentTemplateVersion(
            template_id=template.id,
            version=(current_max or 0) + 1,
            body=body,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        template.active_version_id = row.id
        await self._session.flush()
        return self._active_view(template, row)

    async def set_active(self, key: str, version: int) -> dict[str, Any] | None:
        """롤백 — 대상 버전으로 active 포인터만 이동(복사 없음). 템플릿/버전 없으면 None."""
        template = await self._template_row(key)
        if template is None:
            return None
        target = await self._version_row(template.id, version)
        if target is None:
            return None
        template.active_version_id = target.id
        await self._session.flush()
        return self._active_view(template, target)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    async def _template_row(self, key: str) -> DocumentTemplate | None:
        return await self._session.scalar(
            sa.select(DocumentTemplate).where(DocumentTemplate.key == key)
        )

    async def _version_row(
        self, template_id: uuid.UUID, version: int
    ) -> DocumentTemplateVersion | None:
        return await self._session.scalar(
            sa.select(DocumentTemplateVersion).where(
                DocumentTemplateVersion.template_id == template_id,
                DocumentTemplateVersion.version == version,
            )
        )

    async def _active_version_row(
        self, template: DocumentTemplate
    ) -> DocumentTemplateVersion | None:
        if template.active_version_id is None:
            return None
        return await self._session.get(
            DocumentTemplateVersion, template.active_version_id
        )

    @staticmethod
    def _active_view(
        template: DocumentTemplate, version: DocumentTemplateVersion | None
    ) -> dict[str, Any]:
        if version is None:
            return {
                "key": template.key,
                "name": template.name,
                "version": None,
                "body": None,
                "is_active": False,
                "updated_at": template.updated_at,
            }
        return {
            "key": template.key,
            "name": template.name,
            "version": version.version,
            "body": version.body,
            "is_active": True,
            "updated_at": version.created_at,
        }

    @staticmethod
    def _version_view(
        template: DocumentTemplate, version: DocumentTemplateVersion
    ) -> dict[str, Any]:
        return {
            "version": version.version,
            "body": version.body,
            "is_active": version.id == template.active_version_id,
            "updated_at": version.created_at,
        }
