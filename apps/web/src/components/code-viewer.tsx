"use client";

import { Highlight, type PrismTheme } from "prism-react-renderer";
import * as React from "react";

import { cn } from "@/lib/cn";

import { CopyButton } from "./copy-button";

/** Prism colors come from the code-* tokens in globals.css, never from hex values here. */
const theme: PrismTheme = {
  plain: { color: "var(--code-fg)", backgroundColor: "transparent" },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "var(--code-comment)", fontStyle: "italic" } },
    { types: ["keyword", "boolean", "important", "atrule", "selector"], style: { color: "var(--code-keyword)" } },
    { types: ["string", "char", "attr-value", "regex", "inserted"], style: { color: "var(--code-string)" } },
    { types: ["number", "constant", "symbol"], style: { color: "var(--code-number)" } },
    { types: ["function", "class-name", "decorator"], style: { color: "var(--code-function)" } },
    { types: ["property", "key", "attr-name", "tag"], style: { color: "var(--code-property)" } },
    { types: ["builtin", "variable"], style: { color: "var(--code-builtin)" } },
    { types: ["punctuation", "operator"], style: { color: "var(--code-punctuation)" } },
    { types: ["deleted"], style: { color: "var(--danger)" } },
  ],
};

/** The API's language names mapped to the grammars bundled with prism-react-renderer. */
const GRAMMAR: Record<string, string> = {
  python: "python",
  py: "python",
  yaml: "yaml",
  yml: "yaml",
  json: "json",
  markdown: "markdown",
  md: "markdown",
};

/** Past this size the text is shown plain: tokenizing megabytes freezes the tab. */
const HIGHLIGHT_LIMIT = 300_000;

export function grammarFor(language: string | null | undefined): string {
  return GRAMMAR[(language ?? "").toLowerCase()] ?? "plain";
}

/** "openapi.yaml" -> "yaml", for spec sources that have a filename but no language. */
export function languageFromFilename(name: string): string {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (ext === "yaml" || ext === "yml") return "yaml";
  if (ext === "json") return "json";
  if (ext === "py") return "python";
  if (ext === "md") return "markdown";
  return "text";
}

/**
 * Read-only code with line numbers and syntax highlighting. Always a dark slab; long lines
 * scroll horizontally inside it, never the page.
 */
export function CodeViewer({
  code,
  language,
  title,
  actions,
  className,
  maxHeight = "70vh",
}: {
  code: string;
  language: string;
  title?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  maxHeight?: string;
}) {
  const grammar = code.length > HIGHLIGHT_LIMIT ? "plain" : grammarFor(language);
  const text = code.endsWith("\n") ? code.slice(0, -1) : code;
  return (
    <div className={cn("overflow-hidden rounded-xl bg-code-bg text-code-fg shadow-[var(--elev-1)] ring-1 ring-white/5", className)}>
      <div className="flex min-h-10 items-center justify-between gap-2 bg-white/[0.03] px-3 py-1.5">
        <div className="min-w-0 truncate font-mono text-[12px] text-code-muted">{title}</div>
        <div className="flex shrink-0 items-center gap-1">
          {actions}
          <CopyButton value={code} variant="ghost" className="text-code-fg hover:bg-white/10 hover:text-white" />
        </div>
      </div>
      {text.length === 0 ? (
        <div className="px-4 py-6 text-center font-mono text-[12px] text-code-muted">This file is empty.</div>
      ) : (
        <Highlight code={text} language={grammar} theme={theme}>
          {({ tokens, getLineProps, getTokenProps }) => (
            <pre
              className="overflow-auto py-3 font-mono text-[12px] leading-[1.7]"
              style={{ maxHeight }}
              tabIndex={0}
              aria-label={typeof title === "string" ? `${title} source` : "Source code"}
            >
              <code className="table min-w-full">
                {tokens.map((line, i) => {
                  const lineProps = getLineProps({ line });
                  return (
                    <span key={i} {...lineProps} className={cn("table-row hover:bg-code-line", lineProps.className)}>
                      <span
                        aria-hidden
                        className="table-cell w-[1%] pr-4 pl-4 text-right text-code-gutter tabular select-none"
                      >
                        {i + 1}
                      </span>
                      <span className="table-cell pr-4 whitespace-pre">
                        {line.map((token, key) => (
                          <span key={key} {...getTokenProps({ token })} />
                        ))}
                        {line.length === 1 && line[0]?.empty ? "\n" : null}
                      </span>
                    </span>
                  );
                })}
              </code>
            </pre>
          )}
        </Highlight>
      )}
    </div>
  );
}
