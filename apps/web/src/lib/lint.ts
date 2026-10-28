import type { Finding, Severity } from "./api/types";

/** Lint findings grouped by severity, errors first, each group in report order. */
export const SEVERITIES: readonly Severity[] = ["error", "warning", "info"] as const;

export function groupFindings(report: readonly Finding[]): { severity: Severity; findings: Finding[] }[] {
  return SEVERITIES.map((severity) => ({ severity, findings: report.filter((f) => f.severity === severity) })).filter(
    (g) => g.findings.length > 0,
  );
}

export function severityCounts(report: readonly Finding[]): Record<Severity, number> {
  const out: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
  for (const f of report) out[f.severity] = (out[f.severity] ?? 0) + 1;
  return out;
}

/**
 * The API's 422 details carry `errors` either as plain strings (an invalid spec) or as
 * lint findings (a generation refused because the report has errors). One line each.
 */
export function detailLines(details: Record<string, unknown> | null | undefined): string[] {
  const errors = details?.errors;
  if (!Array.isArray(errors)) return [];
  const out: string[] = [];
  for (const e of errors) {
    if (typeof e === "string") out.push(e);
    else if (e && typeof e === "object" && typeof (e as { message?: unknown }).message === "string") {
      const f = e as { code?: unknown; message: string; pointer?: unknown };
      const where = typeof f.pointer === "string" && f.pointer ? ` (${f.pointer})` : "";
      out.push(`${typeof f.code === "string" ? `${f.code}: ` : ""}${f.message}${where}`);
    }
  }
  return out;
}
