// 문서(stale 연쇄) API 클라이언트 (AXKG-SPEC-004 E · AXKG-DEC-005 E).
//
// concept 문서가 새 버전으로 승인되면, 그 concept 를 [[ ]] 로 참조하는 permanent(종합 노트)에
// "영향 가능성" 배지(stale)가 붙는다. 배지는 참조 기반 과잉 포함이며 "수정 필요" 판단이 아니다
// (SPEC-004 E-1). 사용자는 문서당 독립적으로 [판단 유효·배지 해제] 또는 [재검토·재생성] 을 고른다
// (E-3, 1 문서 = 1 태스크, 일괄 없음).
//
// BE(profile-be, PLAN-009-T-030)와 같은 계약으로 병렬 구현 중이다. stale 플래그/backlink/재생성
// 게이트 배선 세부는 코드 소관(SPEC-004 OQ) — 아래는 T-031 이 합의한 계약 기준이며, 어긋나면
// 리포트에 명시한다(정합은 admin).
//
// - GET  /documents/stale                     stale 문서 목록
// - GET  /documents/{id}                       문서 상세(인덱스 필드) — 재검토 탭 상세 뷰
// - POST /documents/{id}/stale/dismiss        배지 해제(판단 유효)
// - POST /documents/{id}/regenerate           producing source 의 문서화 게이트 재문서화(v++) 오픈

import { ApiError, apiFetch, caseMessage } from "./index";

/** stale 유발 마크 — 어떤 concept 가 어떻게 바뀌었는지 + 배지가 붙은 시각.
 * 문서 하나가 여러 concept 갱신의 영향을 동시에 받을 수 있어 마크는 배열로 온다(T-030 최종 계약). */
export interface StaleMark {
  /** 갱신된 유발 concept 의 wikilink stem([[stem]]). */
  concept_stem: string;
  /** 유발 concept 문서 경로(SoT). */
  concept_path: string;
  /** 변경 요지 — 재생성 판단의 근거(SPEC-004 E-3 입력 계약의 "변경 요지"). */
  change_summary: string;
  /** 배지가 붙은 시각(ISO). */
  marked_at: string;
}

/** stale 배지가 붙은 문서(주로 permanent 종합 노트). 배지는 문서당 1개, 유발 마크는 여러 개일 수 있다. */
export interface StaleDocument {
  document_id: string;
  path: string;
  title: string;
  document_type: string;
  stale_marks: StaleMark[];
}

/** 문서 상세(GET /documents/{id}) — 인덱스 필드 스냅샷. 재검토 탭 우측 상세 헤더/메타에 쓴다.
 *
 * ⚠ 본문(body) seam: 현재 BE DocumentResponse 는 "본문 body 는 Markdown SoT 라 응답에 싣지 않는다"
 * (schemas/documents.py). 즉 이 계약만으로는 "현재 permanent 전문"을 받을 수 없다. BE 가 향후 body 를
 * 실으면 관례적인 필드명 중 하나로 온다고 보고 방어적으로 흡수한다(신규 BE 계약을 요구하지 않는다 —
 * 있으면 렌더, 없으면 메타 + 안내). 정합은 admin (리포트에 명시). */
export interface DocumentDetail {
  id: string;
  path: string;
  stem?: string;
  title: string;
  document_type: string;
  aliases?: string[];
  tags?: string[];
  source_url?: string | null;
  content_hash?: string;
  indexed_at?: string;
  created_at?: string;
  updated_at?: string;
  // 본문 후보 — 현재 계약엔 없음(위 seam). 있으면 그대로 렌더.
  markdown_full?: string | null;
  body?: string | null;
  content?: string | null;
  markdown?: string | null;
}

/** 상세 응답에서 본문을 관례 필드명들로 방어적으로 추출. 없으면 null(계약상 현재는 항상 null). */
export function documentBody(doc: DocumentDetail): string | null {
  return doc.markdown_full ?? doc.body ?? doc.content ?? doc.markdown ?? null;
}

/** 목록 응답은 배열 또는 { documents: [...] } 봉투 어느 쪽이든 허용 (BE 계약 확정 전 방어적). */
type StaleListPayload = StaleDocument[] | { documents?: StaleDocument[] };

function toStaleList(payload: StaleListPayload): StaleDocument[] {
  if (Array.isArray(payload)) return payload;
  return payload?.documents ?? [];
}

/** 재생성 응답 = GateResponse (T-030 최종 계약) — producing source 의 문서화 게이트가
 * 재문서화(v++)로 열린다. root 에 source_id 가 있어 게이트 스택으로 이동할 때 사용한다. */
export interface RegenerateResult {
  source_id?: string | null;
  document_id?: string | null;
}

/** 배지 해제 응답 (T-030) — { document_id, status:"dismissed", dismissed_count }. FE 는 성공 여부만 쓴다. */
export interface DismissResult {
  document_id?: string | null;
  status?: string;
  dismissed_count?: number;
}

// --- Case Matrix (SPEC-004 E · T-030 최종 계약: 404/409 2종) ---

export const DOCUMENT_CASE_MESSAGES: Record<string, string> = {
  DOCUMENT_NOT_FOUND: "문서를 찾을 수 없습니다. 목록을 새로고침해 주세요.",
  STALE_REGENERATION_NOT_ALLOWED: "지금은 이 문서를 재생성할 수 없습니다. 최신 상태를 확인해 주세요.",
};

export function documentCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && DOCUMENT_CASE_MESSAGES[error.errorCode]) {
    return DOCUMENT_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

// --- API ---

/** GET /documents/stale — 영향 가능성(stale) 배지가 붙은 문서 목록. */
export async function listStaleDocuments(): Promise<StaleDocument[]> {
  const payload = await apiFetch<StaleListPayload>("/documents/stale");
  return toStaleList(payload);
}

/** GET /documents/{id} — 문서 상세(인덱스 필드). 재검토 상세 뷰의 헤더/메타/본문 소스. */
export function getDocument(documentId: string): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>(`/documents/${encodeURIComponent(documentId)}`);
}

/** POST /documents/{id}/stale/dismiss — 판단 유효로 보고 배지 해제(SPEC-004 E). */
export function dismissStale(documentId: string): Promise<DismissResult> {
  return apiFetch<DismissResult>(
    `/documents/${encodeURIComponent(documentId)}/stale/dismiss`,
    { method: "POST" },
  );
}

/** POST /documents/{id}/regenerate — producing source 의 문서화 게이트를 재문서화(v++)로 연다.
 * 이후 화면은 기존 문서화 게이트 리뷰/피드백/승인 스택을 그대로 재사용한다(신규 게이트 화면 없음). */
export function regenerateDocument(documentId: string): Promise<RegenerateResult> {
  return apiFetch<RegenerateResult>(
    `/documents/${encodeURIComponent(documentId)}/regenerate`,
    { method: "POST" },
  );
}
