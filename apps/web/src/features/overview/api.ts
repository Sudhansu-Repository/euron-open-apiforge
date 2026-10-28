"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { isActiveGeneration } from "@/lib/chips";
import { POLL_MS, qk, STALE } from "@/lib/query-keys";

/** Counts and recent activity. Polls while something is queued or running. */
export function useOverview() {
  return useQuery({
    queryKey: qk.overview,
    queryFn: () => unwrap(api.GET("/api/v1/overview")),
    staleTime: STALE.activity,
    refetchInterval: (q) =>
      q.state.data && (q.state.data.queued > 0 || q.state.data.recent_generations.some((g) => isActiveGeneration(g.status)))
        ? POLL_MS * 2
        : false,
  });
}
