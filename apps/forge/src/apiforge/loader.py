"""Read a spec from bytes: JSON or YAML, one file or a set of files with relative ``$ref``s.

A spec is untrusted input, on the CLI as much as in the web app:

- YAML is read with a safe loader that builds only plain JSON values (no tags, no objects;
  timestamps stay strings, so an example ``2026-01-01`` is not turned into a date). Aliases
  are shared, not copied, while loading; what bounds a "billion laughs" document is the
  value budget: walking it may visit at most ``MAX_VALUES`` values in total.
- Size and nesting depth are bounded.
- ``$ref`` targets are other files of the same bundle, never URLs: nothing is fetched over
  the network, so a spec cannot make APIForge (or the server running it) call anywhere.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import yaml

from apiforge.errors import RefError, SpecLoadError

MAX_BYTES = 5 * 1024 * 1024
MAX_FILES = 200
MAX_ALIASES = 10_000
MAX_VALUES = 2_000_000
MAX_DEPTH = 64

JSONValue = Any


class _SafeLoader(yaml.SafeLoader):
    """SafeLoader without timestamp parsing, with an alias budget."""

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._aliases = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            self._aliases += 1
            if self._aliases > MAX_ALIASES:
                raise SpecLoadError(
                    f"The YAML uses more than {MAX_ALIASES} aliases. Expand them, or split "
                    "the document."
                )
        return super().compose_node(parent, index)


# Drop the implicit timestamp resolver: dates in examples stay strings, as in JSON.
_SafeLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass
class Bundle:
    """A loaded spec: the root document plus every file a ``$ref`` may point into."""

    root_name: str
    documents: dict[str, JSONValue] = field(default_factory=dict)
    # Nodes produced by inlining $refs so far (examples.expand): bounded, because a small
    # spec whose schemas reference each other can expand exponentially.
    expanded: int = 0

    @property
    def root(self) -> dict[str, JSONValue]:
        doc = self.documents[self.root_name]
        assert isinstance(doc, dict)
        return doc

    def resolve(self, ref: str, base: str) -> tuple[str, str, JSONValue]:
        """Resolve ``ref`` relative to the file ``base``: (file, pointer, value)."""
        target, _, fragment = ref.partition("#")
        if "://" in target or target.startswith("//"):
            raise RefError(
                f"External $ref {ref!r} points to a URL. APIForge never fetches specs over the "
                "network: download the file and pass it alongside the spec (a folder or a zip).",
                pointer=ref,
            )
        name = base
        if target:
            joined = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
            if joined.startswith("../") or joined == ".." or posixpath.isabs(joined):
                raise RefError(f"$ref {ref!r} leaves the spec's folder.", pointer=ref)
            name = joined
        if name not in self.documents:
            raise RefError(
                f"$ref {ref!r} points to {name!r}, which is not part of the spec. Upload the "
                "whole folder as a zip, or bundle the spec into one file.",
                pointer=ref,
            )
        pointer = fragment or ""
        return name, pointer, follow_pointer(self.documents[name], pointer, ref)


def follow_pointer(doc: JSONValue, pointer: str, ref: str) -> JSONValue:
    """Walk an RFC 6901 JSON pointer (``/a/b~1c``)."""
    node = doc
    if pointer in ("", "/"):
        return node
    if not pointer.startswith("/"):
        raise RefError(f"$ref {ref!r} has a fragment that is not a JSON pointer.", pointer=ref)
    for raw in pointer[1:].split("/"):
        part = unquote(raw).replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isascii() and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise RefError(f"$ref {ref!r} points to something that does not exist.", pointer=ref)
    return node


def parse_document(data: bytes, name: str) -> JSONValue:
    """One file's bytes to plain JSON values."""
    if len(data) > MAX_BYTES:
        raise SpecLoadError(
            f"{name} is {len(data) // 1024} KiB; the limit is {MAX_BYTES // 1024 // 1024} MiB."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SpecLoadError(f"{name} is not UTF-8 text.") from exc
    stripped = text.lstrip()
    if not stripped:
        raise SpecLoadError(f"{name} is empty.")
    try:
        # S506: a SafeLoader subclass, see _SafeLoader.
        doc = json.loads(text) if stripped[0] in "{[" else yaml.load(text, Loader=_SafeLoader)  # noqa: S506
    except SpecLoadError:
        raise
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        if isinstance(exc, json.JSONDecodeError):
            where = f" (line {exc.lineno}, column {exc.colno})"
        raise SpecLoadError(f"{name} is not valid JSON or YAML{where}.") from exc
    except RecursionError as exc:
        raise SpecLoadError(f"{name} is nested too deeply.") from exc
    _check_depth(doc, name)
    return doc


# JSON allows "\\ud800" escapes that decode to half of a UTF-16 pair: text no file, database
# or HTTP response can encode. Refused at the door instead of failing deep in generation.
_SURROGATE = re.compile("[\ud800-\udfff]")


def _check_text(text: str, name: str) -> None:
    if _SURROGATE.search(text):
        raise SpecLoadError(
            f"{name} contains an unpaired UTF-16 surrogate (a \\ud800 to \\udfff escape). "
            "Replace it with the character it was meant to be."
        )


def _check_depth(doc: JSONValue, name: str) -> None:
    stack: list[tuple[JSONValue, int]] = [(doc, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > MAX_VALUES:
            raise SpecLoadError(
                f"{name} expands to more than {MAX_VALUES:,} values (usually YAML aliases nested "
                "inside each other). Expand the aliases, or split the document."
            )
        if depth > MAX_DEPTH:
            raise SpecLoadError(f"{name} is nested more than {MAX_DEPTH} levels deep.")
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str):
                    raise SpecLoadError(f"{name} has a non-string key {key!r}.")
                _check_text(key, name)
                stack.append((value, depth + 1))
        elif isinstance(node, list):
            stack.extend((v, depth + 1) for v in node)
        elif isinstance(node, str):
            _check_text(node, name)
        elif not (node is None or isinstance(node, str | int | float | bool)):
            raise SpecLoadError(f"{name} contains a value that is not JSON: {type(node).__name__}.")


def load(
    data: bytes,
    name: str = "openapi.yaml",
    *,
    files: Mapping[str, bytes] | None = None,
) -> Bundle:
    """Load the root spec ``name`` (and, for multi-file specs, its sibling ``files``)."""
    root_name = posixpath.normpath(name.replace("\\", "/")).lstrip("/")
    bundle = Bundle(root_name=root_name)
    bundle.documents[root_name] = parse_document(data, root_name)
    if not isinstance(bundle.documents[root_name], dict):
        raise SpecLoadError(f"{root_name} must be a JSON object or YAML mapping at the top level.")
    if files:
        if len(files) > MAX_FILES:
            raise SpecLoadError(f"The spec has {len(files)} files; the limit is {MAX_FILES}.")
        total = sum(len(v) for v in files.values())
        if total > MAX_BYTES * 4:
            raise SpecLoadError("The spec files together are larger than 20 MiB.")
        for path, content in files.items():
            norm = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
            if norm == root_name or norm.startswith("../"):
                continue
            if norm.endswith((".json", ".yaml", ".yml")):
                bundle.documents[norm] = parse_document(content, norm)
    return bundle
