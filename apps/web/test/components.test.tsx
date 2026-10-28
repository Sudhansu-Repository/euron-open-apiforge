// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { FolderKanbanIcon } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";

import { CodeViewer, grammarFor, languageFromFilename } from "@/components/code-viewer";
import { EmptyState } from "@/components/empty-state";
import { KpiTile } from "@/components/kpi-tile";
import { GenerationChip, OwnerChip } from "@/components/status-chip";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LintReport } from "@/features/specs/components/lint-report";

afterEach(cleanup);

describe("KpiTile", () => {
  it("shows the value and its context", () => {
    render(<KpiTile label="Projects" icon={FolderKanbanIcon} value="5" sub="8 spec versions" />);
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("8 spec versions")).toBeInTheDocument();
  });
  it("renders skeletons while loading", () => {
    const { container } = render(<KpiTile label="Projects" icon={FolderKanbanIcon} value="5" loading />);
    expect(screen.queryByText("5")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-slot='skeleton'], .animate-pulse").length).toBeGreaterThan(0);
  });
});

describe("EmptyState", () => {
  it("always explains itself and offers an action", () => {
    render(
      <EmptyState
        icon={FolderKanbanIcon}
        title="No projects yet"
        description="A project turns a spec into a FastAPI project."
        action={<button type="button">Start from an example</button>}
      />,
    );
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start from an example" })).toBeInTheDocument();
  });
});

describe("chips", () => {
  it("shows generation status and file ownership in words", () => {
    render(
      <TooltipProvider>
        <GenerationChip value="running" />
        <OwnerChip value="user" />
        <OwnerChip value="generated" />
      </TooltipProvider>,
    );
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText("yours")).toBeInTheDocument();
    expect(screen.getByText("generated")).toBeInTheDocument();
  });
});

describe("LintReport", () => {
  it("says the report is clean when there are no findings", () => {
    render(<LintReport report={[]} />);
    expect(screen.getByText("Clean report")).toBeInTheDocument();
  });
  it("shows each finding's code, message and pointer", () => {
    render(<LintReport report={[{ severity: "warning", code: "keyword_not_enforced", message: "not is not enforced.", pointer: "/components/schemas/Loose" }]} />);
    expect(screen.getByText("keyword_not_enforced")).toBeInTheDocument();
    expect(screen.getByText("/components/schemas/Loose")).toBeInTheDocument();
    expect(screen.getByText("1 warning")).toBeInTheDocument();
  });
});

describe("CodeViewer", () => {
  it("numbers every line", () => {
    const { container } = render(<CodeViewer code={"def a():\n    return 1\n"} language="python" title="app/handlers/pets.py" />);
    expect(screen.getByText("app/handlers/pets.py")).toBeInTheDocument();
    const gutter = [...container.querySelectorAll("[aria-hidden].table-cell")].map((n) => n.textContent);
    expect(gutter).toEqual(["1", "2"]);
  });
  it("maps API languages to bundled grammars, plain otherwise", () => {
    expect(grammarFor("python")).toBe("python");
    expect(grammarFor("toml")).toBe("plain");
    expect(languageFromFilename("openapi.YML")).toBe("yaml");
    expect(languageFromFilename("spec.zip")).toBe("text");
  });
});
