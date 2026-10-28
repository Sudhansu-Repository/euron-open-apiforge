import type { Metadata } from "next";
import { Suspense } from "react";

import { GenerationScreen } from "@/features/generations/components/generation-screen";

type Params = Promise<{ slug: string; number: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug, number } = await params;
  return { title: `${decodeURIComponent(slug)} generation #${number}` };
}

export default async function Page({ params }: { params: Params }) {
  const { slug, number } = await params;
  return (
    <Suspense>
      <GenerationScreen slug={decodeURIComponent(slug)} number={Number(number)} />
    </Suspense>
  );
}
