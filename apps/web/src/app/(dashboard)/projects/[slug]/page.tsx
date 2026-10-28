import type { Metadata } from "next";
import { Suspense } from "react";

import { ProjectScreen } from "@/features/projects/components/project-screen";

type Params = Promise<{ slug: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  return { title: decodeURIComponent(slug) };
}

export default async function Page({ params }: { params: Params }) {
  const { slug } = await params;
  return (
    <Suspense>
      <ProjectScreen slug={decodeURIComponent(slug)} />
    </Suspense>
  );
}
