"""Object storage: local disk round trips and refuses keys that escape its root."""

from __future__ import annotations

import pytest

from apiforge_server.core.storage import LocalStorage, ObjectNotFoundError


async def test_local_storage_round_trip(tmp_path: object) -> None:
    storage = LocalStorage(str(tmp_path))
    await storage.put("jobs/a/payload.json", b"{}", "application/json")
    assert await storage.get("jobs/a/payload.json") == b"{}"
    with pytest.raises(ObjectNotFoundError):
        await storage.get("jobs/missing.json")


async def test_local_storage_refuses_path_traversal(tmp_path: object) -> None:
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        await storage.put("../outside.txt", b"x", "text/plain")
