"use client";

import { FolderSearchIcon, PlayIcon, UploadIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Surface } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePermissions } from "@/features/auth/api";
import { GenerateDialog } from "@/features/generations/components/generate-dialog";
import { GenerationsList } from "@/features/generations/components/generations-list";
import { SpecList } from "@/features/specs/components/spec-list";
import { UploadSpecDialog } from "@/features/specs/components/upload-spec-dialog";
import { ApiError } from "@/lib/api/errors";
import { plural } from "@/lib/format";

import { useProject } from "../api";
import { ProjectSettings } from "./project-settings";

const TABS = ["specs", "generations", "settings"] as const;
type Tab = (typeof TABS)[number];

export function isTab(v: unknown): v is Tab {
  return typeof v === "string" && (TABS as readonly string[]).includes(v);
}

export function ProjectScreen({ slug }: { slug: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { canWrite } = usePermissions();
  const q = useProject(slug);
  const tabParam = params.get("tab");
  const tab: Tab = isTab(tabParam) ? tabParam : "specs";
  const [uploading, setUploading] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [initialSpec, setInitialSpec] = React.useState<number | null>(null);

  // /projects/x?upload=1 (right after creating a project) opens the upload dialog once.
  React.useEffect(() => {
    if (params.get("upload") === "1" && canWrite) {
      setUploading(true);
      router.replace(pathname);
    }
  }, [params, canWrite, router, pathname]);

  function setTab(next: unknown) {
    if (!isTab(next)) return;
    router.replace(next === "specs" ? pathname : `${pathname}?tab=${next}`, { scroll: false });
  }

  function generate(spec: number | null = null) {
    setInitialSpec(spec);
    setGenerating(true);
  }

  if (q.isPending) {
    return (
      <div className="space-y-4" aria-busy>
        <Skeleton className="h-14 w-1/2" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }
  if (q.isError) {
    const missing = q.error instanceof ApiError && q.error.status === 404;
    return (
      <>
        <PageHeader title={missing ? "Project not found" : "Project"} />
        <Surface>
          {missing ? (
            <EmptyState
              icon={FolderSearchIcon}
              title={`No project at "${slug}"`}
              description="It may have been deleted. A project keeps its address when it is renamed, so an old link still works while the project exists."
              action={<Button size="sm" variant="secondary" nativeButton={false} render={<Link href="/projects" />}>All projects</Button>}
            />
          ) : (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          )}
        </Surface>
      </>
    );
  }
  const p = q.data;
  const hasSpecs = (p.spec_count ?? 0) > 0;

  return (
    <>
      <PageHeader
        eyebrow={
          <nav aria-label="Breadcrumb" className="text-[12.5px] text-muted-foreground">
            <Link href="/projects" className="hover:text-foreground">Projects</Link>
          </nav>
        }
        title={p.name}
        description={
          <>
            {p.description && <span className="block">{p.description}</span>}
            <span className="text-faint">
              <span className="font-mono">{p.slug}</span>, {plural(p.spec_count ?? 0, "spec version")}, {plural(p.generation_count ?? 0, "generation")}
            </span>
          </>
        }
        actions={
          canWrite && (
            <>
              <Button variant="secondary" onClick={() => setUploading(true)}>
                <UploadIcon />
                Upload spec
              </Button>
              <Button onClick={() => generate()} disabled={!hasSpecs} title={hasSpecs ? undefined : "Upload a spec first"}>
                <PlayIcon />
                Generate
              </Button>
            </>
          )
        }
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="specs">Specs</TabsTrigger>
          <TabsTrigger value="generations">Generations</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="specs">
          <Surface className="overflow-hidden pt-2">
            <SpecList slug={slug} canWrite={canWrite} onUpload={() => setUploading(true)} />
          </Surface>
        </TabsContent>
        <TabsContent value="generations">
          <Surface className="overflow-hidden pt-2">
            <GenerationsList slug={slug} canWrite={canWrite} hasSpecs={hasSpecs} onGenerate={() => generate()} onUpload={() => setUploading(true)} />
          </Surface>
        </TabsContent>
        <TabsContent value="settings">
          <ProjectSettings project={p} canWrite={canWrite} />
        </TabsContent>
      </Tabs>
      {!canWrite && <p className="mt-3 text-xs text-muted-foreground">You have read access: owners and admins upload specs and generate.</p>}
      <UploadSpecDialog slug={slug} open={uploading} onOpenChange={setUploading} onGenerate={(n) => generate(n)} />
      <GenerateDialog project={p} open={generating} onOpenChange={setGenerating} initialSpec={initialSpec} />
    </>
  );
}
