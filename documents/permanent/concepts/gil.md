---
type: concept
title: "GIL(Global Interpreter Lock)"
aliases: ["Global Interpreter Lock", "GIL", "파이썬 GIL"]
tags: ["GIL", "CPython", "동시성", "멀티스레딩", "Python"]
up: []
---

# GIL(Global Interpreter Lock)

## 정의

CPython 인터프리터가 멀티스레드 환경에서 오직 하나의 스레드만 Python 바이트코드를 실행할 수 있도록 강제하는 Mutex Lock; Reference Counting 기반 GC의 Race Condition을 막기 위해 인터프리터 시작부터 존재해온 태생적 구조다.

## 맥락

GIL은 Python의 GC가 [[reference-counting]] 방식으로 동작하기 때문에 필요하다. Reference Count 변수는 여러 스레드가 동시에 접근하는 Critical Section이며, 컨텍스트 스위칭 타이밍에 따라 Race Condition이 발생해 RefCount가 잘못 계산되면 메모리 누수 또는 조기 해제가 일어난다. GIL은 이 문제를 한 번에 하나의 스레드만 접근하도록 직렬화하여 해결한다.

CPython 내부에서는 `take_gil` 함수가 `MUTEX_LOCK`을 호출하고 Lock 해제까지 `while`문으로 무기한 대기한다.

GIL의 성능 영향은 태스크 유형에 따라 다르다:
- **IO Bound**: GIL을 자발적으로 해제하므로 멀티스레딩 효과 있음
- **CPU Bound**: 공유 자원 접근이 잦아 사실상 싱글스레드와 동일하거나 오버헤드로 더 느림

GIL 우회 대안으로는 멀티프로세스(프로세스마다 별도 GIL)와 C-Bindings에서 직접 GIL Release가 있다. 장기적 극복 방향은 [[nogil]] 및 PEP 684(다중 인터프리터)다.

## 근거 출처

- [[cpython-gil-내부구조-성능-nogil-pycon-korea-2022]] — GIL 정의·CPython Mutex Lock 내부 구조·성능 영향·미래 동향의 1차 출처 (PyCon Korea 2022, 한성민)
