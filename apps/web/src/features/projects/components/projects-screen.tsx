"use client";

import { BookOpenIcon, FolderKanbanIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { GenerationChip } from "@/components/status-chip";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePermissions } from "@/features/auth/api";
import { formatRelative, plural } from "@/lib/format";

import { useProjects } from "../api";
import { ExamplesDialog } from "./examples-dialog";
import { NewProjectDialog } from "./new-project-dialog";

/** Errors and warnings of a lint report as two small chips, or a quiet "Clean". */
export function ReportCounts({ errors, warnings }: { errors: number; warnings: number }) {
  if (!errors && !warnings) return <Chip tone="success">Clean</Chip>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {errors > 0 && <Chip tone="danger">{plural(errors, "error")}</Chip>}
      {warnings > 0 && <Chip tone="warning">{plural(warnings, "warning")}</Chip>}
    </span>
  );
}

export function ProjectsScreen() {
  const { canWrite } = usePermissions();
  const q = useProjects();
  const [newOpen, setNewOpen] = React.useState(false);
  const [examplesOpen, setExamplesOpen] = React.useState(false);

  return (
    <>
      <PageHeader
        title="Projects"
        description="One project per API: its spec versions, each linted and compared with the last, and the FastAPI projects generated from them."
        actions={
          canWrite && (
            <>
              <Button variant="secondary" onClick={() => setExamplesOpen(true)}>
                <BookOpenIcon />
                Start from an example
              </Button>
              <Button onClick={() => setNewOpen(true)}>
                <PlusIcon />
                New project
              </Button>
            </>
          )
        }
      />
      <Surface className="overflow-hidden">
        {q.isPending ? (
          <div className="pt-3">
            <TableSkeleton rows={5} cols={5} />
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !q.data.length ? (
          <EmptyState
            icon={FolderKanbanIcon}
            title="No projects yet"
            description={
              canWrite
                ? "A project turns an OpenAPI spec into a FastAPI project you can run and keep. The quickest start is one of the bundled examples."
                : "Projects appear here once an admin creates one. Meanwhile, paste any spec into the playground to see its lint report."
            }
            action={
              canWrite ? (
                <Button size="sm" onClick={() => setExamplesOpen(true)}>
                  <BookOpenIcon />
                  Start from an example
                </Button>
              ) : (
                <Button size="sm" variant="secondary" nativeButton={false} render={<Link href="/playground" />}>
                  Open the playground
                </Button>
              )
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead className="hidden md:table-cell">Latest spec</TableHead>
                <TableHead className="hidden lg:table-cell">Lint report</TableHead>
                <TableHead>Latest generation</TableHead>
                <TableHead className="hidden sm:table-cell">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {q.data.map((p) => (
                <TableRow key={p.id} className="relative">
                  <TableCell className="max-w-[320px]">
                    <Link
                      href={`/projects/${p.slug}`}
                      className="font-medium text-foreground outline-none after:absolute after:inset-0 hover:text-primary focus-visible:underline"
                    >
                      {p.name}
                    </Link>
                    <div className="line-clamp-2 text-[12px] text-muted-foreground sm:line-clamp-none sm:truncate">{p.description || <span className="font-mono">{p.slug}</span>}</div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    {p.latest_spec ? (
                      <>
                        <div className="truncate">
                          {p.latest_spec.title} <span className="text-muted-foreground">{p.latest_spec.api_version}</span>
                        </div>
                        <div className="text-[12px] text-muted-foreground tabular">
                          v{p.latest_spec.number}, {plural(p.latest_spec.operations, "operation")}
                        </div>
                      </>
                    ) : (
                      <span className="text-[12.5px] text-faint">No spec uploaded</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    {p.latest_spec ? <ReportCounts errors={p.latest_spec.errors} warnings={p.latest_spec.warnings} /> : <span className="text-faint">n/a</span>}
                  </TableCell>
                  <TableCell>
                    {p.latest_generation ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="relative z-10">
                          <GenerationChip value={p.latest_generation.status} />
                        </span>
                        <span className="text-[12px] text-muted-foreground tabular">#{p.latest_generation.number}</span>
                      </div>
                    ) : (
                      <span className="text-[12.5px] text-faint">Not generated yet</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap text-muted-foreground sm:table-cell">{formatRelative(p.updated_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Surface>
      {!canWrite && (
        <p className="mt-3 text-xs text-muted-foreground">You have read access: owners and admins create projects, upload specs and generate.</p>
      )}
      <NewProjectDialog open={newOpen} onOpenChange={setNewOpen} />
      <ExamplesDialog open={examplesOpen} onOpenChange={setExamplesOpen} />
    </>
  );
}
