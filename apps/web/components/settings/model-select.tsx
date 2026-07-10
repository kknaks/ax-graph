// 공용 model 드롭다운 (PLAN-009-T-003 · Radix 교체 PLAN-009-T-004 · AXKG-SPEC-007).
// provider가 model 목록을 지배한다 — PROVIDER_MODELS[provider]만 노출.
// 자유 텍스트 입력을 대체해 오타 → CLI 런타임 실패를 막는 순수 FE 가드
// (BE·스키마 무변경, model은 여전히 string|null 통과값).
"use client";

import { PROVIDER_MODELS, type Provider } from "@/lib/api-client/settings";
import { Select, type SelectOption } from "@/components/ui/select";

// Radix Select는 빈 문자열 value를 허용하지 않는다 →
// null(디폴트)을 센티넬로 매핑해 Select에 넘기고 onChange에서 역매핑한다.
const DEFAULT_SENTINEL = "__default__";

export function ModelSelect({
  provider,
  value,
  onChange,
  disabled,
}: {
  provider: Provider;
  value: string | null;
  onChange: (v: string | null) => void;
  disabled?: boolean;
}) {
  const models = PROVIDER_MODELS[provider] ?? [];
  const options: SelectOption[] = models.map((o) => ({
    value: o.value ?? DEFAULT_SENTINEL,
    label: o.label,
  }));
  // 하위호환: 현재 provider 목록에 없는 non-null 값(레거시/커스텀)은
  // "커스텀" 옵션으로 보존해 선택이 실종되지 않게 한다.
  const hasValue = value == null || models.some((o) => o.value === value);
  if (!hasValue && value != null) {
    options.push({ value, label: `커스텀: ${value}` });
  }

  return (
    <Select
      value={value ?? DEFAULT_SENTINEL}
      onValueChange={(v) => onChange(v === DEFAULT_SENTINEL ? null : v)}
      options={options}
      disabled={disabled}
      ariaLabel="model"
      className="font-mono"
    />
  );
}
