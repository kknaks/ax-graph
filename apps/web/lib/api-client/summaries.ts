// 요약(summaries/) API 클라이언트 (AXKG-SPEC-013 — 문서 라이브러리 트리 합류, 읽기 전용).
//
// 요약은 `documents` row 가 없어(SPEC-013 §4) documents 목록/본문 계약으로는 나오지 않는다.
// BE(profile-be, PLAN-012-T-006)와 병렬 구현이며, 아래는 태스크가 고정한 스펙 계약 그대로다.
// 어긋나면 리포트에 명시한다(정합은 admin).
//
// - GET /summaries              → { items: [{ source_id, name, path }] }  (path=`summaries/…` 표시용)
// - GET /summaries/{source_id}  → { source_id, name, path, markdown_full }
// - 대상 없음 = SUMMARY_NOT_FOUND (404)

import { apiFetch } from "./index";

/** 요약 목록 항목 — 트리는 `path`(summaries/…)만으로 구성한다. */
export interface SummaryListItem {
  source_id: string;
  name: string;
  path: string;
}

/** 요약 본문 상세 — read-through markdown_full(없으면 null). */
export interface SummaryDetail {
  source_id: string;
  name: string;
  path: string;
  markdown_full: string | null;
}

/** 목록 응답 봉투 { items: [...] }. */
type SummaryListPayload = { items?: SummaryListItem[] };

/** GET /summaries — 요약 목록. 라이브러리 트리 summaries/ 브랜치 소스. */
export async function listSummaries(): Promise<SummaryListItem[]> {
  const payload = await apiFetch<SummaryListPayload>("/summaries");
  return payload?.items ?? [];
}

/** GET /summaries/{source_id} — 요약 본문(markdown_full). */
export function getSummary(sourceId: string): Promise<SummaryDetail> {
  return apiFetch<SummaryDetail>(`/summaries/${encodeURIComponent(sourceId)}`);
}
