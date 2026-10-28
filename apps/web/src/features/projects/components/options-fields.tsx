"use client";

import { Switch } from "@/components/ui/switch";
import type { GenerationOptions } from "@/lib/api/types";

const OPTIONS: { key: "db" | "docker" | "ci"; label: string; description: string }[] = [
  {
    key: "db",
    label: "Database (--db)",
    description: "Collection resources get a working SQLAlchemy implementation, models and an Alembic migration.",
  },
  { key: "docker", label: "Docker (--docker)", description: "A Dockerfile and a compose.yaml to run the service." },
  { key: "ci", label: "CI (--ci)", description: "A GitHub Actions workflow that lints and runs the generated tests." },
];

export type BoolOptions = Required<Pick<GenerationOptions, "db" | "docker" | "ci">>;

export function toBoolOptions(o: GenerationOptions | null | undefined): BoolOptions {
  return { db: !!o?.db, docker: !!o?.docker, ci: !!o?.ci };
}

/** The three generation switches, used for project defaults and for one generation. */
export function OptionsFields({
  value,
  onChange,
  disabled,
  idPrefix,
}: {
  value: BoolOptions;
  onChange: (v: BoolOptions) => void;
  disabled?: boolean;
  idPrefix: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-xl bg-muted/60 p-1">
      {OPTIONS.map((o) => (
        <label
          key={o.key}
          htmlFor={`${idPrefix}-${o.key}`}
          className="flex cursor-pointer items-start justify-between gap-4 rounded-lg px-3 py-2.5 hover:bg-card/70"
        >
          <span className="min-w-0">
            <span className="block text-[13px] font-medium text-foreground">{o.label}</span>
            <span className="block text-[12px] leading-snug text-muted-foreground">{o.description}</span>
          </span>
          <Switch
            id={`${idPrefix}-${o.key}`}
            checked={value[o.key]}
            disabled={disabled}
            onCheckedChange={(on) => onChange({ ...value, [o.key]: on })}
            className="mt-0.5"
          />
        </label>
      ))}
    </div>
  );
}
