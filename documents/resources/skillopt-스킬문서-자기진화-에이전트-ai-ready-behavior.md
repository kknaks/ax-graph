---
type: reference
title: "SkillOpt: 스킬 문서를 학습하는 자기진화 에이전트와 'AI-Ready Behavior' 전환"
source: "https://blog.pebblous.ai/report/microsoft-skillopt-self-evolving-agents/ko/"
aliases: ["SkillOpt 논문 해설", "스킬 문서 최적화 프레임워크", "Microsoft SkillOpt arXiv:2605.23904"]
tags: ["SkillOpt", "자기진화에이전트", "스킬문서", "에이전트최적화", "텍스트공간학습", "크로스모델전이", "AI-Ready-Behavior", "에이전트거버넌스", "MicrosoftResearch", "페블러스"]
up: ["에이전틱-ai"]
---

# SkillOpt: 스킬 문서를 학습하는 자기진화 에이전트와 'AI-Ready Behavior' 전환

## 요약

Microsoft Research가 2026년 5월 공개한 SkillOpt(arXiv:2605.23904)는 모델 가중치가 아닌 [[스킬-문서|자연어 스킬 문서]]를 학습 대상으로 삼아 딥러닝 훈련 규율을 텍스트 공간에 이식한 에이전트 최적화 프레임워크다. 6개 벤치마크 × 7개 모델 × 3개 실행 환경의 52/52 셀 전체에서 7개 베이스라인을 동등 이상 성능으로 앞섰으며, 페블러스는 이 흐름을 'AI-Ready Data → [[ai-ready-behavior]]'로 해석한다.

## 핵심 내용

### 더 큰 모델의 환상과 SkillOpt의 전환

기존 패러다임은 GPU 증설·파라미터 확대·프롬프트 확장으로 에이전트 성능을 끌어올리려 했으나 현실 에이전트는 여전히 불안정했다 — 같은 문제를 두 번 시키면 다른 결과, 환경 변화에 붕괴, 손으로 다듬은 스킬 문서는 몇 번의 업데이트 후 구식화. SkillOpt의 핵심 명제는 "같은 모델, 같은 추론 비용 위에서 스킬 문서만 교체해 한 세대 분량 성능 점프"다.

**정량 요약 3줄**:
1. **52/52 cells best-or-tied** — 6개 벤치마크 × 7개 모델 × 3개 실행 환경 전 조합, 7개 베이스라인(no-skill·human-skill·one-shot LLM-skill·TextGrad·GEPA·Trace2Skill·EvoSkill) 동등 이상
2. GPT-5.5 direct chat **+23.5pt**, Codex agentic loop **+24.8pt**, Claude Code **+19.1pt** — 모델 한 세대 점프(+15~+20pt)와 동등하거나 더 큰 향상, 프론티어 학습 비용의 6~7 자릿수 아래 비용으로 달성
3. **스킬은 모델 사이를 옮겨다닌다** — Cross-model +15.2%, Cross-harness +31.8%, Codex→Claude Code SpreadsheetBench 22.1→81.8(+59.7pt)

### 스킬 문서 — 학습 대상의 위상 변화

학습되는 유일한 객체는 [[스킬-문서]](`best_skill.md`)다. 절차·도메인 휴리스틱·도구 사용 정책·출력 제약·실패 모드가 자연어로 기술되며, 옵티마이저 모델(별도 LLM)이 타깃 모델의 실행 궤적을 보고 이 문서를 수정한다 — 모델과 에이전트는 frozen.

> "We formulate agent-skill learning as optimization over an external natural-language state and introduce SkillOpt, a harness-agnostic optimizer with rollout batches, reflection minibatches, add/delete/replace edits, textual learning rates, schedules, held-out acceptance, rejected-edit buffers, and epoch-wise slow/meta update."
> — SkillOpt §1 Contributions (arXiv:2605.23904)

가중치 공간(연속·고차원·모델 종속·인간 불가독) → 자연어 공간(이산·의미적·모델 독립·인간 가독)으로의 위상 전환이 핵심이다. 학습 결과물이 GB짜리 모델 파일 대신 수 KB의 마크다운이며, git 추적·사람 검토 게이트 삽입이 가능해 AI 거버넌스 관점에서 "왜 이렇게 결정했는가"를 텍스트로 묻고 답할 수 있다. 개념 상세는 [[스킬-문서]]로 위임.

### 텍스트 공간의 Gradient Descent

**1 Epoch의 4단계**

1. **Rollout**: 타깃 모델이 현재 best_skill.md를 들고 mini-batch 태스크 실행, 궤적·점수 수집
2. **Reflect**: 옵티마이저 모델이 성공·실패 궤적 분리 분석, 재사용 가능한 절차 추출
3. **Edit**: add·delete·replace 세 연산을 edit budget(텍스트 학습률) 한도 내에서 제안
4. **Gate**: held-out validation set에서 점수가 엄격하게 개선될 때만 채택, 아니면 rejected-edit buffer로 이동(다음 epoch의 학습 신호)

> "The deep-learning analogy is operational rather than decorative. Rollout and reflection batch sizes control the noise in the evidence used for each edit; the textual learning rate and schedule control how far one skill version is allowed to move from the previous one; the held-out gate plays the role of validation; and the epoch-wise slow/meta update acts like a momentum term, carrying stable editing directions across epochs."
> — SkillOpt §1

**가중치 공간 ↔ 텍스트 공간 7가지 대응**

| Deep Learning (가중치 공간) | SkillOpt (텍스트 공간) |
|---|---|
| Mini-batch | Rollout / Reflection minibatch |
| Learning rate | Textual learning rate (edit budget) |
| Validation loss | Held-out acceptance gate |
| Momentum | Epoch-wise slow/meta update |
| Gradient | Reflection on success/failure trajectories |
| Negative-sample replay | Rejected-edit buffer |
| Frozen backbone + LoRA | Frozen agent + external skill.md |

**학술 계보 — 8년의 누적**

ReAct(2022, Yao et al.) → Reflexion(2023, Shinn et al., NeurIPS; "semantic gradient" 직계 선조) → Voyager(2023, Wang et al.; ever-growing skill library 최초, "추가만") → DSPy(2023, Khattab et al.; 파이프라인 컴파일러) → TextGrad(2024, Yuksekgonul et al.; "텍스트 미분" 수학적 정당화, SkillOpt 직계 학술 선조) → GEPA(2025, Stanford; Reflective Prompt Evolution이 강화학습 능가, ICLR 2026 oral) → Hermes Agent(2025, NousResearch) → EvoSkill·Trace2Skill(2026; 실패 궤적에서 스킬 발견, SkillOpt 52/52 비교에서 함께 깔림) → **SkillOpt**: "단일 procedural skill document라는 안정된 학습 대상에 deep-learning training discipline 풀세트를 처음으로 이식한 시스템".

### 벤치마크 상세 수치

**GPT-5.5 direct chat 환경, 6개 벤치마크 (arXiv:2605.23904 Table 1)**

| 벤치마크 | 도메인 | No-skill | SkillOpt | 향상 |
|---|---|---|---|---|
| SearchQA | 문서 검색 QA | 77.7 | 87.3 | +9.6 |
| ALFWorld | 임바디드 추론 | 83.6 | 95.5 | +11.9 |
| DocVQA | 스캔 문서 이해 | 78.8 | 91.2 | +12.4 |
| LiveMathematicianBench | 고급 수학 | 37.6 | 66.9 | +29.3 |
| SpreadsheetBench | 스프레드시트 조작 | 41.8 | 80.7 | +38.9 |
| OfficeQA | 엔터프라이즈 생산성 | 33.1 | 72.1 | +39.0 |
| **평균** | — | **58.8** | **82.3** | **+23.5** |

향상폭 패턴: 베이스라인이 낮고 절차적 지식이 결정적인 작업에서 폭발적 향상. OfficeQA +39.0, SpreadsheetBench +38.9, LiveMath +29.3은 모델 한 세대 점프를 두 번 겹친 수치다. EvoSkill이 Codex SpreadsheetBench에서 27.5→67.5를 달성한 위에서 SkillOpt가 67.5→85.0(+17.5)을 추가로 달성. **주의**: 논문은 표준편차·신뢰구간 미공개 — 향상폭으로만 기술하는 것이 정확. 52/52 cells 우위는 일관성(consistency) 자체의 강한 신호.

**Epoch별 학습 동학**: SpreadsheetBench는 epoch 2까지 가파른 향상 후 plateau, SearchQA는 4 epoch 이후 안정, LiveMath는 16 epoch까지 점진적 향상. validation gate가 과적합을 방지하는 양상이 관찰됐다.

### 크로스모델 전이와 비용 자릿수

**전이 실험 세 종류 (arXiv:2605.23904 본문 transfer 표)**

| 전이 유형 | 실험 설정 | 측정 향상폭 |
|---|---|---|
| Cross-model (대→소) | GPT-5.4 학습 → GPT-5.4-mini, SpreadsheetBench | +9.4pt |
| Cross-model (극소형) | GPT-5.4 학습 → GPT-5.4-nano | +15.2% |
| Cross-harness | Codex 학습 → Claude Code 실행 (평균) | +31.8% |
| 단일 극단 사례 | Codex → Claude Code, SpreadsheetBench (22.1→81.8) | +59.7pt |
| Self-optimizer | GPT-5.4-nano가 자기 자신의 옵티마이저 역할 | +10.4% |

**비용 자릿수 비교**

| 학습 방식 | 1회 비용 | 결과물 형식 | 모델 종속성 |
|---|---|---|---|
| Frontier 사전학습 | $78M ~ $500M | 모델 가중치 (GB~TB) | 완전 종속 |
| LoRA 파인튜닝 | $1K ~ $100K | Adapter 가중치 (MB) | 호환 모델 한정 |
| SkillOpt 1회 최적화 | $100 ~ $500 | best_skill.md (KB) | 모델 독립 |

출처: Stanford HAI AI Index 2025·2026, Epoch AI(2024), arXiv:2605.23904 §3 정성 추정. 자릿수 6~7개 차이. 모델 가중치 = 매 세대마다 재작성해야 하는 소모재 vs 스킬 문서 = 누적되는 자본재.

> "SkillOpt instead optimizes a persistent skill document that can be trained, validated, exported, and reused with the adapted model, applying language-level controllability to a stable procedural skill state."
> — SkillOpt §2 Related Work

### 빅테크 두 진영과 한국 AI 동향

**두 진영 비교**

| 축 | 진영 A — 모델 스케일링 | 진영 B — 스킬·행동 자산 학습 |
|---|---|---|
| 대표 주자 | OpenAI, Meta, Google DeepMind, xAI | Microsoft Research, Anthropic, NousResearch, Sentient, Stanford(GEPA) |
| 대표 산출물 | GPT-5.5, Llama 5, Gemini Ultra, Grok 4.3 Heavy | SkillOpt, Claude Skills + Managed Agents Dreaming, Hermes Agent |
| 핵심 명제 | "agentic model first, chat model second" | "Train the procedure, not the weights" |
| 학습 비용 | $100M~$500M | $100~$500 |
| 학습 결과물 | 모델 가중치 (GB~TB), 종속적 | 스킬 문서·메모리·트레이스, 이식 가능 |
| 표준화 게임 | 자사 API·자사 모델 우선 | MCP open standard, Agent Skills open standard, SkillOpt MIT |

Anthropic은 Claude Skills를 open standard로 공개하고 MCP를 Linux Foundation에 기부(2026-05). Microsoft는 SkillOpt를 MIT 라이선스로 GitHub 공개. 저자 해석: 스킬·도구·메모리 계층을 "행동 자산은 공유 가능한 자연어 자산"이라는 합의 위에 올려놓으려는 동시 행동.

**한국의 같은 날 — 2026-05-22**: SkillOpt arXiv 공개 당일 한글과컴퓨터·LG AI연구원이 ChatEXAONE 결합 전략적 사업 협약 체결. 한국 AI 시장: IITP 기준 2025년 3.44조원 → 2027년 4.46조원(CAGR 14.3%). 주요 플레이어: 네이버 "에이전트N", 카카오 "카나나", KT Agent Builder + Agentic Fabric, SK텔레콤 AI Native 전환. **한국 AI 기본법**(2024-12-26 통과, 2026-01-22 시행): EU AI Act 다음 세계 두 번째 포괄적 AI 법률. 핵심 쟁점: "AI 에이전트의 오판 책임은 누구에게 귀속되는가". AgentOps 시장: 2025년 $1.8B → 2034년 $58.4B(CAGR 45%) 추정(MarketIntelo, 출처 추정 명시).

### 진단된 스킬 문서 — AI-Ready Behavior (페블러스 시각)

[[ai-ready-behavior]]의 상세는 해당 concept로 위임. 요지: 페블러스의 기존 명제(데이터를 진단 가능한 상태로)를 SkillOpt가 스킬 문서 진단으로 확장한다. DataClinic 5신호를 SkillClinic 5신호(검증 무결성·전이 가능성·갱신 신선도·의미 누락·실행 이상)로 재맵핑하며, 조직이 묻게 될 세 가지 질문은 (1) 스킬 라이브러리 현황(살아있는 것·죽은 것·중복), (2) 검증 게이트 엄격성, (3) 모델 전환 시 스킬 전이 가능성이다. 한국 AI 기본법의 책임 귀속 쟁점과 직결 — 에이전트 오판 시 어떤 스킬 문서의 어떤 줄에서 비롯되었는지를 사람이 읽을 수 있는 형태로 증명하는 능력이 거버넌스의 새 표준.

### SkillOpt가 열어 보인 좌표

- AI의 학습 가능한 객체 위상이 가중치에서 자연어 문서로 확장
- 자연어 문서는 한 번 만들면 다음 모델로 이전 가능한 누적 자산
- 빅테크 두 곳이 같은 시기에 스킬 계층을 오픈 소스·오픈 스탠더드로 개방
- 페블러스 결론: "진단된 스킬 문서(diagnosed skill documents)"라는 신규 카테고리가 비어 있으며, 데이터 진단을 해온 회사가 자연스럽게 도달하는 다음 좌표

## 연결

- [[에이전틱-ai]] — SkillOpt가 최적화하는 대상이 에이전틱 AI 시스템의 스킬 계층; lineage 상위 개념
- [[루프-엔지니어링]] — 루프의 5요소 중 스킬(Skills) 계층을 SkillOpt가 자동 최적화; 스킬 문서 없는 루프는 매 사이클마다 재파생 필요
- [[스킬-문서]] — SkillOpt가 학습하는 단일 객체 best_skill.md의 개념 SoT; 위상 변화·이식성·인간 가독성 상세 위임
- [[ai-ready-behavior]] — DataClinic→SkillClinic 재맵핑과 스킬 문서 진단 거버넌스 개념 SoT; 페블러스 시각 상세 위임
