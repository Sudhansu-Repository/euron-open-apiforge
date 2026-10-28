"""``apiforge``: lint a spec, generate a project, show what a regeneration would change,
verify a generated project. Works offline, with no account.

Exit codes: 0 success, 1 the spec or project has problems, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from apiforge import __version__
from apiforge.errors import ConflictError, ForgeError
from apiforge.generator import ReportBlockedError, generate, lint
from apiforge.options import GenerateOptions
from apiforge.report import Report

CORPUS = Path(__file__).parent / "corpus"
SPEC_SUFFIXES = (".yaml", ".yml", ".json")


def _read_spec(path: str) -> tuple[bytes, str, dict[str, bytes] | None]:
    """A spec file, a folder (root openapi.yaml/json plus siblings), or a zip."""
    p = Path(path)
    if not p.exists():
        raise ForgeError(f"{path} does not exist.")
    if p.is_dir():
        files = {
            str(f.relative_to(p)).replace("\\", "/"): f.read_bytes()
            for f in sorted(p.rglob("*"))
            if f.is_file() and f.suffix in SPEC_SUFFIXES
        }
        root = next(
            (n for n in ("openapi.yaml", "openapi.yml", "openapi.json") if n in files), None
        )
        if root is None:
            raise ForgeError(
                f"{path} is a folder without an openapi.yaml or openapi.json at its top."
            )
        return files[root], root, files
    if p.suffix == ".zip":
        from apiforge.bundles import read_zip

        return read_zip(p.read_bytes())
    return p.read_bytes(), p.name, None


def _print_report(report: Report, *, quiet: bool = False) -> None:
    findings = report.sorted()
    if not findings:
        if not quiet:
            print("No findings.")
        return
    marks = {"error": "error  ", "warning": "warning", "info": "info   "}
    for f in findings:
        if quiet and f.severity == "info":
            continue
        where = f" {f.pointer}" if f.pointer else ""
        print(f"  {marks[f.severity]}{where}: {f.message}")
    c = report.counts()
    print(f"{c['error']} errors, {c['warning']} warnings, {c['info']} notes")


def cmd_lint(args: argparse.Namespace) -> int:
    data, name, files = _read_spec(args.spec)
    api, report = lint(data, name, files=files)
    if args.json:
        print(
            json.dumps(
                {
                    "title": api.title,
                    "version": api.version,
                    "operations": len(api.operations),
                    "findings": report.as_list(),
                },
                indent=2,
            )
        )
    else:
        print(
            f"{api.title} {api.version}: {len(api.operations)} operations, {len(api.models)} models"
        )
        _print_report(report)
    return 1 if report.errors else 0


def _options(args: argparse.Namespace) -> GenerateOptions:
    return GenerateOptions(
        project_name=args.name, db=args.db, docker=not args.no_docker, ci=not args.no_ci
    )


def cmd_generate(args: argparse.Namespace) -> int:
    from apiforge.archive import build_zip
    from apiforge.writer import write

    data, name, files = _read_spec(args.spec)
    try:
        gen = generate(
            data, name, files=files, options=_options(args), accept_report=args.accept_report
        )
    except ReportBlockedError as exc:
        _print_report(exc.report, quiet=True)
        print(f"\n{exc.message}", file=sys.stderr)
        return 1
    if args.zip:
        Path(args.zip).write_bytes(build_zip(gen))
        print(f"Wrote {args.zip} ({len(gen.files)} files).")
        return 0
    out = Path(args.output or gen.slug)
    try:
        result = write(gen, out, force=args.force)
    except ConflictError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    _print_report(gen.report, quiet=True)
    print(f"\n{gen.api.title}: {len(gen.api.operations)} operations into {out}/")
    print(
        f"  {len(result.created)} created, {len(result.updated)} updated, "
        f"{len(result.unchanged)} unchanged, {len(result.kept)} of yours kept"
    )
    for module, funcs in result.appended.items():
        print(f"  new stubs in {module}: {', '.join(funcs)}")
    for removed in result.removed_operations:
        print(f"  no longer in the spec (handler kept, delete it when ready): {removed}")
    for path in result.deleted:
        print(f"  deleted {path} (no longer generated)")
    if not result.updated and not result.appended and len(result.created) == len(gen.files):
        print(f"\nNext: cd {out} && uv sync && uv run uvicorn app.main:app --reload")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    from apiforge.writer import plan_write

    data, name, files = _read_spec(args.spec)
    gen = generate(data, name, files=files, options=_options(args), accept_report=True)
    result = plan_write(gen, Path(args.output), force=False)
    print(json.dumps(result.as_dict(), indent=2) if args.json else _describe(result.as_dict()))
    return 1 if result.conflicts else 0


def _describe(d: dict[str, Any]) -> str:
    lines = []
    for key in ("created", "updated", "deleted", "conflicts"):
        if d[key]:
            lines.append(f"{key}: " + ", ".join(d[key]))
    for module, funcs in d["appended"].items():
        lines.append(f"new stubs in {module}: {', '.join(funcs)}")
    for removed in d["removed_operations"]:
        lines.append(f"removed from the spec: {removed}")
    return "\n".join(lines) or "Nothing would change."


def cmd_verify(args: argparse.Namespace) -> int:
    from apiforge.verify import verify

    result = verify(Path(args.project))
    for step in result.steps:
        print(f"  {'ok    ' if step.ok else 'FAILED'} {step.name} ({step.seconds:.1f} s)")
        if not step.ok:
            print("\n".join("      " + line for line in step.output.splitlines()[-40:]))
    print("verified" if result.ok else "verification failed")
    return 0 if result.ok else 1


def cmd_examples(args: argparse.Namespace) -> int:
    specs = sorted(p for p in CORPUS.iterdir() if p.suffix in SPEC_SUFFIXES)
    if args.copy:
        dest = Path(args.copy)
        dest.mkdir(parents=True, exist_ok=True)
        for p in specs:
            (dest / p.name).write_bytes(p.read_bytes())
        print(f"Copied {len(specs)} example specs to {dest}/")
        return 0
    for p in specs:
        print(f"  {p.name}")
    print("Copy them with: apiforge examples --copy ./specs")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="apiforge", description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    ap.add_argument("--version", action="version", version=f"apiforge {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("lint", help="Validate a spec and list what APIForge would not generate")
    p.add_argument("spec", help="Spec file (.yaml or .json), a folder, or a zip")
    p.add_argument("--json", action="store_true", help="Print the report as JSON")
    p.set_defaults(func=cmd_lint)

    for name, helptext, fn in (
        ("generate", "Generate a FastAPI project (or update one)", cmd_generate),
        ("diff", "Show what generating into a folder would change", cmd_diff),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument(
            "--spec", required=True, help="Spec file (.yaml or .json), a folder, or a zip"
        )
        p.add_argument(
            "--output",
            "-o",
            required=name == "diff",
            help="Project folder (default: the spec title)",
        )
        p.add_argument("--name", help="Project name (default: from the spec title)")
        p.add_argument(
            "--db",
            action="store_true",
            help="Add SQLAlchemy persistence and CRUD for collection resources",
        )
        p.add_argument(
            "--no-docker", action="store_true", help="Leave out Dockerfile and compose.yaml"
        )
        p.add_argument("--no-ci", action="store_true", help="Leave out the GitHub Actions workflow")
        p.add_argument(
            "--json",
            action="store_true",
            help=argparse.SUPPRESS if name == "generate" else "Print as JSON",
        )
        if name == "generate":
            p.add_argument(
                "--accept-report",
                action="store_true",
                help="Generate even when the report has errors (those parts are left out)",
            )
            p.add_argument(
                "--force",
                action="store_true",
                help="Overwrite generated files even if they were edited by hand",
            )
            p.add_argument("--zip", help="Write a zip archive instead of a folder")
            p.add_argument(
                "--framework", choices=["fastapi"], default="fastapi", help="Target (fastapi)"
            )
        p.set_defaults(func=fn)

    p = sub.add_parser(
        "verify", help="Install a generated project and run its lint, types and tests"
    )
    p.add_argument("project", nargs="?", default=".", help="Project folder (default: .)")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("examples", help="List or copy the bundled example specs")
    p.add_argument("--copy", metavar="FOLDER", help="Copy the examples into FOLDER")
    p.set_defaults(func=cmd_examples)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        code: int = args.func(args)
    except ForgeError as exc:
        print(f"apiforge: {exc}", file=sys.stderr)
        for detail in getattr(exc, "errors", [])[1:10]:
            print(f"  {detail}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
