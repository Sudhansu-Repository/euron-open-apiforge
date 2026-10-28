"use client";

import { CircleAlertIcon } from "lucide-react";

import { ApiError, errorMessage } from "@/lib/api/errors";
import { detailLines } from "@/lib/lint";

/** A rejected spec (422): the message, then each reason from details.errors. */
export function SpecErrorPanel({ error, title = "The spec was rejected" }: { error: unknown; title?: string }) {
  const lines = error instanceof ApiError ? detailLines(error.details) : [];
  const pointer = error instanceof ApiError && typeof error.details.pointer === "string" ? error.details.pointer : null;
  return (
    <div role="alert" className="rounded-xl bg-danger-soft px-4 py-3 text-[13px]">
      <div className="flex items-start gap-2.5">
        <CircleAlertIcon className="mt-0.5 size-4 shrink-0 text-danger" />
        <div className="min-w-0">
          <div className="font-semibold text-foreground">{title}</div>
          <p className="mt-0.5 text-foreground/85">{errorMessage(error)}</p>
          {pointer && <p className="mt-1 font-mono text-[11.5px] break-all text-muted-foreground">{pointer}</p>}
          {lines.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-4 font-mono text-[11.5px] break-words text-foreground/80">
              {lines.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[12px] text-muted-foreground">Fix the spec and try again. The playground lints without saving anything.</p>
        </div>
      </div>
    </div>
  );
}
