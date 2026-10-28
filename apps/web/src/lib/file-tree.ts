import type { FileOwner, GeneratedFile } from "./api/types";

/**
 * The generated project's file list (flat paths) as a tree for the file browser.
 * Folders sort before files, both alphabetically, like an editor's explorer.
 */

export interface FileNode {
  kind: "file";
  name: string;
  path: string;
  owner: FileOwner;
  bytes: number;
}

export interface FolderNode {
  kind: "folder";
  name: string;
  path: string;
  children: TreeNode[];
  /** Every file below is owned by APIForge, every file is yours, or a mix. */
  owner: FileOwner | "mixed";
  files: number;
}

export type TreeNode = FileNode | FolderNode;

function sortNodes(nodes: TreeNode[]): void {
  nodes.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
    return a.name.localeCompare(b.name, "en", { sensitivity: "base" }) || a.name.localeCompare(b.name);
  });
  for (const n of nodes) if (n.kind === "folder") sortNodes(n.children);
}

function summarize(folder: FolderNode): void {
  let files = 0;
  const owners = new Set<FileOwner | "mixed">();
  for (const child of folder.children) {
    if (child.kind === "folder") {
      summarize(child);
      files += child.files;
      if (child.files) owners.add(child.owner);
    } else {
      files += 1;
      owners.add(child.owner);
    }
  }
  folder.files = files;
  folder.owner = owners.size === 1 ? [...owners][0]! : "mixed";
}

export function buildFileTree(files: readonly Pick<GeneratedFile, "path" | "owner" | "bytes">[]): TreeNode[] {
  const root: FolderNode = { kind: "folder", name: "", path: "", children: [], owner: "mixed", files: 0 };
  const folders = new Map<string, FolderNode>([["", root]]);

  for (const f of files) {
    const parts = f.path.split("/").filter(Boolean);
    if (!parts.length) continue;
    let parent = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const path = parts.slice(0, i + 1).join("/");
      let folder = folders.get(path);
      if (!folder) {
        folder = { kind: "folder", name: parts[i]!, path, children: [], owner: "mixed", files: 0 };
        folders.set(path, folder);
        parent.children.push(folder);
      }
      parent = folder;
    }
    parent.children.push({ kind: "file", name: parts[parts.length - 1]!, path: parts.join("/"), owner: f.owner, bytes: f.bytes });
  }
  sortNodes(root.children);
  summarize(root);
  return root.children;
}

/** Every folder that contains `path`: "a/b/c.py" gives ["a", "a/b"]. */
export function ancestorFolders(path: string): string[] {
  const parts = path.split("/").filter(Boolean);
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}

/**
 * The file to open first: the first handler module (where the user writes code), else
 * app/main.py, else the README, else the first file.
 */
export function defaultFile(files: readonly Pick<GeneratedFile, "path">[]): string | null {
  const paths = files.map((f) => f.path);
  const handler = paths
    .filter((p) => /^app\/handlers\/[^/]+\.py$/.test(p) && !p.endsWith("/__init__.py"))
    .sort((a, b) => a.localeCompare(b))[0];
  if (handler) return handler;
  for (const p of ["app/main.py", "README.md"]) if (paths.includes(p)) return p;
  return paths[0] ?? null;
}

/** Counts by owner, for the "N generated, M yours" summary. */
export function ownerCounts(files: readonly Pick<GeneratedFile, "owner">[]): Record<FileOwner, number> {
  const out: Record<FileOwner, number> = { generated: 0, user: 0 };
  for (const f of files) out[f.owner] += 1;
  return out;
}
