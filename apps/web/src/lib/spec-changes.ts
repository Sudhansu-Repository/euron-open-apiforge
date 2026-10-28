import type { SpecChanges } from "./api/types";

/**
 * What changed between two spec versions, as the API reports it: operations added and
 * removed ("GET /pets/{id}") and changed operations with the parts that changed.
 */

export interface ChangedOperation {
  operation: string;
  parts: string[];
}

/** The API types `changed` loosely (a list of objects); read it defensively. */
export function changedOperations(changes: Pick<SpecChanges, "changed"> | null | undefined): ChangedOperation[] {
  const out: ChangedOperation[] = [];
  for (const item of changes?.changed ?? []) {
    const op = (item as { operation?: unknown }).operation;
    const parts = (item as { parts?: unknown }).parts;
    if (typeof op !== "string") continue;
    out.push({ operation: op, parts: Array.isArray(parts) ? parts.filter((p): p is string => typeof p === "string") : [] });
  }
  return out;
}

export interface ChangeCounts {
  added: number;
  removed: number;
  changed: number;
}

export function changeCounts(changes: SpecChanges | null | undefined): ChangeCounts {
  return {
    added: changes?.added?.length ?? 0,
    removed: changes?.removed?.length ?? 0,
    changed: changedOperations(changes).length,
  };
}

/** One line for a version list: "First version, 4 operations", "+1 -0 ~2", "No operation changes". */
export function changeSummary(changes: SpecChanges | null | undefined): string {
  if (!changes) return "No comparison";
  const c = changeCounts(changes);
  if (changes.first) return `First version, ${c.added} operation${c.added === 1 ? "" : "s"}`;
  if (!c.added && !c.removed && !c.changed) return "No operation changes";
  const bits: string[] = [];
  if (c.added) bits.push(`${c.added} added`);
  if (c.removed) bits.push(`${c.removed} removed`);
  if (c.changed) bits.push(`${c.changed} changed`);
  return bits.join(", ");
}

/** "GET /pets/{id}" split into its method and path. */
export function splitOperation(key: string): { method: string; path: string } {
  const i = key.indexOf(" ");
  if (i < 0) return { method: "", path: key };
  return { method: key.slice(0, i), path: key.slice(i + 1) };
}
