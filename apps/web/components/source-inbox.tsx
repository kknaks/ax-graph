// Source Inbox 화면 오케스트레이터 (AXKG-SPEC-003 U-1/U-2/U-3).
// 좌: 큐 목록(상태별 필터) / 우: 선택 source 상세. 상단 우측: Direct Inbox 모달.
// 데이터 로드/재시도/생성 배선을 여기서 모은다. 앱 셸/가드는 (app)/layout 에서 재사용.
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSource,
  listSources,
  queueCollection,
  sourceCaseMessage,
  type ClassificationGateEntry,
  type Source,
} from "@/lib/api-client/sources";
import { SourceList, type StatusFilter } from "@/components/source-list";
import { SourceDetail } from "@/components/source-detail";
import { DirectInboxModal } from "@/components/direct-inbox-modal";
import { SourceDocumentModal } from "@/components/source-document-modal";

export function SourceInbox() {
  const [sources, setSources] = useState<Source[]>([]);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Source | null>(null);

  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);

  // 요약 초안 문서보기 모달 (U-2 · T-015 개정본) + [분류] 진입 안내
  const [docModalOpen, setDocModalOpen] = useState(false);
  const [classifyNotice, setClassifyNotice] = useState<string | null>(null);

  // 목록 로드 (필터 변경 시 재조회)
  const loadList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const items = await listSources(filter === "all" ? undefined : filter);
      setSources(items);
    } catch (err) {
      setSources([]);
      setListError(sourceCaseMessage(err, "목록을 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // source 선택 → 상세 원본 정보 조회 (GET /sources/{id})
  const selectSource = useCallback(async (source: Source) => {
    setSelectedId(source.id);
    setSelected(source); // 목록 데이터로 즉시 표시하고
    setRetryError(null);
    setClassifyNotice(null); // 대상 전환 시 이전 [분류] 안내 초기화
    try {
      const full = await getSource(source.id); // 상세로 보강
      setSelected((cur) => (cur?.id === source.id ? full : cur));
    } catch {
      // 상세 조회 실패 시 목록 데이터로 유지 (blocked 아님)
    }
  }, []);

  // 요약 재시도 (POST /sources/{id}/queue-collection) — 목록/상세 공용.
  // 상세에서 note(원문 복붙/요지)를 함께 넘기면 메모 갱신 + 재요약을 한 번에 처리한다.
  const retrySource = useCallback(
    async (source: Source, note?: string) => {
      if (retrying) return;
      setSelectedId(source.id);
      setRetrying(true);
      setRetryError(null);
      try {
        const updated = await queueCollection(source.id, note);
        setSelected(updated);
        setSources((cur) =>
          cur.map((s) => (s.id === updated.id ? updated : s)),
        );
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

  // 모달 저장 성공 → 목록 새로고침 + 새 항목 선택
  const handleCreated = useCallback(
    (created: Source) => {
      void loadList();
      void selectSource(created);
    },
    [loadList, selectSource],
  );

  // [문서보기] 열기 (summarized 상세 CTA)
  const openDocument = useCallback((source: Source) => {
    setSelectedId(source.id);
    setSelected(source);
    setClassifyNotice(null);
    setDocModalOpen(true);
  }, []);

  // [피드백] 성공 → 재요약(summarizing) 시작된 source 로 목록/상세 갱신.
  // 세션 resume 로 완료되면 다시 summarized 가 되며, 라이브 갱신 연동은 admin 후속.
  const handleSummaryUpdated = useCallback((updated: Source) => {
    setSelected(updated);
    setSources((cur) => cur.map((s) => (s.id === updated.id ? updated : s)));
    setClassifyNotice(null);
  }, []);

  // [분류] 성공 → 분류 게이트 진입. 화면·md 변환은 WP3 범위 밖이라 안내만 표시하고 상태만 갱신.
  const handleClassifyEntered = useCallback(
    (source: Source, entry: ClassificationGateEntry) => {
      if (entry.source) {
        setSelected(entry.source);
        setSources((cur) =>
          cur.map((s) => (s.id === entry.source!.id ? entry.source! : s)),
        );
      }
      setClassifyNotice("분류 게이트로 보냈습니다. 분류 화면은 준비 중입니다 (WP3).");
    },
    [],
  );

  return (
    <main className="w-full px-6 py-5">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">Source Inbox</h1>
      </div>

      {/* 좌: 큐 목록 (300px) / 우: 선택 source 상세 (1fr) — 시안 2컬럼 */}
      <div className="grid grid-cols-[300px_1fr] gap-4">
        <SourceList
          sources={sources}
          selectedId={selectedId}
          filter={filter}
          loading={loading}
          error={listError}
          onSelect={selectSource}
          onFilterChange={setFilter}
          onOpenModal={() => setModalOpen(true)}
          onRetry={retrySource}
        />
        <SourceDetail
          source={selected}
          retrying={retrying}
          retryError={retryError}
          onRetry={retrySource}
          onOpenDocument={openDocument}
          classifyNotice={classifyNotice}
        />
      </div>

      <DirectInboxModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={handleCreated}
      />

      <SourceDocumentModal
        open={docModalOpen}
        source={selected}
        onClose={() => setDocModalOpen(false)}
        onSummaryUpdated={handleSummaryUpdated}
        onClassifyEntered={handleClassifyEntered}
      />
    </main>
  );
}
