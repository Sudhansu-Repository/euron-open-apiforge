"use client";

import { BoxesIcon, LockKeyholeIcon, TagsIcon } from "lucide-react";

import { Surface, SurfaceHeader } from "@/components/surface";
import { Chip } from "@/components/ui/chip";
import type { SchemeSummary, TagSummary } from "@/lib/api/types";
import { plural } from "@/lib/format";

function Empty({ text }: { text: string }) {
  return <p className="px-5 pb-4 text-[12.5px] text-muted-foreground">{text}</p>;
}

export function SchemesCard({ schemes }: { schemes: readonly SchemeSummary[] }) {
  return (
    <Surface>
      <SurfaceHeader title={<><LockKeyholeIcon className="size-4 text-subtle" />Security schemes</>} description="Each becomes a dependency in app/generated/security.py; you verify credentials in app/auth.py." />
      {schemes.length ? (
        <ul className="flex flex-col gap-1 px-5 pb-4">
          {schemes.map((s) => (
            <li key={s.name} className="flex items-center justify-between gap-3 rounded-lg bg-muted/60 px-3 py-2">
              <span className="font-mono text-[12.5px]">{s.name}</span>
              <Chip tone="info">{s.kind}</Chip>
            </li>
          ))}
        </ul>
      ) : (
        <Empty text="No security schemes: every operation is public. Add components.securitySchemes to protect routes." />
      )}
    </Surface>
  );
}

export function TagsCard({ tags }: { tags: readonly TagSummary[] }) {
  return (
    <Surface>
      <SurfaceHeader title={<><TagsIcon className="size-4 text-subtle" />Tags</>} description="One router and one handler module per tag." />
      {tags.length ? (
        <ul className="flex flex-col gap-1 px-5 pb-4">
          {tags.map((t) => (
            <li key={t.name} className="rounded-lg bg-muted/60 px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-[12.5px]">{t.name}</span>
                <span className="text-[12px] text-muted-foreground tabular">{plural(t.operations, "operation")}</span>
              </div>
              {t.description && <div className="mt-0.5 text-[12px] text-muted-foreground">{t.description}</div>}
            </li>
          ))}
        </ul>
      ) : (
        <Empty text="No tags: operations are grouped into a single default module." />
      )}
    </Surface>
  );
}

export function ModelsCard({ models }: { models: readonly string[] }) {
  return (
    <Surface>
      <SurfaceHeader title={<><BoxesIcon className="size-4 text-subtle" />Models</>} description="Pydantic models in app/generated/models.py." />
      {models.length ? (
        <div className="flex flex-wrap gap-1.5 px-5 pb-4">
          {models.map((m) => (
            <span key={m} className="rounded-md bg-muted px-2 py-1 font-mono text-[12px]">
              {m}
            </span>
          ))}
        </div>
      ) : (
        <Empty text="No named schemas under components.schemas. Inline schemas still validate." />
      )}
    </Surface>
  );
}
