"use client";

import { FileWarningIcon, PlayIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { CopyButton } from "@/components/copy-button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/features/auth/api";
import { GenerateDialog } from "@/features/generations/components/generate-dialog";
import { useProject } from "@/features/projects/api";
import { ApiError } from "@/lib/api/errors";
import { emailName, formatBytes, formatDateTime, shortSha } from "@/lib/format";

import { useSpec } from "../api";
import { LintReport, SeverityCounts } from "./lint-report";
import { OperationsTable } from "./operations-table";
import { SpecChangesView } from "./spec-changes";
import { ModelsCard, SchemesCard, TagsCard } from "./spec-facts";
import { SpecSource } from "./spec-source";

function Crumbs({ slug, name }: { slug: string; name?: string }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted-foreground">
      <Link href="/projects" className="hover:text-foreground">Projects</Link>
      <span aria-hidden>/</span>
      <Link href={`/projects/${slug}`} className="hover:text-foreground">{name ?? slug}</Link>
      <span aria-hidden>/</span>
      <Link href={`/projects/${slug}?tab=specs`} className="hover:text-foreground">Specs</Link>
    </nav>
  );
}

export function SpecScreen({ slug, number }: { slug: string; number: number }) {
  const { canWrite } = usePermissions();
  const project = useProject(slug);
  const q = useSpec(slug, number);
  const [generating, setGenerating] = React.useState(false);

  if (!Number.isInteger(number) || number < 1 || (q.error instanceof ApiError && q.error.status === 404)) {
    return (
      <>
        <PageHeader eyebrow={<Crumbs slug={slug} name={project.data?.name} />} title="Spec version not found" />
        <Surface>
          <EmptyState
            icon={FileWarningIcon}
            title={`There is no version ${Number.isFinite(number) ? number : ""} in this project`}
            description="It may never have existed, or the project was deleted. The version list shows every stored version."
            action={<Button size="sm" variant="secondary" nativeButton={false} render={<Link href={`/projects/${slug}?tab=specs`} />}>See all versions</Button>}
          />
        </Surface>
      </>
    );
  }

  if (q.isPending) {
    return (
      <div className="space-y-4" aria-busy>
        <Skeleton className="h-16 w-2/3" />
        <Skeleton className="h-72 rounded-2xl" />
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
  const s = q.data;

  return (
    <>
      <PageHeader
        eyebrow={<Crumbs slug={slug} name={project.data?.name} />}
        title={
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span>v{s.number}: {s.title}</span>
            <span className="text-[15px] font-medium text-muted-foreground">{s.api_version}</span>
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>OpenAPI {s.openapi_version}</span>
            <span className="font-mono">{s.filename}{s.bundle ? " (zip)" : ""}</span>
            <span>{formatBytes(s.size_bytes)}</span>
            <span className="inline-flex items-center gap-1">
              <span className="font-mono" title={s.sha256}>sha256 {shortSha(s.sha256)}</span>
              <CopyButton value={s.sha256} iconOnly label="Copy the full sha256" variant="ghost" />
            </span>
            <span>
              {emailName(s.created_by_email)}, {formatDateTime(s.created_at)}
            </span>
          </span>
        }
        actions={
          canWrite && project.data ? (
            <Button onClick={() => setGenerating(true)}>
              <PlayIcon />
              Generate from this version
            </Button>
          ) : undefined
        }
      />
      {s.note && <p className="-mt-3 mb-5 rounded-xl bg-muted/60 px-4 py-2.5 text-[13px]">{s.note}</p>}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Surface>
            <SurfaceHeader
              title="Lint report"
              description="What APIForge can and cannot express exactly, with the JSON pointer of each finding."
              action={<SeverityCounts report={s.report} />}
            />
            <div className="px-5 pb-5">
              <LintReport report={s.report} />
            </div>
          </Surface>
          <Surface className="overflow-hidden">
            <SurfaceHeader title="Operations" description="Each operation becomes a route in app/generated/ that calls the handler function you own in app/handlers/." />
            <OperationsTable operations={s.operation_list} />
          </Surface>
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <Surface>
            <SurfaceHeader title={s.changes.first ? "First version" : `Changes from version ${s.number - 1}`} />
            <SpecChangesView changes={s.changes} />
          </Surface>
          <SchemesCard schemes={s.schemes} />
          <TagsCard tags={s.tags} />
          <ModelsCard models={s.model_names} />
        </div>
      </div>
      <Surface className="mt-4">
        <SurfaceHeader title="Source" description="Exactly as uploaded. Read only: upload a new version to change it." />
        <SpecSource slug={slug} number={s.number} />
      </Surface>
      {project.data && <GenerateDialog project={project.data} open={generating} onOpenChange={setGenerating} initialSpec={s.number} />}
    </>
  );
}
