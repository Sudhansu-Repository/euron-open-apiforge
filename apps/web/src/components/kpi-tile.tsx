"use client";

import { type LucideIcon } from "lucide-react";
import * as React from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

import { Hint } from "./hint";

/** A headline number with one line of context under it. */
export function KpiTile({
  label,
  value,
  sub,
  icon: Icon,
  hint,
  accent = "primary",
  loading = false,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon: LucideIcon;
  hint?: React.ReactNode;
  accent?: "primary" | "info" | "warning" | "danger";
  loading?: boolean;
}) {
  const iconTone = {
    primary: "bg-primary-soft text-primary",
    info: "bg-info-soft text-info",
    warning: "bg-warning-soft text-warning",
    danger: "bg-danger-soft text-danger",
  }[accent];

  return (
    <div className="surface flex min-w-0 flex-col gap-3 p-4">
      <div className="flex items-center gap-2">
        <span className={cn("flex size-7 items-center justify-center rounded-lg", iconTone)}>
          <Icon className="size-3.5" />
        </span>
        <span className="min-w-0 text-[12.5px] leading-tight font-medium text-muted-foreground">{label}</span>
        {hint && <Hint text={hint} label={`About ${label.toLowerCase()}`} />}
      </div>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-3.5 w-32" />
        </div>
      ) : (
        <div>
          <div className="truncate text-[24px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular">{value}</div>
          {sub && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">{sub}</div>}
        </div>
      )}
    </div>
  );
}
