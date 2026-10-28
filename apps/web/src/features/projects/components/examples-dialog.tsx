"use client";

import { ArrowRightIcon, BookOpenIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { plural } from "@/lib/format";

import { useCreateFromExample, useExamples } from "../api";

/** Pick one of the specs bundled with APIForge; it becomes a project with that spec as version 1. */
export function ExamplesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const q = useExamples(open);
  const create = useCreateFromExample();
  const [picked, setPicked] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setPicked(null);
      setError(null);
    }
  }, [open]);

  function use(name: string) {
    setPicked(name);
    setError(null);
    create.mutate(
      { example: name },
      {
        onSuccess: (p) => {
          toast.success(`Project "${p.name}" created with its spec as version 1.`);
          onOpenChange(false);
          router.push(`/projects/${p.slug}`);
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Start from an example</DialogTitle>
          <DialogDescription>
            Real-world specs that ship with APIForge. Each becomes a project with the spec as version 1, linted and ready to generate.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-2.5">
          {error && <FieldError className="pb-1">{error}</FieldError>}
          {q.isPending ? (
            Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)
          ) : q.isError ? (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
          ) : !q.data.length ? (
            <EmptyState
              compact
              icon={BookOpenIcon}
              title="No examples bundled"
              description="This install ships without example specs. Create an empty project and upload your own spec instead."
              action={
                <Button size="sm" variant="secondary" onClick={() => onOpenChange(false)}>
                  Close
                </Button>
              }
            />
          ) : (
            q.data.map((ex) => (
              <div key={ex.name} className="flex flex-col gap-3 rounded-xl bg-muted/60 p-4 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] font-semibold">{ex.title}</span>
                    <span className="text-[12px] text-muted-foreground tabular">{plural(ex.operations, "operation")}</span>
                  </div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{ex.description}</p>
                  {ex.features.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {ex.features.map((f) => (
                        <Chip key={f} tone="primary">
                          {f}
                        </Chip>
                      ))}
                    </div>
                  )}
                </div>
                <Button size="sm" className="shrink-0" disabled={create.isPending} onClick={() => use(ex.name)}>
                  {create.isPending && picked === ex.name ? "Creating..." : "Use this"}
                  {!(create.isPending && picked === ex.name) && <ArrowRightIcon />}
                </Button>
              </div>
            ))
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
