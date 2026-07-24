---
type: reference
title: "QMD — 로컬 Markdown 하이브리드 검색 CLI (BM25+벡터+LLM 재순위화, MCP 내장)"
source: "https://news.hada.io/topic?id=26213"
aliases: ["QMD", "Quick Markdown Search", "qmd CLI"]
tags: ["마크다운검색", "CLI도구", "로컬AI", "하이브리드검색", "MCP", "BM25", "벡터검색", "SQLite", "오픈소스"]
up: []
---

# QMD — 로컬 Markdown 하이브리드 검색 CLI (BM25+벡터+LLM 재순위화, MCP 내장)

## 요약

Shopify CEO Tobi Lütke가 개발한 오픈소스 CLI로, 개인 노트·기술 문서·회의록 등 로컬 Markdown 파일을 BM25 키워드 검색·벡터 의미 검색·LLM 재순위화의 [[하이브리드-검색-파이프라인]]으로 검색한다. 모든 연산이 로컬에서 수행되며 MCP 서버를 내장해 Claude 등 LLM 기반 워크플로우와 직접 연동할 수 있다.

## 핵심 내용

### 개요

- **QMD(Quick Markdown Search)**: 개인 노트, 기술 문서, 회의록 등 Markdown 기반 문서를 로컬에서 검색하기 위한 경량 CLI 검색 엔진
- 출처: Shopify 창업자·CEO **Tobi Lütke**의 오픈소스 (github.com/tobi)
- 라이선스: **MIT** / 런타임: **TypeScript + Bun**; 인덱스는 **SQLite**에 저장
- **완전 로컬 실행**: 모든 연산이 로컬 환경에서 수행되어 개인정보 유출 없이 AI 수준의 검색 품질 제공

### 검색 모드 3가지

1. **`search`** — BM25 기반 키워드 검색 (빠른 속도)
2. **`vsearch`** — 임베딩 기반 의미 검색
3. **`query`** — 두 방식을 결합하고 LLM으로 재순위화하는 최고 품질 모드

### 하이브리드 검색 품질 파이프라인

[[하이브리드-검색-파이프라인]]의 실제 구현이다. `query` 모드에서 다음 5단계가 순차 실행된다:

1. **질의 확장(Query Expansion)**: 사용자 검색어를 **Qwen3-1.7B** 모델로 확장
2. **병렬 검색**: **SQLite FTS5**(BM25)와 **sqlite-vec**(벡터) 동시 실행
3. **결과 통합**: **Reciprocal Rank Fusion(RRF)**으로 두 결과 합산
4. **재순위화**: **Qwen3-Reranker**로 문서 관련도 재평가
5. **가중치 조정**: 정확도와 의미 유사성 균형 유지

사용 모델(GGUF 포맷, 자동 다운로드·캐시):
- **embeddinggemma-300M** — 임베딩용
- **qwen3-reranker-0.6B** — 재순위화용
- **Qwen3-1.7B** — 질의 확장용

**node-llama-cpp**를 통해 모든 모델을 온디바이스에서 실행한다.

### MCP 서버 내장 및 LLM 워크플로우 연동

**MCP(Model Context Protocol) 서버를 내장**하여 Claude 등 [[에이전틱-ai]] 기반 워크플로우와 직접 연동 가능하다. 루프 엔지니어링 맥락에서 QMD는 Markdown 지식 베이스를 에이전트 툴로 노출하는 MCP 커넥터 역할을 한다.

### 주요 사용 예시

```bash
# 전역 설치
bun install -g https://github.com/tobi/qmd

# 컬렉션 추가
qmd collection add ~/notes --name notes
qmd collection add ~/Documents/meetings --name meetings

# 컨텍스트 설정
qmd context add qmd://notes "Personal notes and ideas"

# 임베딩 생성
qmd embed

# 검색
qmd search "project timeline"          # 키워드 검색
qmd vsearch "how to deploy"            # 의미 검색
qmd query "quarterly planning process" # 하이브리드+재순위화

# 문서 가져오기
qmd get "meetings/2024-01-15.md"
qmd multi-get "journals/2025-05*.md"   # glob 패턴

# 에이전트용 전체 매칭 내보내기
qmd search "API" --all --files --min-score 0.3
```

### 관련 대안 도구 (GeekNews 언급)

- **ir** — 한국어 전처리 지원 로컬 검색 엔진
- **ck** — 로컬 퍼스트 시맨틱·하이브리드 BM25 검색 도구
- **mq** — jq 스타일 Markdown 쿼리 언어

GeekNews 에디터(xguru)는 Obsidian에 정보를 기록하고 iCloud로 동기화하는 환경에서 QMD로 편하게 검색 가능해졌다고 언급했다.

## 연결

- [[하이브리드-검색-파이프라인]] — QMD의 `query` 모드가 구현하는 BM25+벡터+LLM 재순위화 파이프라인 개념 SoT 위임
- [[에이전틱-ai]] — MCP 서버 내장으로 LLM 에이전트 워크플로우와 직접 연동 가능한 검색 도구 사례
