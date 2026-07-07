"""documentation-gates 라우트 (AXKG-SPEC-004 조회 전용 뷰). 계약은 스펙 API Contract를 따른다."""
from fastapi import APIRouter

router = APIRouter(prefix="/documentation-gates", tags=["documentation-gates"])
