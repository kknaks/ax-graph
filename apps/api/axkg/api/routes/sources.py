"""sources 라우트 (AXKG-SPEC-003/001). 계약은 스펙 API Contract를 따른다."""
from fastapi import APIRouter

router = APIRouter(prefix="/sources", tags=["sources"])
