"""내부 전달 객체 (pydantic BaseModel) — 서비스 계층 입출력 전용.

레이어 규칙:
- dto ↔ ORM 변환은 repository에서.
- dto ↔ schemas(API 객체) 변환은 라우터에서.
- services는 schemas를 모른다(dto만 다룬다).
"""
