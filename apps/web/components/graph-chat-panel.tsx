// Graph RAG 채팅 패널 (AXKG-SPEC-006 U-2/U-3 · 21-html page-graph section-spec-006).
// 좌측 문서 그래프(DocumentGraph)와 [graph] | [채팅] split view 를 이룬다.
// - 세션 목록/새 채팅, 질문 입력 → POST → run polling(null-safe), assistant 답변 + Evidence Block
// - 그래프 노드 선택 → selected_node_id context 반영(S-1)
// - Evidence "그래프에서 보기" → 좌측 그래프 노드 강조 요청(S-3)
//
// 현재 BE 는 run 을 queued 로만 생성한다(Phase 2/T-012 가 answer/evidence 를 채움). 폴링은
// terminal(succeeded/failed/cancelled) 까지 반복하고, 응답 필드는 전부 null-safe 로 렌더한다.
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api-client";
import {
  chatCaseMessage,
  getChat,
  getRun,
  isTerminalStatus,
  listChats,
  readEvidenceDocuments,
  readSuggestedActions,
  readUsedPaths,
  sendMessage,
  startChat,
  type ChatRun,
  type ChatSessionSummary,
  type EvidenceDocument,
} from "@/lib/api-client/chat";
import type { GraphSelection } from "@/components/document-graph";
import { formatTime } from "@/lib/format";

// --- 스레드 렌더 모델 (user/assistant/insufficient/error 를 한 목록으로) ---
type ThreadItem =
  | { kind: "user"; key: string; content: string }
  | {
      kind: "assistant";
      key: string;
      content: string;
      evidenceDocuments: EvidenceDocument[];
      usedPaths: string[];
    }
  | {
      kind: "insufficient";
      key: string;
      message: string;
      missingContext: string | null;
      suggestedActions: string[];
    }
  | { kind: "error"; key: string; message: string };

const POLL_INTERVAL_MS = 1500;
const POLL_MAX_ATTEMPTS = 40; // ~60s 안전 상한. BE Phase 2 미배선 시 무한 폴링 방지.

/** missing_context(Any) → 표시용 문자열. 배열/객체/문자열 모두 tolerate. */
function missingContextText(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ");
  return null;
}

function evidenceLabel(doc: EvidenceDocument): string {
  return doc.title || doc.stem || doc.document_id || "문서";
}

export function GraphChatPanel({
  selectedNode,
  onFocusDocument,
}: {
  /** 좌측 그래프에서 현재 선택된 노드(S-1 context). 없으면 전체 그래프 질문(S-2). */
  selectedNode: GraphSelection | null;
  /** Evidence "그래프에서 보기"(S-3) → 좌측 그래프에 해당 문서 노드 강조 요청. */
  onFocusDocument: (documentId: string) => void;
}) {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  // 폴링 중인 run. null 이면 대기 상태.
  const [run, setRun] = useState<{ chatId: string; runId: string } | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // --- 세션 목록 로드 ---
  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listChats());
    } catch {
      // 목록 로드 실패는 조용히 무시 — 새 채팅은 여전히 시작할 수 있다.
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  // --- 스레드 갱신 시 맨 아래로 스크롤 ---
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [thread, run]);

  const appendItem = useCallback((item: ThreadItem) => {
    setThread((prev) => [...prev, item]);
  }, []);

  // --- 기존 세션 열기 → 메시지 이력 → 스레드 변환 ---
  const openSession = useCallback(async (chatId: string) => {
    setRun(null);
    setInputError(null);
    try {
      const detail = await getChat(chatId);
      setActiveChatId(detail.chat_id);
      const items: ThreadItem[] = detail.messages.map((m) => {
        if (m.role === "assistant") {
          return {
            kind: "assistant",
            key: m.id,
            content: m.content,
            evidenceDocuments: readEvidenceDocuments(m.evidence ?? undefined),
            usedPaths: readUsedPaths(m.evidence ?? undefined),
          };
        }
        return { kind: "user", key: m.id, content: m.content };
      });
      setThread(items);
      // 미응답 run 감지 → 폴링 재개: 다른 페이지에 갔다 와도(컴포넌트 재마운트)
      // 진행 중이던 응답 생성을 이어받는다. assistant 메시지가 아직 없는
      // 가장 최근 user 메시지의 run_id 가 폴링 대상.
      const answeredRunIds = new Set(
        detail.messages
          .filter((m) => m.role === "assistant" && m.run_id)
          .map((m) => m.run_id),
      );
      const pendingMsg = [...detail.messages]
        .reverse()
        .find((m) => m.role === "user" && m.run_id && !answeredRunIds.has(m.run_id));
      if (pendingMsg?.run_id) {
        setRun({ chatId: detail.chat_id, runId: pendingMsg.run_id });
      }
    } catch (err) {
      appendItem({
        kind: "error",
        key: `open-${chatId}`,
        message: chatCaseMessage(err, "채팅을 불러오지 못했습니다."),
      });
    }
  }, [appendItem]);

  // --- 새 채팅 ---
  const startNewChat = useCallback(() => {
    setActiveChatId(null);
    setThread([]);
    setRun(null);
    setInputError(null);
  }, []);

  // --- run 종료 처리 → 스레드에 결과 append ---
  const finishRun = useCallback(
    (r: ChatRun) => {
      const suggested = readSuggestedActions(r);
      const evidence = readEvidenceDocuments(r);
      const insufficient =
        r.error_code === "INSUFFICIENT_GRAPH_CONTEXT" ||
        (!r.answer && (r.missing_context != null || suggested.length > 0));

      if (r.status === "failed" && !insufficient) {
        appendItem({
          kind: "error",
          key: `run-${r.run_id}`,
          message:
            r.error_message ||
            chatCaseMessage(
              new ApiError(500, r.error_code ?? "UNKNOWN_ERROR", ""),
              "응답 생성에 실패했습니다.",
            ),
        });
      } else if (r.status === "cancelled") {
        appendItem({
          kind: "error",
          key: `run-${r.run_id}`,
          message: "응답 생성이 취소되었습니다.",
        });
      } else if (insufficient) {
        appendItem({
          kind: "insufficient",
          key: `run-${r.run_id}`,
          message:
            r.answer ||
            "현재 그래프만으로는 답하기 어렵습니다. 근거 문서가 그래프에 없습니다.",
          missingContext: missingContextText(r.missing_context),
          suggestedActions: suggested,
        });
      } else {
        appendItem({
          kind: "assistant",
          key: `run-${r.run_id}`,
          content: r.answer || "응답 본문이 아직 준비되지 않았습니다.",
          evidenceDocuments: evidence,
          usedPaths: readUsedPaths(r),
        });
      }
      void refreshSessions();
    },
    [appendItem, refreshSessions],
  );

  // --- run 폴링: terminal 까지 일정 간격 GET (null-safe) ---
  useEffect(() => {
    if (!run) return;
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      if (cancelled) return;
      attempts += 1;
      try {
        const r = await getRun(run.chatId, run.runId);
        if (cancelled) return;
        if (isTerminalStatus(r.status)) {
          finishRun(r);
          setRun(null);
          return;
        }
      } catch (err) {
        if (cancelled) return;
        appendItem({
          kind: "error",
          key: `poll-${run.runId}`,
          message: chatCaseMessage(err, "응답 상태를 확인하지 못했습니다."),
        });
        setRun(null);
        return;
      }
      if (attempts >= POLL_MAX_ATTEMPTS) {
        appendItem({
          kind: "error",
          key: `timeout-${run.runId}`,
          message: "응답이 지연되고 있습니다. 잠시 후 다시 확인해 주세요.",
        });
        setRun(null);
        return;
      }
      timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
    };

    timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [run, finishRun, appendItem]);

  // --- 질문 전송 ---
  const submit = useCallback(async () => {
    const question = input.trim();
    if (!question) {
      setInputError("질문을 입력해 주세요.");
      return;
    }
    if (sending || run) return;
    setSending(true);
    setInputError(null);
    appendItem({ kind: "user", key: `u-${Date.now()}`, content: question });
    const body = {
      question,
      selected_node_id: selectedNode?.id ?? null,
    };
    try {
      if (activeChatId) {
        const res = await sendMessage(activeChatId, body);
        setRun({ chatId: activeChatId, runId: res.run_id });
      } else {
        const res = await startChat(body);
        setActiveChatId(res.chat_id);
        setRun({ chatId: res.chat_id, runId: res.run_id });
        void refreshSessions();
      }
      setInput("");
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === "EMPTY_QUESTION") {
        setInputError("질문을 입력해 주세요.");
      } else if (err instanceof ApiError && err.errorCode === "NODE_NOT_FOUND") {
        appendItem({
          kind: "error",
          key: `send-${Date.now()}`,
          message: "선택한 문서를 찾지 못했습니다. 그래프에서 다시 선택해 주세요.",
        });
      } else {
        appendItem({
          kind: "error",
          key: `send-${Date.now()}`,
          message: chatCaseMessage(err, "질문 전송에 실패했습니다."),
        });
      }
    } finally {
      setSending(false);
    }
  }, [input, sending, run, selectedNode, activeChatId, appendItem, refreshSessions]);

  const busy = sending || run !== null;

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      {/* 헤더: sparkles + 제목 + 새 채팅 */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <svg
          className="h-4 w-4 text-muted-foreground"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z" />
        </svg>
        <h2 className="text-sm font-semibold">Graph RAG 채팅</h2>
        <button
          type="button"
          onClick={startNewChat}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium hover:bg-secondary/60"
        >
          <svg
            className="h-3.5 w-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden
          >
            <path d="M5 12h14M12 5v14" />
          </svg>
          새 채팅
        </button>
      </div>

      {/* 세션 목록 + 현재 세션 context (SPEC-006 persistent chat) */}
      <div className="border-b border-border bg-secondary/20 px-3 py-2">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            내 채팅
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">
            {sessions.length} sessions
          </span>
        </div>
        {sessions.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-background/60 px-2 py-2 text-center text-[11px] text-muted-foreground">
            아직 채팅이 없습니다. 아래에서 새 질문을 시작해 보세요.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-1.5">
            {sessions.map((s) => {
              const active = s.chat_id === activeChatId;
              return (
                <button
                  key={s.chat_id}
                  type="button"
                  onClick={() => void openSession(s.chat_id)}
                  className={
                    active
                      ? "rounded-md border border-ring bg-background px-2 py-1.5 text-left"
                      : "rounded-md border border-border bg-background/70 px-2 py-1.5 text-left opacity-75 hover:opacity-100"
                  }
                >
                  <div className="truncate text-[11px] font-medium">{s.title}</div>
                  <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                    {s.status}
                    {s.last_message_at ? ` · ${formatTime(s.last_message_at)}` : ""}
                  </div>
                </button>
              );
            })}
          </div>
        )}
        <div className="mt-2 rounded-md border border-border bg-background px-2.5 py-2 text-[10px]">
          <div className="flex items-center justify-between">
            <span className="font-medium">현재 세션</span>
            {selectedNode ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-1.5 py-0.5 font-medium text-secondary-foreground">
                context · {selectedNode.title}
              </span>
            ) : (
              <span className="text-muted-foreground">전체 그래프</span>
            )}
          </div>
          <div className="mt-1 font-mono text-muted-foreground">
            {activeChatId ? `chat_id=${activeChatId}` : "새 채팅 (미저장)"}
          </div>
        </div>
      </div>

      {/* 메시지 스레드 */}
      <div
        ref={scrollRef}
        className="scroll-thin flex-1 space-y-4 overflow-y-auto px-4 py-4"
      >
        {thread.length === 0 && !run ? (
          <div className="grid h-full place-items-center px-6 text-center text-xs leading-relaxed text-muted-foreground">
            그래프에 대해 질문해 보세요.
            <br />
            노드를 선택하면 해당 문서를 우선 근거로 사용합니다.
          </div>
        ) : (
          thread.map((item) => {
            if (item.kind === "user") {
              return (
                <div key={item.key} className="flex justify-end">
                  <div className="max-w-[85%] rounded-lg rounded-tr-sm bg-primary px-3 py-2 text-sm text-primary-foreground">
                    {item.content}
                  </div>
                </div>
              );
            }
            if (item.kind === "assistant") {
              return (
                <div key={item.key} className="flex justify-start">
                  <div className="max-w-[90%] space-y-2">
                    <div className="rounded-lg rounded-tl-sm border border-border bg-secondary/50 px-3 py-2 text-sm leading-relaxed">
                      {item.content}
                    </div>
                    {(item.evidenceDocuments.length > 0 ||
                      item.usedPaths.length > 0) && (
                      <EvidenceBlock
                        docs={item.evidenceDocuments}
                        usedPaths={item.usedPaths}
                        onFocusDocument={onFocusDocument}
                      />
                    )}
                  </div>
                </div>
              );
            }
            if (item.kind === "insufficient") {
              return (
                <div key={item.key} className="flex justify-start">
                  <div className="max-w-[90%] space-y-2">
                    <div
                      className="rounded-lg rounded-tl-sm border border-dashed px-3 py-2 text-sm leading-relaxed"
                      style={{
                        borderColor: "hsl(38 92% 50%)",
                        background: "hsl(38 92% 50% / 0.08)",
                      }}
                    >
                      {item.message}
                      {item.missingContext && (
                        <div className="mt-1 text-[12px] text-muted-foreground">
                          부족한 근거 · {item.missingContext}
                        </div>
                      )}
                    </div>
                    {item.suggestedActions.length > 0 && (
                      <div className="rounded-lg border border-border bg-card p-3">
                        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          suggested actions
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {item.suggestedActions.map((a, i) => (
                            <span
                              key={`${item.key}-act-${i}`}
                              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[11px] font-medium"
                            >
                              {a}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            }
            // error
            return (
              <div key={item.key} className="flex justify-start">
                <div className="max-w-[90%] rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {item.message}
                </div>
              </div>
            );
          })
        )}

        {/* run 폴링 로딩 상태 */}
        {run && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <svg
              className="h-3.5 w-3.5 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            응답 생성 중…
          </div>
        )}
      </div>

      {/* 입력 */}
      <div className="border-t border-border p-3">
        {inputError && (
          <div className="mb-2 text-[11px] text-destructive">{inputError}</div>
        )}
        <div className="flex items-center gap-2 rounded-lg border border-input bg-background px-3 py-2 focus-within:ring-2 focus-within:ring-ring/40">
          <input
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50"
            placeholder="그래프에 대해 질문하기…"
            value={input}
            disabled={busy}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void submit();
              }
            }}
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy}
            aria-label="질문 보내기"
            className="grid h-7 w-7 place-items-center rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" />
              <path d="m21.854 2.147-10.94 10.939" />
            </svg>
          </button>
        </div>
      </div>
    </section>
  );
}

// --- Evidence Block (SPEC-006 U-3) — 근거 문서 + 관련 구절/연결 이유 + used path ---
function EvidenceBlock({
  docs,
  usedPaths,
  onFocusDocument,
}: {
  docs: EvidenceDocument[];
  usedPaths: string[];
  onFocusDocument: (documentId: string) => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <svg
          className="h-3.5 w-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
          <path d="M14 2v4a2 2 0 0 0 2 2h4" />
        </svg>
        Evidence · 근거 문서 {docs.length}
      </div>
      <ul className="space-y-1.5 text-xs">
        {docs.map((doc, i) => (
          <li
            key={doc.document_id ?? `${evidenceLabel(doc)}-${i}`}
            className="rounded-md bg-secondary/50 px-2 py-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate">
                {doc.document_type && (
                  <span className="font-mono text-[10px] text-muted-foreground">
                    [{doc.document_type}]{" "}
                  </span>
                )}
                {evidenceLabel(doc)}
              </span>
              {doc.document_id && (
                <button
                  type="button"
                  onClick={() => onFocusDocument(doc.document_id as string)}
                  className="shrink-0 text-[11px] font-medium text-muted-foreground hover:text-foreground"
                >
                  그래프에서 보기
                </button>
              )}
            </div>
            {/* U-3 관련 구절 요약 (값 없으면 생략) */}
            {doc.excerpt && (
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {doc.excerpt}
              </p>
            )}
            {/* U-3 연결 이유 (값 없으면 생략) */}
            {doc.reason && (
              <p className="mt-1 text-[11px] leading-relaxed text-foreground/70">
                <span className="font-medium text-foreground">연결 이유 · </span>
                {doc.reason}
              </p>
            )}
          </li>
        ))}
      </ul>
      {usedPaths.length > 0 && (
        <div className="mt-2 font-mono text-[10px] text-muted-foreground">
          used path · {usedPaths.join(" → ")}
        </div>
      )}
    </div>
  );
}
