"use client";

import { ActivityIcon, BookOpenIcon, FileCode2Icon, FlaskConicalIcon, FolderKanbanIcon, HourglassIcon, PackageIcon, RouteIcon, TimerIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { KpiTile } from "@/components/kpi-tile";
import { PageHeader } from "@/components/page-header";
import { GenerationChip } from "@/components/status-chip";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePermissions } from "@/features/auth/api";
import { ExamplesDialog } from "@/features/projects/components/examples-dialog";
import { ChangeCounts } from "@/features/specs/components/spec-changes";
import { formatDuration, formatNumber, formatRelative, plural } from "@/lib/format";

import { useOverview } from "../api";

export function OverviewScreen() {
  const { user, canWrite } = usePermissions();
  const q = useOverview();
  const [examplesOpen, setExamplesOpen] = React.useState(false);
  const d = q.data;
  const loading = q.isPending;

  const header = (
    <PageHeader
      title={user ? `Welcome back, ${user.name.split(" ")[0]}` : "Overview"}
      description="OpenAPI specs in, FastAPI projects out: what was uploaded, what was generated, and how it went."
      actions={
        <Button variant="secondary" nativeButton={false} render={<Link href="/playground" />}>
          <FlaskConicalIcon />
          Lint a spec
        </Button>
      }
    />
  );

  if (q.isError && !d) {
    return (
      <>
        {header}
        <Surface>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} title="Could not load the overview" />
        </Surface>
      </>
    );
  }

  if (d && d.projects === 0) {
    return (
      <>
        {header}
        <Surface>
          <EmptyState
            icon={FolderKanbanIcon}
            title="Forge your first API"
            description={
              canWrite
                ? "Pick one of the bundled example specs: it becomes a project with the spec as version 1, linted and ready to generate a FastAPI project you can run and keep."
                : "There are no projects yet, and creating one needs an admin. You can still paste any spec into the playground to see its lint report."
            }
            action={
              canWrite ? (
                <Button onClick={() => setExamplesOpen(true)}>
                  <BookOpenIcon />
                  Start from an example
                </Button>
              ) : (
                <Button variant="secondary" nativeButton={false} render={<Link href="/playground" />}>
                  Open the playground
                </Button>
              )
            }
          />
        </Surface>
        <ExamplesDialog open={examplesOpen} onOpenChange={setExamplesOpen} />
      </>
    );
  }

  return (
    <>
      {header}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <KpiTile
          label="Projects"
          icon={FolderKanbanIcon}
          loading={loading}
          value={formatNumber(d?.projects)}
          sub={d && <span>{plural(d.spec_versions, "spec version")}</span>}
        />
        <KpiTile
          label="Operations described"
          icon={RouteIcon}
          accent="info"
          loading={loading}
          value={formatNumber(d?.operations)}
          hint="Operations across the specs APIForge holds. Each one becomes a route and a handler function."
          sub={d && <span>{plural(d.generations, "generation")} all time</span>}
        />
        <KpiTile
          label="Generations, 7 days"
          icon={PackageIcon}
          loading={loading}
          value={formatNumber(d?.generations_7d)}
          sub={
            d && (
              <>
                <Chip tone="success">{d.succeeded_7d} succeeded</Chip>
                <Chip tone={d.failed_7d ? "danger" : "neutral"}>{d.failed_7d} failed</Chip>
              </>
            )
          }
        />
        <KpiTile
          label="Median generation time"
          icon={TimerIcon}
          accent="info"
          loading={loading}
          value={d?.median_duration_ms == null ? <span className="text-faint">n/a</span> : formatDuration(d.median_duration_ms)}
          hint="From queued to the archive being stored, across finished generations."
          sub={d && <span>{d.median_duration_ms == null ? "No finished generations yet" : "Render, format and archive"}</span>}
        />
        <KpiTile
          label="Queued now"
          icon={HourglassIcon}
          accent={d?.queued ? "warning" : "primary"}
          loading={loading}
          value={formatNumber(d?.queued)}
          sub={d && <span>{d.queued ? "Workers are on it" : "Workers are idle"}</span>}
        />
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Surface className="overflow-hidden">
          <SurfaceHeader
            title={<><ActivityIcon className="size-4 text-subtle" />Recent generations</>}
            description="Newest first. Open one to browse its files or download the zip."
          />
          {loading ? (
            <TableSkeleton rows={5} cols={4} />
          ) : !d?.recent_generations.length ? (
            <EmptyState
              compact
              icon={PackageIcon}
              title="Nothing generated yet"
              description="Open a project and press Generate: a worker builds a runnable FastAPI project from its latest spec."
              action={<Button size="sm" variant="secondary" nativeButton={false} render={<Link href="/projects" />}>Go to projects</Button>}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Project</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="hidden sm:table-cell">Spec</TableHead>
                  <TableHead className="hidden md:table-cell text-right">Duration</TableHead>
                  <TableHead className="text-right">When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.recent_generations.map((g) => (
                  <TableRow key={g.id} className="relative">
                    <TableCell>
                      <Link
                        href={`/projects/${g.project_slug}/generations/${g.number}`}
                        className="font-medium outline-none after:absolute after:inset-0 hover:text-primary focus-visible:underline"
                      >
                        {g.project_slug}
                      </Link>
                      <span className="ml-1.5 text-muted-foreground tabular">#{g.number}</span>
                    </TableCell>
                    <TableCell>
                      <span className="relative z-10">
                        <GenerationChip value={g.status} />
                      </span>
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground sm:table-cell">v{g.spec_number}</TableCell>
                    <TableCell className="hidden text-right tabular md:table-cell">{g.duration_ms == null ? <span className="text-faint">n/a</span> : formatDuration(g.duration_ms)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap text-muted-foreground">{formatRelative(g.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Surface>

        <Surface className="overflow-hidden">
          <SurfaceHeader
            title={<><FileCode2Icon className="size-4 text-subtle" />Recent spec changes</>}
            description="Operations added (+), removed (-) and changed (~) by each upload."
          />
          {loading ? (
            <TableSkeleton rows={5} cols={3} />
          ) : !d?.recent_specs.length ? (
            <EmptyState
              compact
              icon={FileCode2Icon}
              title="No spec uploaded yet"
              description="Upload a spec to a project; each version is linted and compared with the one before."
              action={<Button size="sm" variant="secondary" nativeButton={false} render={<Link href="/projects" />}>Go to projects</Button>}
            />
          ) : (
            <ul className="flex flex-col px-3 pb-3">
              {d.recent_specs.map((s) => (
                <li key={`${s.project_slug}-${s.number}`}>
                  <Link
                    href={`/projects/${s.project_slug}/specs/${s.number}`}
                    className="flex items-center gap-3 rounded-lg px-2 py-2.5 outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium">
                        {s.project_name} <span className="text-muted-foreground tabular">v{s.number}</span>
                      </div>
                      <div className="truncate text-[12px] text-muted-foreground">
                        {s.title} {s.api_version}, {formatRelative(s.created_at)}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <ChangeCounts added={s.added} removed={s.removed} changed={s.changed} />
                      {(s.errors > 0 || s.warnings > 0) && (
                        <span className="flex gap-1">
                          {s.errors > 0 && <Chip tone="danger">{s.errors} err</Chip>}
                          {s.warnings > 0 && <Chip tone="warning">{s.warnings} warn</Chip>}
                        </span>
                      )}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Surface>
      </div>
    </>
  );
}
