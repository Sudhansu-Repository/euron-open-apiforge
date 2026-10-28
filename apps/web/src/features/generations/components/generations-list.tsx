"use client";

import { PackageIcon, PlayIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { GenerationChip, OptionChips } from "@/components/status-chip";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { emailName, formatBytes, formatDuration, formatNumber, formatRelative } from "@/lib/format";

import { useGenerations } from "../api";

export function GenerationsList({
  slug,
  canWrite,
  hasSpecs,
  onGenerate,
  onUpload,
}: {
  slug: string;
  canWrite: boolean;
  hasSpecs: boolean;
  onGenerate: () => void;
  onUpload: () => void;
}) {
  const q = useGenerations(slug);
  if (q.isPending) return <div className="pt-3"><TableSkeleton rows={4} cols={6} /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data.length) {
    return (
      <EmptyState
        icon={PackageIcon}
        title="Nothing generated yet"
        description={
          hasSpecs
            ? "A generation turns a spec version into a runnable FastAPI project: routers, models, tests and the handler stubs you fill in."
            : "Upload a spec first. Every generation starts from a stored, linted spec version."
        }
        action={
          canWrite ? (
            hasSpecs ? (
              <Button size="sm" onClick={onGenerate}>
                <PlayIcon />
                Generate
              </Button>
            ) : (
              <Button size="sm" onClick={onUpload}>
                Upload a spec
              </Button>
            )
          ) : undefined
        }
      />
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Generation</TableHead>
          <TableHead className="hidden sm:table-cell">Spec</TableHead>
          <TableHead className="hidden lg:table-cell">Options</TableHead>
          <TableHead className="hidden md:table-cell text-right">Files</TableHead>
          <TableHead className="hidden md:table-cell text-right">Archive</TableHead>
          <TableHead className="hidden md:table-cell text-right">Duration</TableHead>
          <TableHead className="hidden xl:table-cell">By</TableHead>
          <TableHead className="text-right">When</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {q.data.map((g) => (
          <TableRow key={g.id} className="relative">
            <TableCell>
              <div className="flex items-center gap-2.5">
                <Link
                  href={`/projects/${slug}/generations/${g.number}`}
                  className="font-medium tabular outline-none after:absolute after:inset-0 hover:text-primary focus-visible:underline"
                >
                  #{g.number}
                </Link>
                <span className="relative z-10">
                  <GenerationChip value={g.status} />
                </span>
              </div>
            </TableCell>
            <TableCell className="hidden sm:table-cell">
              <Link href={`/projects/${slug}/specs/${g.spec_number}`} className="relative z-10 hover:text-primary">
                v{g.spec_number}
              </Link>{" "}
              <span className="text-muted-foreground">{g.spec_title}</span>
            </TableCell>
            <TableCell className="hidden lg:table-cell">
              <OptionChips options={g.options} />
            </TableCell>
            <TableCell className="hidden text-right tabular md:table-cell">{g.file_count == null ? <span className="text-faint">n/a</span> : formatNumber(g.file_count)}</TableCell>
            <TableCell className="hidden text-right tabular md:table-cell">{g.archive_bytes == null ? <span className="text-faint">n/a</span> : formatBytes(g.archive_bytes)}</TableCell>
            <TableCell className="hidden text-right tabular md:table-cell">{g.duration_ms == null ? <span className="text-faint">n/a</span> : formatDuration(g.duration_ms)}</TableCell>
            <TableCell className="hidden text-muted-foreground xl:table-cell">{emailName(g.created_by_email)}</TableCell>
            <TableCell className="text-right whitespace-nowrap text-muted-foreground">{formatRelative(g.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
