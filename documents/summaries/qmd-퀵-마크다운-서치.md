---
type: summary
title: QMD - 퀵 마크다운 서치
source_url: https://news.hada.io/topic?id=26213
tags:
- 마크다운 검색
- CLI
- BM25
- 벡터 검색
- 하이브리드 검색
- LLM 재순위화
- MCP
- 로컬 AI
- SQLite
- Obsidian
summarized_at: '2026-07-13T01:13:12.144356+00:00'
---

## 개요

- **QMD(Quick Markdown Search)**: 개인 노트, 기술 문서, 회의록 등 다양한 Markdown 기반 문서를 **로컬에서 검색**하기 위해 개발된 경량 CLI 검색 엔진
- 출처: github.com/tobi (Shopify 창업자·CEO **Tobi Lütke**의 오픈소스)
- 라이선스: **MIT**
- 런타임: **TypeScript** + **Bun 런타임**; 인덱스는 **SQLite 데이터베이스**에 저장

## 핵심 특징

- **하이브리드 검색 파이프라인**: BM25 전체 텍스트 검색 + 벡터 의미 검색 + LLM 재순위화(re-ranking) 결합
- **완전 로컬 실행**: 모든 연산이 로컬 환경에서 수행 → 개인정보 유출 없이 AI 수준의 검색 품질 제공
- **MCP(Model Context Protocol) 서버 내장**: Claude 등 LLM 기반 워크플로우와 직접 연동 가능
- **node-llama-cpp**를 통해 모든 모델을 온디바이스에서 실행

## 검색 모드 3가지

1. **`search`**: BM25 기반 키워드 검색 (빠른 속도)
2. **`vsearch`**: 임베딩 기반 의미 검색
3. **`query`**: 두 방식을 결합하고 LLM으로 재순위화하는 최고 품질 모드

## 검색 품질 향상 파이프라인

1. 사용자 검색 요청을 **Qwen3-1.7B** 모델로 **질의 확장(Query Expansion)** 수행
2. **SQLite FTS5**와 **sqlite-vec**을 통한 병렬 검색 진행
3. **Reciprocal Rank Fusion (RRF)**으로 결과 통합
4. **Qwen3-Reranker**로 문서 관련도 재평가
5. 순위별 가중치 조정으로 정확도와 의미 유사성 균형 유지

## 사용 모델 (GGUF 포맷, 자동 다운로드·캐시)

- **embeddinggemma-300M**: 임베딩용
- **qwen3-reranker-0.6B**: 재순위화용
- **Qwen3-1.7B**: 질의 확장용

## 주요 사용 예시

```bash
# 전역 설치
bun install -g https://github.com/tobi/qmd

# 컬렉션 추가
qmd collection add ~/notes --name notes
qmd collection add ~/Documents/meetings --name meetings
qmd collection add ~/work/docs --name docs

# 컨텍스트 설정
qmd context add qmd://notes "Personal notes and ideas"
qmd context add qmd://meetings "Meeting transcripts and notes"

# 임베딩 생성
qmd embed

# 검색
qmd search "project timeline"          # 키워드 검색
qmd vsearch "how to deploy"            # 의미 검색
qmd query "quarterly planning process" # 하이브리드+재순위화 (최고 품질)

# 문서 가져오기
qmd get "meetings/2024-01-15.md"
qmd get "#abc123"                      # docid로 가져오기
qmd multi-get "journals/2025-05*.md"   # glob 패턴

# 컬렉션 지정 검색
qmd search "API" -c notes

# 에이전트용 전체 매칭 내보내기
qmd search "API" --all --files --min-score 0.3
```

## 관련 언급 (GeekNews 에디터·댓글)

- **xguru(에디터)**: Obsidian에 정보를 기록하고 Windows·Mac·iPhone에서 iCloud로 동기화해 사용 중; QMD로 편하게 검색 가능해졌다고 언급
- 관련 대안 도구로 **ir**(한국어 전처리 지원 로컬 검색 엔진), **ck**(로컬 퍼스트 시맨틱·하이브리드 BM25 검색 도구), **mq**(jq 스타일 Markdown 쿼리 언어) 등이 소개됨
