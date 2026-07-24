---
type: summary
title: Global Interpreter Lock(GIL) 자세히 톺아보기 — CPython 내부 구조·성능·미래 동향
source_url: https://m.youtube.com/watch?v=hj8BnSAalEs&pp=ygUN7YyM7J207I2sIGdpbA%3D%3D&ra=m
tags:
- GIL
- CPython
- Reference Counting
- Race Condition
- Mutex Lock
- Atomic Operator
- nogil
- 멀티스레딩
- IO Bound
- CPU Bound
summarized_at: '2026-07-15T13:41:58.926375+00:00'
---

## 발표 개요

- 발표자: **한성민** (Riiid 데이터 엔지니어, 전 네이버 클로바·심심이)
- 행사: **PyCon Korea 2022**
- 구성: GIL 개념 및 CPython 내부 → 성능 분석 → GIL의 미래

---

## 1. GIL이란 무엇인가

### Lock의 존재 이유
- 여러 Worker(스레드)가 공통 자원(**Critical Section**)에 동시 접근할 때 발생하는 Violation을 막기 위해 존재
- 메모리 보호 및 접근 통제가 목적

### GIL의 정의
- 멀티스레드 환경에서 **오직 하나의 스레드만** Critical Section에 접근할 수 있도록 제어하는 Lock
- Python 인터프리터 시작부터 존재해온 태생적 구조

### 공통 자원(Critical Section)의 실체: Reference Counting
- Python의 GC는 **Reference Counting** 방식으로 동작
  - 변수를 참조할 때마다 카운트 +1, 참조 해제 시 -1
  - 카운트가 0이 되면 메모리 해제
- Reference Count 변수 자체가 Critical Section
- 멀티스레드 환경에서 Violation 발생 시: 실제 참조가 없어도 RefCount가 0이 되지 않아 **메모리 누수** 발생 가능

### Race Condition 원리
- CPU는 `num += 1` 같은 단일 표현식도 최소 3단계 어셈블리로 처리
  1. `LOAD` — 레지스터(eax)에 변수 값 불러오기
  2. `INC` — 레지스터 값에 1 더하기
  3. `STORE` — 계산 결과를 변수에 저장
- 이 3단계 사이에 **컨텍스트 스위칭**이 발생하면 두 스레드가 동일한 초기값을 읽어 최종 결과가 기대값보다 작아짐
- 예: RefCount가 2 증가해야 할 상황에서 두 스레드 모두 초기값 0을 읽으면 최종값이 2가 아닌 1로 저장됨 → **Race Condition**

### CPython 내부의 Mutex Lock
- CPython(`take_gil` 함수)에서 `MUTEX_LOCK` 호출 확인 가능
- Lock이 해제될 때까지 `while`문으로 무기한 대기
- 이 방식으로 한 번에 하나의 스레드만 공유 자원 접근 가능

---

## 2. GIL 환경에서의 성능

### 멀티스레드 성능 문제
- GIL Mutex Lock으로 인해 나머지 스레드는 공유 자원 사용이 끝날 때까지 대기
- 결과적으로 멀티스레드 환경이 **싱글스레드와 비슷하거나 오버헤드로 더 느릴 수 있음**

### IO Bound Task: GIL 효과 있음
- 네트워크 다운로드·프린터 출력 같은 IO 작업 중에는 GIL을 **자발적으로 해제**하여 다른 스레드가 CPU 작업 수행 가능
- 예시 코드: `ThreadPoolExecutor`(워커 5개)로 URL 목록을 병렬 다운로드 — 적절한 IO Bound 활용 사례

### CPU Bound Task: GIL 효과 없음
- 지역 변수 연산(예: 소인수분해)은 공유 자원 접근이 잦아 스레드 하나만 실행 가능
- 멀티스레드 성능 이점 기대 어려움

### 대안 1: 멀티프로세스
- `Process` vs `Thread` — API 차이는 키워드 하나지만 듀얼코어 이상 환경에서 성능 차이 뚜렷
- 단점: 프로세스는 **OS 자원**으로 스레드 대비 무거움 → 소규모 태스크에 남용하면 오히려 오버헤드

### 대안 2: C-Bindings
- Python은 C 코드 영역을 불러와 실행 가능
- 그러나 C-Bindings도 기본적으로 **단일 스레드 내에서 GIL을 취득**하여 실행
- C-Bindings 실행 중 다른 스레드는 전부 대기 → 오랜 시간 소요 시 웹 서버 요청 전체 블로킹 위험
- 해결책: C-Bindings 코드 내에서 **직접 GIL을 Release**해야 함

---

## 3. GIL의 미래

### PEP 684: 다중 인터프리터(Sub-interpreters)
- 인터프리터를 여러 개 사용하여 멀티스레드와 유사한 환경 구현 → GIL 제약을 간접 우회
- 프로세스와 달리 **Python 런타임 레벨** 개념이므로 커널↔유저 스페이스 컨텍스트 스위칭 비용 최소화

### nogil 플래그 (PyConUS 2022 소개)
- GIL 없는 CPython 환경을 목표로 하는 프로젝트; 향후 Python 버전 Proposal 가능성
- **CPU Bound Task에서도 멀티스레드 성능 이점** 획득 가능

#### Atomic Operator 원리
- 전통적 Mutex Lock: Lock 해제 대기 → **유휴 시간** 발생 → 비효율
- **Atomic Operator(Lock-free 방식)**: 스레드 간 특별한 대기 없이 메모리 가시성 문제 해결
- 슬라이드 기준 설명: **Fetch And Add(FAA)** Operator
  - 일반 덧셈: LOAD → INC → STORE 3단계 → 사이에 다른 스레드 개입 가능
  - FAA: `LOCK ADD` 명령으로 **메모리 버스 수준에서 캐시 차단** → 단일 원자적 연산으로 처리
  - Mutex Lock보다 low-level이지만 더 효율적

#### nogil에서의 RefCount 처리
- RefCount +1 시 Python 산술 연산 대신 **FAA Operator(Atomic)**를 이용
- Python Binding 함수(`atomic_fetch_add`)를 통해 스레드 안전 + Lock-free로 RefCount 증가
- 이 방식으로 GIL 없이도 스레드 안전성과 성능 효율을 동시에 달성
