"""docx 텍스트 추출 어댑터 (AXKG-SPEC-012, AXKG-DEC-007 D5). WP11 Phase 2.

기업 요구 docx는 본문 **텍스트만** 추출하면 충분하다 — 기능별 구조화는 어댑터가 아니라
적응형 요약①이 담당한다(AXKG-DEC-007 D5). 표 보존·이미지 대체텍스트·병합셀·중첩표·스캔
이미지 같은 파싱 계약은 두지 않는다: 표 셀 텍스트는 문단 텍스트로 함께 흘러나오고, 요약①이
원문 구조를 따라 정리한다.

의존성 없이(python-docx 미사용) stdlib `zipfile`+`xml`으로 `word/document.xml`의 문단
텍스트만 뽑는다. docx는 OOXML zip 컨테이너다.
"""
from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

# WordprocessingML 네임스페이스 (OOXML). 문단 w:p / 텍스트 런 w:t / 탭·개행 제어.
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P = f"{{{_W_NS}}}p"
_T = f"{{{_W_NS}}}t"
_TAB = f"{{{_W_NS}}}tab"
_BR = f"{{{_W_NS}}}br"
_CR = f"{{{_W_NS}}}cr"
_DOCUMENT_XML = "word/document.xml"

# 수집 계층 어휘: adapter=수집 방식, content_format=원문 성격 (SourceMaterial 계약, SPEC-012).
DOCX_ADAPTER = "docx_text"
DOCX_FORMAT = "doc_text"

# docx 확장자.
DOCX_EXTENSION = ".docx"


class DocxExtractError(ValueError):
    """docx로 열리지 않거나 document.xml이 없다(손상/비-docx zip)."""


def is_docx_filename(filename: str | None) -> bool:
    return bool(filename) and filename.strip().lower().endswith(DOCX_EXTENSION)


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    """한 문단(w:p) 안의 텍스트 런을 문서 순서대로 이어붙인다.

    w:t=텍스트, w:tab=탭(스페이스), w:br/w:cr=문단 내 개행. 표 셀(w:tc) 안의 w:p도
    상위 iter가 각각 문단으로 잡으므로 여기서는 이 문단 하위만 본다.
    """
    parts: list[str] = []
    for node in paragraph.iter():
        tag = node.tag
        if tag == _T:
            parts.append(node.text or "")
        elif tag == _TAB:
            parts.append("\t")
        elif tag in (_BR, _CR):
            parts.append("\n")
    return "".join(parts)


def extract_docx_text(content: bytes) -> str:
    """docx 바이트에서 본문 텍스트만 추출한다(문단 = 한 줄).

    손상/비-docx(zip 아님, document.xml 없음, XML 파싱 실패)는 `DocxExtractError`.
    빈 문서는 ""(호출측이 EMPTY 처리). 표/이미지 파싱 계약 없음 — 표 셀 텍스트는
    문단으로 함께 흘러나온다.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            try:
                document_xml = archive.read(_DOCUMENT_XML)
            except KeyError as exc:
                raise DocxExtractError("docx에 word/document.xml이 없습니다.") from exc
    except zipfile.BadZipFile as exc:
        raise DocxExtractError("docx(zip)로 열 수 없는 파일입니다.") from exc

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise DocxExtractError("docx document.xml 파싱 실패.") from exc

    lines = [_paragraph_text(p) for p in root.iter(_P)]
    # 문단 = 한 줄. 말미 공백 정리 + 3연속 이상 빈 줄 축소(요약 입력 잡음 감소).
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        stripped = line.rstrip()
        if not stripped.strip():
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
            continue
        blank_run = 0
        cleaned.append(stripped)
    return "\n".join(cleaned).strip()
