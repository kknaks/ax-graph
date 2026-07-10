// 재사용 Select (PLAN-009-T-004) — @radix-ui/react-select 래핑.
// native <select>의 OS 기본 팝업 대신 토큰 팔레트에 맞춘 스타일 드롭다운.
// shadcn식 구조지만 레포 관례(hand-rolled Tailwind · 인라인 svg)를 따른다.
// 호출측이 { value, label }[] 옵션을 넘긴다(범용).
"use client";

import * as RadixSelect from "@radix-ui/react-select";

/** 새 유틸 라이브러리 도입 금지 — truthy className만 합성. */
function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export interface SelectOption {
  value: string;
  label: string;
}

export function Select({
  value,
  onValueChange,
  options,
  disabled,
  placeholder,
  ariaLabel,
  className,
}: {
  value: string;
  onValueChange: (v: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RadixSelect.Trigger
        aria-label={ariaLabel}
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-xs outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60 data-[placeholder]:text-muted-foreground",
          className,
        )}
      >
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon>
          <svg className="h-3.5 w-3.5 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m6 9 6 6 6-6" />
          </svg>
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={4}
          className="z-[60] max-h-64 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border border-border bg-background shadow-md"
        >
          <RadixSelect.Viewport className="p-1">
            {options.map((o) => (
              <RadixSelect.Item
                key={o.value}
                value={o.value}
                className="relative flex cursor-pointer select-none items-center rounded-sm py-1.5 pl-7 pr-2 text-xs outline-none data-[highlighted]:bg-secondary data-[state=checked]:font-medium"
              >
                <RadixSelect.ItemIndicator className="absolute left-2 inline-flex items-center">
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                </RadixSelect.ItemIndicator>
                <RadixSelect.ItemText>{o.label}</RadixSelect.ItemText>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
