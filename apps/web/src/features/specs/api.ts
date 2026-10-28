"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { SpecUploaded } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

export function useSpecs(slug: string) {
  return useQuery({
    queryKey: qk.specs(slug),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{slug}/specs", { params: { path: { slug } } })),
    staleTime: STALE.activity,
  });
}

/** A stored spec version never changes, so it is cached for the session. */
export function useSpec(slug: string, number: number) {
  return useQuery({
    queryKey: qk.spec(slug, number),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{slug}/specs/{number}", { params: { path: { slug, number } } })),
    staleTime: STALE.immutable,
    enabled: Number.isInteger(number) && number > 0,
  });
}

export function useSpecContent(slug: string, number: number, enabled = true) {
  return useQuery({
    queryKey: qk.specContent(slug, number),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{slug}/specs/{number}/content", { params: { path: { slug, number } } })),
    staleTime: STALE.immutable,
    enabled,
  });
}

function useSpecWritten(slug: string) {
  const client = useQueryClient();
  return (r: SpecUploaded) => {
    client.setQueryData(qk.spec(slug, r.spec.number), r.spec);
    if (!r.created) return;
    void client.invalidateQueries({ queryKey: qk.specs(slug), exact: true });
    void client.invalidateQueries({ queryKey: qk.project(slug), exact: true });
    void client.invalidateQueries({ queryKey: qk.projects, exact: true });
    void client.invalidateQueries({ queryKey: qk.overview });
  };
}

/** Multipart upload of a .yaml, .yml, .json or .zip file, with an optional note. */
export function useUploadSpecFile(slug: string) {
  const done = useSpecWritten(slug);
  return useMutation({
    mutationFn: ({ file, note }: { file: File; note: string }) =>
      unwrap(
        api.POST("/api/v1/projects/{slug}/specs", {
          params: { path: { slug } },
          // The generated type describes the form fields; the serializer sends the real file.
          body: { file: file.name, note },
          bodySerializer: () => {
            const form = new FormData();
            form.append("file", file, file.name);
            if (note) form.append("note", note);
            return form;
          },
        }),
      ),
    onSuccess: done,
  });
}

/** Upload pasted text (what the editor and the playground send). */
export function useUploadSpecText(slug: string) {
  const done = useSpecWritten(slug);
  return useMutation({
    mutationFn: (body: { content: string; filename: string }) =>
      unwrap(api.POST("/api/v1/projects/{slug}/specs/text", { params: { path: { slug } }, body })),
    onSuccess: done,
  });
}
