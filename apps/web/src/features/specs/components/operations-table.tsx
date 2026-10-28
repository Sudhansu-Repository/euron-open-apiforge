"use client";

import { RouteIcon, SearchIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { MethodChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { OperationSummary } from "@/lib/api/types";
import { cn } from "@/lib/cn";

/** Every operation with the handler function APIForge generates for it, filterable by tag. */
export function OperationsTable({ operations }: { operations: readonly OperationSummary[] }) {
  const [tag, setTag] = React.useState<string>("");
  const [query, setQuery] = React.useState("");
  const tags = React.useMemo(() => {
    const counts = new Map<string, number>();
    for (const o of operations) counts.set(o.tag, (counts.get(o.tag) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [operations]);
  const q = query.trim().toLowerCase();
  const rows = operations.filter(
    (o) =>
      (!tag || o.tag === tag) &&
      (!q || [o.path, o.operation_id, o.function, o.summary, o.method].some((v) => v.toLowerCase().includes(q))),
  );

  if (!operations.length) {
    return (
      <EmptyState
        compact
        icon={RouteIcon}
        title="No operations"
        description="This spec describes no paths yet. Add operations under paths: and upload it again; models alone generate no routes."
      />
    );
  }

  return (
    <div>
      <div className="flex flex-col gap-2 px-5 pb-3 sm:flex-row sm:items-center sm:justify-between">
        {tags.length > 1 ? (
          <div role="radiogroup" aria-label="Filter by tag" className="no-scrollbar flex gap-1 overflow-x-auto">
            {[["", operations.length] as const, ...tags].map(([name, count]) => (
              <button
                key={name || "all"}
                type="button"
                role="radio"
                aria-checked={tag === name}
                onClick={() => setTag(name)}
                className={cn(
                  "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12.5px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
                  tag === name && "bg-primary-soft text-primary hover:bg-primary-soft hover:text-primary",
                )}
              >
                {name || "All tags"}
                <span className="tabular opacity-70">{count}</span>
              </button>
            ))}
          </div>
        ) : (
          <span />
        )}
        <div className="relative w-full sm:w-56">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-faint" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Path, id or function" aria-label="Filter operations" className="h-8 pl-8 text-[13px]" />
        </div>
      </div>
      {!rows.length ? (
        <EmptyState
          compact
          icon={SearchIcon}
          title="No operation matches"
          description="Nothing matches this tag and search. Clear the filters to see every operation."
          action={
            <Button size="sm" variant="secondary" onClick={() => { setTag(""); setQuery(""); }}>
              Clear filters
            </Button>
          }
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Operation</TableHead>
              <TableHead className="hidden lg:table-cell">Operation id</TableHead>
              <TableHead className="hidden md:table-cell">Handler</TableHead>
              <TableHead className="hidden xl:table-cell">Tag</TableHead>
              <TableHead className="hidden sm:table-cell">Auth</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((o) => (
              <TableRow key={`${o.method} ${o.path}`} className={cn(o.deprecated && "opacity-70")}>
                <TableCell>
                  <div className="flex items-start gap-2.5">
                    <MethodChip method={o.method} className="mt-px" />
                    <div className="min-w-0">
                      <div className={cn("font-mono text-[12.5px] break-all", o.deprecated && "line-through")}>{o.path}</div>
                      <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
                        {o.summary && <span>{o.summary}</span>}
                        {o.deprecated && <Chip tone="warning">Deprecated</Chip>}
                      </div>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="hidden font-mono text-[12px] text-muted-foreground lg:table-cell">{o.operation_id}</TableCell>
                <TableCell className="hidden font-mono text-[12px] md:table-cell">{o.function}()</TableCell>
                <TableCell className="hidden text-muted-foreground xl:table-cell">{o.tag}</TableCell>
                <TableCell className="hidden sm:table-cell">
                  {o.secured && o.schemes.length ? (
                    <span className="inline-flex flex-wrap gap-1">
                      {o.schemes.map((s) => (
                        <Chip key={s} tone="info" className="font-mono text-[10.5px]">
                          {s}
                        </Chip>
                      ))}
                    </span>
                  ) : (
                    <span className="text-[12px] text-faint">Public</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
