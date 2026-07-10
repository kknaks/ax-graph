FROM python:3.12-slim

# node install — claude CLI 실행 런타임 (claude binary 자체는 호스트의 ~/.local 에서 mount 됨)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# PyPI 패키지 설치 (소스 복사 없음)
RUN pip install --no-cache-dir "open-kknaks==2.0.2"

# 워커 코드 + 요약/분류 작업 workspace — root 로 실행 (mount 한 호스트 ~/.local 권한 회피).
# build context = repo root (docker-compose worker.build.context: .). 따라서:
#   1) apps/worker/ 전체를 /app 으로 → run.py + workspace 진입 문서(CLAUDE.md/agent.md).
#   2) repo-root context/ 를 /app/workspace/context/ 로 → SoT 단일본(para-classification.md,
#      source-summary-guide.md 등)을 빌드 시점 이미지에 고정. workspace/context 는 로컬 dev용
#      심링크라 .dockerignore 로 제외되고, 여기서 실파일로 다시 채운다.
# claude 는 이 workspace 안에서 실행되어 진입 문서와 context/ 지침을 스스로 읽는다 — 마운트 아님.
WORKDIR /app
COPY apps/worker/ .
COPY context/ ./workspace/context/

# claude 실행 프로젝트 = 이미지에 박힌 요약 workspace. run.py 기본값과 동일하나 명시 고정.
ENV WORK_DIR=/app/workspace

CMD ["python3", "run.py"]
