"""블록 조립 (AXKG-SPEC-011 Assembly Contract, AXKG-DEC-005).

**조립 방식은 변수 치환이 아니라 블록 조립이다.** DB 프롬프트 본문에
`{{template}}` 같은 변수를 두지 않는다. 코드 고정 프레임 문구로 블록을 쌓는다:

    [프롬프트(지시)]
    + [코드 고정 프레임 문구 + 활성 템플릿 body]   (문서화 게이트류만)
    + [handler가 준 데이터 블록들]
    + [코드 고정 프레임 문구 + output_schema(JSON Schema)]

프레임 문구는 코드 소유라 admin이 프롬프트를 잘못 편집해도 템플릿/출력 계약
주입은 깨지지 않는다. 프롬프트는 "어떻게 채울지"(톤·밀도·강조)만 담당한다.
"""
import json
import uuid
from typing import Any

from axkg.dto.ai import AssembledBlockDTO, AssembledInputDTO

# 코드 고정 프레임 문구 — DB 프롬프트가 아니라 코드가 소유한다.
TEMPLATE_FRAME_TEXT = (
    "아래 템플릿 뼈대(frontmatter와 섹션 구조)를 그대로 따라 문서를 작성하라. "
    "템플릿의 구조를 바꾸거나 섹션을 임의로 제거하지 말고 내용만 채운다."
)
OUTPUT_CONTRACT_FRAME_TEXT = (
    "출력은 아래 JSON Schema를 만족하는 JSON 객체 하나로만 응답하라. "
    "JSON 외의 어떤 텍스트도 출력하지 않는다."
)


def assemble_input(
    *,
    prompt_text: str,
    output_schema: dict[str, Any],
    prompt_version_id: uuid.UUID | None,
    data_blocks: list[AssembledBlockDTO],
    template_body: str | None = None,
    template_version_id: uuid.UUID | None = None,
    fallback_codes: list[str] | None = None,
) -> AssembledInputDTO:
    """프롬프트/템플릿/데이터/출력 계약을 순서대로 쌓아 AssembledInput을 만든다."""
    blocks: list[AssembledBlockDTO] = [
        AssembledBlockDTO(kind="prompt", label="instruction", text=prompt_text)
    ]
    if template_body is not None:
        blocks.append(
            AssembledBlockDTO(
                kind="template_frame",
                label="template",
                text=f"{TEMPLATE_FRAME_TEXT}\n\n{template_body}",
            )
        )
    blocks.extend(data_blocks)
    blocks.append(
        AssembledBlockDTO(
            kind="output_contract",
            label="output_schema",
            text=(
                f"{OUTPUT_CONTRACT_FRAME_TEXT}\n\n"
                f"{json.dumps(output_schema, ensure_ascii=False, indent=2)}"
            ),
        )
    )
    return AssembledInputDTO(
        blocks=blocks,
        output_schema=output_schema,
        prompt_version_id=prompt_version_id,
        template_version_id=template_version_id,
        fallback_codes=list(fallback_codes or []),
    )
