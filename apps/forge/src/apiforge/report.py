"""The lint report: everything APIForge noticed, with where it is in the spec.

Nothing in the spec is dropped silently. A construct APIForge cannot express is an
``unsupported`` finding (error when it changes what the API accepts or returns, warning when
only documentation is lost), a guess APIForge made (a derived operation id, a renamed field)
is ``info``. Generation refuses to run while there are errors unless the caller accepts the
report (``--accept-report`` on the CLI, a checkbox in the web app).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]
_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    message: str
    pointer: str  # RFC 6901 pointer into the root document, "" for the whole spec

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: Severity, code: str, message: str, pointer: str = "") -> None:
        finding = Finding(severity, code, message, pointer)
        if finding not in self.findings:
            self.findings.append(finding)

    def error(self, code: str, message: str, pointer: str = "") -> None:
        self.add("error", code, message, pointer)

    def warning(self, code: str, message: str, pointer: str = "") -> None:
        self.add("warning", code, message, pointer)

    def info(self, code: str, message: str, pointer: str = "") -> None:
        self.add("info", code, message, pointer)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    def sorted(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (_ORDER[f.severity], f.pointer, f.code))

    def counts(self) -> dict[str, int]:
        return {s: sum(1 for f in self.findings if f.severity == s) for s in _ORDER}

    def as_list(self) -> list[dict[str, str]]:
        return [f.as_dict() for f in self.sorted()]


def pointer(*parts: str | int) -> str:
    """Build an RFC 6901 pointer from path segments."""
    out = []
    for p in parts:
        out.append(str(p).replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(out) if out else ""
