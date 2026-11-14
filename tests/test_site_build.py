"""Integration tests against a real Hugo production build of the fixture site."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from lib import mdscan
from lib.common import sha256_file
from PIL import Image

from tests.conftest import COMMIT, REPO, hugo_bin

pytestmark = pytest.mark.hugo

NO_POST = "posts/lenket-artikkel/index.html"
EN_POST = "en/posts/linked-article/index.html"
UNPUBLISHED = ("HEMMELIG UTKAST", "FREMTIDIG ARTIKKEL", "UTLØPT ARTIKKEL", "hemmelig-utkast", "fremtidig", "utlopt")


def read(site: dict[str, Any], rel: str) -> str:
    return (site["public"] / rel).read_text(encoding="utf-8")


def test_build_and_site_validation_pass(built_site: dict[str, Any]) -> None:
    check = built_site["site_check"]
    assert check.returncode == 0, check.stdout + check.stderr


def test_norwegian_at_root_english_under_en_and_no_duplicate_no_tree(built_site: dict[str, Any]) -> None:
    public = built_site["public"]
    assert (public / NO_POST).is_file() and (public / EN_POST).is_file()
    assert (public / "om/index.html").is_file() and (public / "en/about/index.html").is_file()
    assert not list((public / "no").rglob("*.html")), "Norwegian pages must not also exist under /no/"
    assert not (public / "posts/2026-10-01-lenket-artikkel").exists(), (
        "the date prefix of the folder is not part of the URL"
    )
    assert "lang=nb" in read(built_site, "index.html")[:300] and "lang=en-GB" in read(built_site, "en/index.html")[:300]
    assert (public / "CNAME").read_text() == "bengt.no\n"


def test_translations_are_linked_and_single_language_posts_are_not(built_site: dict[str, Any]) -> None:
    no, en = read(built_site, NO_POST), read(built_site, EN_POST)
    assert "hreflang=en-GB href=https://bengt.no/en/posts/linked-article/" in no
    assert "hreflang=nb href=https://bengt.no/posts/lenket-artikkel/" in en
    assert "href=/en/posts/linked-article/" in no, "the language switcher links the real translation"
    single = read(built_site, "posts/bare-norsk/index.html")
    assert "hreflang" not in single and "/en/posts/bare-norsk/" not in single
    assert not (built_site["public"] / "en/posts/bare-norsk").exists()
    assert "<link rel=canonical href=https://bengt.no/posts/lenket-artikkel/>" in no


def test_unpublished_pages_are_absent_everywhere(built_site: dict[str, Any]) -> None:
    public = built_site["public"]
    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in public.rglob("*")
        if p.suffix in (".html", ".xml", ".json")
    )
    for needle in UNPUBLISHED:
        assert needle not in corpus, f"{needle!r} leaked into the production build"


def test_search_index_and_rss_are_per_language(built_site: dict[str, Any]) -> None:
    no_index = json.loads(read(built_site, "index.json"))
    en_index = json.loads(read(built_site, "en/index.json"))
    no_links = {item["permalink"] for item in no_index}
    en_links = {item["permalink"] for item in en_index}
    assert "/posts/lenket-artikkel/" in no_links and "/en/posts/linked-article/" in en_links
    assert not any(link.startswith("/en/") for link in no_links) and all(link.startswith("/en/") for link in en_links)
    no_rss, en_rss = read(built_site, "index.xml"), read(built_site, "en/index.xml")
    assert "https://bengt.no/posts/lenket-artikkel/" in no_rss and "linked-article" not in no_rss
    assert "https://bengt.no/en/posts/linked-article/" in en_rss and "lenket-artikkel" not in en_rss
    assert "<language>nb</language>" in no_rss and "<language>en-GB</language>" in en_rss
    sitemap = read(built_site, "sitemap.xml") + read(built_site, "no/sitemap.xml") + read(built_site, "en/sitemap.xml")
    assert "https://bengt.no/posts/lenket-artikkel/" in sitemap


def test_featured_section_is_deterministic_and_excludes_unpublished(built_site: dict[str, Any]) -> None:
    home = read(built_site, "index.html")
    section = home.split("id=bn-featured-title", 1)[1].split("id=bn-recent-title", 1)[0]
    order = re.findall(r"href=/posts/([a-z0-9-]+)/", section)
    assert list(dict.fromkeys(order)) == ["bare-norsk", "lenket-artikkel", "serie-del-en"], (
        "weight 1, weight 2, then unweighted"
    )
    recent = home.split("id=bn-recent-title", 1)[1]
    assert "serie-del-ti" in recent and "bare-norsk" not in recent, "featured articles are not repeated under recent"
    assert "href=/index.xml" in home, "the RSS route is visible on the homepage"


def test_series_uses_numeric_order(built_site: dict[str, Any]) -> None:
    page = read(built_site, "posts/serie-del-ti/index.html")
    block = page.split("Serie A", 1)[1][:3000]
    parts = re.findall(r"Del (\d+):", block)
    assert parts[:3] == ["1", "2", "10"], "numeric order, not the lexical 1, 10, 2"
    assert (built_site["public"] / "series/serie-a/index.html").is_file()


def test_manifest_lists_exactly_the_published_pages(built_site: dict[str, Any]) -> None:
    manifest = built_site["manifest"]
    assert manifest["content_commit"] == COMMIT and manifest["schema_version"] == 1
    ids = [p["id"] for p in manifest["pages"]]
    assert ids == ["en:linked", "no:bare-norsk", "no:linked", "no:serie-del-en", "no:serie-del-ti"]
    assert not (built_site["public"] / "en/publication-manifest.json").exists()
    text = json.dumps(manifest)
    assert "Innledning med et bilde" not in text and "draft" not in text, "no article text and no draft information"
    for page in manifest["pages"]:
        assert page["permalink"].startswith("https://bengt.no/") and page["content_hash"].startswith("sha256:")


def test_pages_carry_the_content_commit_not_some_other_sha(built_site: dict[str, Any]) -> None:
    for rel in (NO_POST, EN_POST, "index.html"):
        assert f'<meta name=x-content-commit content="{COMMIT}">' in read(built_site, rel)


def test_originals_are_excluded_and_derivatives_follow_the_policy(built_site: dict[str, Any]) -> None:
    public, root = built_site["public"], built_site["root"]
    bundle = root / "content/no/posts/2026-10-01-lenket-artikkel"
    out = public / "posts/lenket-artikkel"
    names = sorted(p.name for p in out.iterdir() if p.is_file())
    public_hashes = {sha256_file(p) for p in public.rglob("*") if p.is_file()}
    for original in ("photo.jpg", "small.jpg", "shot.png", "feature.webp", "index.md", "unlinked.txt"):
        assert sha256_file(bundle / original) not in public_hashes, f"{original} must not be published"
    assert "unlinked.txt" not in names and "notes.txt" in names, "an attachment is published only when linked"

    html = read(built_site, NO_POST)
    photo = [p for p in out.iterdir() if p.name.startswith("photo_")]
    assert photo and all(max(Image.open(p).size) <= 1920 for p in photo), "nothing above the 1920 px policy"
    largest = max(photo, key=lambda p: Image.open(p).size[1])
    with Image.open(largest) as img:
        assert img.size == (1440, 1920), "EXIF orientation applied: the landscape pixels are delivered as portrait"
        assert img.convert("RGB").getpixel((720, 100))[0] > 150, "red half is at the top after rotation"
    for p in photo:
        with Image.open(p) as img:
            exif = img.getexif()
            assert not exif.get_ifd(0x8825) and 0x010F not in exif, f"{p.name} still carries EXIF or GPS"
    assert {p.suffix for p in photo} == {".webp", ".jpg"} and "<source type=image/webp" in html

    small = [p for p in out.iterdir() if p.name.startswith("small_")]
    assert small and all(Image.open(p).size == (400, 300) for p in small), "a small photo is never upscaled"

    shots = [p for p in out.iterdir() if p.name.startswith("shot_")]
    assert {p.suffix for p in shots} == {".webp", ".png"}
    for p in shots:
        with Image.open(p) as img:
            rgba = img.convert("RGBA")
            assert rgba.getpixel((5, 5))[3] == 0, "transparency survives"
            scale = img.width / 1200
            assert rgba.getpixel((int(600 * scale), int(400 * scale)))[:3] == (250, 248, 244), (
                "screenshots are lossless"
            )

    with Image.open(out / "anim.gif") as gif:
        assert getattr(gif, "is_animated", False) and gif.n_frames == 3, "animation is kept"
    assert sha256_file(out / "anim.gif") == sha256_file(bundle / "anim.gif")
    assert (out / "diagram.svg").read_text() == (bundle / "diagram.svg").read_text(), (
        "SVG is served as is, never rasterised"
    )
    assert re.search(
        r"<img src=/posts/lenket-artikkel/diagram\.svg alt=Vektordiagram loading=lazy decoding=async width=320 height=120>",
        html,
    )
    assert "width=1440 height=1920" in html and "loading=lazy" in html
    assert "<figcaption>Et foto</figcaption>" in html


def test_originals_were_pruned_by_the_site_check_not_by_luck(built_site: dict[str, Any]) -> None:
    pruned = [i for i in built_site["site_report"]["items"] if i["status"] == "pruned"]
    assert all(i["path"].endswith(("feature.webp", ".jpg", ".png")) for i in pruned)
    assert not [i for i in built_site["site_report"]["items"] if i["status"] == "error"]


def test_code_fence_with_image_syntax_is_rendered_as_code(built_site: dict[str, Any]) -> None:
    html = read(built_site, NO_POST)
    assert "finnes-ikke.png" in html and "<img" not in html.split("finnes-ikke.png")[0][-400:]
    assert not list(built_site["public"].rglob("finnes-ikke*"))


def test_math_and_mermaid_assets_load_only_where_needed(built_site: dict[str, Any]) -> None:
    math, mermaid, plain = (
        read(built_site, f"posts/{slug}/index.html") for slug in ("bare-norsk", "serie-del-en", "serie-del-ti")
    )
    assert "katex.min" in math and "class=katex" in math and "<math" in math
    assert "$50" in math and "$75" in math, "prices are plain text"
    assert "<code>$x$</code>" in math, "math-looking code stays code"
    assert "mermaid.bundle" not in math
    assert "mermaid.bundle" in mermaid and '<pre class="not-prose mermaid"' in mermaid and "katex.min" not in mermaid
    assert "mermaid.bundle" not in plain and "katex.min" not in plain
    home = read(built_site, "index.html")
    assert "mermaid.bundle" not in home and "katex.min" not in home


def test_social_metadata_uses_a_real_jpeg_and_separate_description(built_site: dict[str, Any]) -> None:
    html = read(built_site, NO_POST)
    og = re.search(r'<meta property="og:image" content="(https://bengt\.no/[^"]+)"', html)
    assert og and og.group(1).endswith(".jpg")
    with Image.open(built_site["public"] / og.group(1).removeprefix("https://bengt.no/")) as img:
        assert img.format == "JPEG" and img.size == (1200, 630)
    assert '<meta property="og:image:type" content="image/jpeg">' in html
    assert re.search(r'<meta name="?twitter:card"? content="summary_large_image">', html)
    description = re.search(r'<meta name=description content="([^"]+)"', html).group(1)
    assert description.startswith("Norsk beskrivelse") and 150 <= len(description) <= 160
    assert "Et sammendrag som er formulert annerledes" in read(built_site, "posts/index.html"), "cards use the summary"
    assert "Et sammendrag som er formulert annerledes" not in description
    home = read(built_site, "index.html")
    default = re.search(r'<meta property="og:image" content="https://bengt\.no/([^"]+)"', home).group(1)
    with Image.open(built_site["public"] / default) as img:
        assert img.format == "PNG" and img.size == (1200, 630), "the site default is PNG, not SVG"


def test_no_analytics_cookies_or_third_party_requests(built_site: dict[str, Any]) -> None:
    for rel in ("index.html", NO_POST, "en/index.html"):
        html = read(built_site, rel)
        hosts = set(re.findall(r'(?:src|href)=["\']?(https?://[^/"\'\s>]+)', html))
        assert hosts <= {
            "https://bengt.no",
            "https://github.com",
            "https://linkedin.com",
            "https://www.linkedin.com",
            "https://x.com",
            "https://twitter.com",
            "https://bsky.app",
            "https://gohugo.io",
            "https://blowfish.page",
        }, hosts
        scripts = set(re.findall(r"<script[^>]*src=([^\s>]+)", html))
        assert all(s.strip("\"'").startswith("/") for s in scripts), "only first-party scripts"
        assert "google-analytics" not in html and "document.cookie" not in html


def test_no_repository_internals_in_the_output(built_site: dict[str, Any]) -> None:
    public = built_site["public"]
    for forbidden in ("inbox", "social-drafts", "reports", "data", "scripts", "prompts", "schemas"):
        assert not (public / forbidden).exists()
    assert not list(public.rglob("*.md")) and not list(public.rglob(".env*")) and not list(public.rglob("*.py"))
    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in public.rglob("*")
        if p.suffix in (".html", ".json", ".xml", ".js")
    )
    assert "sk-ant-" not in corpus and "ANTHROPIC_API_KEY" not in corpus


def test_not_found_page_offers_navigation_without_article_titles(built_site: dict[str, Any]) -> None:
    for rel, word in (("404.html", "Fant ikke siden"), ("en/404.html", "Page not found")):
        html = read(built_site, rel)
        assert word in html and "bn-404-search" in html
        assert "Lenket artikkel" not in html and "Linked article" not in html


def test_heading_anchor_model_matches_hugo(built_site: dict[str, Any]) -> None:
    html = read(built_site, NO_POST)
    body = (
        (built_site["root"] / "content/no/posts/2026-10-01-lenket-artikkel/index.md").read_text().split("---\n", 2)[2]
    )
    for anchor in mdscan.heading_anchors(mdscan.scan(body).headings):
        assert f"id={anchor}" in html or f'id="{anchor}"' in html
    assert "href=/posts/lenket-artikkel/#en-tabell" in html


def test_title_edit_changes_neither_url_nor_bundle_path(built_site: dict[str, Any], tmp_path: Path) -> None:
    root = tmp_path / "site"
    shutil.copytree(built_site["root"], root, symlinks=True, ignore=shutil.ignore_patterns("public", "resources"))
    index = root / "content/no/posts/2026-10-05-serie-del-ti/index.md"
    index.write_text(index.read_text().replace("title: Serie del ti", "title: En helt annen tittel"))
    build = subprocess.run([hugo_bin(), "--source", str(root), "--quiet"], capture_output=True, text=True, check=False)
    assert build.returncode == 0, build.stderr
    page = root / "public/posts/serie-del-ti/index.html"
    assert page.is_file() and "En helt annen tittel" in page.read_text()
    assert not (root / "public/posts/en-helt-annen-tittel").exists()


def test_missing_image_fails_the_build(built_site: dict[str, Any], tmp_path: Path) -> None:
    root = tmp_path / "site"
    shutil.copytree(built_site["root"], root, symlinks=True, ignore=shutil.ignore_patterns("public", "resources"))
    index = root / "content/no/posts/2026-10-05-serie-del-ti/index.md"
    index.write_text(index.read_text() + "\n![borte](borte.png)\n")
    build = subprocess.run([hugo_bin(), "--source", str(root)], capture_output=True, text=True, check=False)
    assert build.returncode != 0 and "borte.png" in (build.stdout + build.stderr)


def test_draft_build_is_possible_without_an_api_key(tmp_path: Path) -> None:
    out = tmp_path / "preview"
    env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
    build = subprocess.run(
        [hugo_bin(), "--source", str(REPO), "--buildDrafts", "--destination", str(out), "--quiet"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    assert (out / "posts/slik-publiseres-dette-nettstedet/index.html").is_file()
    assert (out / "en/posts/how-this-site-is-published/index.html").is_file()
