---
type: summary
title: 'Tool Calling: LLM과 실시간 데이터를 연결하는 기법'
source_url: https://m.youtube.com/watch?v=h8gMhXYAv1k&pp=ygUQbGxtIHRvb2wgY2FsbGluZw%3D%3D&ra=m
tags:
- Tool Calling
- Embedded Tool Calling
- LLM
- hallucination
- API
- 도구 정의
- 라이브러리
- 실시간 데이터
- AI
- IBM Technology
summarized_at: '2026-07-15T14:29:07.623970+00:00'
---

## Tool Calling 개요

- **Tool Calling**이란 LLM을 데이터베이스·API 등 실시간 데이터 소스와 연결하는 기법이다.
- 주로 채팅 인터페이스를 통해 호출되며, **클라이언트 애플리케이션**과 **LLM** 두 축으로 구성된다.

## 전통적 Tool Calling 흐름

1. 클라이언트 애플리케이션이 **메시지**와 **도구 정의(tool definition) 목록**을 LLM에 전송한다.
2. LLM은 메시지와 도구 목록을 함께 보고 호출해야 할 도구를 추천한다.
3. 클라이언트 애플리케이션이 해당 도구를 실제로 호출하고 결과를 LLM에 반환한다.
4. LLM은 도구 응답을 해석해 다음 호출 도구를 안내하거나 최종 답변을 생성한다.

## 도구 정의(Tool Definition) 구성 요소

- **이름(name)**: 도구를 식별하는 명칭
- **설명(description)**: 도구 사용 방법·사용 시점 등 추가 정보
- **입력 파라미터(input parameters)**: 도구 호출에 필요한 인자
- 도구의 종류: API, 데이터베이스, 코드 인터프리터 등 무엇이든 가능

## 예시: 마이애미 날씨 조회

- 사용자 질문: "마이애미의 기온은?"
- 제공 도구 목록에 **Weather API** 포함
- LLM이 도구 정의를 참고해 Weather API 호출 방법을 생성
- 클라이언트가 API를 호출해 결과(예: 71°F)를 LLM에 전달
- LLM 최종 답변 예시: "마이애미 날씨는 꽤 좋습니다. 기온은 71도입니다."

## 전통적 Tool Calling의 한계

- LLM이 **환각(hallucination)**을 일으킬 수 있음
- 잘못된 도구 호출(incorrect tool calls)을 생성할 수 있음

## Embedded Tool Calling

- **라이브러리 또는 프레임워크**가 애플리케이션과 LLM 사이에 위치한다.
- 라이브러리가 **도구 정의**와 **도구 실행** 모두를 담당한다.

### Embedded Tool Calling 흐름

1. 애플리케이션이 메시지를 라이브러리로 전송한다.
2. 라이브러리가 도구 정의를 메시지에 자동으로 추가해 LLM에 전달한다.
3. LLM의 도구 호출 응답이 애플리케이션/사용자가 아닌 **라이브러리**로 전달된다.
4. 라이브러리가 도구를 실행하고 최종 답변을 애플리케이션에 반환한다.
5. 필요 시 라이브러리가 **재시도(retry)**를 자동 처리한다.

### Embedded Tool Calling의 장점

- LLM의 환각 방지: 라이브러리가 도구 실행을 제어하므로 LLM이 직접 잘못된 호출을 수행하지 않음
- 도구 실행 실패 시 자동 재시도 지원

## 결론

- 전통적 Tool Calling은 구조가 단순하지만 환각·잘못된 호출 위험이 있다.
- **Embedded Tool Calling**은 라이브러리가 도구 정의·실행을 모두 처리해 신뢰성을 높이고 환각을 방지한다.
- 도구는 API, 데이터베이스, 코드 인터프리터 등 다양한 형태로 활용 가능하다.
