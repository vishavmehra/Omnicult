"use client";

import { useId } from "react";

import { useAtlas } from "./api";
import { Labelled, NativeSelect } from "./parts";

/** Every state and union territory, from the atlas (already cached by the other views). Built states say so. */
export function StateSelect({
  campaignId,
  value,
  onChange,
  label = "State",
  placeholder,
  exclude = [],
  className,
}: {
  campaignId: string;
  value: string | null;
  onChange(code: string): void;
  label?: string;
  placeholder?: string;
  exclude?: string[];
  className?: string;
}) {
  const id = useId();
  const atlas = useAtlas(campaignId);
  const states = (atlas.data?.states ?? []).filter((s) => !exclude.includes(s.code) || s.code === value);
  return (
    <Labelled label={label} htmlFor={id} className={className}>
      <NativeSelect id={id} value={value ?? ""} onChange={(e) => e.target.value && onChange(e.target.value)} disabled={atlas.isPending}>
        {(value === null || placeholder) && <option value="">{placeholder ?? "Choose a state"}</option>}
        {states.map((s) => (
          <option key={s.code} value={s.code}>
            {s.name}
            {s.claims > 0 ? "" : " (no claims)"}
          </option>
        ))}
      </NativeSelect>
    </Labelled>
  );
}
