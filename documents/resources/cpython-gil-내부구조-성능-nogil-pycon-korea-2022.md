---
type: reference
title: "CPython GIL 톺아보기 — 내부 구조·성능·nogil 미래 동향 (PyCon Korea 2022, 한성민)"
source: "https://m.youtube.com/watch?v=hj8BnSAalEs&pp=ygUN7YyM7J207I2sIGdpbA%3D%3D&ra=m"
aliases: ["GIL 톺아보기", "PyCon Korea 2022 GIL 발표", "한성민 GIL", "CPython GIL 심층 분석"]
tags: ["GIL", "CPython", "동시성", "멀티스레딩", "Reference-Counting", "nogil", "Atomic-Operator", "Python", "성능최적화", "PyConKorea2022"]
up: ["gil", "reference-counting", "nogil"]
---

# CPython GIL 톺아보기 — 내부 구조·성능·nogil 미래 동향 (PyCon Korea 2022, 한성민)

## 요약

PyCon Korea 2022에서 한성민(Riiid 데이터 엔지니어)이 발표한 CPython GIL 심층 분석 세션이다. GIL의 존재 이유를 Reference Counting과 Race Condition 관점에서 CPython 소스코드 수준까지 파고들고, 멀티스레드 성능 병목 원인과 대안, 그리고 PEP 684·nogil을 통한 GIL 극복 방향까지 다룬다.

## 핵심 내용

### 1. GIL이란 무엇인가

**Lock의 존재 이유**: 여러 스레드가 공통 자원(Critical Section)에 동시 접근할 때 발생하는 Violation을 막기 위해 메모리 보호 및 접근 통제 목적으로 존재한다.

**GIL의 정의**: 멀티스레드 환경에서 오직 하나의 스레드만 Critical Section에 접근할 수 있도록 제어하는 Lock으로, Python 인터프리터 시작부터 존재해온 태생적 구조다. 개념 상세는 [[gil]] 참조.

**공통 자원의 실체 — Reference Counting**: Python GC는 [[reference-counting]] 방식으로 동작한다. 변수를 참조할 때마다 카운트 +1, 해제 시 -1, 0이 되면 메모리 해제한다. 이 Reference Count 변수 자체가 Critical Section이며, 멀티스레드 환경에서 Violation 발생 시 실제 참조가 없어도 RefCount가 0이 되지 않아 메모리 누수가 생길 수 있다.

**Race Condition 원리**: CPU는 `num += 1` 같은 단일 표현식도 최소 3단계 어셈블리로 처리한다.
1. `LOAD` — 레지스터(eax)에 변수 값 불러오기
2. `INC` — 레지스터 값에 1 더하기
3. `STORE` — 계산 결과를 변수에 저장

이 3단계 사이에 컨텍스트 스위칭이 발생하면 두 스레드가 동일한 초기값을 읽어 최종 결과가 기대값보다 작아진다. 예: RefCount가 2 증가해야 할 상황에서 두 스레드 모두 초기값 0을 읽으면 최종값이 2가 아닌 1로 저장된다.

**CPython 내부의 Mutex Lock**: CPython `take_gil` 함수에서 `MUTEX_LOCK` 호출을 확인할 수 있다. Lock이 해제될 때까지 `while`문으로 무기한 대기하며, 이 방식으로 한 번에 하나의 스레드만 공유 자원에 접근 가능하다.

### 2. GIL 환경에서의 성능

**멀티스레드 성능 문제**: GIL Mutex Lock으로 인해 나머지 스레드는 공유 자원 사용이 끝날 때까지 대기한다. 결과적으로 멀티스레드 환경이 싱글스레드와 비슷하거나 오버헤드로 더 느릴 수 있다.

**IO Bound Task — GIL 효과 있음**: 네트워크 다운로드·프린터 출력 같은 IO 작업 중에는 GIL을 자발적으로 해제하여 다른 스레드가 CPU 작업을 수행할 수 있다. `ThreadPoolExecutor`(워커 5개)로 URL 목록을 병렬 다운로드하는 것이 적절한 IO Bound 활용 사례다.

**CPU Bound Task — GIL 효과 없음**: 지역 변수 연산(소인수분해 등)은 공유 자원 접근이 잦아 스레드 하나만 실행 가능하다. 멀티스레드 성능 이점을 기대하기 어렵다.

**대안 1 — 멀티프로세스**: `Process` vs `Thread`의 API 차이는 키워드 하나지만 듀얼코어 이상 환경에서 성능 차이가 뚜렷하다. 단, 프로세스는 OS 자원으로 스레드 대비 무거워 소규모 태스크에 남용하면 오히려 오버헤드가 발생한다.

**대안 2 — C-Bindings**: Python은 C 코드 영역을 불러와 실행할 수 있으나, C-Bindings도 기본적으로 단일 스레드 내에서 GIL을 취득하여 실행된다. C-Bindings 실행 중 다른 스레드는 전부 대기하므로 오랜 시간 소요 시 웹 서버 요청 전체가 블로킹될 위험이 있다. 해결책은 C-Bindings 코드 내에서 직접 GIL을 Release하는 것이다.

### 3. GIL의 미래

**PEP 684 — 다중 인터프리터(Sub-interpreters)**: 인터프리터를 여러 개 사용하여 멀티스레드와 유사한 환경을 구현함으로써 GIL 제약을 간접 우회한다. 프로세스와 달리 Python 런타임 레벨 개념이므로 커널↔유저 스페이스 컨텍스트 스위칭 비용을 최소화한다.

**nogil 플래그**: GIL 없는 CPython 환경을 목표로 하는 프로젝트로 PyConUS 2022에서 소개됐다. CPU Bound Task에서도 멀티스레드 성능 이점 획득이 가능하다. 개념 상세는 [[nogil]] 참조.

**Atomic Operator 원리**: 전통적 Mutex Lock은 Lock 해제 대기 중 유휴 시간이 발생해 비효율적이다. [[atomic-operator]] 방식은 스레드 간 특별한 대기 없이 메모리 가시성 문제를 해결한다. 발표 기준 **Fetch And Add(FAA)** Operator가 핵심 사례다.
- 일반 덧셈: LOAD → INC → STORE 3단계로 사이에 다른 스레드 개입 가능
- FAA: `LOCK ADD` 명령으로 메모리 버스 수준에서 캐시를 차단 → 단일 원자적 연산으로 처리. Mutex Lock보다 low-level이지만 더 효율적

**nogil에서의 RefCount 처리**: RefCount +1 시 Python 산술 연산 대신 FAA Operator(Atomic)를 이용한다. Python Binding 함수(`atomic_fetch_add`)를 통해 스레드 안전 + Lock-free로 RefCount를 증가시켜, GIL 없이도 스레드 안전성과 성능 효율을 동시에 달성한다.

## 연결

- [[gil]] — GIL 개념 정의·CPython 내 Mutex Lock 동작의 SoT 위임
- [[reference-counting]] — Python GC의 Reference Counting 방식 개념 SoT 위임
- [[nogil]] — GIL 없는 CPython 환경 목표 프로젝트 개념 SoT 위임
- [[atomic-operator]] — Lock-free RefCount를 가능하게 하는 Atomic Operator(FAA) 개념 SoT 위임
