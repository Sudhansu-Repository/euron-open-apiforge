import { Skeleton } from "@/components/ui/skeleton";

/** Shown while a route's code loads, so a navigation never flashes an empty page. */
export default function Loading() {
  return (
    <div className="space-y-4" aria-busy aria-label="Loading">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-8 w-72" />
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  );
}
