"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { api, unwrap } from "@/lib/api/client";
import type { GenerationIn } from "@/lib/api/types";
import { isActiveGeneration } from "@/lib/chips";
import { POLL_MS, qk, STALE } from "@/lib/query-keys";

/** Polls every POLL_MS while any generation is queued or running, then stops. */
export function useGenerations(slug: string) {
  return useQuery({
    queryKey: qk.generations(slug),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{slug}/generations", { params: { path: { slug }, query: { limit: 100 } } })),
    staleTime: STALE.activity,
    refetchInterval: (q) => (q.state.data?.some((g) => isActiveGeneration(g.status)) ? POLL_MS : false),
  });
}

export function useGeneration(slug: string, number: number) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: qk.generation(slug, number),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{slug}/generations/{number}", { params: { path: { slug, number } } })),
    // A finished generation never changes; one in flight is polled.
    staleTime: (q) => (q.state.data && !isActiveGeneration(q.state.data.status) ? STALE.immutable : 0),
    refetchInterval: (q) => (q.state.data && isActiveGeneration(q.state.data.status) ? POLL_MS : false),
    enabled: Number.isInteger(number) && number > 0,
  });

  // When it finishes, lists and counts that showed it in flight are stale. Exact keys:
  // a prefix match on the list key would also hit this very query and cancel it.
  const status = query.data?.status;
  const previous = React.useRef(status);
  React.useEffect(() => {
    if (previous.current && isActiveGeneration(previous.current) && status && !isActiveGeneration(status)) {
      void client.invalidateQueries({ queryKey: qk.generations(slug), exact: true });
      void client.invalidateQueries({ queryKey: qk.project(slug), exact: true });
      void client.invalidateQueries({ queryKey: qk.projects, exact: true });
      void client.invalidateQueries({ queryKey: qk.overview, exact: true });
    }
    previous.current = status;
  }, [status, slug, client]);
  return query;
}

/** One file of a finished generation: immutable, cached for the session. */
export function useGenerationFile(slug: string, number: number, path: string | null, enabled = true) {
  return useQuery({
    queryKey: qk.generationFile(slug, number, path ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{slug}/generations/{number}/file", {
          params: { path: { slug, number }, query: { path: path ?? "" } },
        }),
      ),
    staleTime: STALE.immutable,
    enabled: enabled && !!path,
  });
}

export function useCreateGeneration(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: GenerationIn) =>
      unwrap(api.POST("/api/v1/projects/{slug}/generations", { params: { path: { slug } }, body })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.generations(slug), exact: true });
      void client.invalidateQueries({ queryKey: qk.project(slug), exact: true });
      void client.invalidateQueries({ queryKey: qk.projects, exact: true });
      void client.invalidateQueries({ queryKey: qk.overview, exact: true });
    },
  });
}

/** Same-origin download link (Next proxies /api), so the session cookie goes along. */
export function archiveUrl(slug: string, number: number): string {
  return `/api/v1/projects/${encodeURIComponent(slug)}/generations/${number}/archive`;
}
