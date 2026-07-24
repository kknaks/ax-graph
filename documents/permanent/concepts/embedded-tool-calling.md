---
type: concept
title: "Embedded Tool Calling"
aliases: ["임베디드 툴 콜링", "라이브러리 기반 Tool Calling"]
tags: ["Embedded Tool Calling", "Tool Calling", "LLM", "hallucination", "라이브러리", "프레임워크"]
up: ["에이전틱-ai"]
---

# Embedded Tool Calling

## 정의

라이브러리 또는 프레임워크가 애플리케이션과 LLM 사이의 중간 레이어로서 도구 정의와 도구 실행을 모두 담당해 LLM 환각·잘못된 호출을 구조적으로 방지하는 [[tool-calling]] 발전형.

## 맥락

전통적 [[tool-calling]]에서는 클라이언트 애플리케이션이 LLM의 도구 호출 추천을 직접 실행하므로 LLM 환각이 외부 시스템 오호출로 이어질 수 있다. Embedded Tool Calling은 라이브러리를 중간 레이어로 두어 이 위험을 제거한다.

흐름: 애플리케이션 → 라이브러리(도구 정의 자동 추가) → LLM → 라이브러리(도구 실행·재시도) → 애플리케이션. LLM의 응답이 사용자나 클라이언트가 아닌 라이브러리로 전달되므로, 라이브러리가 실행 제어권을 갖는다.

핵심 장점: (1) LLM이 직접 잘못된 호출을 수행하지 않아 환각 방지, (2) 실행 실패 시 라이브러리가 자동 재시도 처리. [[에이전틱-ai]] 프레임워크(VoltAgent, Mastra 등)의 도구 시스템이 이 패턴을 구현한다 — VoltAgent `createTool()`이 대표적 사례([[voltagent-tools-도구-생성-실행-제어-가이드]] 참조).

## 근거 출처

- [[tool-calling-embedded-tool-calling-llm-실시간데이터-ibm-technology]] — IBM Technology Roy Derks가 Embedded Tool Calling 구조·흐름·장점을 전통적 Tool Calling과 대비해 설명한 1차 출처
