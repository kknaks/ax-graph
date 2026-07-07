"""DB 접근 계층 — 여기(repository)만 session을 만진다.

레이어 규칙:
- repository는 ORM(models)을 알고, 밖으로는 dto만 반환한다(dto ↔ ORM 변환 담당).
- commit/rollback은 core.database.get_session(DI)이 소유한다. repository는 flush까지만.
- services만 repository를 호출한다. routes가 직접 import하지 않는다.
"""
