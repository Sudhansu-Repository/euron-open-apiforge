/**
 * One mapping from states to a chip tone, label and explanation, so a status reads the same
 * on every screen.
 */

export type Tone = "success" | "savings" | "info" | "primary" | "warning" | "danger" | "neutral";

export interface ChipSpec {
  label: string;
  tone: Tone;
  hint: string;
}

const GENERATION: Record<string, ChipSpec> = {
  queued: { label: "Queued", tone: "neutral", hint: "Waiting for a worker. It starts within a few seconds." },
  running: { label: "Running", tone: "info", hint: "A worker is building the project and running its checks." },
  succeeded: { label: "Succeeded", tone: "success", hint: "The archive is ready to browse and download." },
  failed: { label: "Failed", tone: "danger", hint: "Nothing was produced. Open the generation to see the error." },
};

const SEVERITY: Record<string, ChipSpec> = {
  error: {
    label: "Error",
    tone: "danger",
    hint: "APIForge cannot generate this part faithfully. Fix it, or accept the report to generate without it.",
  },
  warning: { label: "Warning", tone: "warning", hint: "Generated, but not everything is enforced exactly as written." },
  info: { label: "Info", tone: "info", hint: "Worth knowing; nothing is lost." },
};

const OWNER: Record<string, ChipSpec> = {
  generated: {
    label: "generated",
    tone: "neutral",
    hint: "Owned by APIForge: rewritten on every generation. Do not edit it; change the spec instead.",
  },
  user: {
    label: "yours",
    tone: "primary",
    hint: "Yours: created once and never overwritten. Put your business logic and configuration here.",
  },
};

function fallback(value: string): ChipSpec {
  const label = value ? value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ") : "Unknown";
  return { label, tone: "neutral", hint: "" };
}

export const generationChip = (v: string | null | undefined): ChipSpec => GENERATION[v ?? ""] ?? fallback(v ?? "");
export const severityChip = (v: string | null | undefined): ChipSpec => SEVERITY[v ?? ""] ?? fallback(v ?? "");
export const ownerChip = (v: string | null | undefined): ChipSpec => OWNER[v ?? ""] ?? fallback(v ?? "");

/** Still in flight: the UI keeps polling until this turns false. */
export function isActiveGeneration(status: string | null | undefined): boolean {
  return status === "queued" || status === "running";
}

export type MethodTone = "get" | "post" | "put" | "patch" | "delete" | "other";

/** HTTP methods get one hue each, the way API docs color them. */
export function methodTone(method: string): MethodTone {
  const m = method.toLowerCase();
  return m === "get" || m === "post" || m === "put" || m === "patch" || m === "delete" ? m : "other";
}
