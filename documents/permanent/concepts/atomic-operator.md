---
type: concept
title: "Atomic Operator(원자적 연산자)"
aliases: ["Atomic Operator", "원자적 연산", "Lock-free 연산", "Fetch And Add", "FAA"]
tags: ["Atomic-Operator", "동시성", "Lock-free", "멀티스레딩", "nogil", "CPython"]
up: []
---

# Atomic Operator(원자적 연산자)

## 정의

메모리 버스 수준에서 캐시를 차단해 읽기-수정-쓰기를 단일 원자적 연산으로 처리하는 CPU 명령; Mutex Lock 없이도 스레드 안전성을 보장하는 Lock-free 동시성 기법이다.

## 맥락

전통적 Mutex Lock은 Lock 해제 대기 중 유휴 시간이 발생해 비효율적이다. Atomic Operator는 스레드 간 특별한 대기 없이 메모리 가시성 문제를 해결하므로 Mutex Lock보다 low-level이지만 더 효율적이다.

대표 사례는 **Fetch And Add(FAA)**다. 일반 덧셈은 LOAD → INC → STORE 3단계로 처리되어 그 사이에 다른 스레드가 개입 가능하지만, FAA는 `LOCK ADD` 명령 하나로 메모리 버스 수준에서 캐시를 차단해 전 과정을 단일 연산으로 완료한다.

[[nogil]] 프로젝트는 이 원리를 [[reference-counting]]에 적용한다. RefCount 변경 시 Python 산술 연산 대신 `atomic_fetch_add` Binding 함수를 호출함으로써 [[gil]] 없이도 스레드 안전한 RefCount 관리를 달성한다.

## 근거 출처

- [[cpython-gil-내부구조-성능-nogil-pycon-korea-2022]] — Atomic FAA Operator의 작동 원리(LOCK ADD, 메모리 버스 캐시 차단)와 nogil RefCount 적용 방식의 1차 출처 (PyCon Korea 2022, 한성민)
