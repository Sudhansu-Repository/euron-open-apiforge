"use client";

import { TriangleAlertIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { OptionsFields, toBoolOptions, type BoolOptions } from "@/features/projects/components/options-fields";
import { SpecErrorPanel } from "@/features/specs/components/spec-error";
import { useSpec, useSpecs } from "@/features/specs/api";
import type { Project } from "@/lib/api/types";
import { plural } from "@/lib/format";

import { useCreateGeneration } from "../api";

/**
 * Queue a generation: pick the spec version (latest by default) and the options (the
 * project's defaults). A version whose report has errors needs an explicit "accept".
 */
export function GenerateDialog({
  project,
  open,
  onOpenChange,
  initialSpec,
}: {
  project: Project;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initialSpec?: number | null;
}) {
  const router = useRouter();
  const specs = useSpecs(project.slug);
  const create = useCreateGeneration(project.slug);
  const [spec, setSpec] = React.useState<string>("");
  const [options, setOptions] = React.useState<BoolOptions>(toBoolOptions(project.default_options));
  const [accept, setAccept] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setOptions(toBoolOptions(project.default_options));
      setAccept(false);
      create.reset();
      setSpec(initialSpec ? String(initialSpec) : "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialSpec]);

  const latest = specs.data?.[0];
  const chosenNumber = spec ? Number(spec) : (latest?.number ?? 0);
  const chosen = specs.data?.find((s) => s.number === chosenNumber);
  const hasErrors = (chosen?.errors ?? 0) > 0;
  const detail = useSpec(project.slug, hasErrors ? chosenNumber : 0);
  const errorFindings = (detail.data?.report ?? []).filter((f) => f.severity === "error");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!chosen) return;
    create.mutate(
      { spec_number: chosen.number, options: { ...options, project_name: project.default_options.project_name ?? null }, accept_report: hasErrors && accept },
      {
        onSuccess: (g) => {
          toast.success(`Generation #${g.number} queued.`);
          onOpenChange(false);
          router.push(`/projects/${project.slug}/generations/${g.number}`);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Generate a FastAPI project</DialogTitle>
          <DialogDescription>
            A worker builds a deterministic zip: the same spec and options always give the same archive. Files you own are created once and never overwritten.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            {specs.isPending ? (
              <Skeleton className="h-9" />
            ) : specs.isError ? (
              <SpecErrorPanel error={specs.error} title="Could not load the spec versions" />
            ) : !specs.data.length ? (
              <p className="rounded-xl bg-muted/60 px-4 py-3 text-[13px] text-muted-foreground">
                This project has no spec yet. Upload one first; generation always starts from a stored version.
              </p>
            ) : (
              <Field label="Spec version" htmlFor="gen-spec">
                <SimpleSelect
                  id="gen-spec"
                  value={String(chosenNumber)}
                  onValueChange={(v) => { setSpec(v); setAccept(false); }}
                  options={specs.data.map((s, i) => ({
                    value: String(s.number),
                    label: `v${s.number}: ${s.title} ${s.api_version}${i === 0 ? " (latest)" : ""}${s.errors ? `, ${plural(s.errors, "error")}` : ""}`,
                  }))}
                />
              </Field>
            )}
            <div className="space-y-1.5">
              <div className="text-[13px] font-medium">Options</div>
              <OptionsFields idPrefix="gen" value={options} onChange={setOptions} />
            </div>
            {hasErrors && (
              <div className="rounded-xl bg-warning-soft px-4 py-3 text-[13px]">
                <div className="flex items-start gap-2.5">
                  <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-warning" />
                  <div className="min-w-0">
                    <div className="font-semibold">Version {chosen?.number} has {plural(chosen?.errors ?? 0, "error")}</div>
                    <p className="text-muted-foreground">APIForge cannot generate these parts faithfully. Accept the report to generate without them, or fix the spec first.</p>
                    {detail.isPending ? (
                      <Skeleton className="mt-2 h-10" />
                    ) : (
                      <ul className="mt-2 space-y-1 font-mono text-[11.5px]">
                        {errorFindings.slice(0, 10).map((f, i) => (
                          <li key={i} className="break-words">
                            <span className="font-semibold">{f.code}</span>: {f.message} <span className="text-muted-foreground">{f.pointer}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    <label className="mt-3 flex cursor-pointer items-center gap-2 font-medium">
                      <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} className="size-4 accent-[var(--primary)]" />
                      Accept the report and generate without these parts
                    </label>
                  </div>
                </div>
              </div>
            )}
            {create.error && <SpecErrorPanel error={create.error} title="The generation was not queued" />}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending || !chosen || (hasErrors && !accept)}>
              {create.isPending ? "Queueing..." : "Generate"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
