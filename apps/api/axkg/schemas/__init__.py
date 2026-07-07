"""API 요청/응답 객체 (pydantic) — 라우터 계층 전용.

레이어 규칙: services/repositories는 schemas를 import하지 않는다.
dto ↔ schemas 변환은 라우터에서 수행한다.
"""
