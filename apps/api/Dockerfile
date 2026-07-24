FROM python:3.12-slim

# git — 문서 SoT 동기화(AXKG-DEC-010/SPEC-015)에서 commit/rebase/push 수행.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 먼저 — 소스 변경 시 캐시 재사용
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY axkg/ axkg/
COPY alembic/ alembic/
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# migration은 compose command에서 수행 (alembic upgrade head)
CMD ["uvicorn", "axkg.main:app", "--host", "0.0.0.0", "--port", "8000"]
