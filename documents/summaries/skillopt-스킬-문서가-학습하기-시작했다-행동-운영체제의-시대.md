---
type: summary
title: 'SkillOpt: 스킬 문서가 학습하기 시작했다 — 행동 운영체제의 시대'
source_url: https://blog.pebblous.ai/report/microsoft-skillopt-self-evolving-agents/ko/
tags:
- SkillOpt
- 자기진화 에이전트
- 스킬 문서
- 에이전트 최적화
- Microsoft Research
- 텍스트 공간 학습
- 행동 자산
- 크로스모델 전이
- AI-Ready Behavior
- 에이전트 거버넌스
summarized_at: '2026-07-13T04:36:32.570466+00:00'
---

## Executive Summary

- **SkillOpt**(arXiv:2605.23904, Microsoft Research, 2026-05-22): 에이전트 스킬을 학습 가능한 상태로 다루는 프레임워크
- 핵심 명제: "모델을 계속 바꾸려 하지 말고, 에이전트의 스킬 자체를 학습 가능한 상태로 다뤄라"
- **정량 요약 3줄**:
  1. **52/52 cells best-or-tied** — 6개 벤치마크 × 7개 모델 × 3개 실행 환경 전 조합에서 no-skill·human-skill·one-shot LLM-skill·TextGrad·GEPA·Trace2Skill·EvoSkill 7개 베이스라인 모두 동등 이상
  2. GPT-5.5 direct chat **+23.5pt**, Codex agentic loop **+24.8pt**, Claude Code **+19.1pt** — 모델 한 세대 점프(GPT-3.5→GPT-4, 통상 +15~+20pt)와 동등하거나 더 큰 향상, 프론티어 학습 비용의 6~7 자릿수 아래 가격으로 달성
  3. **스킬은 모델 사이를 옮겨다닌다** — Cross-model +15.2%, Cross-harness +31.8%, Codex→Claude Code SpreadsheetBench 22.1→81.8(+59.7pt)

## 1. 더 큰 모델의 환상

- 기존 패러다임: GPU 증설·파라미터 확대·프롬프트 확장으로 에이전트 성능을 끌어올리려 했으나, 현실 에이전트는 여전히 불안정
  - 같은 문제를 두 번 시키면 다른 결과 출력
  - 환경이 조금만 바뀌면 붕괴
  - 인간이 손으로 다듬은 스킬 문서는 몇 번의 업데이트 후 구식화
- SkillOpt의 전환: 같은 모델, 같은 추론 비용 위에서 스킬 문서만 교체해 한 세대 분량 성능 점프

### 2026년 봄 빅테크 전략의 두 갈래

- **진영 A — 모델 스케일링**: OpenAI GPT-5/o3, Anthropic Opus 4.x, Google Gemini Ultra, Meta Llama 5, xAI Grok 4.3 Heavy
- **진영 B — 행동 자산 학습**: Microsoft SkillOpt(2026-05-22), Anthropic Claude Skills + Managed Agents Dreaming, NousResearch Hermes, Sentient EvoSkill, Stanford GEPA

## 2. 스킬 문서가 던지는 질문

- 학습되는 유일한 객체: **best_skill.md** — 절차(procedures), 도메인 휴리스틱, 도구 사용 정책, 출력 제약, 실패 모드가 자연어로 기술됨
- 옵티마이저 모델(별도 LLM)이 타깃 모델의 실행 궤적을 보고 이 문서를 수정
- 모델과 에이전트는 frozen, 학습되는 것은 두 모델 사이의 텍스트 한 장

> "We formulate agent-skill learning as optimization over an external natural-language state and introduce SkillOpt, a harness-agnostic optimizer with rollout batches, reflection minibatches, add/delete/replace edits, textual learning rates, schedules, held-out acceptance, rejected-edit buffers, and epoch-wise slow/meta update."
> — SkillOpt §1 Contributions (arXiv:2605.23904)

### 2.1 학습 대상의 위상이 바뀌었다

- 가중치 공간(연속·고차원·모델 종속·인간 불가독) → 자연어 공간(이산·의미적·모델 독립·인간 가독)
- 스킬 문서는 모델에 묶이지 않고, 사람이 읽을 수 있으며, 부분 수정이 자연스러움

### 2.2 학습 결과물을 인간이 읽을 수 있다

- GB짜리 모델 파일 대신 수 KB의 마크다운
- 변경 이력을 git으로 추적 가능, 사람의 검토 게이트 삽입 가능
- AI 거버넌스·책임 귀속 관점에서 "왜 이렇게 결정했는가"를 텍스트로 묻고 답할 수 있게 됨

### 2.3 학습 결과가 다른 모델로 옮겨갈 수 있다

> "A skill is a portable natural-language artifact that packages procedures, domain heuristics, tool policies, output constraints, and failure modes, letting a frozen agent adapt through external text."
> — SkillOpt §1 Introduction

- GPT-5.5에서 학습한 스킬 → Qwen3.5-4B 이전 가능
- Codex 환경 스킬 → Claude Code 환경 이전 가능

## 3. 텍스트 공간의 Gradient Descent

### 알고리즘 1 Epoch의 4단계

1. **Rollout**: 타깃 모델이 현재 best_skill.md를 들고 mini-batch 태스크 실행, 궤적·점수 수집
2. **Reflect**: 옵티마이저 모델이 성공·실패 궤적을 분리 분석, 재사용 가능한 절차 추출
3. **Edit**: add·delete·replace 세 연산을 edit budget(텍스트 학습률) 한도 내에서 제안
4. **Gate**: held-out validation set에서 점수가 엄격하게 개선될 때만 채택, 아니면 rejected-edit buffer로 이동(다음 epoch의 학습 신호)

> "The deep-learning analogy is operational rather than decorative. Rollout and reflection batch sizes control the noise in the evidence used for each edit; the textual learning rate and schedule control how far one skill version is allowed to move from the previous one; the held-out gate plays the role of validation; and the epoch-wise slow/meta update acts like a momentum term, carrying stable editing directions across epochs."
> — SkillOpt §1

### 3.1 가중치 공간 ↔ 텍스트 공간 7가지 대응

| Deep Learning (가중치 공간) | SkillOpt (텍스트 공간) |
|---|---|
| Mini-batch | Rollout / Reflection minibatch |
| Learning rate | Textual learning rate (edit budget) |
| Validation loss | Held-out acceptance gate |
| Momentum | Epoch-wise slow/meta update |
| Gradient | Reflection on success/failure trajectories |
| Negative-sample replay | Rejected-edit buffer |
| Frozen backbone + LoRA | Frozen agent + external skill.md |

> "Train agent skills like you train neural networks — with epochs, (mini-)batchsize, learning rates, and validation gates — but without touching model weights."
> — microsoft/SkillOpt README (MIT License)

### 3.2 학술 계보 — 8년의 누적

- **ReAct** (2022, Yao et al.): 추론과 행동을 interleaved 시퀀스로 결합, 에이전트의 "호흡" 확립
- **Reflexion** (2023, Shinn et al., NeurIPS): binary/scalar feedback → verbal feedback 변환, "semantic gradient" 개념의 직계 선조. episodic 메모리에 머무름
- **Voyager** (2023, Wang et al.): GPT-4 위에 ever-growing skill library 최초 구현. 스킬을 "추가만" 했음
- **DSPy** (2023, Khattab et al.): "프롬프트를 짜지 말고 LM을 프로그래밍하라", 파이프라인 컴파일러 위상 정립
- **TextGrad** (2024, Yuksekgonul et al.): "텍스트 미분"의 수학적 정당화 첫 시도. SkillOpt의 직계 학술 선조
- **GEPA** (2025, Stanford): Reflective Prompt Evolution이 강화학습을 능가할 수 있음을 입증. ICLR 2026 oral
- **Hermes Agent** (2025, NousResearch): 산업 구현체로서의 self-evolving 에이전트
- **EvoSkill·Trace2Skill** (2026): 실패 궤적에서 스킬을 발견하는 직계 경쟁자. SkillOpt 52/52 비교에서 함께 깔림
- SkillOpt: 이 모든 흐름을 받아 "단일 procedural skill document라는 안정된 학습 대상에 deep-learning training discipline 풀세트를 처음으로 이식한 시스템"

## 4. 평균 뒤의 이야기 — 벤치마크별 상세 수치

### GPT-5.5 direct chat 환경, 6개 벤치마크 (No-skill vs SkillOpt)

| 벤치마크 | 도메인 | No-skill | SkillOpt | 향상 |
|---|---|---|---|---|
| SearchQA | 문서 검색 QA | 77.7 | 87.3 | +9.6 |
| ALFWorld | 임바디드 추론 | 83.6 | 95.5 | +11.9 |
| DocVQA | 스캔 문서 이해 | 78.8 | 91.2 | +12.4 |
| LiveMathematicianBench | 고급 수학 | 37.6 | 66.9 | +29.3 |
| SpreadsheetBench | 스프레드시트 조작 | 41.8 | 80.7 | +38.9 |
| OfficeQA | 엔터프라이즈 생산성 | 33.1 | 72.1 | +39.0 |
| **평균** | — | **58.8** | **82.3** | **+23.5** |

출처: arXiv:2605.23904, Table 1

- **향상폭 패턴**: 베이스라인이 낮고 절차적 지식이 결정적인 작업에서 향상폭 폭발 — OfficeQA +39.0, SpreadsheetBench +38.9, LiveMath +29.3
- 이 세 셀은 모델 한 세대 점프(+15~+20pt)를 두 번 겹친 수치
- EvoSkill이 Codex SpreadsheetBench에서 27.5→67.5를 달성한 위에서 SkillOpt가 67.5→85.0(+17.5)을 추가로 달성

**주의**: 논문은 표준편차·신뢰구간을 미공개. "통계적으로 robust"라는 단정은 학술적으로 위험하며, 보고된 향상폭으로 기술하는 것이 정확함. 다만 52/52 cells 우위는 셀 단위 측정이므로 일관성(consistency) 자체는 강한 신호.

### Epoch별 학습 동학

- SpreadsheetBench: epoch 2까지 가파른 향상 후 plateau
- SearchQA: 4 epoch 이후 안정
- LiveMath: 16 epoch까지 점진적 향상
- validation gate가 과적합을 방지하는 양상 관찰됨

> "SkillOpt is best or tied-best on 52 of 52 cells and outperforms no-skill, human-skill, one-shot LLM-skill, prompt-optimization (TextGrad, GEPA), and skill-evolution (Trace2Skill, EvoSkill) baselines under every model."
> — SkillOpt §1 Contributions

## 5. 옮겨다니는 스킬, 옮겨다닐 수 없는 가중치

### 5.1 전이 실험 — 세 종류의 옮겨다님

| 전이 유형 | 실험 설정 | 측정 향상폭 |
|---|---|---|
| Cross-model (대→소) | GPT-5.4 학습 → GPT-5.4-mini, SpreadsheetBench | +9.4pt |
| Cross-model (극소형) | GPT-5.4 학습 → GPT-5.4-nano (논문 추정) | +15.2% |
| Cross-harness | Codex 학습 → Claude Code 실행 (평균) | +31.8% |
| 단일 극단 사례 | Codex → Claude Code, SpreadsheetBench (22.1→81.8) | +59.7pt |
| Self-optimizer | GPT-5.4-nano가 자기 자신의 옵티마이저 역할 | +10.4% |

출처: arXiv:2605.23904 본문 transfer 표

### 5.2 비용 자릿수 비교

| 학습 방식 | 1회 비용 | 결과물 형식 | 모델 종속성 |
|---|---|---|---|
| Frontier 사전학습 | $78M ~ $500M | 모델 가중치 (GB~TB) | 완전 종속 |
| LoRA 파인튜닝 | $1K ~ $100K | Adapter 가중치 (MB) | 호환 모델 한정 |
| SkillOpt 1회 최적화 | $100 ~ $500 | best_skill.md (KB) | 모델 독립 |

출처: Stanford HAI AI Index 2025·2026, Epoch AI(2024), arXiv:2605.23904 §3 정성 추정

- 자릿수 6~7개 차이: Frontier 학습이 $10^8 수준이라면 SkillOpt는 $10^2 수준
- **모델 가중치 = 매 세대마다 재작성해야 하는 소모재** vs **스킬 문서 = 누적되는 자본재**

> "SkillOpt instead optimizes a persistent skill document that can be trained, validated, exported, and reused with the adapted model, applying language-level controllability to a stable procedural skill state."
> — SkillOpt §2 Related Work

## 6. 학습하는 조직, 진영의 분기

### 빅테크 두 진영 비교

| 축 | 진영 A — 모델 스케일링 | 진영 B — 스킬·행동 자산 학습 |
|---|---|---|
| 대표 주자 | OpenAI, Meta, Google DeepMind, xAI | Microsoft Research, Anthropic, NousResearch, Sentient, Stanford(GEPA) |
| 대표 산출물 | GPT-5.5, Llama 5, Gemini Ultra, Grok 4.3 Heavy | SkillOpt, Claude Skills + Managed Agents Dreaming, Hermes Agent |
| 핵심 명제 | "agentic model first, chat model second" | "Train the procedure, not the weights" |
| 학습 비용 | $100M~$500M | $100~$500 |
| 학습 결과물 | 모델 가중치 (GB~TB), 종속적 | 스킬 문서·메모리·트레이스, 이식 가능 |
| 표준화 게임 | 자사 API·자사 모델 우선 | MCP open standard, Agent Skills open standard, SkillOpt MIT |

- Anthropic: Claude Skills를 open standard로 공개, MCP를 Linux Foundation에 기부(2026-05)
- Microsoft: SkillOpt를 MIT 라이선스로 GitHub 공개
- 저자 해석: 스킬·도구·메모리 계층을 "행동 자산은 공유 가능한 자연어 자산"이라는 합의 위에 올려놓으려는 동시 행동

### 6.1 한국의 같은 날 — 2026-05-22

- **2026-05-22**: SkillOpt arXiv 공개 당일, 한글과컴퓨터와 LG AI연구원이 ChatEXAONE 결합 전략적 사업 협약 체결 (ZDNet Korea, AI타임스, 디지털데일리 동시 보도)
- 한국 AI 시장: IITP 기준 2025년 3.44조원 → 2027년 4.46조원(CAGR 14.3%)
- 주요 플레이어: 네이버 "에이전트N", 카카오 "카나나", 업스테이지, KT Agent Builder + Agentic Fabric, SK텔레콤 AI Native 전환
- **한국 AI 기본법**: 2024-12-26 통과, 2026-01-22 시행. EU AI Act 다음 세계 두 번째 포괄적 AI 법률
  - 핵심 쟁점: "AI 에이전트의 오판 책임은 누구에게 귀속되는가"
- AgentOps 시장: 2025년 $1.8B → 2034년 $58.4B(CAGR 45%) 추정(MarketIntelo, 출처 추정 명시됨)
- **SkillOps**라는 새 하위 범주가 태어나고 있다는 저자의 시각

## 7. 진단된 스킬 문서 — 데이터에서 행동으로 (페블러스 시각)

- 페블러스 기존 명제: 데이터를 진단 가능한 상태로 만든다(DataClinic·AI-Ready Data·DataGreenhouse·PebbloSim)
- SkillOpt가 확장한 방향: **AI-Ready Data → AI-Ready Behavior**

### 7.1 DataClinic 5신호 → SkillClinic 5신호 재맵핑

| DataClinic (학습 데이터) | SkillClinic (스킬 문서) | 진단 질문 |
|---|---|---|
| 레이블 무결성 | 검증 무결성 | held-out gate 통과 이력이 깨끗한가? |
| 분포 균형 | 전이 가능성 | 다른 모델·하니스에서도 작동하는가? |
| 신선도 | 갱신 신선도 | 옵티마이저가 마지막으로 다듬은 게 언제인가? 죽은 스킬은 아닌가? |
| 결측 | 의미 누락 | 어떤 실패 모드를 아직 다루지 못하고 있는가? |
| 이상치 | 실행 이상 | rejected-edit buffer에 같은 종류 거절이 반복되는가? |

### 7.2 고객이 묻게 될 세 가지 질문

1. **현재 상태**: 우리 회사의 스킬 라이브러리는 지금 몇 개이며, 그 중 살아 있는 것·죽은 것·중복인 것은 얼마인가?
2. **검증**: 옵티마이저가 수정한 스킬을 사람이 어떻게 검토하는가? 검증 게이트는 충분히 엄격한가?
3. **전이**: 모델을 GPT-5.5에서 Claude Code로 갈아탔을 때 어떤 스킬이 전이되고 어떤 스킬이 깨지는가?

- 한국 AI 기본법의 책임 귀속 쟁점과 직결: 에이전트 오판 시 어떤 스킬 문서의 어떤 줄에서 비롯되었는지를 사람이 읽을 수 있는 형태로 증명하는 능력이 거버넌스의 새 표준이 됨
- 행동 데이터베이스(에이전트 성공/실패 로그, 실행 궤적, 도구 호출 패턴)가 PebbloSim·DataGreenhouse 자산과 자연스럽게 결합 가능하다는 저자 주장

## 8. 한 편의 논문이 그린 좌표

- SkillOpt가 열어 보인 것: AI의 학습 가능한 객체의 위상이 가중치에서 자연어 문서로 확장
- 자연어 문서는 한 번 만들면 다음 모델로 이전 가능한 누적 자산
- 빅테크 두 곳이 같은 시기에 스킬 계층을 오픈 소스·오픈 스탠더드로 개방
- 페블러스 결론: **"진단된 스킬 문서(diagnosed skill documents)"**라는 신규 카테고리가 비어 있으며, 데이터 진단을 해온 회사가 자연스럽게 도달하는 다음 좌표

## 참고문헌 (논문 내 인용 목록)

- arXiv:2605.23904 — SkillOpt 본 논문
- ReAct (arXiv:2210.03629), Reflexion (arXiv:2303.11366), Voyager (arXiv:2305.16291)
- DSPy (arXiv:2310.03714), TextGrad (arXiv:2406.07496), GEPA (arXiv:2507.19457)
- EvoSkill (arXiv:2603.02766), Trace2Skill (arXiv:2603.25158)
- Stanford HAI AI Index 2026, Epoch AI(2024), McKinsey(2025-11), MarketsAndMarkets(2026)
