FROM python:3.12-slim

# node install — claude CLI 실행 런타임 (claude binary 자체는 호스트의 ~/.local 에서 mount 됨)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# PyPI 패키지 설치 (소스 복사 없음)
RUN pip install --no-cache-dir "open-kknaks==2.0.2"

# 워커 코드 + 요약 작업 workspace — root 로 실행 (mount 한 호스트 ~/.local 권한 회피).
# COPY . . 가 build context(apps/worker) 전체를 넣으므로 workspace/(진입 문서 CLAUDE.md/
# agent.md + context/source-summary-guide.md)도 /app/workspace 로 이미지에 고정된다.
# claude 는 이 workspace 안에서 실행되어 진입 문서를 스스로 읽는다 — 마운트 아님, 빌드 시점 고정.
WORKDIR /app
COPY . .

# claude 실행 프로젝트 = 이미지에 박힌 요약 workspace. run.py 기본값과 동일하나 명시 고정.
ENV WORK_DIR=/app/workspace

CMD ["python3", "run.py"]
