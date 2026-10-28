"""The loader treats a spec as untrusted input."""

from __future__ import annotations

import pytest

from apiforge.errors import RefError, SpecLoadError
from apiforge.loader import MAX_DEPTH, load, parse_document


def test_json_and_yaml_give_the_same_document() -> None:
    a = parse_document(b'{"openapi": "3.0.3", "x": [1, 2]}', "a.json")
    b = parse_document(b"openapi: 3.0.3\nx: [1, 2]\n", "a.yaml")
    assert a == b


def test_dates_in_yaml_stay_strings() -> None:
    doc = parse_document(b"example: 2026-01-15\nwhen: 2026-01-15T09:30:00Z\n", "a.yaml")
    assert doc == {"example": "2026-01-15", "when": "2026-01-15T09:30:00Z"}


def test_alias_bombs_are_refused() -> None:
    # Each level refers to the previous one nine times: 9**10 values once expanded.
    lines = ["l0: &l0 [x, x, x, x, x, x, x, x, x]"]
    lines += [f"l{i}: &l{i} [{', '.join([f'*l{i - 1}'] * 9)}]" for i in range(1, 11)]
    with pytest.raises(SpecLoadError, match="aliases"):
        parse_document("\n".join(lines).encode(), "bomb.yaml")


def test_ordinary_aliases_are_fine() -> None:
    lines = ["shared: &s {type: string}"] + [f"p{i}: *s" for i in range(500)]
    assert len(parse_document("\n".join(lines).encode(), "ok.yaml")) == 501


def test_tags_that_build_objects_are_refused() -> None:
    with pytest.raises(SpecLoadError):
        parse_document(b"x: !!python/object/apply:os.system ['echo hi']\n", "evil.yaml")


def test_size_and_depth_limits() -> None:
    with pytest.raises(SpecLoadError, match="limit"):
        parse_document(b"x" * (5 * 1024 * 1024 + 1), "big.yaml")
    deep = "[" * (MAX_DEPTH + 5) + "]" * (MAX_DEPTH + 5)
    with pytest.raises(SpecLoadError, match="nested"):
        parse_document(deep.encode(), "deep.json")


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"", "empty"),
        (b"\xff\xfe\x00", "UTF-8"),
        (b"{bad json", "not valid"),
        (b"a: [1,", "not valid"),
    ],
)
def test_unreadable_input_is_explained(data: bytes, match: str) -> None:
    with pytest.raises(SpecLoadError, match=match):
        parse_document(data, "spec.yaml")


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(SpecLoadError, match="top level"):
        load(b"[1, 2]", "spec.json")


def test_url_refs_are_never_fetched() -> None:
    bundle = load(b"openapi: 3.0.3\n", "openapi.yaml")
    for ref in (
        "https://example.com/schema.yaml",
        "//example.com/x.yaml",
        "http://169.254.169.254/latest",
    ):
        with pytest.raises(RefError, match="never fetches"):
            bundle.resolve(ref, "openapi.yaml")


def test_refs_cannot_leave_the_spec_folder() -> None:
    bundle = load(b"openapi: 3.0.3\n", "api/openapi.yaml", files={"api/schemas.yaml": b"A: {}\n"})
    with pytest.raises(RefError, match="leaves"):
        bundle.resolve("../../etc/passwd", "api/openapi.yaml")
    assert bundle.resolve("schemas.yaml#/A", "api/openapi.yaml")[2] == {}


def test_multi_file_refs_resolve_and_missing_files_are_named() -> None:
    bundle = load(
        b"openapi: 3.0.3\n",
        "openapi.yaml",
        files={
            "schemas/pet.yaml": b"Pet:\n  type: object\n  properties:\n    name: {type: string}\n"
        },
    )
    _, pointer, value = bundle.resolve("schemas/pet.yaml#/Pet", "openapi.yaml")
    assert pointer == "/Pet" and value["type"] == "object"
    with pytest.raises(RefError, match="not part of the spec"):
        bundle.resolve("schemas/missing.yaml", "openapi.yaml")
    with pytest.raises(RefError, match="does not exist"):
        bundle.resolve("#/nowhere", "openapi.yaml")


def test_json_pointer_escapes() -> None:
    bundle = load(b'{"a/b": {"c~d": 1}}', "openapi.json")
    assert bundle.resolve("#/a~1b/c~0d", "openapi.json")[2] == 1


def test_zip_bundles_are_read_safely() -> None:
    import io
    import zipfile

    from apiforge.bundles import read_zip

    def make(entries: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        return buf.getvalue()

    _root, name, files = read_zip(
        make({"api/openapi.yaml": b"openapi: 3.0.3\n", "api/s/pet.yaml": b"A: {}\n"})
    )
    assert name == "openapi.yaml" and set(files) == {"openapi.yaml", "s/pet.yaml"}
    with pytest.raises(SpecLoadError, match="no openapi"):
        read_zip(make({"x.yaml": b"a: 1\n"}))
    with pytest.raises(SpecLoadError, match="unsafe"):
        read_zip(make({"openapi.yaml": b"a: 1\n", "../evil.yaml": b"a: 1\n"}))
    with pytest.raises(SpecLoadError, match="not a valid zip"):
        read_zip(b"not a zip")
    bomb = make({"openapi.yaml": b"a: 1\n", "big.yaml": b"0" * (21 * 1024 * 1024)})
    with pytest.raises(SpecLoadError, match="expand"):
        read_zip(bomb)
