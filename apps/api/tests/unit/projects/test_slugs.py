"""Project addresses come from names: readable, stable and safe in a URL."""

from __future__ import annotations

import pytest

from apiforge_server.projects.service import _slugify


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Payments API", "payments-api"),
        ("E2E Tests", "e2e-tests"),
        ("OAuth2 Server", "oauth2-server"),
        ("Café Menü", "cafe-menu"),
        ("  ../../etc  ", "etc"),
        ("!!!", "project"),
        ("x" * 80, "x" * 60),
    ],
)
def test_slugs(name: str, slug: str) -> None:
    assert _slugify(name) == slug
