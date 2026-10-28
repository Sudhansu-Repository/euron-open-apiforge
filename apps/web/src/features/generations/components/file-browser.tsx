"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { CodeViewer } from "@/components/code-viewer";
import { ErrorState } from "@/components/error-state";
import { OwnerChip } from "@/components/status-chip";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Skeleton } from "@/components/ui/skeleton";
import type { GeneratedFile } from "@/lib/api/types";
import { ancestorFolders, buildFileTree, defaultFile, ownerCounts } from "@/lib/file-tree";
import { formatBytes } from "@/lib/format";

import { useGenerationFile } from "../api";
import { FileTree } from "./file-tree";

/** Tree on the left, the selected file on the right; the selection lives in ?file=. */
export function FileBrowser({ slug, number, files }: { slug: string; number: number; files: GeneratedFile[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tree = React.useMemo(() => buildFileTree(files), [files]);
  const requested = params.get("file");
  const known = requested && files.some((f) => f.path === requested) ? requested : null;
  const selected = known ?? defaultFile(files);
  const [open, setOpen] = React.useState<Set<string>>(() => new Set(selected ? ancestorFolders(selected) : []));
  const counts = ownerCounts(files);
  const entry = files.find((f) => f.path === selected);
  const q = useGenerationFile(slug, number, selected);

  React.useEffect(() => {
    if (!selected) return;
    setOpen((prev) => {
      const missing = ancestorFolders(selected).filter((a) => !prev.has(a));
      return missing.length ? new Set([...prev, ...missing]) : prev;
    });
  }, [selected]);

  function select(path: string) {
    const next = new URLSearchParams(params.toString());
    next.set("file", path);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function toggle(path: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader
        title="Files"
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1.5">
              <OwnerChip value="generated" /> {counts.generated} rewritten on every generation
            </span>
            <span className="inline-flex items-center gap-1.5">
              <OwnerChip value="user" /> {counts.user} created once, never overwritten
            </span>
          </span>
        }
      />
      {requested && !known && (
        <p className="mx-5 mb-3 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning">
          This generation has no file <span className="font-mono">{requested}</span>; showing {selected} instead.
        </p>
      )}
      <div className="grid gap-3 px-3 pb-3 md:grid-cols-[280px_minmax(0,1fr)]">
        <div className="max-h-[42vh] overflow-y-auto rounded-xl bg-muted/50 p-1.5 md:max-h-[72vh]">
          <FileTree nodes={tree} open={open} onToggle={toggle} selected={selected} onSelect={select} />
        </div>
        <div className="min-w-0">
          {!selected ? (
            <p className="p-6 text-[13px] text-muted-foreground">This archive has no files.</p>
          ) : q.isPending ? (
            <Skeleton className="h-[50vh] rounded-xl" />
          ) : q.isError ? (
            <div className="rounded-xl bg-muted/50">
              <ErrorState error={q.error} onRetry={() => void q.refetch()} title={`Could not open ${selected}`} compact />
            </div>
          ) : (
            <CodeViewer
              code={q.data.content}
              language={q.data.language}
              title={
                <span className="flex items-center gap-2">
                  <span className="truncate">{q.data.path}</span>
                  {entry && <span className="shrink-0 text-code-gutter">{formatBytes(entry.bytes)}</span>}
                </span>
              }
              actions={<OwnerChip value={q.data.owner} />}
              maxHeight="66vh"
            />
          )}
        </div>
      </div>
    </Surface>
  );
}
