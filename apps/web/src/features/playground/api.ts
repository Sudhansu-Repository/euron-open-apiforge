"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { LintIn } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

/** Lint without saving anything. */
export function useLint() {
  return useMutation({ mutationFn: (body: LintIn) => unwrap(api.POST("/api/v1/lint", { body })) });
}

/** Load a stored spec's text into the editor (cached: stored versions never change). */
export function useLoadSpecText() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, number }: { slug: string; number: number }) =>
      client.fetchQuery({
        queryKey: qk.specContent(slug, number),
        queryFn: () => unwrap(api.GET("/api/v1/projects/{slug}/specs/{number}/content", { params: { path: { slug, number } } })),
        staleTime: STALE.immutable,
      }),
  });
}

/** Load a bundled example's text into the editor (examples ship with the server). */
export function useLoadExampleText() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      client.fetchQuery({
        queryKey: qk.example(name),
        queryFn: () => unwrap(api.GET("/api/v1/examples/{name}", { params: { path: { name } } })),
        staleTime: STALE.immutable,
      }),
  });
}

/**
 * Create a project and upload the editor's text as its version 1. Two calls: when the
 * upload is rejected the project still exists (empty), and the error says so.
 */
export function useCreateProjectFromText() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ name, content, filename }: { name: string; content: string; filename: string }) => {
      const project = await unwrap(api.POST("/api/v1/projects", { body: { name } }));
      try {
        const uploaded = await unwrap(
          api.POST("/api/v1/projects/{slug}/specs/text", { params: { path: { slug: project.slug } }, body: { content, filename } }),
        );
        return { project, uploaded };
      } catch (err) {
        throw Object.assign(err instanceof Error ? err : new Error(String(err)), { createdSlug: project.slug });
      }
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.projects, exact: true });
      void client.invalidateQueries({ queryKey: qk.overview });
    },
  });
}
