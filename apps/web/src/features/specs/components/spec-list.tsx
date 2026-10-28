"use client";

import { FileCode2Icon, UploadIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ReportCounts } from "@/features/projects/components/projects-screen";
import { emailName, formatRelative } from "@/lib/format";
import { changeCounts } from "@/lib/spec-changes";

import { useSpecs } from "../api";
import { ChangeCounts } from "./spec-changes";

export function SpecList({ slug, canWrite, onUpload }: { slug: string; canWrite: boolean; onUpload: () => void }) {
  const q = useSpecs(slug);
  if (q.isPending) return <div className="pt-3"><TableSkeleton rows={4} cols={6} /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data.length) {
    return (
      <EmptyState
        icon={FileCode2Icon}
        title="No spec uploaded yet"
        description="Upload an OpenAPI 3.0 or 3.1 document (YAML, JSON, or a zip with relative $refs). It is linted right away, so you see what will generate before anything is built."
        action={
          canWrite ? (
            <Button size="sm" onClick={onUpload}>
              <UploadIcon />
              Upload a spec
            </Button>
          ) : undefined
        }
      />
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Version</TableHead>
          <TableHead className="hidden md:table-cell text-right">Operations</TableHead>
          <TableHead className="hidden lg:table-cell">Report</TableHead>
          <TableHead className="hidden sm:table-cell">Changes</TableHead>
          <TableHead className="hidden xl:table-cell">Note</TableHead>
          <TableHead className="text-right">Uploaded</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {q.data.map((s, i) => (
          <TableRow key={s.id} className="relative">
            <TableCell>
              <div className="flex items-center gap-2">
                <Link
                  href={`/projects/${slug}/specs/${s.number}`}
                  className="font-medium tabular outline-none after:absolute after:inset-0 hover:text-primary focus-visible:underline"
                >
                  v{s.number}
                </Link>
                {i === 0 && <Chip tone="primary">Latest</Chip>}
              </div>
              <div className="text-[12px] text-muted-foreground">
                {s.title} {s.api_version} <span className="text-faint">OpenAPI {s.openapi_version}</span>
              </div>
            </TableCell>
            <TableCell className="hidden text-right tabular md:table-cell">{s.operations}</TableCell>
            <TableCell className="hidden lg:table-cell">
              <ReportCounts errors={s.errors} warnings={s.warnings} />
            </TableCell>
            <TableCell className="hidden sm:table-cell">
              {s.changes.first ? <span className="text-[12px] text-muted-foreground">First version</span> : <ChangeCounts {...changeCounts(s.changes)} />}
            </TableCell>
            <TableCell className="hidden max-w-[260px] truncate text-muted-foreground xl:table-cell">{s.note || <span className="text-faint">No note</span>}</TableCell>
            <TableCell className="text-right whitespace-nowrap">
              <div className="text-muted-foreground">{formatRelative(s.created_at)}</div>
              <div className="text-[11.5px] text-faint">{emailName(s.created_by_email)}</div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
