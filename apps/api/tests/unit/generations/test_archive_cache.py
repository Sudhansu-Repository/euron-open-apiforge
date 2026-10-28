"""The in-process cache of unpacked archives stays within its count and byte bounds."""

from __future__ import annotations

from apiforge_server.generations.service import _ArchiveCache, etag


def test_least_recently_used_archive_goes_first_when_over_count() -> None:
    cache = _ArchiveCache(max_archives=2)
    cache.put("a", {"f": b"1"})
    cache.put("b", {"f": b"2"})
    assert cache.get("a") is not None  # a is now the most recent
    cache.put("c", {"f": b"3"})
    assert cache.get("b") is None and cache.get("a") and cache.get("c")


def test_bytes_bound_evicts_but_always_keeps_the_newest() -> None:
    cache = _ArchiveCache(max_archives=10, max_bytes=10)
    cache.put("a", {"f": b"x" * 6})
    cache.put("b", {"f": b"y" * 6})
    assert cache.get("a") is None and cache.get("b")
    cache.put("huge", {"f": b"z" * 100})
    assert cache.get("huge") and cache.get("b") is None


def test_putting_the_same_archive_twice_does_not_double_count() -> None:
    cache = _ArchiveCache(max_archives=10, max_bytes=10)
    cache.put("a", {"f": b"x" * 6})
    cache.put("a", {"f": b"x" * 6})
    cache.put("b", {"f": b"y" * 4})
    assert cache.get("a") and cache.get("b")


def test_etags_name_the_archive_or_one_file() -> None:
    assert etag("abc") == '"abc"'
    assert etag("abc", "app/main.py") == '"abc:app/main.py"'
