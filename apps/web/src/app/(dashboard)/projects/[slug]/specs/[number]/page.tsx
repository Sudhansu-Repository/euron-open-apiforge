import type { Metadata } from "next";

import { SpecScreen } from "@/features/specs/components/spec-screen";

type Params = Promise<{ slug: string; number: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug, number } = await params;
  return { title: `${decodeURIComponent(slug)} spec v${number}` };
}

export default async function Page({ params }: { params: Params }) {
  const { slug, number } = await params;
  return <SpecScreen slug={decodeURIComponent(slug)} number={Number(number)} />;
}
