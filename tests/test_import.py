from __future__ import annotations

import json
from pathlib import Path

import import_drafts
from lib import fm
from PIL import Image

ROUGH = "# Rough notes on overlays\n\nText with an image: ![diagram](overlay.png)\n\n```bash\necho '![not an image](nope.png)'\n```\ntrailing text without newline"


def _inbox(repo: Path, lang: str = "en", name: str = "rough-notes.md", text: str = ROUGH) -> Path:
    path = repo / "inbox" / lang / name
    path.write_text(text)
    return path


def _asset(repo: Path, rel: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), "teal").save(path)


def _manifest(repo: Path) -> dict:
    return json.loads((repo / "data/import-manifest.json").read_text())["entries"]


def test_rough_draft_imports_once_then_is_a_noop_then_conflicts(repo: Path, capsys) -> None:
    source = _inbox(repo)
    _asset(repo, "inbox/en/rough-notes/overlay.png")
    assert import_drafts.main([]) == 0
    bundle = repo / "content/en/posts/2026-11-13-rough-notes-on-overlays"
    doc = fm.load(bundle / "index.md")
    assert doc.body == ROUGH.encode(), "the Markdown body must be preserved byte for byte"
    assert doc.meta["draft"] is True and doc.meta["auto_enrich"] is True
    assert doc.meta["slug"] == "rough-notes-on-overlays" and doc.meta["date"] == "2026-11-13T10:00:00+01:00"
    assert (bundle / "overlay.png").is_file()
    assert not (bundle / "nope.png").exists(), "image syntax inside a code fence is not a reference"
    assert source.read_text() == ROUGH, "the inbox source stays intact"

    snapshot = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and "reports" not in p.parts}
    assert import_drafts.main([]) == 0
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and "reports" not in p.parts} == snapshot

    source.write_text(ROUGH + "\nedited")
    capsys.readouterr()
    assert import_drafts.main([]) == 1
    assert "conflict" in capsys.readouterr().out
    assert fm.load(bundle / "index.md").body == ROUGH.encode(), "an edited article is never overwritten"

    assert import_drafts.main(["--acknowledge", "inbox/en/rough-notes.md"]) == 0
    assert import_drafts.main([]) == 0


def test_supplied_metadata_is_respected_but_draft_is_forced(repo: Path) -> None:
    _inbox(
        repo, "no", "min.md",
        "---\ntitle: Blåbær på Ærø\nslug: egen-slug\ntranslationKey: delt-nokkel\ndate: 2026-05-17\ndraft: false\ncustom: keep-me\ntags: [Hugo]\n---\nTekst.\n",
    )  # fmt: skip
    assert import_drafts.main([]) == 0
    doc = fm.load(repo / "content/no/posts/2026-05-17-egen-slug/index.md")
    assert doc.meta["title"] == "Blåbær på Ærø" and doc.meta["translationKey"] == "delt-nokkel"
    assert doc.meta["date"] == "2026-05-17T00:00:00+02:00"
    assert doc.meta["draft"] is True, "imported articles stay drafts until marked ready"
    assert doc.meta["custom"] == "keep-me" and doc.meta["tags"] == ["Hugo"]


def test_slug_from_norwegian_title(repo: Path) -> None:
    _inbox(repo, "no", "x.md", "# Blåbærsyltetøy på Ærø\n\nTekst.\n")
    assert import_drafts.main([]) == 0
    assert (repo / "content/no/posts/2026-11-13-blabaersyltetoy-pa-aero/index.md").is_file()


def test_missing_asset_is_an_actionable_error_not_a_broken_link(repo: Path, capsys) -> None:
    _inbox(repo)
    assert import_drafts.main([]) == 1
    out = capsys.readouterr().out
    assert "overlay.png" in out and "inbox/en/rough-notes/" in out
    assert not list((repo / "content/en/posts").iterdir()), "no partial bundle is left behind"
    assert _manifest(repo) == {}


def test_intake_media_and_hero_are_copied(repo: Path) -> None:
    _inbox(repo, text="---\ntitle: With media\nhero: /inbox/media/cover.jpg\n---\n![d](overlay.png)\n")
    _asset(repo, "inbox/media/overlay.png")
    _asset(repo, "inbox/media/cover.jpg")
    assert import_drafts.main([]) == 0
    bundle = repo / "content/en/posts/2026-11-13-with-media"
    assert (bundle / "overlay.png").is_file() and (bundle / "feature.jpg").is_file()
    assert "hero" not in fm.load(bundle / "index.md").meta


def test_ambiguous_asset_is_rejected(repo: Path, capsys) -> None:
    _inbox(repo)
    _asset(repo, "inbox/en/rough-notes/overlay.png")
    Image.new("RGB", (41, 30), "red").save(repo / "inbox/media/overlay.png")
    assert import_drafts.main([]) == 1
    assert "different content" in capsys.readouterr().out


def test_traversal_symlinks_env_files_and_collisions_are_rejected(repo: Path, tmp_path: Path, capsys) -> None:
    _inbox(repo, name="escape.md", text="# Escape\n\n![x](../../../data/secret.png)\n")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n")
    (repo / "inbox/en/link.md").symlink_to(outside)
    (repo / "inbox/en/.env").write_text("ANTHROPIC_API_KEY=abc\n")
    (repo / "inbox/en/notes.txt").write_text("not markdown\n")
    _inbox(repo, name="first.md", text="---\ntitle: Same\nslug: same\n---\nA\n")
    assert import_drafts.main([]) == 1
    out = capsys.readouterr().out
    assert "symlinks are not imported" in out and "only .md files" in out and "relative paths" in out
    assert ".env" not in out
    assert sorted(p.name for p in (repo / "content/en/posts").iterdir()) == ["2026-11-13-same"]

    _inbox(repo, name="second.md", text="---\ntitle: Same again\nslug: same\n---\nB\n")
    assert import_drafts.main([]) == 1
    assert fm.load(repo / "content/en/posts/2026-11-13-same/index.md").body == b"A\n"
    assert not any(p.name == ".env" for p in (repo / "content").rglob("*"))


def test_toml_front_matter_is_rejected(repo: Path, capsys) -> None:
    _inbox(repo, name="toml.md", text="+++\ntitle = 'x'\n+++\nBody\n")
    assert import_drafts.main([]) == 1
    assert "TOML front matter" in capsys.readouterr().out


def test_dry_run_changes_nothing(repo: Path) -> None:
    _inbox(repo, text="# Dry\n")
    assert import_drafts.main(["--dry-run"]) == 0
    assert not list((repo / "content/en/posts").iterdir()) and _manifest(repo) == {}
