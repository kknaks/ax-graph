---
type: concept
title: "nogil(GIL-free CPython)"
aliases: ["nogil", "GIL-free Python", "nogil 플래그", "Lock-free CPython"]
tags: ["nogil", "GIL", "CPython", "Atomic-Operator", "멀티스레딩", "Python", "성능최적화"]
up: []
---

# nogil(GIL-free CPython)

## 정의

[[gil]] 없이 동작하는 CPython 환경을 목표로 하는 프로젝트; [[reference-counting]]을 전통적 Mutex Lock 대신 [[atomic-operator]](Fetch And Add)로 처리해 Lock-free 스레드 안전성을 달성한다.

## 맥락

PyConUS 2022에서 소개된 nogil은 향후 Python 버전 Proposal 가능성이 있는 프로젝트다. 핵심 목표는 CPU Bound Task에서도 멀티스레드 성능 이점을 얻는 것으로, 기존 GIL 환경에서는 불가능했던 영역이다.

구현 원리는 RefCount +1 시 Python 산술 연산 대신 Atomic FAA(Fetch And Add) Operator를 사용하는 것이다. `atomic_fetch_add` Python Binding 함수가 메모리 버스 수준에서 캐시를 차단해 LOAD → INC → STORE 3단계를 단일 원자적 연산으로 처리한다. 이로써 스레드 간 특별한 대기 없이 메모리 가시성 문제를 해결한다.

GIL 극복의 또 다른 방향인 PEP 684(다중 인터프리터, Sub-interpreters)는 인터프리터를 여러 개 사용해 GIL 제약을 간접 우회하는 방식으로, Python 런타임 레벨이라 커널↔유저 스페이스 컨텍스트 스위칭 비용이 프로세스 대비 적다.

## 근거 출처

- [[cpython-gil-내부구조-성능-nogil-pycon-korea-2022]] — nogil 플래그·Atomic FAA Operator 기반 Lock-free RefCount 처리 방식·PEP 684 소개의 1차 출처 (PyCon Korea 2022, 한성민)
