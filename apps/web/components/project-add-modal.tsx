// 프로젝트 추가 모달 (AXKG-SPEC-014 U-1 · U-2) — 회사 프로젝트 수동·독립 스캐폴드.
//  U-1: 회사명 입력 → slug 실시간 미리보기(GET /projects:slug-preview) + 충돌 여부 표시.
//  U-2: slug 충돌 시 확인 분기 — [기존에 추가](merge) / [새 프로젝트로](create_new) → POST /projects.
// 이 작업은 업로드/분류와 별개인 수동 디렉토리 스캐폴딩이다(AI 자동 생성 아님).
// admin 전용 표면(/projects 라우트 가드로 보호) — 여기서 별도 권한 분기는 하지 않는다.
"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api-client";
import {
  createProject,
  previewSlug,
  projectCaseMessage,
  type CreateProjectResult,
  type OnConflict,
  type SlugPreview,
} from "@/lib/api-client/projects";

export function ProjectAddModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  /** 생성/합류 성공 시 결과(slug)를 부모에 전달 — 목록 갱신·해당 corp 선택. */
  onCreated: (result: CreateProjectResult) => void;
}) {
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<SlugPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setPreview(null);
      setPreviewing(false);
      setSubmitting(false);
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // 회사명 입력 → 디바운스 slug 미리보기(U-1 실시간). 빈 입력은 미리보기 제거.
  useEffect(() => {
    if (!open) return;
    const trimmed = name.trim();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!trimmed) {
      setPreview(null);
      setPreviewing(false);
      return;
    }
    setPreviewing(true);
    debounceRef.current = setTimeout(() => {
      let alive = true;
      previewSlug(trimmed)
        .then((p) => {
          if (alive) setPreview(p);
        })
        .catch(() => {
          if (alive) setPreview(null);
        })
        .finally(() => {
          if (alive) setPreviewing(false);
        });
      return () => {
        alive = false;
      };
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [name, open]);

  if (!open) return null;

  const trimmed = name.trim();
  const conflict = preview?.conflict === true;

  async function submit(onConflict?: OnConflict) {
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createProject({
        name: trimmed,
        ...(onConflict ? { on_conflict: onConflict } : {}),
      });
      onCreated(result);
      onClose();
    } catch (err) {
      // 미리보기 이후 경쟁적으로 충돌이 생겨 409 SLUG_CONFLICT 가 오면 U-2 분기(합류/신규)를 노출한다.
      if (err instanceof ApiError && err.errorCode === "SLUG_CONFLICT") {
        setPreview((cur) => (cur ? { ...cur, conflict: true } : cur));
      }
      setError(projectCaseMessage(err, "프로젝트를 만들지 못했습니다. 잠시 후 다시 시도해 주세요."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="프로젝트 추가"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold">프로젝트 추가</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary"
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
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <label htmlFor="corp-name" className="text-[11px] font-medium text-muted-foreground">
          회사명
        </label>
        <input
          id="corp-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !conflict) submit();
          }}
          autoFocus
          className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
          placeholder="회사명을 입력하세요(예: 더에스씨)"
        />

        {/* slug 미리보기(U-1) — 입력 중이면 loading, 결과 있으면 slug 표시. */}
        <div className="mt-2 min-h-[1.25rem] text-[11px]">
          {previewing ? (
            <span className="text-muted-foreground">slug 미리보기…</span>
          ) : preview ? (
            <span className="text-muted-foreground">
              slug 미리보기: <span className="font-mono text-foreground">{preview.slug}</span>
            </span>
          ) : (
            <span className="text-muted-foreground">회사명을 입력하면 slug 를 미리 보여줍니다.</span>
          )}
        </div>

        {/* U-2 slug 충돌 확인 — 기존 사용(merge) / 새 프로젝트로(create_new) */}
        {conflict && preview && (
          <div
            className="mt-2 rounded-md border border-dashed p-3 text-[11px]"
            style={{
              borderColor: "hsl(var(--tier-caution) / .45)",
              background: "hsl(var(--tier-caution) / .06)",
            }}
          >
            <div className="font-medium" style={{ color: "hsl(var(--tier-caution))" }}>
              이미 <span className="font-mono">{preview.slug}</span> 프로젝트가 있습니다. 어떻게 할까요?
            </div>
            <p className="mt-1 leading-relaxed text-muted-foreground">
              기존에 추가 = 기존 프로젝트를 그대로 씁니다(중복 생성 안 함) · 새 프로젝트로 = suffix 로 분리 생성합니다.
            </p>
          </div>
        )}

        {error && (
          <p
            className="mt-2 rounded-md px-2.5 py-2 text-[11px] text-destructive"
            style={{ background: "hsl(var(--destructive) / .08)" }}
          >
            {error}
          </p>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-secondary"
          >
            취소
          </button>
          {conflict ? (
            <>
              <button
                type="button"
                onClick={() => submit("merge")}
                disabled={submitting}
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-secondary disabled:opacity-60"
              >
                기존에 추가
              </button>
              <button
                type="button"
                onClick={() => submit("create_new")}
                disabled={submitting}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
              >
                {submitting ? "만드는 중…" : "새 프로젝트로"}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => submit()}
              disabled={submitting || !trimmed}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
            >
              {submitting ? "만드는 중…" : "만들기"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
