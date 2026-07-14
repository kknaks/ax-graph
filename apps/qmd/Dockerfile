# qmd 사이드카 — Graph RAG 2단 retriever 1단 후보 발굴 (AXKG-WORK-008 C-1)
#
# 공식 docker 이미지가 없어(ghcr/dockerhub 미배포) node:22-slim 위에 직접 빌드한다.
# qmd(github.com/tobi/qmd)는 Bun/Node ≥22 + node-llama-cpp(GGUF) 기반. 여기선 npm 글로벌 설치.
#
# 실측 근거(PLAN-013-T-006 C-1):
#  - embeddinggemma-300M(~334MB)만 pre-bake한다. 리랭크 기본 off(CPU-only 60s+)이므로
#    reranker(0.6b)·query-expansion(1.7B)은 굽지 않는다(GPU 배포에서 rerank on 시 첫 호출에
#    내려받거나 별도 이미지로 pre-bake). 벡터검색(rerank off)은 embed 모델만 필요.
#  - `qmd mcp --http`는 ::1(IPv6 loopback)에만 바인딩된다 → 별도 컨테이너에서 안 닿는다.
#    socat으로 0.0.0.0:8181 → [::1]:8182 브리지해 도커 네트워크에 노출한다(entrypoint).
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 make g++ ca-certificates socat \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @tobilu/qmd@2.6.3 || npm install -g @tobilu/qmd

ENV QMD_HOME=/root/.cache/qmd
WORKDIR /work

# embed 모델 pre-bake: seed 문서 1개로 collection 만들고 embed → embeddinggemma 다운로드 캐시.
# 캐시(~/.cache/qmd/models)만 남기고 seed collection은 제거해 검색 결과 오염을 막는다.
# (실제 workspace는 런타임에 /workspace 로 마운트되고 entrypoint가 재인덱싱한다.)
RUN mkdir -p /seed && printf '%s\n' '# seed' 'qmd embed model prebake.' > /seed/seed.md \
 && qmd collection add /seed --name seed \
 && qmd embed \
 && qmd collection remove seed \
 && rm -rf /seed || true

COPY apps/qmd/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8181
ENTRYPOINT ["/entrypoint.sh"]
