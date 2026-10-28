"use client";

import * as React from "react";

import { cn } from "@/lib/cn";

/** A plain monospace textarea with a line-number gutter that scrolls with it. */
export function SpecEditor({
  value,
  onChange,
  onSubmit,
  className,
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
  className?: string;
  id?: string;
}) {
  const gutter = React.useRef<HTMLDivElement>(null);
  const lines = React.useMemo(() => Math.max(1, value.split("\n").length), [value]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      onSubmit?.();
      return;
    }
    // Tab indents with two spaces (YAML); Escape then Tab still leaves the field.
    if (e.key === "Tab" && !e.shiftKey && !e.altKey) {
      const el = e.currentTarget;
      if (el.dataset.escaped === "1") return;
      e.preventDefault();
      const { selectionStart: s, selectionEnd: end } = el;
      const next = `${value.slice(0, s)}  ${value.slice(end)}`;
      onChange(next);
      requestAnimationFrame(() => el.setSelectionRange(s + 2, s + 2));
    }
    e.currentTarget.dataset.escaped = e.key === "Escape" ? "1" : "0";
  }

  return (
    <div className={cn("flex overflow-hidden rounded-xl bg-code-bg text-code-fg shadow-[var(--elev-1)] ring-1 ring-white/5", className)}>
      <div
        ref={gutter}
        aria-hidden
        className="no-scrollbar shrink-0 overflow-hidden py-3 pr-3 pl-3 text-right font-mono text-[12px] leading-[1.7] text-code-gutter select-none"
      >
        {Array.from({ length: lines }, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
        }}
        spellCheck={false}
        autoCapitalize="off"
        autoComplete="off"
        autoCorrect="off"
        wrap="off"
        aria-label="OpenAPI spec"
        aria-describedby={id ? `${id}-help` : undefined}
        className="min-w-0 flex-1 resize-none bg-transparent py-3 pr-4 font-mono text-[12px] leading-[1.7] text-code-fg caret-[var(--code-keyword)] outline-none placeholder:text-code-muted"
        placeholder="Paste an OpenAPI 3.0 or 3.1 document"
      />
    </div>
  );
}
