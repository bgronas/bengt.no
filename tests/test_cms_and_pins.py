from __future__ import annotations

import json
import tomllib
from pathlib import Path

import policy_schema
import sync_cms_schema
import yaml
from lib.common import load_policy, sha256_file

from tests.conftest import REPO


def cms() -> dict:
    return yaml.safe_load((REPO / ".pages.yml").read_text())


def collection(name: str) -> dict:
    return next(c for c in cms()["content"] if c["name"] == name)


def fields(name: str) -> dict:
    return {f["name"]: f for f in collection(name)["fields"]}


def test_pages_yml_is_generated_from_the_policy() -> None:
    assert sync_cms_schema.main(["--check"]) == 0
    policy = load_policy(REPO)
    for name in ("posts_no", "posts_en", "intake_no", "intake_en"):
        f = fields(name)
        assert f["categories"]["options"]["values"] == list(policy.taxonomy.categories)
        assert f["categories"]["options"]["max"] == 2 and f["categories"]["options"]["multiple"] is True
        assert f["tags"]["options"]["values"] == list(policy.taxonomy.tags.canonical)


def test_drift_is_detected(tmp_path: Path, monkeypatch) -> None:
    from tests.conftest import seed_repo

    root = seed_repo(tmp_path / "r")
    monkeypatch.setenv("BN_ROOT", str(root))
    assert sync_cms_schema.main([]) == 0 and sync_cms_schema.main(["--check"]) == 0
    tax = root / "data/taxonomy-policy.yaml"
    tax.write_text(tax.read_text().replace("    - GitOps\n", "    - GitOps\n    - Networking\n"))
    assert sync_cms_schema.main(["--check"]) == 1


def test_existing_bundles_are_edit_only_and_never_renamed() -> None:
    for name in ("posts_no", "posts_en"):
        c = collection(name)
        assert c["operations"] == {"create": False, "rename": False, "delete": False}
        assert c["view"]["layout"] == "tree" and c["view"]["node"] == {"filename": "index.md", "hideDirs": "nodes"}
        assert c["filename"]["field"] is False, "no filename field: a title edit can never rename a published bundle"
        f = fields(name)
        assert f["slug"]["readonly"] is True and f["translationKey"]["readonly"] is True
        assert f["body"]["type"] == "code" and f["body"]["options"]["format"] == "markdown", "source-mode Markdown"


def test_browser_intake_uses_the_inbox_and_a_media_area_outside_published_paths() -> None:
    config = cms()
    assert [m["input"] for m in config["media"]] == ["inbox/media"]
    for lang in ("no", "en"):
        c = collection(f"intake_{lang}")
        assert c["path"] == f"inbox/{lang}" and c["operations"]["delete"] is False and c["subfolders"] is False
    assert not any(m["input"].startswith(("content", "static", "assets")) for m in config["media"])
    assert config["settings"]["content"]["merge"] is True, "fields the CMS does not show are preserved on save"


def test_internal_state_is_not_exposed_as_editable_fields() -> None:
    text = (REPO / ".pages.yml").read_text()
    for forbidden in ("social_generated", "source_hash", "content_hash", "output_sha256", "input_hash"):
        assert forbidden not in text
    f = fields("posts_en")
    assert {s["name"] for s in f["social"]["fields"]} == {"enabled", "language", "regenerate"}
    assert "translation" not in f and "translation_reviewed" in f, "review status is separate from the draft flag"
    assert {
        "draft",
        "date",
        "lastmod",
        "expiryDate",
        "featured",
        "featured_weight",
        "auto_enrich",
        "auto_translate",
        "summary",
        "series",
        "series_order",
    } <= set(f)
    assert "secret" not in text.lower() and "token" not in text.lower()


def test_cms_actions_are_bound_to_real_workflows() -> None:
    actions = {a["name"]: a for a in cms()["actions"]}
    assert set(actions) == {"run-checks", "process-and-deploy"}
    for action in actions.values():
        workflow = yaml.safe_load((REPO / ".github/workflows" / action["workflow"]).read_text())
        assert "payload" in workflow[True]["workflow_dispatch"]["inputs"], (
            "Pages CMS dispatches with a single payload input"
        )


def test_policy_schema_is_in_sync() -> None:
    assert policy_schema.main(["--check"]) == 0


def test_theme_overrides_still_match_their_upstream_files() -> None:
    data = json.loads((REPO / "data/theme-overrides.json").read_text())
    assert {o["local"] for o in data["overrides"]} == {
        "layouts/partials/head.html",
        "layouts/_default/rss.xml",
        "layouts/_default/index.json",
    }
    for item in data["overrides"]:
        assert (REPO / item["local"]).is_file()
        upstream = REPO / item["upstream"]
        if upstream.exists():
            assert sha256_file(upstream) == item["upstream_sha256"], (
                f"{item['upstream']} changed: re-apply the edits in {item['local']}"
            )


def test_pins_are_consistent() -> None:
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    versions = {p["name"]: p["version"] for p in lock["package"]}
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert f"hugo=={versions['hugo']}" in pyproject["project"]["dependencies"], "Hugo is pinned exactly"
    assert (REPO / ".python-version").read_text().strip() == "3.12"
    gitmodules = (REPO / ".gitmodules").read_text()
    assert "themes/blowfish" in gitmodules and "nunocoracao/blowfish" in gitmodules
    assert not any((REPO / name).exists() for name in ("hugo.toml", "config.toml", "hugo.yaml")), (
        "one configuration location only"
    )


def test_fonts_are_self_hosted_with_licences() -> None:
    fonts = REPO / "assets/fonts"
    for line in (fonts / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        assert sha256_file(fonts / name) == digest
    assert "SIL Open Font License" in (fonts / "LICENSE-Roboto.txt").read_text()
    assert "SIL Open Font License" in (fonts / "LICENSE-RobotoMono.txt").read_text()
    head = (REPO / "layouts/partials/extend-head.html").read_text()
    assert "fonts.googleapis" not in head and "fonts/roboto-latin-wght-normal.woff2" in head
