"""templates 라우트 (AXKG-SPEC-010). 계약은 스펙 API Contract를 따른다."""
from fastapi import APIRouter

router = APIRouter(prefix="/templates", tags=["templates"])
