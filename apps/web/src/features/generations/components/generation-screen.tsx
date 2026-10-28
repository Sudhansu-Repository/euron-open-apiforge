"use client";

import { CircleAlertIcon, DownloadIcon, Loader2Icon, PackageSearchIcon, RotateCwIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { CopyButton } from "@/components/copy-button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { GenerationChip, OptionChips } from "@/components/status-chip";
import { Surface } from "@/components/surface";
import { Button, buttonVariants } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/features/auth/api";
import { useProject } from "@/features/projects/api";
import { ApiError } from "@/lib/api/errors";
import { isActiveGeneration } from "@/lib/chips";
import { ownerCounts } from "@/lib/file-tree";
import { emailName, formatBytes, formatDateTime, formatDuration, shortSha } from "@/lib/format";

import { archiveUrl, useGeneration } from "../api";
import { FileBrowser } from "./file-browser";
import { GenerateDialog } from "./generate-dialog";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/60 px-3 py-2">
      <dt className="text-[11.5px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px] font-medium">{children}</dd>
    </div>
  );
}

function Crumbs({ slug, name }: { slug: string; name?: string }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted-foreground">
      <Link href="/projects" className="hover:text-foreground">Projects</Link>
      <span aria-hidden>/</span>
      <Link href={`/projects/${slug}`} className="hover:text-foreground">{name ?? slug}</Link>
      <span aria-hidden>/</span>
      <Link href={`/projects/${slug}?tab=generations`} className="hover:text-foreground">Generations</Link>
    </nav>
  );
}

export function GenerationScreen({ slug, number }: { slug: string; number: number }) {
  const { canWrite } = usePermissions();
  const project = useProject(slug);
  const q = useGeneration(slug, number);
  const [again, setAgain] = React.useState(false);

  if (!Number.isInteger(number) || number < 1 || (q.error instanceof ApiError && q.error.status === 404)) {
    return (
      <>
        <PageHeader eyebrow={<Crumbs slug={slug} name={project.data?.name} />} title="Generation not found" />
        <Surface>
          <EmptyState
            icon={PackageSearchIcon}
            title="No such generation in this project"
            description="The number may be mistyped, or the project was deleted. The generations list shows every run."
            action={<Button size="sm" variant="secondary" nativeButton={false} render={<Link href={`/projects/${slug}?tab=generations`} />}>All generations</Button>}
          />
        </Surface>
      </>
    );
  }
  if (q.isPending) {
    return (
      <div className="space-y-4" aria-busy>
        <Skeleton className="h-14 w-1/2" />
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-96 rounded-2xl" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <Surface>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Surface>
    );
  }

  const g = q.data;
  const active = isActiveGeneration(g.status);
  const counts = ownerCounts(g.files);

  return (
    <>
      <PageHeader
        eyebrow={<Crumbs slug={slug} name={project.data?.name} />}
        title={
          <span className="flex flex-wrap items-center gap-3">
            Generation #{g.number}
            <GenerationChip value={g.status} />
          </span>
        }
        description={
          <>
            From{" "}
            <Link href={`/projects/${slug}/specs/${g.spec_number}`} className="font-medium text-foreground hover:text-primary">
              spec v{g.spec_number}: {g.spec_title}
            </Link>
            , queued by {emailName(g.created_by_email)} on {formatDateTime(g.created_at)}.
          </>
        }
        actions={
          <>
            {canWrite && project.data && !active && (
              <Button variant="secondary" onClick={() => setAgain(true)}>
                <RotateCwIcon />
                Generate again
              </Button>
            )}
            {g.status === "succeeded" && (
              <a href={archiveUrl(slug, g.number)} download className={buttonVariants()}>
                <DownloadIcon />
                Download zip
              </a>
            )}
          </>
        }
      />

      <Surface className="mb-4 p-4">
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Fact label="Options">
            <OptionChips options={g.options} />
          </Fact>
          <Fact label="Files">
            {g.file_count == null ? <span className="text-faint">n/a</span> : `${g.file_count} (${counts.user} yours)`}
          </Fact>
          <Fact label="Archive size">{g.archive_bytes == null ? <span className="text-faint">n/a</span> : formatBytes(g.archive_bytes)}</Fact>
          <Fact label="Duration">{g.duration_ms == null ? <span className="text-faint">{active ? "In progress" : "n/a"}</span> : formatDuration(g.duration_ms)}</Fact>
          <Fact label="Archive sha256">
            {g.archive_sha256 ? (
              <span className="inline-flex items-center gap-1">
                <span className="font-mono" title={g.archive_sha256}>{shortSha(g.archive_sha256)}</span>
                <CopyButton value={g.archive_sha256} iconOnly label="Copy the full sha256" variant="ghost" />
              </span>
            ) : (
              <span className="text-faint">n/a</span>
            )}
          </Fact>
          <Fact label="Report errors accepted">{g.accept_report ? <Chip tone="warning">Yes</Chip> : "No"}</Fact>
        </dl>
        {g.resources && g.resources.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted-foreground">
            <span>Collection resources implemented with --db:</span>
            {g.resources.map((r) => (
              <Chip key={r} tone="primary" className="font-mono">
                {r}
              </Chip>
            ))}
          </div>
        )}
      </Surface>

      {active ? (
        <Surface>
          <div className="flex flex-col items-center px-6 py-14 text-center" aria-live="polite">
            <Loader2Icon className="mb-3 size-7 animate-spin text-primary" />
            <h2 className="text-sm font-semibold">{g.status === "queued" ? "Waiting for a worker" : "Building the project"}</h2>
            <p className="mt-1 max-w-md text-[13px] text-muted-foreground">
              {g.status === "queued"
                ? "The generation is queued and starts within a few seconds."
                : "Rendering the code, then running the generated tests against it."}{" "}
              This page updates by itself; the files appear here when it is done.
            </p>
          </div>
        </Surface>
      ) : g.status === "failed" ? (
        <Surface>
          <div role="alert" className="flex flex-col gap-3 px-5 py-5 sm:flex-row sm:items-start">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-danger-soft text-danger">
              <CircleAlertIcon className="size-5" />
            </span>
            <div className="min-w-0">
              <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                The generation failed
                {g.error_code && <Chip tone="danger" className="font-mono">{g.error_code}</Chip>}
              </h2>
              <p className="mt-1 text-[13px] break-words whitespace-pre-wrap text-foreground/85">{g.error || "No error message was recorded."}</p>
              <p className="mt-2 text-[12.5px] text-muted-foreground">
                {g.error_code === "generation_timeout"
                  ? "It took longer than the configured timeout. Try again; a very large spec may need a higher GENERATION_TIMEOUT_S."
                  : g.error_code === "worker_lost"
                    ? "The worker stopped while building. Generate again; it is safe to retry."
                    : "Generate again. If it keeps failing, check the worker logs and the spec's lint report."}
              </p>
            </div>
          </div>
        </Surface>
      ) : g.files.length ? (
        <FileBrowser slug={slug} number={g.number} files={g.files} />
      ) : (
        <Surface>
          <EmptyState
            icon={PackageSearchIcon}
            title="No files recorded"
            description="The archive finished but lists no files. Download the zip to inspect it, or generate again."
            action={<a href={archiveUrl(slug, g.number)} download className={buttonVariants({ size: "sm", variant: "secondary" })}>Download zip</a>}
          />
        </Surface>
      )}
      {project.data && <GenerateDialog project={project.data} open={again} onOpenChange={setAgain} initialSpec={g.spec_number} />}
    </>
  );
}
