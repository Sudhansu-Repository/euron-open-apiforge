"use client";

import { InfoIcon } from "lucide-react";
import * as React from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

/** A small (i) that explains a term on hover or keyboard focus. */
export function Hint({ text, label = "What does this mean?", className }: { text: React.ReactNode; label?: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={label}
            className={cn(
              "inline-flex size-4 shrink-0 items-center justify-center rounded-full text-faint transition-colors hover:text-muted-foreground focus-visible:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
              className,
            )}
          />
        }
      >
        <InfoIcon className="size-3.5" />
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}
