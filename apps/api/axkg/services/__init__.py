"""비즈니스 로직 계층.

레이어 규칙:
- services는 repositories만 호출한다(직접 session 조작·raw query 금지).
- services는 schemas(API 객체)를 모른다 — 입출력은 dto만.
- routes → services → repositories → models 단방향. 역참조 금지.
"""
