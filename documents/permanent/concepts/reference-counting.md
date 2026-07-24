---
type: concept
title: "Reference Counting(참조 카운팅)"
aliases: ["Reference Counting", "참조 카운팅", "RefCount", "Python 메모리 관리"]
tags: ["Reference-Counting", "CPython", "GC", "메모리관리", "Python"]
up: []
---

# Reference Counting(참조 카운팅)

## 정의

CPython이 채택한 메모리 관리(GC) 방식; 각 객체에 참조 횟수(RefCount)를 기록하여 참조 시 +1, 해제 시 -1하고 0이 되면 즉시 메모리를 해제한다.

## 맥락

Reference Count 변수는 여러 스레드가 동시에 읽고 쓰는 Critical Section이다. CPU는 `num += 1`도 LOAD → INC → STORE 3단계 어셈블리로 처리하므로, 이 사이에 컨텍스트 스위칭이 발생하면 두 스레드가 동일한 초기값을 읽어 최종 RefCount가 기대보다 작아지는 Race Condition이 발생한다. 이것이 [[gil]]의 존재 이유다.

[[nogil]] 프로젝트에서는 이 문제를 Mutex Lock 대신 [[atomic-operator]](Fetch And Add)로 해결한다. `atomic_fetch_add` 함수가 메모리 버스 수준에서 캐시를 차단해 단일 원자적 연산으로 RefCount를 증가시킴으로써 Lock 없이도 스레드 안전성을 확보한다.

## 근거 출처

- [[cpython-gil-내부구조-성능-nogil-pycon-korea-2022]] — Reference Counting이 GIL Critical Section의 실체임을 설명하고, nogil에서 Atomic Operator로 대체하는 방식을 다루는 1차 출처
