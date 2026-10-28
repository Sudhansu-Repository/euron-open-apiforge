"""Errors the generator raises. Every message says what is wrong and what to do next."""

from __future__ import annotations


class ForgeError(Exception):
    """Base class: a problem with the input or the options, never a bug report."""

    code = "forge_error"

    def __init__(self, message: str, *, pointer: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.pointer = pointer

    def __str__(self) -> str:
        return f"{self.message} (at {self.pointer})" if self.pointer else self.message


class SpecLoadError(ForgeError):
    """The bytes are not a readable JSON or YAML document within the limits."""

    code = "spec_unreadable"


class SpecInvalidError(ForgeError):
    """The document is not a valid OpenAPI 3.0 or 3.1 description."""

    code = "spec_invalid"

    def __init__(
        self, message: str, *, pointer: str | None = None, errors: list[str] | None = None
    ):
        super().__init__(message, pointer=pointer)
        self.errors = errors or []


class UnsupportedVersionError(ForgeError):
    """Swagger 2.0, or an OpenAPI version this release does not read."""

    code = "spec_version_unsupported"


class RefError(ForgeError):
    """A ``$ref`` that cannot be resolved, or one that points somewhere it may not."""

    code = "spec_ref_unresolved"


class SpecTooComplexError(ForgeError):
    """Inlining the spec's references would produce more than the expansion budget."""

    code = "spec_too_complex"


class ToolMissingError(ForgeError):
    """A command needs an external tool (uv for ``apiforge verify``) that is not installed."""

    code = "tool_missing"


class ConflictError(ForgeError):
    """Regeneration would overwrite a generated file that was edited by hand."""

    code = "generated_file_edited"

    def __init__(self, paths: list[str]) -> None:
        listed = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
        super().__init__(
            f"These generated files were edited since the last generation: {listed}. Move your "
            "changes into app/handlers (which APIForge never overwrites), or pass --force to "
            "replace them."
        )
        self.paths = paths
