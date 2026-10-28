"use client";

import { GitCompareArrowsIcon, MinusIcon, PencilIcon, PlusIcon } from "lucide-react";

import { MethodChip } from "@/components/status-chip";
import { Chip } from "@/components/ui/chip";
import type { SpecChanges } from "@/lib/api/types";
import { changedOperations, changeCounts, splitOperation } from "@/lib/spec-changes";

function OpLine({ op }: { op: string }) {
  const { method, path } = splitOperation(op);
  return (
    <span className="flex min-w-0 items-center gap-2">
      {method && <MethodChip method={method} />}
      <span className="min-w-0 font-mono text-[12.5px] break-all">{path}</span>
    </span>
  );
}

/** Small "+3 -1 ~2" counts for lists. */
export function ChangeCounts({ added, removed, changed }: { added: number; removed: number; changed: number }) {
  if (!added && !removed && !changed) return <span className="text-[12px] text-faint">No operation changes</span>;
  return (
    <span className="inline-flex gap-2 font-mono text-[12px] tabular">
      <span className={added ? "text-savings" : "text-faint"}>+{added}</span>
      <span className={removed ? "text-danger" : "text-faint"}>-{removed}</span>
      <span className={changed ? "text-warning" : "text-faint"}>~{changed}</span>
    </span>
  );
}

/** Operations added, removed and changed compared with the previous version. */
export function SpecChangesView({ changes }: { changes: SpecChanges }) {
  const c = changeCounts(changes);
  const changed = changedOperations(changes);

  if (changes.first) {
    return (
      <div className="px-5 pb-4">
        <p className="mb-2 text-[12.5px] text-muted-foreground">The first version of this project: all {c.added} operations are new.</p>
        <ul className="flex flex-col gap-1">
          {changes.added.map((op) => (
            <li key={op} className="rounded-lg bg-muted/60 px-3 py-1.5">
              <OpLine op={op} />
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (!c.added && !c.removed && !c.changed) {
    return (
      <div className="flex items-start gap-3 px-5 pb-4 text-[12.5px] text-muted-foreground">
        <GitCompareArrowsIcon className="mt-0.5 size-4 shrink-0 text-faint" />
        No operation was added, removed or changed. The edit touched descriptions, metadata or models only.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4 px-5 pb-4">
      {changes.added.length > 0 && (
        <section>
          <h3 className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-semibold text-savings">
            <PlusIcon className="size-3.5" /> {c.added} added
          </h3>
          <ul className="flex flex-col gap-1">
            {changes.added.map((op) => (
              <li key={op} className="rounded-lg bg-savings-soft/60 px-3 py-1.5">
                <OpLine op={op} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {changes.removed.length > 0 && (
        <section>
          <h3 className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-semibold text-danger">
            <MinusIcon className="size-3.5" /> {c.removed} removed
          </h3>
          <ul className="flex flex-col gap-1">
            {changes.removed.map((op) => (
              <li key={op} className="rounded-lg bg-danger-soft/60 px-3 py-1.5">
                <OpLine op={op} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {changed.length > 0 && (
        <section>
          <h3 className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-semibold text-warning">
            <PencilIcon className="size-3.5" /> {c.changed} changed
          </h3>
          <ul className="flex flex-col gap-1">
            {changed.map((op) => (
              <li key={op.operation} className="flex flex-col gap-1.5 rounded-lg bg-warning-soft/60 px-3 py-1.5">
                <OpLine op={op.operation} />
                {op.parts.length > 0 && (
                  <span className="flex flex-wrap gap-1">
                    {op.parts.map((p) => (
                      <Chip key={p} tone="warning">
                        {p}
                      </Chip>
                    ))}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
