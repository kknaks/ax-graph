#!/usr/bin/env bash
# qmd 사이드카 entrypoint (AXKG-WORK-008 C-1/C-2).
#
#  1) /workspace(마운트된 Markdown SoT) 초기 인덱싱 + embed
#  2) C-2 증분 인덱싱: 백그라운드에서 주기적으로 `qmd update`(변경분만) + `qmd embed`.
#     인덱싱은 사이드카가 소유하므로 api의 채팅 요청 경로에는 인덱싱 비용이 0이다.
#  3) `qmd mcp --http`(::1 바인딩) 기동
#  4) socat으로 0.0.0.0:${QMD_PORT} → [::1]:${QMD_INTERNAL_PORT} 브리지(::1 바인딩 우회)
set -euo pipefail

WORKSPACE="${QMD_WORKSPACE:-/workspace}"
COLLECTION="${QMD_COLLECTION:-axkg}"
QMD_PORT="${QMD_PORT:-8181}"              # 외부(도커 네트워크) 노출 포트
QMD_INTERNAL_PORT="${QMD_INTERNAL_PORT:-8182}"  # qmd가 ::1에 바인딩하는 내부 포트
REINDEX_INTERVAL="${QMD_REINDEX_INTERVAL:-30}"  # 증분 재인덱싱 주기(초)

echo "[qmd] initial index of ${WORKSPACE} (collection=${COLLECTION})"
qmd collection add "${WORKSPACE}" --name "${COLLECTION}" 2>&1 | tail -3 || true
qmd embed 2>&1 | tail -3 || true

# C-2 증분 인덱싱 루프(백그라운드). qmd update는 content 변경분만 재인덱싱한다.
(
  while true; do
    sleep "${REINDEX_INTERVAL}"
    qmd update >/dev/null 2>&1 || true
    qmd embed  >/dev/null 2>&1 || true
  done
) &

# ::1 바인딩 우회: 외부 포트 → 내부 ::1 포트 브리지.
echo "[qmd] socat bridge 0.0.0.0:${QMD_PORT} -> [::1]:${QMD_INTERNAL_PORT}"
socat "TCP4-LISTEN:${QMD_PORT},fork,reuseaddr" "TCP6:[::1]:${QMD_INTERNAL_PORT}" &

echo "[qmd] starting MCP http server on [::1]:${QMD_INTERNAL_PORT}"
exec qmd mcp --http --port "${QMD_INTERNAL_PORT}"
