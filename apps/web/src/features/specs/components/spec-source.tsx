"use client";

import { FileArchiveIcon } from "lucide-react";

import { CodeViewer, languageFromFilename } from "@/components/code-viewer";
import { ErrorState } from "@/components/error-state";
import { Skeleton } from "@/components/ui/skeleton";

import { useSpecContent } from "../api";

/** The stored spec text, read only. For a zip bundle: the root file plus the bundle's file list. */
export function SpecSource({ slug, number }: { slug: string; number: number }) {
  const q = useSpecContent(slug, number);
  if (q.isPending) return <Skeleton className="mx-5 mb-5 h-64 rounded-xl" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />;
  const files = q.data.files ?? [];
  return (
    <div className="space-y-3 px-5 pb-5">
      {files.length > 0 && (
        <div className="rounded-xl bg-muted/60 px-4 py-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-medium">
            <FileArchiveIcon className="size-4 text-subtle" />
            Zip bundle with {files.length} files; the root document is shown below
          </div>
          <ul className="grid gap-x-4 gap-y-0.5 font-mono text-[12px] text-muted-foreground sm:grid-cols-2">
            {files.map((f) => (
              <li key={f} className={f === q.data.filename ? "font-semibold text-foreground" : undefined}>
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}
      <CodeViewer code={q.data.content} language={languageFromFilename(q.data.filename)} title={q.data.filename} maxHeight="60vh" />
    </div>
  );
}
