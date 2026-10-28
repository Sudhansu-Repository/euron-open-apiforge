"use client";

import { CircleAlertIcon, CircleCheckIcon, InfoIcon, TriangleAlertIcon } from "lucide-react";

import { Chip } from "@/components/ui/chip";
import type { Finding, Severity } from "@/lib/api/types";
import { severityChip } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { groupFindings, severityCounts } from "@/lib/lint";

const ICON: Record<Severity, typeof InfoIcon> = { error: CircleAlertIcon, warning: TriangleAlertIcon, info: InfoIcon };
const TONE: Record<Severity, string> = { error: "text-danger", warning: "text-warning", info: "text-info" };

const GROUP_HINT: Record<Severity, string> = {
  error: "APIForge cannot generate these faithfully. Fix them, or accept the report when generating to leave them out.",
  warning: "Generated, but not enforced exactly as written. The rest of the API is unaffected.",
  info: "Worth knowing; nothing is lost.",
};

export function SeverityCounts({ report }: { report: readonly Finding[] }) {
  const c = severityCounts(report);
  return (
    <span className="inline-flex flex-wrap gap-1">
      <Chip tone={c.error ? "danger" : "neutral"}>{plural(c.error, "error")}</Chip>
      <Chip tone={c.warning ? "warning" : "neutral"}>{plural(c.warning, "warning")}</Chip>
      <Chip tone={c.info ? "info" : "neutral"}>{c.info} info</Chip>
    </span>
  );
}

/** The lint report grouped by severity: code, message and the JSON pointer of each finding. */
export function LintReport({ report }: { report: readonly Finding[] }) {
  const groups = groupFindings(report);
  if (!groups.length) {
    return (
      <div className="flex items-start gap-3 rounded-xl bg-savings-soft px-4 py-3.5 text-[13px]">
        <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-savings" />
        <div>
          <div className="font-medium text-foreground">Clean report</div>
          <div className="text-muted-foreground">Every construct in this spec is generated and enforced exactly as written.</div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      {groups.map(({ severity, findings }) => {
        const Icon = ICON[severity];
        return (
          <section key={severity} aria-label={`${severityChip(severity).label} findings`}>
            <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <h3 className={cn("flex items-center gap-1.5 text-[13px] font-semibold", TONE[severity])}>
                <Icon className="size-4" />
                {findings.length} {severity === "info" ? "info" : `${severity}${findings.length === 1 ? "" : "s"}`}
              </h3>
              <span className="text-[12px] text-muted-foreground">{GROUP_HINT[severity]}</span>
            </div>
            <ul className="flex flex-col gap-1">
              {findings.map((f, i) => (
                <li key={`${f.code}-${f.pointer}-${i}`} className="rounded-lg bg-muted/60 px-3.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip tone={severityChip(severity).tone} className="font-mono text-[10.5px]">
                      {f.code}
                    </Chip>
                    <span className="min-w-0 text-[13px] text-foreground">{f.message}</span>
                  </div>
                  {f.pointer && <div className="mt-1 font-mono text-[11.5px] break-all text-muted-foreground">{f.pointer}</div>}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
