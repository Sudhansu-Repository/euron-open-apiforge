"use client";

import { ChevronRightIcon, FileIcon, FolderIcon, FolderOpenIcon } from "lucide-react";
import * as React from "react";

import { OwnerChip } from "@/components/status-chip";
import { cn } from "@/lib/cn";
import type { TreeNode } from "@/lib/file-tree";
import { formatBytes } from "@/lib/format";

function Node({
  node,
  depth,
  open,
  toggle,
  selected,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  open: ReadonlySet<string>;
  toggle: (path: string) => void;
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  const pad = { paddingLeft: `${8 + depth * 14}px` };
  if (node.kind === "folder") {
    const isOpen = open.has(node.path);
    return (
      <li role="treeitem" aria-expanded={isOpen} aria-selected={false}>
        <button
          type="button"
          onClick={() => toggle(node.path)}
          style={pad}
          className="flex h-7 w-full items-center gap-1.5 rounded-md pr-2 text-left text-[12.5px] text-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
        >
          <ChevronRightIcon className={cn("size-3.5 shrink-0 text-subtle transition-transform", isOpen && "rotate-90")} />
          {isOpen ? <FolderOpenIcon className="size-3.5 shrink-0 text-subtle" /> : <FolderIcon className="size-3.5 shrink-0 text-subtle" />}
          <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
          {node.owner !== "mixed" && <OwnerChip value={node.owner} withHint={false} />}
        </button>
        {isOpen && (
          <ul role="group">
            {node.children.map((c) => (
              <Node key={c.path} node={c} depth={depth + 1} open={open} toggle={toggle} selected={selected} onSelect={onSelect} />
            ))}
          </ul>
        )}
      </li>
    );
  }
  const active = node.path === selected;
  return (
    <li role="treeitem" aria-selected={active}>
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        style={pad}
        title={`${node.path}, ${formatBytes(node.bytes)}`}
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex h-7 w-full items-center gap-1.5 rounded-md pr-2 text-left text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
          active && "bg-primary-soft text-primary hover:bg-primary-soft hover:text-primary",
        )}
      >
        <span className="size-3.5 shrink-0" aria-hidden />
        <FileIcon className="size-3.5 shrink-0 opacity-70" />
        <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
        <OwnerChip value={node.owner} withHint={false} />
      </button>
    </li>
  );
}

/** Collapsible folders; each file and each single-owner folder shows generated or yours. */
export function FileTree({
  nodes,
  open,
  onToggle,
  selected,
  onSelect,
}: {
  nodes: TreeNode[];
  open: ReadonlySet<string>;
  onToggle: (path: string) => void;
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  return (
    <ul role="tree" aria-label="Generated files" className="flex flex-col gap-px">
      {nodes.map((n) => (
        <Node key={n.path} node={n} depth={0} open={open} toggle={onToggle} selected={selected} onSelect={onSelect} />
      ))}
    </ul>
  );
}
