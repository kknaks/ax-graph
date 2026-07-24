---
type: summary
title: Shopify 창업자 Tobi Lütke가 만든 로컬 하이브리드 검색 엔진 QMD
source_url: https://wikidocs.net/blog/@jaehong/13046/
tags:
- QMD
- 로컬 검색 엔진
- 하이브리드 검색
- BM25
- 벡터 임베딩
- LLM 재순위
- MCP
- Tobi Lütke
- GGUF
- 개인 지식 관리
summarized_at: '2026-07-13T01:14:05.794250+00:00'
---

## 문제 정의

- 개인 노트·회의록·기술 문서가 수백~수천 개로 쌓이면 필요한 순간에 찾지 못하는 문제 발생
- 파일 이름 검색 → 내용 미검색, 전문 검색(full-text search) → 무관 문서 과다 반환
- AI 에이전트 시대에는 검색 품질이 곧 에이전트 최종 답변 품질을 결정
- **QMD**는 Shopify 창업자 **Tobi Lütke**가 공개한 로컬 CLI 검색 엔진으로, 이 문제를 정면 겨냥
- GitHub 별(star) 2만 4천 개 이상 획득

## 핵심 개요

- **QMD**: 마크다운 노트·회의록·기술 문서를 로컬에서 색인·검색하는 CLI 기반 검색 엔진
- 세 가지 검색 전략 조합: BM25 키워드 검색 + 벡터 의미 검색 + LLM 재순위(re-ranking)
- 모든 처리 로컬 실행 — 문서가 외부 서버로 전송되지 않음
- **node-llama-cpp** 위에서 GGUF 모델 3개 실행 (총 ~2GB)
- **MCP(Model Context Protocol)** 서버 내장 → Claude Desktop·Claude Code 등 AI 에이전트가 도구로 직접 호출 가능
- "컨텍스트(context)" 기능: 컬렉션·경로에 설명 메타데이터를 트리 구조로 부여

## 세 가지 검색 전략의 조합

### 1. BM25 전문 검색
- SQLite FTS5 엔진 사용
- 키워드가 정확히 일치하는 문서를 빠르게 탐색
- 한계: 동의어·번역어 검색 미지원 (예: "배포 방법" → "deploy" 문서 미검색)

### 2. 벡터 의미 검색 (Vector Semantic Search)
- 문서·검색어를 **임베딩**(텍스트 → 숫자 벡터)으로 변환, 의미적 거리 계산
- 단어가 달라도 의미 유사 문서 탐색 가능
- 한계: 정확한 키워드 매칭에서 BM25보다 약할 수 있음

### 3. LLM 재순위 (Re-ranking)
- 앞 두 검색이 뽑은 후보 30개를 소형 LLM(**Qwen3 Reranker**, 640MB)이 재평가·순위 조정
- "이 문서가 이 질문에 정말 관련 있는가?"를 LLM이 판단

### 파이프라인 상세
1. 사용자 쿼리를 소형 LLM이 2개의 변형 쿼리로 확장 (원본 쿼리에 2배 가중치)
2. 3개 쿼리 각각이 BM25 + 벡터 검색 병렬 실행 → 총 6개 결과 목록 생성
3. **RRF(Reciprocal Rank Fusion)**로 6개 결과 통합
4. LLM 재순위 적용 — **Position-Aware Blending** 방식:
   - 1~3위 문서: 원래 검색 점수 75% + 재순위 점수 25%
   - 11위 이하: 재순위 점수 60%로 상향
   - 목적: 정확한 키워드 매칭으로 상위 진입한 문서가 LLM 재순위에서 밀려나지 않도록 방지

## 로컬 실행 모델 구성

| 모델 | 용도 | 크기 |
|---|---|---|
| embeddinggemma-300M | 벡터 임베딩 생성 | ~300MB |
| qwen3-reranker-0.6b | 검색 결과 재순위 | ~640MB |
| qmd-query-expansion-1.7B | 쿼리 확장 (파인튜닝됨) | ~1.1GB |

- 전부 **GGUF 형식** 양자화 모델, node-llama-cpp로 로컬 CPU/GPU 실행
- 첫 실행 시 HuggingFace 자동 다운로드 → `~/.cache/qmd/models/` 캐시
- **쿼리 확장 모델**(`qmd-query-expansion-1.7B`)은 QMD 전용 파인튜닝 모델 — Tobi 본인 HuggingFace 계정(`tobil`) 호스팅

### 로컬 실행 선택 이유
- 회의록·개인 노트·사내 문서의 프라이버시 보호
- API 호출 비용·네트워크 지연 없음
- 오프라인 동작
- 트레이드오프: 대형 임베딩 모델(예: OpenAI text-embedding-3-large) 대비 의미 포착 능력 차이 가능 → 하이브리드 검색 + 쿼리 확장으로 보완

## 청킹(Chunking) 알고리즘

- 약 **900토큰** 단위로 분할, 단순 글자 수 절단 아님
- 마크다운 구조적 경계에 점수 부여:
  - `# Heading`: 100점
  - `## Heading`: 90점
  - 코드 블록 경계: 80점
  - 빈 줄: 20점
  - 일반 줄바꿈: 1점
- 900토큰 지점 앞 200토큰 구간에서 거리 감쇠(distance decay)를 적용해 의미적으로 최적 끊김 지점 선택
- 코드 블록 내부 끊김 방지 (코드 보호)
- 코드 파일(TypeScript·Python·Go·Rust 등): **tree-sitter** 기반 **AST** 청킹 지원 (`--chunk-strategy auto`)

## AI 에이전트 통합

### MCP 서버
- Claude Desktop·Claude Code에서 QMD를 도구로 등록 → 에이전트가 자연어로 문서 검색·내용 조회
- 설치 방법:
  ```
  claude plugin marketplace add tobi/qmd
  claude plugin install qmd@qmd
  ```
- 또는 `~/.claude/settings.json`에 직접 추가
- 기본: stdio 방식(서브프로세스)
- HTTP 모드(`qmd mcp --http --daemon`): 여러 클라이언트가 하나의 서버 공유, LLM 모델 VRAM 상주로 매번 로딩 오버헤드 제거

### 컨텍스트(Context) 기능
- 컬렉션·경로에 설명 문자열을 트리 구조로 부여:
  ```
  qmd context add qmd://notes "개인 노트와 아이디어"
  qmd context add qmd://meetings "회의 녹취록과 회의록"
  qmd context add qmd://docs "업무 문서"
  ```
- 검색 결과와 함께 메타데이터 반환 → 에이전트가 문서 성격 파악 후 우선순위 더 정확하게 판단

## 설치 및 기본 사용법

- 요구사항: Node.js 22 이상 또는 Bun 1.0 이상
- 설치: `npm install -g @tobilu/qmd`

```bash
# 컬렉션 등록
qmd collection add ~/notes --name notes
qmd collection add ~/Documents/meetings --name meetings

# 벡터 임베딩 생성
qmd embed

# 키워드 검색 (빠름)
qmd search "프로젝트 일정"

# 의미 검색
qmd vsearch "배포 방법"

# 하이브리드 검색 + 재순위 (최고 품질)
qmd query "분기별 계획 프로세스"
```

- Node.js/Bun SDK로 애플리케이션에 직접 임베딩 가능 (`createStore` API)
- CJK(한국어·일본어·중국어) 문서 다수 시: 기본 임베딩 모델 대신 Qwen3-Embedding으로 교체 가능

## 핵심 통찰

- 2~3년 전 BM25 + 벡터 + LLM 재순위 파이프라인은 Elasticsearch 클러스터·GPU 서버 필요 → **GGUF 양자화와 소형 특화 모델**이 이 장벽을 허물었음
- "검색은 클라우드 서비스의 영역"이라는 전제가 흔들리는 시점
- 에이전트 워크플로의 검색 계층을 로컬로 끌어내린 사례
- 프라이버시·비용·지연 시간 세 가지를 동시에 해결하면서 하이브리드 전략으로 검색 품질 확보
