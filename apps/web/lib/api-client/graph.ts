// 문서 링크 그래프 API 클라이언트 (AXKG-SPEC-005 Interface Contract).
//
// BE(profile-be) WP2 라이브 계약을 소비한다(읽기 전용 뷰). 스키마는
// apps/api/axkg/schemas/graph.py · documents.py 를 grounding 했다.
//
// 엔드포인트:
// - GET  /graph/documents                      노드/엣지 (type=source 기본 제외)
// - GET  /graph/documents/{id}/neighborhood     depth BFS 서브그래프 (관련 노드 강조)
// - GET  /documents/{id}                         문서 메타(인덱스 필드, 본문 없음)
// - GET  /documents/{id}/links                   wikilink/up/backlink (U-2 상세 패널)
// - POST /graph/search                           keyword+edge distance retriever (선택)

import { ApiError, apiFetch, caseMessage } from "./index";

// --- 엣지 방향 규약 (schemas/graph.py 주석) ---
// assoc(source_syntax=wikilink): 방향 없음(from→to는 저장 방향).
// lineage(source_syntax=up): to_document=upstream, from_document=current → 의미 방향 upstream→current.
export type EdgeType = "assoc" | "lineage";

export interface GraphNode {
  document_id: string;
  stem: string;
  title: string;
  document_type: string;
}

export interface GraphEdge {
  from_document_id: string;
  to_document_id: string;
  edge_type: string; // assoc | lineage
  source_syntax: string; // wikilink | up
  label?: string | null;
  is_broken: boolean;
}

export interface GraphDocuments {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/** 문서 메타 (GET /documents/{id}). 본문 body 는 Markdown SoT 라 응답에 없음. */
export interface DocumentMeta {
  id: string;
  path: string;
  stem: string;
  document_type: string;
  title: string;
  aliases: string[];
  tags: string[];
  source_url?: string | null;
  content_hash: string;
  indexed_at: string;
  created_at: string;
  updated_at: string;
}

/** 단일 링크 뷰 (wikilink/up/backlink 공용). resolve 안 된 target 은 document_id=null·is_broken. */
export interface DocumentLink {
  target: string;
  label?: string | null;
  edge_type: string; // assoc | lineage
  source_syntax: string; // wikilink | up
  is_broken: boolean;
  document_id?: string | null;
  title?: string | null;
  stem?: string | null;
}

/** 문서 링크 조회 (SPEC-005 U-2): 참조(assoc out) / 상류(up) / 백링크(incoming). */
export interface DocumentLinks {
  wikilinks: DocumentLink[];
  up: DocumentLink[];
  backlinks: DocumentLink[];
}

// --- Case Matrix (SPEC-005) — error_code → 프론트 문구 ---
export const GRAPH_CASE_MESSAGES: Record<string, string> = {
  DOCUMENT_NOT_FOUND: "문서를 찾을 수 없습니다. 그래프를 새로고침해 주세요.",
};

export function graphCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && GRAPH_CASE_MESSAGES[error.errorCode]) {
    return GRAPH_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

/** GET /graph/documents — 확정 문서 노드/엣지(type=source 제외). */
export function getGraphDocuments(): Promise<GraphDocuments> {
  return apiFetch<GraphDocuments>("/graph/documents");
}

/** GET /graph/documents/{id}/neighborhood — 선택 노드 depth 이내 서브그래프(관련 노드 강조). */
export function getNeighborhood(
  documentId: string,
  depth = 1,
): Promise<GraphDocuments> {
  return apiFetch<GraphDocuments>(
    `/graph/documents/${encodeURIComponent(documentId)}/neighborhood?depth=${depth}`,
  );
}

/** GET /documents/{id} — 문서 메타. */
export function getDocument(documentId: string): Promise<DocumentMeta> {
  return apiFetch<DocumentMeta>(`/documents/${encodeURIComponent(documentId)}`);
}

/** GET /documents/{id}/links — wikilink/up/backlink (상세 패널). */
export function getDocumentLinks(documentId: string): Promise<DocumentLinks> {
  return apiFetch<DocumentLinks>(
    `/documents/${encodeURIComponent(documentId)}/links`,
  );
}

// --- keyword + edge distance retriever (선택 검색) ---
export interface GraphSearchResult {
  document_id: string;
  stem: string;
  title: string;
  document_type: string;
  score: number;
  distance?: number | null;
  snippet: string;
}

export interface GraphSearchResponse {
  query: string;
  results: GraphSearchResult[];
}

/** POST /graph/search — keyword+edge distance retriever. selected_stem 이면 그 노드 neighborhood 우선. */
export function graphSearch(
  query: string,
  selectedStem?: string | null,
): Promise<GraphSearchResponse> {
  return apiFetch<GraphSearchResponse>("/graph/search", {
    method: "POST",
    body: JSON.stringify({ query, selected_stem: selectedStem ?? null }),
  });
}
