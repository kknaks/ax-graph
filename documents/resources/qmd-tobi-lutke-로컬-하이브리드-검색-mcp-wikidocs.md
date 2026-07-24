---
type: reference
title: "QMD — Tobi Lütke의 로컬 하이브리드 검색 엔진(BM25+벡터+LLM 재순위, MCP 내장)"
source: "https://wikidocs.net/blog/@jaehong/13046/"
aliases: ["QMD wikidocs", "QMD Tobi Lütke 해설", "QMD 로컬 검색엔진"]
tags: ["로컬검색", "하이브리드검색", "RAG", "MCP", "GGUF", "임베딩", "LLM재순위", "개인지식관리", "node-llama-cpp", "에이전트도구"]
up: ["하이브리드-검색-파이프라인"]
---

# QMD — Tobi Lütke의 로컬 하이브리드 검색 엔진(BM25+벡터+LLM 재순위, MCP 내장)

## 요약

Shopify 창업자 Tobi Lütke가 공개한 CLI 기반 로컬 문서 검색 엔진 QMD를 심층 해설한 글이다. BM25·벡터·LLM 재순위를 결합한 [[하이브리드-검색-파이프라인]]의 내부 동작(쿼리 확장, RRF, Position-Aware Blending)과 구조적 청킹 알고리즘, MCP 연동, 컨텍스트 기능을 다룬다.

## 핵심 내용

### 문제 정의

개인 노트·회의록·기술 문서가 수백~수천 개로 쌓이면 필요한 순간에 찾지 못하는 문제가 생긴다. 파일 이름 검색은 내용을 보지 못하고, 전문 검색(full-text search)은 무관 문서를 과다 반환한다. AI 에이전트 시대에는 검색 품질이 에이전트의 최종 답변 품질을 결정한다. QMD는 GitHub 별 2만 4천 개 이상을 획득하며 이 문제를 정면 겨냥한 도구다.

### 세 가지 검색 전략의 조합

[[하이브리드-검색-파이프라인]]의 실제 구현이다. QMD는 BM25 전문 검색·벡터 의미 검색·LLM 재순위를 결합한다.

**BM25 전문 검색**: SQLite FTS5 엔진으로 키워드가 정확히 일치하는 문서를 빠르게 탐색한다. 동의어·번역어 검색은 지원하지 않는다("배포 방법" → "deploy" 문서 미검색).

**벡터 의미 검색**: 문서와 검색어를 임베딩(텍스트 → 숫자 벡터)으로 변환해 의미적 거리를 계산한다. 단어가 달라도 의미 유사 문서를 탐색하지만, 정확한 키워드 매칭에서는 BM25보다 약할 수 있다.

**LLM 재순위**: 앞 두 검색이 뽑은 후보 30개를 소형 LLM(Qwen3 Reranker, 640MB)이 재평가·순위 조정한다.

### 하이브리드 파이프라인 상세

1. 사용자 쿼리를 소형 LLM이 2개의 변형 쿼리로 확장(원본 쿼리에 2배 가중치)
2. 3개 쿼리 각각이 BM25 + 벡터 검색 병렬 실행 → 총 6개 결과 목록 생성
3. **RRF(Reciprocal Rank Fusion)**로 6개 결과 통합
4. LLM 재순위 적용 — **Position-Aware Blending** 방식:
   - 1~3위 문서: 원래 검색 점수 75% + 재순위 점수 25%
   - 11위 이하: 재순위 점수 60%로 상향
   - 목적: 정확한 키워드 매칭으로 상위 진입한 문서가 LLM 재순위에서 밀려나지 않도록 방지

### 로컬 실행 모델 구성

| 모델 | 용도 | 크기 |
|---|---|---|
| embeddinggemma-300M | 벡터 임베딩 생성 | ~300MB |
| qwen3-reranker-0.6b | 검색 결과 재순위 | ~640MB |
| qmd-query-expansion-1.7B | 쿼리 확장 (QMD 전용 파인튜닝) | ~1.1GB |

전부 GGUF 형식 양자화 모델로 node-llama-cpp로 로컬 CPU/GPU에서 실행한다. 첫 실행 시 HuggingFace에서 자동 다운로드해 `~/.cache/qmd/models/`에 캐시한다. 쿼리 확장 모델(`qmd-query-expansion-1.7B`)은 Tobi 본인 HuggingFace 계정(`tobil`)에서 호스팅하는 QMD 전용 파인튜닝 모델이다.

로컬 실행의 이유: 회의록·개인 노트·사내 문서의 프라이버시 보호, API 비용·네트워크 지연 없음, 오프라인 동작. 트레이드오프로 대형 임베딩 모델(OpenAI text-embedding-3-large 등) 대비 의미 포착 능력 차이가 있으나, 하이브리드 검색 + 쿼리 확장으로 보완한다.

### 청킹 알고리즘

약 900토큰 단위로 분할하되 단순 글자 수 절단이 아니다. 마크다운 구조적 경계에 점수를 부여한다:

| 경계 | 점수 |
|---|---|
| `# Heading` | 100점 |
| `## Heading` | 90점 |
| 코드 블록 경계 | 80점 |
| 빈 줄 | 20점 |
| 일반 줄바꿈 | 1점 |

900토큰 지점 앞 200토큰 구간에서 거리 감쇠(distance decay)를 적용해 의미적으로 최적인 끊김 지점을 선택하며, 코드 블록 내부 끊김을 방지한다. TypeScript·Python·Go·Rust 등 코드 파일은 `--chunk-strategy auto` 옵션으로 **tree-sitter 기반 AST 청킹**을 지원한다.

### AI 에이전트 통합 — MCP 서버와 컨텍스트

[[에이전틱-ai]] 워크플로와 직접 연동 가능한 MCP 서버를 내장한다. Claude Desktop·Claude Code에서 QMD를 도구로 등록하면 에이전트가 자연어로 문서를 검색·조회한다.

```bash
claude plugin marketplace add tobi/qmd
claude plugin install qmd@qmd
```

기본은 stdio 방식(서브프로세스)이고, HTTP 모드(`qmd mcp --http --daemon`)를 사용하면 여러 클라이언트가 하나의 서버를 공유하면서 LLM 모델이 VRAM에 상주해 매번 로딩 오버헤드를 제거한다.

**컨텍스트(Context) 기능**: 컬렉션·경로에 설명 문자열을 트리 구조로 부여한다. 검색 결과와 함께 메타데이터를 반환해 에이전트가 문서 성격을 파악하고 우선순위를 더 정확하게 판단할 수 있다.

```bash
qmd context add qmd://notes "개인 노트와 아이디어"
qmd context add qmd://meetings "회의 녹취록과 회의록"
```

### 설치 및 기본 사용법

요구사항: Node.js 22 이상 또는 Bun 1.0 이상. 설치: `npm install -g @tobilu/qmd`.

```bash
qmd collection add ~/notes --name notes
qmd embed
qmd search "프로젝트 일정"       # 키워드 검색(빠름)
qmd vsearch "배포 방법"          # 의미 검색
qmd query "분기별 계획 프로세스" # 하이브리드+재순위(최고 품질)
```

CJK(한국어·일본어·중국어) 문서가 많을 경우 기본 임베딩 모델 대신 Qwen3-Embedding으로 교체할 수 있다. Node.js/Bun SDK로 애플리케이션에 직접 임베딩도 가능하다(`createStore` API).

### 핵심 통찰

2~3년 전 BM25 + 벡터 + LLM 재순위 파이프라인은 Elasticsearch 클러스터·GPU 서버를 필요로 했다. **GGUF 양자화와 소형 특화 모델**이 이 장벽을 허물었다. "검색은 클라우드 서비스의 영역"이라는 전제가 흔들리는 시점이며, 에이전트 워크플로의 검색 계층을 로컬로 끌어내린 사례다. 프라이버시·비용·지연 시간 세 가지를 동시에 해결하면서 하이브리드 전략으로 검색 품질을 확보한다.

## 연결

- [[하이브리드-검색-파이프라인]] — QMD가 구현하는 BM25+벡터+LLM 재순위화 파이프라인 개념 SoT 위임; up 노드
- [[에이전틱-ai]] — MCP 서버 내장으로 AI 에이전트 워크플로와 직접 연동 가능한 로컬 검색 도구 사례
- [[qmd-로컬-마크다운-하이브리드-검색-cli]] — 동일 도구(QMD)를 GeekNews 출처로 다룬 자매 reference; 기본 개요·대안 도구 비교 보완
