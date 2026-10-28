"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";

import { useCreateProject } from "../api";
import { OptionsFields, type BoolOptions } from "./options-fields";

export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const create = useCreateProject();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [options, setOptions] = React.useState<BoolOptions>({ db: false, docker: true, ci: true });
  const [error, setError] = React.useState<string | null>(null);
  const [nameError, setNameError] = React.useState<string | undefined>();

  React.useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setOptions({ db: false, docker: true, ci: true });
      setError(null);
      setNameError(undefined);
    }
  }, [open]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setNameError("Name the API this project generates, for example \"Billing API\".");
      return;
    }
    setNameError(undefined);
    setError(null);
    create.mutate(
      { name: name.trim(), description: description.trim(), default_options: options },
      {
        onSuccess: (p) => {
          toast.success(`Project "${p.name}" created. Upload its spec to get started.`);
          onOpenChange(false);
          router.push(`/projects/${p.slug}?upload=1`);
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            A project holds the versions of one OpenAPI spec and every FastAPI project generated from them.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <Field label="Name" htmlFor="np-name" error={nameError}>
              <Input id="np-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Billing API" autoFocus />
            </Field>
            <Field label="Description" htmlFor="np-desc" hint="Optional. Shown in the project list.">
              <Textarea id="np-desc" value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} rows={2} />
            </Field>
            <div className="space-y-1.5">
              <div className="text-[13px] font-medium">Default generation options</div>
              <OptionsFields idPrefix="np" value={options} onChange={setOptions} />
              <p className="text-xs text-muted-foreground">Each generation starts from these; you can change them per run.</p>
            </div>
            {error && <FieldError>{error}</FieldError>}
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
