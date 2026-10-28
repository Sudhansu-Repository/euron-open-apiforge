"use client";

import { CheckCircle2Icon, FileUpIcon, InfoIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import type { SpecUploaded } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatBytes, plural } from "@/lib/format";
import { changeSummary } from "@/lib/spec-changes";

import { useUploadSpecFile, useUploadSpecText } from "../api";
import { SpecErrorPanel } from "./spec-error";

const ACCEPT = ".yaml,.yml,.json,.zip";

export function acceptedSpecFile(name: string): boolean {
  return /\.(ya?ml|json|zip)$/i.test(name);
}

function Result({ slug, result, onGenerate }: { slug: string; result: SpecUploaded; onGenerate?: (n: number) => void }) {
  const s = result.spec;
  return (
    <div className="space-y-4">
      <div className={cn("flex gap-3 rounded-xl px-4 py-3 text-[13px]", result.created ? "bg-savings-soft" : "bg-info-soft")}>
        {result.created ? <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-savings" /> : <InfoIcon className="mt-0.5 size-4 shrink-0 text-info" />}
        <div>
          <div className="font-semibold text-foreground">{result.created ? `Version ${s.number} created` : `This exact spec is already version ${s.number}`}</div>
          <div className="text-muted-foreground">
            {result.created
              ? "Linted and compared with the previous version. It is ready to generate."
              : "Uploads are identified by their content, so nothing new was stored."}
          </div>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-[13px] sm:grid-cols-4">
        {[
          ["Title", `${s.title} ${s.api_version}`],
          ["Operations", String(s.operations)],
          ["Report", s.errors || s.warnings ? `${plural(s.errors, "error")}, ${plural(s.warnings, "warning")}` : "Clean"],
          ["Changes", changeSummary(s.changes)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-lg bg-muted/60 px-3 py-2">
            <dt className="text-[11.5px] text-muted-foreground">{k}</dt>
            <dd className="font-medium break-words">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" nativeButton={false} render={<Link href={`/projects/${slug}/specs/${s.number}`} />}>
          Open version {s.number}
        </Button>
        {onGenerate && (
          <Button size="sm" onClick={() => onGenerate(s.number)}>
            Generate from it
          </Button>
        )}
      </div>
    </div>
  );
}

export function UploadSpecDialog({
  slug,
  open,
  onOpenChange,
  onGenerate,
}: {
  slug: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onGenerate?: (specNumber: number) => void;
}) {
  const uploadFile = useUploadSpecFile(slug);
  const uploadText = useUploadSpecText(slug);
  const [mode, setMode] = React.useState<"file" | "paste">("file");
  const [file, setFile] = React.useState<File | null>(null);
  const [note, setNote] = React.useState("");
  const [text, setText] = React.useState("");
  const [filename, setFilename] = React.useState("openapi.yaml");
  const [localError, setLocalError] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const pending = uploadFile.isPending || uploadText.isPending;
  const result = mode === "file" ? uploadFile.data : uploadText.data;
  const error = mode === "file" ? uploadFile.error : uploadText.error;

  React.useEffect(() => {
    if (open) {
      setFile(null);
      setNote("");
      setText("");
      setFilename("openapi.yaml");
      setLocalError(null);
      uploadFile.reset();
      uploadText.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function pick(f: File | null | undefined) {
    if (!f) return;
    if (!acceptedSpecFile(f.name)) {
      setLocalError("Choose a .yaml, .yml or .json file, or a .zip of a spec with relative $refs.");
      return;
    }
    setLocalError(null);
    uploadFile.reset();
    setFile(f);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    const onSuccess = (r: SpecUploaded) =>
      toast.success(r.created ? `Version ${r.spec.number} uploaded.` : `Already stored as version ${r.spec.number}.`);
    if (mode === "file") {
      if (!file) return setLocalError("Choose a spec file first.");
      uploadFile.mutate({ file, note: note.trim() }, { onSuccess });
    } else {
      if (!text.trim()) return setLocalError("Paste the spec's YAML or JSON first.");
      const name = filename.trim() || "openapi.yaml";
      if (!/\.(ya?ml|json)$/i.test(name)) return setLocalError("The filename must end in .yaml, .yml or .json.");
      uploadText.mutate({ content: text, filename: name }, { onSuccess });
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Upload a spec version</DialogTitle>
          <DialogDescription>Each upload is linted and compared with the previous version. Nothing is generated until you ask.</DialogDescription>
        </DialogHeader>
        {result ? (
          <>
            <DialogBody>
              <Result slug={slug} result={result} onGenerate={onGenerate ? (n) => { onOpenChange(false); onGenerate(n); } : undefined} />
            </DialogBody>
            <DialogFooter>
              <Button variant="ghost" onClick={() => { uploadFile.reset(); uploadText.reset(); setFile(null); }}>
                Upload another
              </Button>
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
            <DialogBody className="space-y-4">
              <Segmented
                ariaLabel="How to provide the spec"
                value={mode}
                onChange={(m) => { setMode(m); setLocalError(null); }}
                options={[
                  { value: "file", label: "Upload a file" },
                  { value: "paste", label: "Paste text" },
                ]}
                className="sm:max-w-xs"
              />
              {mode === "file" ? (
                <>
                  <div
                    onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); }}
                    className={cn(
                      "flex flex-col items-center justify-center gap-2 rounded-xl bg-muted/60 px-6 py-8 text-center transition-colors",
                      dragging && "bg-primary-soft",
                    )}
                  >
                    <FileUpIcon className="size-6 text-primary" />
                    {file ? (
                      <div className="text-[13px]">
                        <span className="font-mono font-medium">{file.name}</span> <span className="text-muted-foreground">({formatBytes(file.size)})</span>
                      </div>
                    ) : (
                      <div className="text-[13px] text-muted-foreground">Drop openapi.yaml, openapi.json or a .zip bundle here</div>
                    )}
                    <Button type="button" size="sm" variant="outline" onClick={() => inputRef.current?.click()}>
                      {file ? "Choose another file" : "Choose a file"}
                    </Button>
                    <input
                      ref={inputRef}
                      type="file"
                      accept={ACCEPT}
                      className="sr-only"
                      aria-label="Spec file"
                      onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }}
                    />
                  </div>
                  <Field label="Note" htmlFor="spec-note" hint="Optional: what changed, shown in the version list.">
                    <Input id="spec-note" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Orders can be cancelled" />
                  </Field>
                </>
              ) : (
                <>
                  <Field label="Filename" htmlFor="spec-filename" hint="Decides how the text is parsed: .yaml, .yml or .json.">
                    <Input id="spec-filename" value={filename} onChange={(e) => setFilename(e.target.value)} className="font-mono text-[13px]" />
                  </Field>
                  <Field label="Spec" htmlFor="spec-text">
                    <Textarea
                      id="spec-text"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      rows={12}
                      spellCheck={false}
                      placeholder={"openapi: 3.1.0\ninfo:\n  title: My API\n  version: 1.0.0\npaths: {}"}
                      className="font-mono text-[12px] leading-[1.6]"
                    />
                  </Field>
                </>
              )}
              {localError && <p role="alert" className="text-xs font-medium text-danger">{localError}</p>}
              {error && <SpecErrorPanel error={error} />}
            </DialogBody>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {pending ? "Linting..." : "Upload and lint"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
