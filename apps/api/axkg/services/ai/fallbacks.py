"""코드 내장 fallback 상수 (AXKG-SPEC-009/010 S-3, AXKG-SPEC-011 S-4).

활성 프롬프트/템플릿 버전 로드 실패(없음/조회 에러)는 파이프라인을 중단시키지
않는다 — 여기 상수로 조립을 계속하고, `ai_tasks.prompt_version_id`/
`template_version_id`는 null로 두며 payload에 fallback 사실을 기록한다.

스테이지(prompt key)별 정교한 fallback 본문은 도메인 WP 소관이다. 스켈레톤은
공통 generic fallback으로 실행 경로만 보장한다.
"""
from typing import Any

# Case Matrix 관찰 코드 (실패 아님 — payload/로그 기록용)
PROMPT_FALLBACK_USED = "PROMPT_FALLBACK_USED"
TEMPLATE_FALLBACK_USED = "TEMPLATE_FALLBACK_USED"
# qmd 사이드카 장애로 retriever 1단을 keyword+edge로 폴백(품질 강등, ③④ 공통, AXKG-SPEC-011).
RETRIEVER_FALLBACK_USED = "RETRIEVER_FALLBACK_USED"

FALLBACK_PROMPT_TEXT = (
    "당신은 개인 지식 베이스 파이프라인의 AI 작업자다. 아래에 이어지는 데이터 "
    "블록들을 근거로 요청된 작업을 수행하라. 근거에 없는 사실을 추가하지 말고, "
    "출력은 반드시 마지막에 제시되는 JSON Schema를 만족하는 JSON 객체 하나로만 한다."
)

# 최소 강제: JSON object여야 한다. 필드 구조 강제는 활성 output_schema 소관.
FALLBACK_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
}

FALLBACK_TEMPLATE_BODY = """---
type: reference
title: ""
tags: []
up: ""
---

# {title}

## 요약

## 핵심 내용

## 연결

- up: [[]]
- 관련: [[]]
"""
