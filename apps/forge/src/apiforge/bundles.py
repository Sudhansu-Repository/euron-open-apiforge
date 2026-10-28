"""A multi-file spec in a zip: the root document plus every file a ``$ref`` may name.

The archive is untrusted: its declared sizes are checked before anything is decompressed
(a small zip can expand to gigabytes), names are normalized and may not be absolute or
climb out with ``..``, and only JSON and YAML files are read.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
import zlib

from apiforge.errors import SpecLoadError
from apiforge.loader import MAX_BYTES, MAX_FILES

ROOT_NAMES = ("openapi.yaml", "openapi.yml", "openapi.json")
SPEC_SUFFIXES = (".yaml", ".yml", ".json")
MAX_TOTAL = MAX_BYTES * 4


def read_zip(data: bytes) -> tuple[bytes, str, dict[str, bytes]]:
    """(root bytes, root name, all spec files) from a zip archive."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SpecLoadError("The upload is not a valid zip archive.") from exc
    with archive:
        members = [
            i
            for i in archive.infolist()
            if not i.is_dir()
            and i.filename.endswith(SPEC_SUFFIXES)
            and not i.filename.startswith("__MACOSX/")
            and not posixpath.basename(i.filename).startswith(".")
        ]
        if len(members) > MAX_FILES:
            raise SpecLoadError(f"The zip has {len(members)} spec files; the limit is {MAX_FILES}.")
        total = sum(i.file_size for i in members)
        if total > MAX_TOTAL:
            raise SpecLoadError(
                f"The zip's spec files expand to {total // 1024 // 1024} MiB; the limit is "
                f"{MAX_TOTAL // 1024 // 1024} MiB."
            )
        files: dict[str, bytes] = {}
        for info in members:
            name = posixpath.normpath(info.filename.replace("\\", "/"))
            if name.startswith(("/", "../")) or name == "..":
                raise SpecLoadError(f"The zip contains an unsafe path: {info.filename!r}.")
            if info.file_size > MAX_BYTES:
                raise SpecLoadError(f"{name} is larger than {MAX_BYTES // 1024 // 1024} MiB.")
            if info.flag_bits & 0x1:
                raise SpecLoadError(f"{name} is encrypted; upload an unencrypted zip.")
            try:
                with archive.open(info) as fh:
                    content = fh.read(MAX_BYTES + 1)
            except (
                zipfile.BadZipFile,
                NotImplementedError,
                RuntimeError,
                EOFError,
                zlib.error,
            ) as exc:
                raise SpecLoadError(
                    f"{name} could not be read from the zip ({type(exc).__name__}): use a plain "
                    "zip (stored or deflated)."
                ) from exc
            if len(content) > MAX_BYTES:  # the declared size lied
                raise SpecLoadError(f"{name} is larger than {MAX_BYTES // 1024 // 1024} MiB.")
            files[name] = content
    roots = sorted(
        (n for n in files if posixpath.basename(n) in ROOT_NAMES), key=lambda n: n.count("/")
    )
    if not roots:
        raise SpecLoadError(
            "The zip has no openapi.yaml or openapi.json; put the root document at the top "
            "of the archive."
        )
    root = roots[0]
    prefix = posixpath.dirname(root)
    if prefix:  # make paths relative to the root document's folder
        files = {
            posixpath.relpath(n, prefix): v
            for n, v in files.items()
            if n == root or n.startswith(prefix + "/")
        }
        root = posixpath.basename(root)
    return files[root], root, files
