FROM python:3.12-slim

# node install — claude CLI 실행 런타임 (claude binary 자체는 호스트의 ~/.local 에서 mount 됨)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# PyPI 패키지 설치 (소스 복사 없음)
RUN pip install --no-cache-dir "open-kknaks==2.0.2"

# 워커 코드 — root 로 실행 (mount 한 호스트 ~/.local 권한 회피)
WORKDIR /app
COPY . .

CMD ["python3", "run.py"]
