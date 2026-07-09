// 그래프 탐색 + Graph RAG 채팅 (AXKG-SPEC-005 WP2 + AXKG-SPEC-006 WP4).
// [graph] | [채팅] split view (21-html page-graph). 좌측 그래프(WP2 유지)와 우측 채팅을
// 페이지에서 연결한다:
//  - 그래프 노드 선택 → 채팅 selected_node_id context (S-1)
//  - Evidence "그래프에서 보기" → 좌측 그래프 노드 강조 (S-3)
"use client";

import { useCallback, useState } from "react";
import { DocumentGraph, type GraphSelection } from "@/components/document-graph";
import { GraphChatPanel } from "@/components/graph-chat-panel";

export default function GraphPage() {
  // 좌측 그래프 선택 노드 → 채팅 context.
  const [selectedNode, setSelectedNode] = useState<GraphSelection | null>(null);
  // Evidence "그래프에서 보기" → 좌측 그래프 강조 요청(nonce 로 같은 노드 재요청도 트리거).
  const [focusRequest, setFocusRequest] = useState<{ id: string; nonce: number } | null>(
    null,
  );

  const handleFocusDocument = useCallback((documentId: string) => {
    setFocusRequest((prev) => ({ id: documentId, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  return (
    <main className="flex h-[calc(100vh-3.5rem)] w-full flex-col px-6 py-5">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">Graph Chat</h1>
      </div>

      {/* [graph] | [채팅] split view (SPEC-006 Placement) */}
      <div className="grid min-h-0 flex-1 grid-cols-[1fr_460px] gap-4">
        <DocumentGraph onSelectNode={setSelectedNode} focusRequest={focusRequest} />
        <GraphChatPanel
          selectedNode={selectedNode}
          onFocusDocument={handleFocusDocument}
        />
      </div>
    </main>
  );
}
