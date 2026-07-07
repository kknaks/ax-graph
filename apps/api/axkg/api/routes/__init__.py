"""라우터 계층 — 얇게 유지한다: schemas 변환 + service 호출만.

레이어 규칙:
- routes는 repositories/models를 직접 import하지 않는다.
- dto ↔ schemas 변환은 여기(라우터)에서 수행한다.
- Bearer 인증 적용/제외는 axkg.main의 include_router가 소유한다 (AXKG-SPEC-008).
"""
