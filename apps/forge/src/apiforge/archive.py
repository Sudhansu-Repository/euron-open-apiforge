"""A generation as a zip archive, byte-identical for identical input.

Entries are sorted, timestamps are fixed (1980-01-01, the earliest a zip can hold),
permissions are fixed, and the compression level is pinned, so the archive's SHA-256 is a
fingerprint of the spec and options: the web app and the CLI produce the same bytes.
"""

from __future__ import annotations

import io
import zipfile

from apiforge.generator import Generation

FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def build_zip(gen: Generation, *, folder: str | None = None) -> bytes:
    prefix = (folder if folder is not None else gen.slug).strip("/")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in sorted(gen.files, key=lambda x: x.path):
            info = zipfile.ZipInfo(f"{prefix}/{f.path}" if prefix else f.path, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3  # Unix, so the attributes above are read the same everywhere
            zf.writestr(info, f.content.encode("utf-8"), compresslevel=9)
    return buf.getvalue()
