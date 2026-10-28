"use client";

import { Chip } from "@/components/ui/chip";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { generationChip, methodTone, ownerChip, severityChip, type ChipSpec, type Tone } from "@/lib/chips";
import { cn } from "@/lib/cn";

export function SpecChip({
  spec,
  withHint = true,
  dot = true,
  pulse = false,
  className,
}: {
  spec: ChipSpec;
  withHint?: boolean;
  dot?: boolean;
  pulse?: boolean;
  className?: string;
}) {
  const chip = (
    <Chip tone={spec.tone} dot={dot && !pulse} className={className}>
      {pulse && (
        <span aria-hidden className="relative flex size-1.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex size-1.5 rounded-full bg-current" />
        </span>
      )}
      {spec.label}
    </Chip>
  );
  if (!withHint || !spec.hint) return chip;
  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={0} className="inline-flex rounded-full focus-visible:outline-2 focus-visible:outline-ring" />}>
        {chip}
      </TooltipTrigger>
      <TooltipContent>{spec.hint}</TooltipContent>
    </Tooltip>
  );
}

export function GenerationChip({ value }: { value: string }) {
  return <SpecChip spec={generationChip(value)} pulse={value === "queued" || value === "running"} />;
}

export const SeverityChip = ({ value }: { value: string }) => <SpecChip spec={severityChip(value)} dot={false} />;

/** "generated" (APIForge rewrites it) or "yours" (created once, never overwritten). */
export function OwnerChip({ value, withHint = true }: { value: string; withHint?: boolean }) {
  return <SpecChip spec={ownerChip(value)} dot={false} withHint={withHint} className="h-[18px] px-1.5 text-[10.5px]" />;
}

const METHOD_TONE: Record<ReturnType<typeof methodTone>, Tone> = {
  get: "info",
  post: "success",
  put: "warning",
  patch: "warning",
  delete: "danger",
  other: "neutral",
};

export function MethodChip({ method, className }: { method: string; className?: string }) {
  return (
    <Chip tone={METHOD_TONE[methodTone(method)]} className={cn("w-[58px] justify-center font-mono text-[10.5px] uppercase", className)}>
      {method}
    </Chip>
  );
}

/** Options a generation was built with (db, docker, ci) as quiet chips. */
export function OptionChips({ options }: { options: { db?: boolean; docker?: boolean; ci?: boolean } | null | undefined }) {
  const on = (["db", "docker", "ci"] as const).filter((k) => options?.[k]);
  if (!on.length) return <span className="text-[12px] text-faint">Defaults only</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {on.map((k) => (
        <Chip key={k} tone="neutral" className="font-mono text-[10.5px]">
          --{k}
        </Chip>
      ))}
    </span>
  );
}
