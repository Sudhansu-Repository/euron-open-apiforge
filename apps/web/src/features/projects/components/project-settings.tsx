"use client";

import { LockIcon, Trash2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import type { Project } from "@/lib/api/types";
import { plural } from "@/lib/format";

import { useDeleteProject, useUpdateProject } from "../api";
import { OptionsFields, toBoolOptions, type BoolOptions } from "./options-fields";

export function ProjectSettings({ project, canWrite }: { project: Project; canWrite: boolean }) {
  const router = useRouter();
  const update = useUpdateProject(project.slug);
  const remove = useDeleteProject();
  const [name, setName] = React.useState(project.name);
  const [description, setDescription] = React.useState(project.description);
  const [options, setOptions] = React.useState<BoolOptions>(toBoolOptions(project.default_options));
  const [error, setError] = React.useState<string | null>(null);
  const [confirming, setConfirming] = React.useState(false);

  React.useEffect(() => {
    setName(project.name);
    setDescription(project.description);
    setOptions(toBoolOptions(project.default_options));
  }, [project]);

  const initial = toBoolOptions(project.default_options);
  const dirty =
    name.trim() !== project.name ||
    description.trim() !== project.description ||
    (["db", "docker", "ci"] as const).some((k) => options[k] !== initial[k]);

  function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("A project needs a name.");
    setError(null);
    update.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        default_options: { ...options, project_name: project.default_options.project_name ?? null },
      },
      { onSuccess: () => toast.success("Project saved."), onError: (err) => setError(errorMessage(err)) },
    );
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)]">
      <Surface>
        <SurfaceHeader title="Project" description={`The URL stays /projects/${project.slug} when you rename it.`} />
        <form onSubmit={save} className="space-y-4 px-5 pb-5" noValidate>
          {!canWrite && (
            <p className="flex items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-[12.5px] text-muted-foreground">
              <LockIcon className="size-3.5" /> Read only: owners and admins change projects.
            </p>
          )}
          <Field label="Name" htmlFor="ps-name">
            <Input id="ps-name" value={name} maxLength={120} disabled={!canWrite} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Description" htmlFor="ps-desc">
            <Textarea id="ps-desc" value={description} maxLength={2000} disabled={!canWrite} rows={3} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="space-y-1.5">
            <div className="text-[13px] font-medium">Default generation options</div>
            <OptionsFields idPrefix="ps" value={options} onChange={setOptions} disabled={!canWrite} />
          </div>
          {error && <FieldError>{error}</FieldError>}
          {canWrite && (
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                disabled={!dirty || update.isPending}
                onClick={() => { setName(project.name); setDescription(project.description); setOptions(initial); setError(null); }}
              >
                Discard
              </Button>
              <Button type="submit" disabled={!dirty || update.isPending}>
                {update.isPending ? "Saving..." : "Save changes"}
              </Button>
            </div>
          )}
        </form>
      </Surface>
      <Surface>
        <SurfaceHeader title="Delete project" description="Removes the project, every spec version and every generated archive." />
        <div className="px-5 pb-5">
          <p className="mb-3 text-[13px] text-muted-foreground">
            {plural(project.spec_count ?? 0, "spec version")} and {plural(project.generation_count ?? 0, "generation")} go with it. Projects you
            downloaded keep working; they do not depend on APIForge.
          </p>
          <Button variant="destructive-soft" disabled={!canWrite} onClick={() => setConfirming(true)}>
            <Trash2Icon />
            Delete project
          </Button>
          {!canWrite && <p className="mt-2 text-xs text-muted-foreground">Only owners and admins can delete projects.</p>}
        </div>
      </Surface>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`Delete "${project.name}"?`}
        description="Its spec versions, generations and archives are deleted for good. This cannot be undone."
        confirmLabel="Delete project"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(project.slug, {
            onSuccess: () => {
              toast.success(`Deleted "${project.name}".`);
              setConfirming(false);
              router.replace("/projects");
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      />
    </div>
  );
}
