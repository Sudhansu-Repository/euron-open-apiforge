"use client";

import { FlaskConicalIcon, FolderPlusIcon, Loader2Icon, PlayIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { usePermissions } from "@/features/auth/api";
import { useExamples, useProjects } from "@/features/projects/api";
import { LintReport, SeverityCounts } from "@/features/specs/components/lint-report";
import { OperationsTable } from "@/features/specs/components/operations-table";
import { ModelsCard, SchemesCard, TagsCard } from "@/features/specs/components/spec-facts";
import { SpecErrorPanel } from "@/features/specs/components/spec-error";
import { errorMessage } from "@/lib/api/errors";
import type { LintOut } from "@/lib/api/types";
import { plural, shortSha } from "@/lib/format";

import { useCreateProjectFromText, useLint, useLoadExampleText, useLoadSpecText } from "../api";
import { STARTER_SPEC } from "../starter";
import { SpecEditor } from "./spec-editor";

function CreateFromSpecDialog({
  open,
  onOpenChange,
  content,
  filename,
  suggested,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  content: string;
  filename: string;
  suggested: string;
}) {
  const router = useRouter();
  const create = useCreateProjectFromText();
  const [name, setName] = React.useState(suggested);
  const [error, setError] = React.useState<unknown>(null);

  React.useEffect(() => {
    if (open) {
      setName(suggested);
      setError(null);
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, suggested]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError(new Error("Give the project a name."));
    setError(null);
    create.mutate(
      { name: name.trim(), content, filename },
      {
        onSuccess: ({ project, uploaded }) => {
          toast.success(`Project "${project.name}" created with this spec as version ${uploaded.spec.number}.`);
          onOpenChange(false);
          router.push(`/projects/${project.slug}/specs/${uploaded.spec.number}`);
        },
        onError: (err) => {
          const slug = (err as { createdSlug?: string }).createdSlug;
          if (slug) {
            toast.error(`The project was created, but the spec was rejected: ${errorMessage(err)}`);
            onOpenChange(false);
            router.push(`/projects/${slug}`);
            return;
          }
          setError(err);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Create a project from this spec</DialogTitle>
          <DialogDescription>The editor&apos;s text becomes version 1. You can generate from it right away.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-3">
            <Field label="Project name" htmlFor="pg-name">
              <Input id="pg-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} autoFocus />
            </Field>
            {error != null && <p role="alert" className="text-xs font-medium text-danger">{errorMessage(error)}</p>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating..." : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Results({ result }: { result: LintOut }) {
  return (
    <div className="flex flex-col gap-4">
      <Surface>
        <SurfaceHeader
          title={
            <span>
              {result.title} <span className="font-medium text-muted-foreground">{result.api_version}</span>
            </span>
          }
          description={
            <span>
              OpenAPI {result.openapi_version}, {plural(result.operations.length, "operation")}, {plural(result.models.length, "model")}, sha256{" "}
              <span className="font-mono">{shortSha(result.sha256)}</span>
            </span>
          }
          action={<SeverityCounts report={result.report} />}
        />
        <div className="px-5 pb-5">
          <LintReport report={result.report} />
        </div>
      </Surface>
      <Surface className="overflow-hidden">
        <SurfaceHeader title="Operations" description="The routes and handler functions a generation would create." />
        <OperationsTable operations={result.operations} />
      </Surface>
      <div className="grid gap-4 lg:grid-cols-3">
        <TagsCard tags={result.tags} />
        <SchemesCard schemes={result.schemes} />
        <ModelsCard models={result.models} />
      </div>
    </div>
  );
}

const STARTER = "starter";
const EXAMPLE = "example:";

export function PlaygroundScreen() {
  const { canWrite } = usePermissions();
  const lint = useLint();
  const load = useLoadSpecText();
  const projects = useProjects();
  const examples = useExamples();
  const loadExample = useLoadExampleText();
  const [content, setContent] = React.useState(STARTER_SPEC);
  const [filename, setFilename] = React.useState("openapi.yaml");
  const [source, setSource] = React.useState(STARTER);
  const [creating, setCreating] = React.useState(false);

  const sources = React.useMemo(
    () => [
      { value: STARTER, label: "Starter: Todo API" },
      ...(examples.data ?? []).map((e) => ({ value: `${EXAMPLE}${e.name}`, label: `Example: ${e.title}` })),
      ...(projects.data ?? [])
        .filter((p) => p.latest_spec)
        .map((p) => ({ value: `${p.slug}:${p.latest_spec!.number}`, label: `${p.name}, v${p.latest_spec!.number}` })),
    ],
    [projects.data, examples.data],
  );

  function run() {
    if (!content.trim()) return;
    const name = filename.trim() || "openapi.yaml";
    lint.mutate({ content, filename: name });
  }

  function pickSource(v: string) {
    setSource(v);
    lint.reset();
    if (v === STARTER) {
      setContent(STARTER_SPEC);
      setFilename("openapi.yaml");
      return;
    }
    if (v.startsWith(EXAMPLE)) {
      const name = v.slice(EXAMPLE.length);
      loadExample.mutate(name, {
        onSuccess: (e) => {
          setContent(e.content);
          setFilename(e.name);
        },
        onError: (e) => toast.error(errorMessage(e)),
      });
      return;
    }
    const [slug, n] = v.split(":");
    if (!slug || !n) return;
    load.mutate(
      { slug, number: Number(n) },
      {
        onSuccess: (c) => {
          if (c.files && c.files.length) {
            toast.message("That spec is a zip bundle; only its root document was loaded, so relative $refs will not resolve here.");
          }
          setContent(c.content);
          setFilename(/\.(ya?ml|json)$/i.test(c.filename) ? c.filename : "openapi.yaml");
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    );
  }

  return (
    <>
      <PageHeader
        title="Playground"
        description="Paste or edit a spec and lint it: the same report, operations and models a project upload shows. Nothing is saved."
        actions={
          <Button
            variant="secondary"
            disabled={!canWrite || !content.trim()}
            title={canWrite ? undefined : "Owners and admins create projects"}
            onClick={() => setCreating(true)}
          >
            <FolderPlusIcon />
            Create a project from this spec
          </Button>
        }
      />
      {!canWrite && <p className="-mt-3 mb-4 text-xs text-muted-foreground">Linting is open to everyone; creating a project needs an owner or admin.</p>}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Surface className="flex flex-col xl:sticky xl:top-[4.5rem]">
          <div className="grid gap-3 px-4 pt-4 pb-3 sm:grid-cols-[minmax(0,1fr)_180px]">
            <Field label="Load" htmlFor="pg-source">
              <SimpleSelect id="pg-source" value={source} onValueChange={pickSource} options={sources} disabled={load.isPending || loadExample.isPending} />
            </Field>
            <Field label="Filename" htmlFor="pg-filename">
              <Input id="pg-filename" value={filename} onChange={(e) => setFilename(e.target.value)} className="font-mono text-[13px]" />
            </Field>
          </div>
          <div className="relative px-4">
            {(load.isPending || loadExample.isPending) && (
              <div className="absolute inset-0 z-10 mx-4 flex items-center justify-center rounded-xl bg-code-bg/80 text-code-fg">
                <Loader2Icon className="size-5 animate-spin" />
              </div>
            )}
            <SpecEditor id="pg-editor" value={content} onChange={setContent} onSubmit={run} className="h-[56vh] min-h-[320px]" />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <p id="pg-editor-help" className="text-[12px] text-muted-foreground">
              Ctrl or Cmd + Enter lints. Tab indents; press Escape first to move focus on.
            </p>
            <Button onClick={run} disabled={lint.isPending || !content.trim()}>
              {lint.isPending ? <Loader2Icon className="animate-spin" /> : <PlayIcon />}
              {lint.isPending ? "Linting..." : "Lint"}
            </Button>
          </div>
        </Surface>
        <div className="min-w-0" aria-live="polite">
          {lint.isError ? (
            <SpecErrorPanel error={lint.error} title="This is not a spec APIForge can read" />
          ) : lint.data ? (
            <Results result={lint.data} />
          ) : (
            <Surface>
              <EmptyState
                icon={FlaskConicalIcon}
                title={lint.isPending ? "Linting..." : "Lint to see the report"}
                description="The report lists what APIForge cannot express exactly, each with its JSON pointer, plus every operation, tag, security scheme and model it found."
                action={
                  <Button size="sm" onClick={run} disabled={lint.isPending || !content.trim()}>
                    <PlayIcon />
                    Lint this spec
                  </Button>
                }
              />
            </Surface>
          )}
        </div>
      </div>
      <CreateFromSpecDialog
        open={creating}
        onOpenChange={setCreating}
        content={content}
        filename={filename.trim() || "openapi.yaml"}
        suggested={lint.data?.title ?? ""}
      />
    </>
  );
}
