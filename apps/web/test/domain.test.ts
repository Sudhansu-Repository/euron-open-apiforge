import { describe, expect, it } from "vitest";

import { generationChip, isActiveGeneration, methodTone, ownerChip, severityChip } from "@/lib/chips";
import { ancestorFolders, buildFileTree, defaultFile, ownerCounts, type FolderNode } from "@/lib/file-tree";
import { detailLines, groupFindings, severityCounts } from "@/lib/lint";
import { activeNavItem } from "@/lib/nav";
import { canManageUsers, canWrite, roleLabel } from "@/lib/roles";
import { changeCounts, changedOperations, changeSummary, splitOperation } from "@/lib/spec-changes";

describe("status chips", () => {
  it("maps every generation status to a tone and an explanation", () => {
    expect(generationChip("queued")).toMatchObject({ label: "Queued", tone: "neutral" });
    expect(generationChip("running").tone).toBe("info");
    expect(generationChip("succeeded").tone).toBe("success");
    expect(generationChip("failed").tone).toBe("danger");
    for (const s of ["queued", "running", "succeeded", "failed"]) expect(generationChip(s).hint).not.toBe("");
    expect(generationChip("cancelled_by_admin")).toMatchObject({ label: "Cancelled by admin", tone: "neutral" });
  });
  it("polls only while a generation is in flight", () => {
    expect(isActiveGeneration("queued")).toBe(true);
    expect(isActiveGeneration("running")).toBe(true);
    expect(isActiveGeneration("succeeded")).toBe(false);
    expect(isActiveGeneration("failed")).toBe(false);
    expect(isActiveGeneration(undefined)).toBe(false);
  });
  it("labels file ownership and lint severity", () => {
    expect(ownerChip("generated").label).toBe("generated");
    expect(ownerChip("user").label).toBe("yours");
    expect(severityChip("error").tone).toBe("danger");
    expect(severityChip("warning").tone).toBe("warning");
    expect(methodTone("GET")).toBe("get");
    expect(methodTone("options")).toBe("other");
  });
});

const FILES = [
  { path: "app/main.py", owner: "user" as const, bytes: 832 },
  { path: "app/generated/routers/pets.py", owner: "generated" as const, bytes: 3035 },
  { path: "app/generated/models.py", owner: "generated" as const, bytes: 1466 },
  { path: "app/handlers/__init__.py", owner: "user" as const, bytes: 0 },
  { path: "app/handlers/stores.py", owner: "user" as const, bytes: 900 },
  { path: "app/handlers/pets.py", owner: "user" as const, bytes: 2303 },
  { path: "README.md", owner: "user" as const, bytes: 2528 },
  { path: "apiforge.lock", owner: "generated" as const, bytes: 2600 },
];

describe("file tree", () => {
  it("nests paths into folders, folders first, alphabetically", () => {
    const tree = buildFileTree(FILES);
    expect(tree.map((n) => n.name)).toEqual(["app", "apiforge.lock", "README.md"]);
    const app = tree[0] as FolderNode;
    expect(app.kind).toBe("folder");
    expect(app.children.map((n) => n.name)).toEqual(["generated", "handlers", "main.py"]);
    expect(app.files).toBe(6);
  });
  it("marks a folder with a single owner, else mixed", () => {
    const app = buildFileTree(FILES)[0] as FolderNode;
    const generated = app.children[0] as FolderNode;
    const handlers = app.children[1] as FolderNode;
    expect(generated.owner).toBe("generated");
    expect(handlers.owner).toBe("user");
    expect(app.owner).toBe("mixed");
    expect((generated.children[0] as FolderNode).path).toBe("app/generated/routers");
  });
  it("opens the first handler module by default", () => {
    expect(defaultFile(FILES)).toBe("app/handlers/pets.py");
    expect(defaultFile([{ path: "README.md" }, { path: "app/main.py" }])).toBe("app/main.py");
    expect(defaultFile([{ path: "x.txt" }])).toBe("x.txt");
    expect(defaultFile([])).toBeNull();
  });
  it("lists the folders to expand for a deep link, and counts owners", () => {
    expect(ancestorFolders("app/generated/routers/pets.py")).toEqual(["app", "app/generated", "app/generated/routers"]);
    expect(ancestorFolders("README.md")).toEqual([]);
    expect(ownerCounts(FILES)).toEqual({ generated: 3, user: 5 });
  });
  it("ignores empty paths", () => {
    expect(buildFileTree([{ path: "", owner: "user", bytes: 0 }])).toEqual([]);
  });
});

describe("spec changes", () => {
  const changes = {
    first: false,
    added: ["DELETE /pets/{petId}"],
    removed: [],
    changed: [{ operation: "GET /pets", parts: ["parameters", "responses"] }, { bogus: true }],
  };
  it("reads changed operations defensively", () => {
    expect(changedOperations(changes)).toEqual([{ operation: "GET /pets", parts: ["parameters", "responses"] }]);
    expect(changeCounts(changes)).toEqual({ added: 1, removed: 0, changed: 1 });
  });
  it("summarizes a version in one line", () => {
    expect(changeSummary(changes)).toBe("1 added, 1 changed");
    expect(changeSummary({ first: true, added: ["GET /a", "POST /a"], removed: [], changed: [] })).toBe("First version, 2 operations");
    expect(changeSummary({ first: false, added: [], removed: [], changed: [] })).toBe("No operation changes");
    expect(changeSummary(null)).toBe("No comparison");
  });
  it("splits an operation key", () => {
    expect(splitOperation("GET /pets/{petId}")).toEqual({ method: "GET", path: "/pets/{petId}" });
    expect(splitOperation("/odd")).toEqual({ method: "", path: "/odd" });
  });
});

describe("lint report", () => {
  const report = [
    { severity: "warning" as const, code: "keyword_not_enforced", message: "not is not enforced.", pointer: "/a" },
    { severity: "error" as const, code: "callbacks_unsupported", message: "Callbacks are not generated.", pointer: "/b" },
    { severity: "warning" as const, code: "tuple_not_enforced", message: "prefixItems", pointer: "/c" },
  ];
  it("groups findings errors first and counts them", () => {
    expect(groupFindings(report).map((g) => [g.severity, g.findings.length])).toEqual([
      ["error", 1],
      ["warning", 2],
    ]);
    expect(severityCounts(report)).toEqual({ error: 1, warning: 2, info: 0 });
    expect(groupFindings([])).toEqual([]);
  });
  it("turns 422 details into lines, from strings or findings", () => {
    expect(detailLines({ errors: ["(root): 'paths' is a required property"] })).toEqual(["(root): 'paths' is a required property"]);
    expect(detailLines({ errors: [report[1]] })).toEqual(["callbacks_unsupported: Callbacks are not generated. (/b)"]);
    expect(detailLines({})).toEqual([]);
    expect(detailLines(null)).toEqual([]);
  });
});

describe("navigation and roles", () => {
  it("highlights the right section, with nested pages under Projects", () => {
    expect(activeNavItem("/")?.label).toBe("Overview");
    expect(activeNavItem("/projects/pet-store/generations/2")?.label).toBe("Projects");
    expect(activeNavItem("/playground")?.label).toBe("Playground");
    expect(activeNavItem("/nowhere")).toBeUndefined();
  });
  it("lets viewers read and admins write", () => {
    expect(canWrite("viewer")).toBe(false);
    expect(canWrite("admin")).toBe(true);
    expect(canManageUsers("admin")).toBe(false);
    expect(roleLabel("owner")).toBe("Owner");
  });
});
