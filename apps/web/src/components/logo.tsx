"use client";

import { useId } from "react";

import { cn } from "@/lib/cn";

/** The APIForge mark: a forge spark struck between a pair of curly braces. */
export function ForgeMark({ className }: { className?: string }) {
  // A unique gradient id per instance: when the first SVG defining a shared id sits in a
  // hidden subtree (the collapsed sidebar on phones), browsers resolve the fill to nothing.
  const gradient = `af-mark-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-7 shrink-0", className)}>
      <defs>
        <linearGradient id={gradient} x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--primary)" />
          <stop offset="1" stopColor="var(--info)" />
        </linearGradient>
      </defs>
      <rect x="2.5" y="2.5" width="27" height="27" rx="8" fill={`url(#${gradient})`} />
      <g fill="none" stroke="var(--primary-foreground)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M11.5 9c-1.9 0-2.8 1-2.8 2.8v1.6c0 1-.5 1.9-1.7 2.6 1.2.7 1.7 1.6 1.7 2.6v1.6c0 1.8.9 2.8 2.8 2.8" />
        <path d="M20.5 9c1.9 0 2.8 1 2.8 2.8v1.6c0 1 .5 1.9 1.7 2.6-1.2.7-1.7 1.6-1.7 2.6v1.6c0 1.8-.9 2.8-2.8 2.8" />
      </g>
      <path d="M16 11.2l1.15 3.65L20.8 16l-3.65 1.15L16 20.8l-1.15-3.65L11.2 16l3.65-1.15z" fill="var(--primary-foreground)" />
    </svg>
  );
}

export function ForgeLogo({ className, collapsed = false }: { className?: string; collapsed?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <ForgeMark />
      {!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em] text-foreground">APIForge</span>}
    </span>
  );
}
