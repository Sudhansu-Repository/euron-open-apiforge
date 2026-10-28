/**
 * Query keys in one place, so invalidation after a mutation names exactly what it
 * touched.
 */
export const qk = {
  me: ["auth", "me"] as const,
  system: ["system"] as const,
  users: ["users"] as const,
  keys: (includeRevoked = false) => ["keys", { includeRevoked }] as const,
  keysAll: ["keys"] as const,
  audit: (action?: string) => ["audit", { action }] as const,

  overview: ["overview"] as const,
  examples: ["examples"] as const,
  example: (name: string) => ["examples", name] as const,
  projects: ["projects"] as const,
  project: (slug: string) => ["projects", slug] as const,
  specs: (slug: string) => ["projects", slug, "specs"] as const,
  spec: (slug: string, n: number) => ["projects", slug, "specs", n] as const,
  specContent: (slug: string, n: number) => ["projects", slug, "specs", n, "content"] as const,
  generations: (slug: string) => ["projects", slug, "generations"] as const,
  generation: (slug: string, n: number) => ["projects", slug, "generations", n] as const,
  generationFile: (slug: string, n: number, path: string) => ["projects", slug, "generations", n, "file", path] as const,
};

/** staleTime per kind of data, chosen deliberately (see docs/architecture/HLD.md). */
export const STALE = {
  /** Lists and counts that change when someone uploads or generates. */
  activity: 15_000,
  config: 30_000,
  /** Spec versions, generated files and archives never change once written. */
  immutable: Infinity,
  static: 5 * 60_000,
} as const;

/** How often an in-flight generation is polled. */
export const POLL_MS = 1500;
