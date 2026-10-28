#!/usr/bin/env python3
"""Download the latest succeeded generation of an APIForge project and verify it.

For CI: a read-only API key (afk_...) is enough. The script lists the project's
generations (newest first), picks the newest one that succeeded, downloads its archive,
and checks the SHA-256 of the bytes against the hash the service recorded for that
generation (and against the ETag it served). Only then is the file written, atomically.

    APIFORGE_API_KEY=afk_... python examples/download_latest.py pet-store
    python examples/download_latest.py pet-store --url https://apiforge.example.com \
        --key afk_... --out build/pet-store.zip --expect-sha256 <hash from a trusted run>

Exit codes: 0 downloaded and verified, 1 nothing to download or the hash does not match,
2 usage, network or HTTP error. Standard library only (Python 3.11 or newer).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TIMEOUT_S = 60


class ApiError(Exception):
    """An HTTP or network error, with the service's message when it sent one."""


def _request(url: str, key: str) -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json, application/zip"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 the URL is the caller's
            return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            error = json.loads(body)["error"]
            detail = f"{error['code']}: {error['message']}"
        except (ValueError, KeyError, TypeError):
            detail = body[:200].decode("utf-8", "replace")
        raise ApiError(f"{exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"cannot reach {url}: {exc.reason}") from exc


def latest_succeeded(base: str, key: str, project: str) -> dict[str, Any] | None:
    slug = urllib.parse.quote(project, safe="")
    body, _ = _request(f"{base}/api/v1/projects/{slug}/generations?limit=200", key)
    generations: list[dict[str, Any]] = json.loads(body)
    return next((g for g in generations if g.get("status") == "succeeded"), None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("project", help="The project's slug (as in its URL), e.g. pet-store")
    ap.add_argument(
        "--url",
        default=os.environ.get("APIFORGE_URL", "http://localhost:4630"),
        help="The APIForge API (default: $APIFORGE_URL or http://localhost:4630)",
    )
    ap.add_argument(
        "--key",
        default=os.environ.get("APIFORGE_API_KEY"),
        help="A read-only API key (default: $APIFORGE_API_KEY)",
    )
    ap.add_argument("--out", help="Where to write the zip (default: <slug>-<number>.zip)")
    ap.add_argument(
        "--expect-sha256",
        help="Also require this exact archive hash (pin a generation you reviewed)",
    )
    args = ap.parse_args(argv)
    if not args.key:
        print("Set APIFORGE_API_KEY or pass --key (an afk_... read-only key).", file=sys.stderr)
        return 2
    base = args.url.rstrip("/")

    try:
        gen = latest_succeeded(base, args.key, args.project)
        if gen is None:
            print(f"{args.project} has no succeeded generation yet.", file=sys.stderr)
            return 1
        number, recorded = gen["number"], gen["archive_sha256"]
        slug = urllib.parse.quote(args.project, safe="")
        data, headers = _request(
            f"{base}/api/v1/projects/{slug}/generations/{number}/archive", args.key
        )
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    actual = hashlib.sha256(data).hexdigest()
    etag = headers.get("etag", "").strip('"')
    problems = []
    if actual != recorded:
        problems.append(f"the archive hashes to {actual}, the service recorded {recorded}")
    if etag and etag != actual:
        problems.append(f"the ETag says {etag}")
    if args.expect_sha256 and actual != args.expect_sha256.lower():
        problems.append(f"expected {args.expect_sha256}")
    if problems:
        print(f"generation {number}: hash mismatch: " + "; ".join(problems), file=sys.stderr)
        return 1

    out = Path(args.out or f"{args.project}-{number}.zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out.parent, delete=False, suffix=".part") as tmp:
        tmp.write(data)
    Path(tmp.name).replace(out)
    print(
        f"{args.project} generation {number} (spec v{gen['spec_number']}, "
        f"{gen.get('file_count')} files): {out} {len(data):,} bytes, sha256 {actual} verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
