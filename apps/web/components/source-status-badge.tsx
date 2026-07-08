// Source 상태 배지 (AXKG-SPEC-003). 배지 텍스트는 21-html 시안대로 status enum 토큰을 쓴다.
// 색: summarized=tier-ok, collection_failed=tier-caution, documented=tier-ok(옅음), 그 외=secondary.
import type { SourceStatus } from "@/lib/api-client/sources";

type BadgeTone = {
  /** 시안의 inline style(hsl(var(--tier-*) / a)) 을 그대로 재현. */
  style?: React.CSSProperties;
  className?: string;
};

const TONES: Record<SourceStatus, BadgeTone> = {
  received: {
    style: {
      background: "hsl(var(--secondary))",
      color: "hsl(var(--secondary-foreground))",
    },
  },
  summarizing: {
    style: {
      background: "hsl(var(--tier-caution) / .15)",
      color: "hsl(var(--tier-caution))",
    },
  },
  summarized: {
    style: {
      background: "hsl(var(--tier-ok) / .15)",
      color: "hsl(var(--tier-ok))",
    },
  },
  collection_failed: {
    style: {
      background: "hsl(var(--tier-caution) / .15)",
      color: "hsl(var(--tier-caution))",
    },
  },
  ignored: {
    className: "bg-secondary text-muted-foreground",
  },
  documented: {
    style: {
      background: "hsl(var(--tier-ok) / .12)",
      color: "hsl(var(--tier-ok))",
    },
  },
  archived: {
    className: "bg-secondary text-muted-foreground",
  },
  deleted: {
    className: "bg-secondary text-muted-foreground",
  },
};

export function SourceStatusBadge({
  status,
  className = "",
}: {
  status: SourceStatus;
  className?: string;
}) {
  const tone = TONES[status];
  return (
    <span
      className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${tone.className ?? ""} ${className}`}
      style={tone.style}
    >
      {status}
    </span>
  );
}
