"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { FromExampleIn, Project, ProjectIn, ProjectPatch } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

export function useProjects() {
  return useQuery({ queryKey: qk.projects, queryFn: () => unwrap(api.GET("/api/v1/projects")), staleTime: STALE.activity });
}

export function useProject(slug: string) {
  return useQuery({
    queryKey: qk.project(slug),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{slug}", { params: { path: { slug } } })),
    staleTime: STALE.activity,
  });
}

export function useExamples(enabled = true) {
  return useQuery({ queryKey: qk.examples, queryFn: () => unwrap(api.GET("/api/v1/examples")), staleTime: STALE.static, enabled });
}

/** A new or changed project shows up in the list, the overview and its own page. */
function useProjectWritten() {
  const client = useQueryClient();
  return (p: Project) => {
    client.setQueryData(qk.project(p.slug), p);
    void client.invalidateQueries({ queryKey: qk.projects, exact: true });
    void client.invalidateQueries({ queryKey: qk.overview });
  };
}

export function useCreateProject() {
  const done = useProjectWritten();
  return useMutation({ mutationFn: (body: ProjectIn) => unwrap(api.POST("/api/v1/projects", { body })), onSuccess: done });
}

export function useCreateFromExample() {
  const done = useProjectWritten();
  return useMutation({
    mutationFn: (body: FromExampleIn) => unwrap(api.POST("/api/v1/projects/from-example", { body })),
    onSuccess: done,
  });
}

export function useUpdateProject(slug: string) {
  const done = useProjectWritten();
  return useMutation({
    mutationFn: (body: ProjectPatch) => unwrap(api.PATCH("/api/v1/projects/{slug}", { params: { path: { slug } }, body })),
    onSuccess: done,
  });
}

export function useDeleteProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => unwrap(api.DELETE("/api/v1/projects/{slug}", { params: { path: { slug } } })),
    onSuccess: (_d, slug) => {
      client.removeQueries({ queryKey: qk.project(slug) });
      void client.invalidateQueries({ queryKey: qk.projects, exact: true });
      void client.invalidateQueries({ queryKey: qk.overview });
    },
  });
}
