---
type: summary
title: 'SkillOpt: AI 에이전트 스킬을 훈련 가능한 파라미터로 만드는 프레임워크'
source_url: https://www.microsoft.com/en-us/research/blog/skillopt-agent-skills-as-trainable-parameters/
tags:
- SkillOpt
- AI agent
- skill optimization
- trainable parameters
- LLM
- prompt optimization
- agent skills
- transfer learning
- benchmark
- Microsoft Research
summarized_at: '2026-07-13T04:35:25.877683+00:00'
---

## 개요 및 문제 제기

**대형 언어 모델(LLM)**은 증거 수집·도구 호출·다단계 태스크를 수행하는 에이전트로 점점 더 많이 배포되고 있다. 현재 에이전트의 핵심 난제는 도구 호출 가능 여부가 아니라 **신뢰성 있는 태스크 완수**다.

기존 에이전트 스킬 작성 방식 세 가지:
- 전문가가 수동으로 작성
- 프론티어 모델이 원샷(one-shot)으로 생성
- 에이전트가 실행 후 느슨하게 수정

이 방식들의 공통 문제:
- 딥러닝 옵티마이저처럼 동작하지 않음
- 스텝 크기 제어, 검증 분리, 실패 편집 기억 기능 없음
- 스킬이 매 재작성마다 길어지고 표류(drift)함
- 합리적으로 보이는 수정이 실제 성능을 조용히 저하시킬 수 있음
- 에이전트 프로토타입 → 프로덕션 배포로의 전환에 주요 장애물

## SkillOpt의 핵심 개념

**핵심 재구성**: "더 나은 프롬프트를 어떻게 쓸까?" → "스킬을 어떻게 훈련할까?"

- **스킬 파일**을 동결된(frozen) 타깃 모델 외부에 존재하는 **훈련 가능한 파라미터**로 취급
- 훈련 스타일의 최적화 루프를 도입
- 결과물: 읽기 가능하고(readable), 감사 가능하며(auditable), 이전 가능한(transferable) 소형 스킬 파일(`best_skill.md`)

## 작동 원리: 전진-후진-업데이트 사이클

### 전진 패스(Forward Pass)
- 동결된 타깃 모델이 현재 스킬로 훈련 태스크 배치를 실행
- **롤아웃 배치 크기**가 각 업데이트가 받는 증거량을 제어

### 후진 패스(Backward Pass)
- 별도의 **옵티마이저 모델**이 결과 궤적(trajectory)을 반성 미니배치로 읽음
- 성공 궤적에서 보존할 패턴, 실패 궤적에서 수정할 패턴을 추출

### 업데이트 단계(Update Step)
- 옵티마이저가 소규모 add·delete·replace 편집 제안
- 후보 편집들이 병합·중복제거·랭킹·클리핑됨 (**텍스트 학습률**: 단계당 편집 예산)
- **검증 게이트(Validation Gate)**: 후보 스킬이 held-out 검증 분할에서 현재 스킬보다 엄격히 높은 점수를 받을 때만 채택
- 기각된 편집 → **기각 편집 버퍼(rejected-edit buffer)**: 같은 에포크 내 이후 옵티마이저 호출의 부정 피드백으로 활용

### 슬로우/메타 업데이트(Slow/Meta Update)
- 에포크 단위로 동작하는 느린 cadence 업데이트
- 단일 배치로는 드러나지 않는 장기 패턴 통합

**4가지 제어 메커니즘**: 경계 있는 텍스트 편집 + 검증 게이팅 + 최선 버전 선택 + 기각 편집 피드백 → 스킬이 표류 없이 수렴

## 평가 결과

### 평가 범위
- **6개 벤치마크**: SearchQA, SpreadsheetBench, OfficeQA, DocVQA, LiveMathematicianBench, ALFWorld
- **7개 타깃 모델**: 프론티어급 GPT-5.5부터 소형 오픈 웨이트 Qwen3.5-4B까지
- **3가지 실행 모드**: direct chat, Codex, Claude Code
- **총 52개 평가 셀**

### 비교 대상
Human-written skills, 원샷 LLM skills, Trace2Skill, TextGrad, GEPA, EvoSkill

### 주요 성과
- **모든 52개 평가 셀**에서 최고 또는 공동 최고 성능
- GPT-5.5 direct chat: 6벤치마크 평균 58.8 → **82.3** (+23.5점 절대 향상)
  - 단일 최고 경쟁 방법을 셀별로 선택한 오라클보다 +5.4점 상회
- 절차적 벤치마크에서 가장 큰 향상:
  - SpreadsheetBench: 41.8 → **80.7**
  - OfficeQA: 33.1 → **72.1**
  - LiveMathematicianBench: 37.6 → **66.9**
- 에이전틱 루프에서도 성과:
  - Codex 내 GPT-5.5: +24.8점
  - Claude Code 내 GPT-5.5: +19.1점 (no skill 대비)

## 소형 모델 + 스킬 파일 = 상위 모델 기준선 근접

모델 가중치 변경 없이, 추론 시 추가 모델 호출 없이:
- **GPT-5.4-mini** 최적화 후 평균(64.3) > 상위 GPT-5.4 no-skill 기준선(59.7)
- **GPT-5.4-nano** 최적화 후(57.4) > GPT-5.2 no-skill 기준선(51.3)
- **Qwen3.5-4B**(4B 파라미터 오픈 웨이트 모델)도 GPT-5.2 no-skill 기준선 상회

> 과거에는 더 큰 모델이 필요했던 성능 향상을 하나의 최적화된 스킬 파일로 근사할 수 있다.

## 스킬 이전성(Transferability)

최적화된 스킬 파일은 특정 모델·벤치마크·실행 환경에 과적합된 지시가 아닌 **재사용 가능한 태스크 해결 절차**를 담는다.

이전 실험 결과:
- 모델 스케일 간 이전 → 성능 유지
- 실행 하네스 간 이전 → 성능 유지
- 인접 수학 벤치마크로 이전 → 성능 유지

**가장 명확한 예시 — 크로스 하네스 이전**:
- Codex 내에서 훈련된 스프레드시트 스킬을 추가 최적화 없이 Claude Code에 이식
- no-skill 기준선 22.1 → **81.8** (+59.7)
- Claude Code 내 직접 훈련 결과(80.4)를 소폭 상회
- 두 하네스가 서로 다른 도구 인터페이스를 노출함에도 이전 성공 → **SkillOpt는 하네스 특화 레시피가 아닌 범용 워크플로우 로직을 학습**함을 시사

## 스킬 파일의 특성: 소형·가독성·최소 편집

- 최종 배포 아티팩트: `best_skill.md`
- 불투명한 파라미터 블롭도 아니고, 끝없이 늘어나는 로그도 아님
- 6개 케이스 스터디에서 중앙값 최종 스킬 길이: **약 920토큰**
- 검증 게이트가 대부분 제안을 기각 → 최종 파일에 채택되는 편집: **1~4개**
  - OfficeQA의 +39.0점 향상은 **단 1개의 채택 편집**에서 비롯
- 학습된 규칙은 "숙련된 실무자의 조언"처럼 읽힘

### 컴포넌트 제거(Ablation) 결과
- 기각 편집 버퍼 제거 → 3개 ablation 벤치마크 모두 점수 하락
- 메타 스킬 + 슬로우 업데이트 모두 제거 → SpreadsheetBench 77.5 → 55.0 하락

## 결론: 에이전트 시대의 새로운 적응 계층

SkillOpt가 제시하는 경량 도메인 적응 경로:
- 가중치 파인튜닝 불필요
- 태스크 로직 하드코딩 불필요
- 수동 프롬프트 튜닝 불필요
- 대신: 자동 평가 또는 신뢰할 수 있는 검증기가 존재하는 곳이라면 **소형·버전 관리 가능·감사 가능한 자연어 스킬 계층** 훈련 가능

> 학습률·스케줄·검증 분리·기각 샘플·슬로우 업데이트를 에이전트 스킬에 도입함으로써, SkillOpt는 훈련이 모델 가중치에만 국한될 필요가 없음을 시사한다. 모델 외부의 절차적 지식도 최적화될 수 있다.

자연어 스킬이 제어되고 검증되고 기록된 과정을 거칠 때, 프론티어 모델 능력과 실세계 워크로드 사이의 **안정적·이전 가능·가역적 어댑터**가 된다.

## 리소스
- 논문: SkillOpt: Executive Strategy for Self-Evolving Agent Skills
- 프로젝트 페이지: aka.ms/skillopt
- GitHub: github.com/microsoft/SkillOpt
- 컴패니언 프로젝트: **SkillLens**

## 저자 (Microsoft Research Lab - Asia)
- Yifan Yang (Senior Research SDE)
- Xuemei Gao (Researcher)
- Qi Dai (Principal Researcher)
- Bei Liu (Senior Researcher)
- Kai Qiu (Researcher)
- Dongdong Chen (Senior Researcher)
- Chong Luo (Sr. Principal Research Manager)
