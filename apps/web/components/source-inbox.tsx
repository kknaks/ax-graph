// Source Inbox 원페이지 오케스트레이터 (AXKG-SPEC-001/002/003 · 21-html page-approval SSOT).
// 페이지 하나에서 파이프라인 전체를 추적한다: 좌=Source Inbox 큐, 우=요약→분류 게이트→문서화 세로 스택.
// 게이트 액션(진입/피드백/승인/재시도)과 폴링을 여기서 모은다. 앱 셸/가드는 (app)/layout 재사용.
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  activeRevisionOf,
  approveGate,
  enterClassificationGate,
  feedbackGate,
  getSource,
  getSourceGates,
  isGateRunning,
  listSources,
  queueCollection,
  regenerateGate,
  requestReclassification,
  retryGate,
  sourceCaseMessage,
  summaryFeedback,
  type Gate,
  type Source,
} from "@/lib/api-client/sources";
import {
  dismissStale,
  documentCaseMessage,
  listStaleDocuments,
  regenerateDocument,
  type StaleDocument,
} from "@/lib/api-client/documents";
import { SourceList, type StatusFilter } from "@/components/source-list";
import { GateHistoryStack } from "@/components/gate-history-stack";
import { StaleList, StaleDetail, type StaleRegenInfo } from "@/components/stale-documents";
import {
  GateFeedbackModal,
  type FeedbackTarget,
} from "@/components/gate-feedback-modal";
import { DirectInboxModal } from "@/components/direct-inbox-modal";

// 피드백 모달이 겨냥하는 대상 — 요약 초안(재요약) 또는 특정 게이트(재생성).
type FeedbackContext =
  | { kind: "summary"; source: Source }
  | { kind: "gate"; gate: Gate };

const POLL_MS = 2500;

export function SourceInbox() {
  const [sources, setSources] = useState<Source[]>([]);
  const [filter, setFilter] = useState<StatusFilter>("inbox");
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  // 완료(documented) 탭 — visible=false 라 기본 목록에 없어 별도 로드.
  const [documented, setDocumented] = useState<Source[]>([]);
  const [documentedLoading, setDocumentedLoading] = useState(false);
  const [documentedError, setDocumentedError] = useState<string | null>(null);

  // stale(영향 가능성) 문서 — 재검토 탭 전용 (SPEC-004 E · T-033). concept 갱신 → 참조 permanent 배지.
  const [staleDocs, setStaleDocs] = useState<StaleDocument[]>([]);
  const [staleLoading, setStaleLoading] = useState(false);
  const [staleError, setStaleError] = useState<string | null>(null);
  const [staleBusyId, setStaleBusyId] = useState<string | null>(null);
  // 재검토 탭 좌 목록에서 선택된 stale 문서 → 우 상세 뷰 대상.
  const [selectedStaleId, setSelectedStaleId] = useState<string | null>(null);
  // 재생성 진행 중인 stale 문서(세션 내) — document_id → producing gate 좌표. 진행 표시/버튼 잠금/게이트 이동.
  // BE stale 목록 계약엔 게이트 status가 없어(문서→게이트 역참조 불가) 새로고침 시 유실된다(리포트 한계).
  const [regeneratingStale, setRegeneratingStale] = useState<Record<string, StaleRegenInfo>>({});

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Source | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedId;

  // 우측 스택 게이트 상태
  const [gates, setGates] = useState<Gate[]>([]);
  const [gatesLoading, setGatesLoading] = useState(false);
  const [gatesError, setGatesError] = useState<string | null>(null);
  const [classifying, setClassifying] = useState(false);
  const [gateBusyId, setGateBusyId] = useState<string | null>(null);

  // collection_failed 요약 재시도
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);

  // 공통 피드백 모달
  const [fbContext, setFbContext] = useState<FeedbackContext | null>(null);
  const [fbTarget, setFbTarget] = useState<FeedbackTarget | null>(null);
  const [fbBusy, setFbBusy] = useState(false);
  const [fbError, setFbError] = useState<string | null>(null);

  // --- 목록 로드 (visible 전체를 받고 inbox/승인 구분은 SourceList가 inbox_label 로 클라이언트 분류) ---
  const loadList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const items = await listSources();
      setSources(items);
    } catch (err) {
      setSources([]);
      setListError(sourceCaseMessage(err, "목록을 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // --- 완료(documented) 목록 로드 (GET /sources?status=documented) ---
  const loadDocumented = useCallback(async () => {
    setDocumentedLoading(true);
    setDocumentedError(null);
    try {
      const items = await listSources("documented");
      setDocumented(items);
    } catch (err) {
      setDocumented([]);
      setDocumentedError(sourceCaseMessage(err, "완료 목록을 불러오지 못했습니다."));
    } finally {
      setDocumentedLoading(false);
    }
  }, []);

  // --- stale 문서 목록 로드 (GET /documents/stale · SPEC-004 E) ---
  const loadStale = useCallback(async () => {
    setStaleLoading(true);
    setStaleError(null);
    try {
      const items = await listStaleDocuments();
      setStaleDocs(items);
    } catch (err) {
      setStaleDocs([]);
      setStaleError(documentCaseMessage(err, "영향 가능성 목록을 불러오지 못했습니다."));
    } finally {
      setStaleLoading(false);
    }
  }, []);

  // 완료 탭 진입 시 완료 source 목록 로드.
  useEffect(() => {
    if (filter === "documented") void loadDocumented();
  }, [filter, loadDocumented]);

  // stale 목록: 마운트 시 1회(재검토 탭 배지 카운트를 어느 탭에서든 노출) + 재검토 탭 진입 시 최신화.
  useEffect(() => {
    void loadStale();
  }, [loadStale]);

  useEffect(() => {
    if (filter === "review") void loadStale();
  }, [filter, loadStale]);

  // --- 게이트 로드 (선택 유지 시에만 반영) ---
  const loadGates = useCallback(async (sourceId: string, spinner = true) => {
    if (spinner) setGatesLoading(true);
    setGatesError(null);
    try {
      const fresh = await getSourceGates(sourceId);
      if (selectedIdRef.current === sourceId) setGates(fresh);
    } catch (err) {
      if (selectedIdRef.current === sourceId) {
        setGatesError(sourceCaseMessage(err, "게이트 상태를 불러오지 못했습니다."));
      }
    } finally {
      if (spinner) setGatesLoading(false);
    }
  }, []);

  // source 최신화(inbox_label 갱신 → 좌측 리스트/우측 헤더 반영)
  const patchSource = useCallback(async (sourceId: string) => {
    try {
      const full = await getSource(sourceId);
      setSelected((cur) => (cur?.id === sourceId ? full : cur));
      setSources((cur) => cur.map((s) => (s.id === sourceId ? full : s)));
    } catch {
      // 최신화 실패는 조용히 무시 (다음 폴링/액션에서 회복)
    }
  }, []);

  // --- source 선택 → 상세 + 게이트 로드 ---
  const selectSource = useCallback(
    async (source: Source) => {
      setSelectedId(source.id);
      selectedIdRef.current = source.id;
      setSelected(source);
      setGates([]);
      setGatesError(null);
      setRetryError(null);
      setGateBusyId(null);
      void getSource(source.id)
        .then((full) => {
          setSelected((cur) => (cur?.id === source.id ? full : cur));
        })
        .catch(() => {});
      void loadGates(source.id);
    },
    [loadGates],
  );

  // --- generating/regenerating 게이트 폴링 ---
  useEffect(() => {
    if (!selectedId) return;
    if (!gates.some(isGateRunning)) return;
    const timer = setInterval(() => {
      void loadGates(selectedId, false).then(() => patchSource(selectedId));
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [selectedId, gates, loadGates, patchSource]);

  // --- collection_failed 요약 재시도 ---
  const retryCollection = useCallback(
    async (source: Source, note?: string) => {
      if (retrying) return;
      setRetrying(true);
      setRetryError(null);
      try {
        const updated = await queueCollection(source.id, note);
        setSelected(updated);
        setSources((cur) => cur.map((s) => (s.id === updated.id ? updated : s)));
      } catch (err) {
        setRetryError(
          sourceCaseMessage(err, "요약 재시도에 실패했습니다. 잠시 후 다시 시도해 주세요."),
        );
      } finally {
        setRetrying(false);
      }
    },
    [retrying],
  );

  // --- [분류] 분류 게이트 생성 → 폴링 시작 ---
  const handleClassify = useCallback(
    async (source: Source) => {
      if (classifying) return;
      setClassifying(true);
      setGatesError(null);
      try {
        const gate = await enterClassificationGate(source.id);
        if (selectedIdRef.current === source.id) setGates([gate]);
        // 분류 시작 → 인박스에서 승인 게이트 대기로 이동 → 승인 탭으로 전환해 이동을 눈에 보이게.
        setFilter("approval");
        await loadGates(source.id, false);
        await patchSource(source.id);
      } catch (err) {
        setGatesError(sourceCaseMessage(err, "분류를 시작하지 못했습니다. 잠시 후 다시 시도해 주세요."));
      } finally {
        setClassifying(false);
      }
    },
    [classifying, loadGates, patchSource],
  );

  // --- 게이트 승인 ---
  const handleApproveGate = useCallback(
    async (gate: Gate) => {
      if (gateBusyId) return;
      setGateBusyId(gate.id);
      setGatesError(null);
      const active = activeRevisionOf(gate);
      try {
        await approveGate(gate.id, active?.id);
        await loadGates(gate.source_id, false);
        await patchSource(gate.source_id);
        // 문서화 승인 → source documented (visible=false): inbox/승인에서 빠지고 완료 탭으로.
        // stale 재생성 v2 승인도 이 경로다 → BE가 배지 해제하므로 재검토 목록/카운트도 최신화한다
        // (T-015 진행 표시 세션 맵은 목록에서 사라진 문서를 prune 하여 정합)(PLAN-010-T-016).
        if (gate.gate_kind === "documentation") {
          await loadList();
          await loadDocumented();
          await loadStale();
        }
      } catch (err) {
        // STALE/ALREADY_APPROVED 등은 최신 상태를 다시 불러와 화면을 정합화.
        await loadGates(gate.source_id, false);
        setGatesError(sourceCaseMessage(err, "승인에 실패했습니다. 최신 상태를 확인해 주세요."));
      } finally {
        setGateBusyId(null);
      }
    },
    [gateBusyId, loadGates, patchSource, loadList, loadDocumented, loadStale],
  );

  // --- 게이트 실패 재시도 ---
  const handleRetryGate = useCallback(
    async (gate: Gate) => {
      if (gateBusyId) return;
      setGateBusyId(gate.id);
      setGatesError(null);
      try {
        await retryGate(gate.id);
        await loadGates(gate.source_id, false);
        await patchSource(gate.source_id);
      } catch (err) {
        setGatesError(sourceCaseMessage(err, "재시도에 실패했습니다. 잠시 후 다시 시도해 주세요."));
      } finally {
        setGateBusyId(null);
      }
    },
    [gateBusyId, loadGates, patchSource],
  );

  // --- 피드백 모달 열기 ---
  const openSummaryFeedback = useCallback((source: Source) => {
    setFbContext({ kind: "summary", source });
    setFbTarget({ label: "요약 초안 ①", version: "초안", submitLabel: "다시 요약" });
    setFbError(null);
    setFbBusy(false);
  }, []);

  const openGateFeedback = useCallback((gate: Gate) => {
    const active = activeRevisionOf(gate);
    const isDoc = gate.gate_kind === "documentation";
    setFbContext({ kind: "gate", gate });
    setFbTarget({
      label: isDoc ? "문서화 승인 게이트 ③" : "분류 게이트 ②",
      version: active ? `v${active.version}` : "v1",
      submitLabel: "재생성",
      // SPEC-004 U-4: "이 destination이 아님" 보조 옵션은 문서화 게이트(③)에만.
      allowReclassify: isDoc,
    });
    setFbError(null);
    setFbBusy(false);
  }, []);

  const closeFeedback = useCallback(() => {
    if (fbBusy) return;
    setFbContext(null);
    setFbTarget(null);
    setFbError(null);
  }, [fbBusy]);

  // --- 피드백 제출 (대상별 배선) ---
  const submitFeedback = useCallback(
    async (body: string) => {
      if (!fbContext || fbBusy) return;
      setFbBusy(true);
      setFbError(null);
      try {
        if (fbContext.kind === "summary") {
          // 요약 초안 재요약(세션 resume) → summarizing 로 전이된 source 반영.
          const updated = await summaryFeedback(fbContext.source.id, body);
          setSelected(updated);
          setSources((cur) => cur.map((s) => (s.id === updated.id ? updated : s)));
        } else {
          // 게이트 피드백 저장 → v2 재생성 실행(폴링이 이어받음).
          const gate = fbContext.gate;
          await feedbackGate(gate.id, body);
          await regenerateGate(gate.id);
          await loadGates(gate.source_id, false);
          await patchSource(gate.source_id);
        }
        setFbContext(null);
        setFbTarget(null);
      } catch (err) {
        setFbError(sourceCaseMessage(err, "피드백 전송에 실패했습니다. 잠시 후 다시 시도해 주세요."));
      } finally {
        setFbBusy(false);
      }
    },
    [fbContext, fbBusy, loadGates, patchSource],
  );

  // --- "이 destination이 아님" 재분류 요청 (SPEC-004 S-3 · BE T-009) ---
  // 문서화 게이트에 재분류 요청 → 문서화 게이트 cancelled(reclassification_requested) +
  // 분류 게이트 approved→regenerating(새 분류 revision). GET /sources/{id}/gates 재조회로 화면을
  // "분류 다시 검토"로 되돌리고, regenerating 게이트는 폴링이 이어받는다.
  const submitReclassification = useCallback(
    async (reason: string) => {
      if (!fbContext || fbContext.kind !== "gate" || fbBusy) return;
      setFbBusy(true);
      setFbError(null);
      const gate = fbContext.gate;
      try {
        await requestReclassification(gate.id, reason);
        await loadGates(gate.source_id, false);
        await patchSource(gate.source_id);
        setFbContext(null);
        setFbTarget(null);
      } catch (err) {
        setFbError(
          sourceCaseMessage(err, "재분류 요청에 실패했습니다. 최신 상태를 확인해 주세요."),
        );
      } finally {
        setFbBusy(false);
      }
    },
    [fbContext, fbBusy, loadGates, patchSource],
  );

  // 모달 저장 성공 → 목록 새로고침 + 새 항목 선택
  const handleCreated = useCallback(
    (created: Source) => {
      void loadList();
      void selectSource(created);
    },
    [loadList, selectSource],
  );

  // --- stale [판단 유효 · 배지 해제] (SPEC-004 E dismiss) ---
  const handleDismissStale = useCallback(
    async (doc: StaleDocument) => {
      if (staleBusyId) return;
      setStaleBusyId(doc.document_id);
      setStaleError(null);
      try {
        await dismissStale(doc.document_id);
        // 낙관적 제거 후 서버 재조회로 정합. 선택돼 있던 문서면 상세 선택 해제.
        setStaleDocs((cur) => cur.filter((d) => d.document_id !== doc.document_id));
        setSelectedStaleId((cur) => (cur === doc.document_id ? null : cur));
        await loadStale();
      } catch (err) {
        setStaleError(documentCaseMessage(err, "배지 해제에 실패했습니다. 최신 상태를 확인해 주세요."));
        await loadStale();
      } finally {
        setStaleBusyId(null);
      }
    },
    [staleBusyId, loadStale],
  );

  // --- stale [재검토 · 재생성] (SPEC-004 E regenerate) ---
  // producing source 의 문서화 게이트가 재문서화(v++)로 열리고 재생성 task가 큐잉된다. 배지 해제는
  // v2 승인 시점이므로(설계대로) 여기선 문서를 목록에서 지우지 않고 "재생성 진행 중"으로 표시하고
  // 버튼을 잠근다. 이동은 자동 전환 대신 배너의 "게이트에서 보기"로(사용자가 흐름을 알게).
  const handleRegenerateStale = useCallback(
    async (doc: StaleDocument) => {
      if (staleBusyId || regeneratingStale[doc.document_id]) return;
      setStaleBusyId(doc.document_id);
      setStaleError(null);
      try {
        const result = await regenerateDocument(doc.document_id);
        // 진행 상태를 실물 응답(GateResponse)의 gate id·source_id로 세션에 기록 → 진행 표시/이동 좌표.
        setRegeneratingStale((cur) => ({
          ...cur,
          [doc.document_id]: {
            sourceId: result.source_id ?? null,
            gateId: result.id ?? null,
          },
        }));
        await loadStale(); // 여전히 stale(배지 미해제)이라 목록에 남고, 진행 표시가 유지된다.
      } catch (err) {
        setStaleError(documentCaseMessage(err, "재생성 게이트를 열지 못했습니다. 최신 상태를 확인해 주세요."));
        await loadStale();
      } finally {
        setStaleBusyId(null);
      }
    },
    [staleBusyId, regeneratingStale, loadStale],
  );

  // --- 진행 중 "게이트에서 보기": producing source 문서화 게이트 스택으로 이동(기존 스택 재사용) ---
  const openStaleGate = useCallback(
    async (doc: StaleDocument) => {
      const info = regeneratingStale[doc.document_id];
      if (!info?.sourceId) return;
      try {
        const src = await getSource(info.sourceId);
        await selectSource(src); // regenerating 게이트를 우측 스택 폴링이 이어받음
        setFilter("approval"); // 승인 탭으로 전환해 이동을 눈에 보이게(T-031/T-033 흐름)
      } catch {
        // source 조회 실패는 조용히 무시 — 게이트는 승인 탭에서 다시 열 수 있다.
      }
    },
    [regeneratingStale, selectSource],
  );

  // --- 완료(v2 승인→배지 해제)로 목록에서 사라진 문서의 진행 상태 정리(세션 맵 누수 방지) ---
  useEffect(() => {
    setRegeneratingStale((cur) => {
      const ids = new Set(staleDocs.map((d) => d.document_id));
      const next = Object.fromEntries(Object.entries(cur).filter(([id]) => ids.has(id)));
      return Object.keys(next).length === Object.keys(cur).length ? cur : next;
    });
  }, [staleDocs]);

  return (
    <main className="flex h-[calc(100vh-3.5rem)] w-full flex-col px-6 py-5">
      <div className="mb-4 shrink-0">
        <h1 className="text-xl font-semibold tracking-tight">문서함</h1>
      </div>

      {/* 좌: 큐 목록 (300px) / 우: 상세 (1fr) — 21-html 2컬럼. 문서함 높이는 탭 무관 항상 100%(뷰포트 채움).
          재검토 탭: 좌 stale 목록 + 우 stale 상세. 그 외: 좌 source 목록 + 우 게이트 스택. */}
      <div className="grid min-h-0 flex-1 grid-cols-[300px_1fr] gap-4">
        {filter === "review" ? (
          <>
            <StaleList
              items={staleDocs}
              selectedId={selectedStaleId}
              filter={filter}
              loading={staleLoading}
              error={staleError}
              regeneratingIds={new Set(Object.keys(regeneratingStale))}
              onSelect={(doc) => setSelectedStaleId(doc.document_id)}
              onFilterChange={setFilter}
              onOpenModal={() => setModalOpen(true)}
            />
            <StaleDetail
              doc={staleDocs.find((d) => d.document_id === selectedStaleId) ?? null}
              busyId={staleBusyId}
              regenerating={selectedStaleId ? regeneratingStale[selectedStaleId] ?? null : null}
              onDismiss={handleDismissStale}
              onRegenerate={handleRegenerateStale}
              onOpenGate={openStaleGate}
            />
          </>
        ) : (
          <>
            <SourceList
              sources={filter === "documented" ? documented : sources}
              selectedId={selectedId}
              filter={filter}
              reviewCount={staleDocs.length}
              loading={filter === "documented" ? documentedLoading : loading}
              error={filter === "documented" ? documentedError : listError}
              onSelect={selectSource}
              onFilterChange={setFilter}
              onOpenModal={() => setModalOpen(true)}
              onRetry={retryCollection}
            />
            <GateHistoryStack
              source={selected}
              gates={gates}
              gatesLoading={gatesLoading}
              gatesError={gatesError}
              classifying={classifying}
              gateBusyId={gateBusyId}
              retrying={retrying}
              retryError={retryError}
              onSummaryFeedback={openSummaryFeedback}
              onClassify={handleClassify}
              onGateFeedback={openGateFeedback}
              onApproveGate={handleApproveGate}
              onRetryGate={handleRetryGate}
              onRetryCollection={retryCollection}
            />
          </>
        )}
      </div>

      <DirectInboxModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={handleCreated}
      />

      <GateFeedbackModal
        open={fbContext !== null}
        target={fbTarget}
        busy={fbBusy}
        error={fbError}
        onClose={closeFeedback}
        onSubmit={submitFeedback}
        onReclassify={submitReclassification}
      />
    </main>
  );
}
