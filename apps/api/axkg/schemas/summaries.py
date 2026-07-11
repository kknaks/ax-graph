"""문서 라이브러리 요약 브랜치 API 응답 (AXKG-SPEC-013 §4 Interface Contract).

읽기 전용 2종:
- `GET /summaries`          → `{ items: [{ source_id, name, path }] }`
- `GET /summaries/{source_id}` → `{ source_id, name, path, markdown_full }`

`markdown_full` 필드명은 확정 문서 상세와 동일하게 맞춰 FE 렌더 자산을 재사용한다.
"""
import uuid

from pydantic import BaseModel

from axkg.dto.source import SummaryLibraryDetailDTO, SummaryLibraryItemDTO


class SummaryListItem(BaseModel):
    source_id: uuid.UUID
    name: str
    path: str

    @classmethod
    def from_dto(cls, dto: SummaryLibraryItemDTO) -> "SummaryListItem":
        return cls(source_id=dto.source_id, name=dto.name, path=dto.path)


class SummaryListResponse(BaseModel):
    items: list[SummaryListItem]


class SummaryDetailResponse(BaseModel):
    source_id: uuid.UUID
    name: str
    path: str
    markdown_full: str

    @classmethod
    def from_dto(cls, dto: SummaryLibraryDetailDTO) -> "SummaryDetailResponse":
        return cls(
            source_id=dto.source_id,
            name=dto.name,
            path=dto.path,
            markdown_full=dto.markdown_full,
        )
