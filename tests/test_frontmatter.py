from __future__ import annotations

from pathlib import Path

import pytest
from lib import fm
from lib.common import UserError, slugify

RAW = b'---\ntitle: "Hei"   # kommentar\ndraft: true\nsocial:\n  enabled: true\n  language: no\n  regenerate: true\nunknown_field: [1, 2]\n---\n\n  Body with trailing spaces  \n\n```\n---\n```\nno newline at end'


def test_body_is_the_exact_byte_slice() -> None:
    doc = fm.parse(RAW, Path("x.md"))
    assert doc.body == RAW.split(b"---\n", 2)[2]
    assert doc.meta["unknown_field"] == [1, 2]
    assert doc.render() == RAW


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_rewrite_keeps_body_bytes_for_both_line_endings(newline: bytes) -> None:
    raw = RAW.replace(b"\n", newline)
    doc = fm.parse(raw, Path("x.md"))
    out = doc.with_meta({**doc.meta, "title": "Ny tittel"})
    assert out.endswith(doc.body)
    assert fm.parse(out, Path("x.md")).meta["title"] == "Ny tittel"
    assert fm.parse(out, Path("x.md")).body == doc.body


def test_bom_is_preserved() -> None:
    doc = fm.parse(b"\xef\xbb\xbf" + RAW, Path("x.md"))
    assert doc.set_scalars({"draft": False}).startswith(b"\xef\xbb\xbf---\n")


def test_scalar_edit_changes_only_the_target_line() -> None:
    doc = fm.parse(RAW, Path("x.md"))
    out = doc.set_scalars({"draft": False, "social.regenerate": False})
    before, after = RAW.decode().split("\n"), out.decode().split("\n")
    changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert changed == [("draft: true", "draft: false"), ("  regenerate: true", "  regenerate: false")]


def test_scalar_edit_keeps_inline_comment_and_appends_missing_key() -> None:
    doc = fm.parse(RAW, Path("x.md"))
    out = doc.set_scalars({"title": "Ny", "math": True}).decode()
    assert 'title: "Ny"   # kommentar' in out
    assert "math: true\n---\n" in out


def test_language_key_no_is_a_string_not_a_boolean() -> None:
    doc = fm.parse(RAW, Path("x.md"))
    assert doc.meta["social"]["language"] == "no"
    assert fm.parse(doc.with_meta(doc.meta), Path("x.md")).meta["social"]["language"] == "no"


def test_dates_stay_strings() -> None:
    doc = fm.parse(b"---\ndate: 2026-11-13T09:00:00+01:00\n---\nx", Path("x.md"))
    assert doc.meta["date"] == "2026-11-13T09:00:00+01:00"


@pytest.mark.parametrize("raw", [b"+++\ntitle = 'x'\n+++\nbody", b'{"title": "x"}\nbody', b"no front matter"])
def test_unsupported_front_matter_is_rejected_clearly(raw: bytes) -> None:
    with pytest.raises(UserError) as err:
        fm.parse(raw, Path("x.md"))
    assert "x.md" in str(err.value)


def test_save_is_a_noop_when_nothing_changed(tmp_path: Path) -> None:
    path = tmp_path / "x.md"
    path.write_bytes(RAW)
    doc = fm.load(path)
    stamp = path.stat().st_mtime_ns
    assert fm.save(doc, doc.render()) is False
    assert path.stat().st_mtime_ns == stamp


def test_slug_transliteration_is_deterministic() -> None:
    assert slugify("Blåbærsyltetøy på Ærø") == "blabaersyltetoy-pa-aero"
    assert slugify("Grønås") == "gronas"
    assert slugify("  Hello,   World! ") == "hello-world"
    assert slugify("Crème brûlée") == "creme-brulee"
