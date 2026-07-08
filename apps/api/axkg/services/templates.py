"""문서 템플릿 동적 관리 service (AXKG-SPEC-010). WP5 Phase 3.

경계:
- 목록/버전/저장(body → 새 버전 + 활성)/롤백(포인터 이동)까지.
- AI 실행 시 활성 버전 로드는 `pipeline._load_active_template`가 담당 — 건드리지 않는다.
- FE(Phase 4)는 이 service 밖이다.

저장은 항상 **새 버전**을 만든다(기존 버전 불변). 롤백은 기존 버전으로 active 포인터만
옮긴다. Prompt와 달리 output_schema가 없고 body(md)만 검증한다. key는 seed 3종
(reference/permanent/project_baseline)만 유효 — 임의 key 생성 안 함.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.repositories.document_templates import DocumentTemplateRepository


class TemplateNotFoundError(Exception):
    """존재하지 않는 템플릿 key (Case Matrix: TEMPLATE_NOT_FOUND)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"template not found: {key}")
        self.key = key


class EmptyTemplateBodyError(Exception):
    """body 공백 (Case Matrix: EMPTY_TEMPLATE_BODY)."""


class TemplateVersionNotFoundError(Exception):
    """롤백 대상 버전 없음 (Case Matrix: TEMPLATE_VERSION_NOT_FOUND)."""

    def __init__(self, key: str, version: int) -> None:
        super().__init__(f"template version not found: {key} v{version}")
        self.key = key
        self.version = version


class TemplateSaveError(Exception):
    """버전 저장 실패 (Case Matrix: TEMPLATE_SAVE_FAILED)."""


class TemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self._templates = DocumentTemplateRepository(session)

    async def list(self) -> list[dict[str, Any]]:
        return await self._templates.list_templates()

    async def get(self, key: str) -> dict[str, Any]:
        view = await self._templates.get_template(key)
        if view is None:
            raise TemplateNotFoundError(key)
        return view

    async def versions(self, key: str) -> list[dict[str, Any]]:
        views = await self._templates.list_versions(key)
        if views is None:
            raise TemplateNotFoundError(key)
        return views

    async def save(
        self,
        key: str,
        *,
        body: str,
        created_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """새 버전 저장 + 활성화. body 검증 → key 확인 순."""
        if not (body or "").strip():
            raise EmptyTemplateBodyError
        try:
            view = await self._templates.create_version(
                key, body=body, created_by=created_by
            )
        except Exception as exc:  # noqa: BLE001 — 저장 실패는 코드로 표면화
            raise TemplateSaveError(str(exc)) from exc
        if view is None:
            raise TemplateNotFoundError(key)
        return view

    async def rollback(self, key: str, version: int) -> dict[str, Any]:
        """지정 버전으로 active 포인터를 옮긴다(새 row 없음)."""
        if await self._templates.get_template(key) is None:
            raise TemplateNotFoundError(key)
        if await self._templates.get_version(key, version) is None:
            raise TemplateVersionNotFoundError(key, version)
        view = await self._templates.set_active(key, version)
        if view is None:  # 경합 등으로 사라진 경우 방어
            raise TemplateVersionNotFoundError(key, version)
        return view
