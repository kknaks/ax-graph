"""gates 라우트 (AXKG-SPEC-002 공통 게이트 액션). 계약은 스펙 API Contract를 따른다."""
from fastapi import APIRouter

router = APIRouter(prefix="/gates", tags=["gates"])
