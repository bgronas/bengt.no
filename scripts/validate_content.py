#!/usr/bin/env python3
"""Validate source content, a built site, or external links.

  validate_content.py                     source checks (metadata contract, references, images, collisions)
  validate_content.py --allow-pending     as above; `draft: false` + `auto_enrich: true` is reported as
                                          pending instead of failing (pull requests and local checks)
  validate_content.py --site public       checks on Hugo's output: nothing unpublished leaked, no source
                                          files or secrets, originals excluded, social images valid
  validate_content.py --external-links    opt-in, bounded, rate-limited check of external links

Deterministic checks never touch the network. Only --external-links does.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lib import content, mdscan
from lib.common import LoadedPolicy, Report, load_policy, now_local, run_cli, sha256_file
from lib.taxonomy import Taxonomy
from PIL import Image

TEXT_EXTS = (".html", ".xml", ".json", ".css", ".js", ".txt", ".webmanifest", ".svg")
FORBIDDEN_DIRS = (
    "inbox",
    "social-drafts",
    "reports",
    "translation-review",
    ".state",
    "scripts",
    "data",
    "prompts",
    "schemas",
    "tests",
    "docs",
)
FORBIDDEN_SUFFIXES = (".md", ".env", ".py", ".yaml", ".yml", ".toml", ".sh", ".lock")
SECRET_PATTERNS = {
    "anthropic-key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "github-token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
_OG_IMAGE_RE = re.compile(r"<meta\s+property=\"?og:image\"?\s+content=\"?([^\">\s]+)", re.IGNORECASE)


# ---------- source ----------


def eligibility(meta: dict[str, Any], now: datetime) -> str:
    """Why Hugo's production build includes or excludes this article."""
    if meta.get("draft") is not False:
        return "draft"
    start = content.parse_date(meta.get("publishDate")) or content.parse_date(meta.get("date"))
    if start and start > now:
        return "future"
    end = content.parse_date(meta.get("expiryDate"))
    if end and end <= now:
        return "expired"
    return "published"


def check_source(policy: LoadedPolicy, allow_pending: bool) -> tuple[Report, dict[str, Any]]:
    tax = Taxonomy(policy.taxonomy)
    report = Report("validate")
    bundles = content.discover(policy)
    collisions = content.find_collisions(bundles)
    now = now_local(policy.tz())
    overview: dict[str, list[str]] = {
        "published": [], "draft": [], "future": [], "expired": [], "pending_enrichment": [],
        "translation_requested": [], "machine_translation_drafts": [], "missing_alt": [], "social_regenerate": [],
    }  # fmt: skip
    for b in bundles:
        rel = b.rel(policy.root)
        issues = [
            *content.validate_meta(policy, tax, b.meta, allow_pending=allow_pending),
            *content.validate_bundle_files(policy, b),
            *collisions.get(str(b.index), []),
        ]
        state = eligibility(b.meta, now)
        overview[state].append(rel)
        if content.is_true(b.meta.get("auto_enrich")):
            overview["pending_enrichment"].append(rel)
        if content.is_true(b.meta.get("auto_translate")):
            overview["translation_requested"].append(rel)
        if content.is_unreviewed_translation(b.meta):
            overview["machine_translation_drafts"].append(rel)
        if isinstance(b.meta.get("social"), dict) and b.meta["social"].get("regenerate") is True:
            overview["social_regenerate"].append(rel)
        if any(i.code == "alt-missing" for i in issues):
            overview["missing_alt"].append(rel)
        errors = [i for i in issues if i.severity == "error"]
        others = [i for i in issues if i.severity != "error"]
        status = "error" if errors else ("pending" if any(i.severity == "pending" for i in others) else "ok")
        report.add(
            rel,
            status,
            state=state,
            errors=[i.message for i in errors] or None,
            notes=[f"{i.severity}: {i.message}" for i in others] or None,
        )
    report.totals = {k: len(v) for k, v in overview.items()}
    return report, overview


# ---------- built site ----------


def _url_path(policy: LoadedPolicy, lang: str, slug: str) -> str:
    prefix = "" if lang == policy.p.default_language else f"{lang}/"
    return f"{prefix}{policy.p.posts_section}/{slug}/"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def check_site(policy: LoadedPolicy, site: Path, prune: bool) -> Report:
    report = Report("site")
    if not (site / "index.html").is_file():
        report.add(site.as_posix(), "error", reason="no index.html; build the site first")
        return report
    now = now_local(policy.tz())
    bundles = content.discover(policy)
    files = [p for p in site.rglob("*") if p.is_file()]
    text_files = [p for p in files if p.suffix.lower() in TEXT_EXTS]

    # 1. Publication gates.
    listings: dict[str, str] = {}
    for lang in policy.p.languages:
        base = site if lang == policy.p.default_language else site / lang
        blob = []
        for name in (
            "index.html",
            "index.json",
            "index.xml",
            "sitemap.xml",
            "publication-manifest.json",
            f"{policy.p.posts_section}/index.html",
            f"{policy.p.posts_section}/index.xml",
        ):
            blob.append(_read(base / name))
        listings[lang] = "\n".join(blob)
    listings[policy.p.default_language] += _read(site / "publication-manifest.json")
    for b in bundles:
        slug = b.meta.get("slug")
        if not isinstance(slug, str):
            continue
        state = eligibility(b.meta, now)
        path = _url_path(policy, b.lang, slug)
        page = site / path / "index.html"
        rel = b.rel(policy.root)
        if state == "published":
            if not page.is_file():
                report.add(rel, "error", reason=f"published article is missing from the build (expected /{path})")
            continue
        leaks = []
        if page.is_file():
            leaks.append(f"page /{path}")
        if f"/{path}" in listings[b.lang]:
            leaks.append("home page, search index, RSS, sitemap or manifest")
        if leaks:
            report.add(rel, "error", reason=f"{state} article leaked into the production build: {', '.join(leaks)}")

    # 2. Things that must never be served.
    for forbidden in FORBIDDEN_DIRS:
        if (site / forbidden).exists():
            report.add(f"{site.name}/{forbidden}", "error", reason="repository directory was published")
    for p in files:
        if p.suffix.lower() in FORBIDDEN_SUFFIXES or p.name.startswith(".env"):
            report.add(
                p.relative_to(site.parent).as_posix(), "error", reason="source or configuration file type was published"
            )
    default_dir = site / policy.p.default_language
    if default_dir.is_dir() and any(p.suffix == ".html" for p in default_dir.rglob("*")):
        report.add(
            f"{site.name}/{policy.p.default_language}",
            "error",
            reason="default-language pages are duplicated under a language subdirectory",
        )
    cname = site / "CNAME"
    expected_host = urlparse(policy.p.site_origin).hostname or ""
    if not cname.is_file() or cname.read_text(encoding="utf-8") != expected_host + "\n":
        report.add(f"{site.name}/CNAME", "error", reason=f"CNAME must contain exactly {expected_host}")

    # 3. Secrets. Only the pattern name and file are reported, never the match.
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    for p in text_files:
        text = _read(p)
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                report.add(p.relative_to(site.parent).as_posix(), "error", reason=f"possible secret ({name})")
        if key and len(key) >= 12 and key in text:
            report.add(
                p.relative_to(site.parent).as_posix(),
                "error",
                reason="the configured API key value appears in this file",
            )

    # 4. Originals stay out. Processed formats and feature images are served as derivatives only.
    originals: dict[str, str] = {}
    for b in bundles:
        feature = {c.name for c in content.feature_candidates(b.dir)}
        for src in b.dir.rglob("*"):
            if not src.is_file():
                continue
            ext = src.suffix.lower()
            if (
                ext in (".jpg", ".jpeg", ".png")
                or (src.name in feature and ext in content.RASTER_EXTS)
                or src.name == "index.md"
            ):
                originals[sha256_file(src)] = src.relative_to(policy.root).as_posix()
    corpus: str | None = None
    for p in files:
        if p.suffix.lower() not in (*content.RASTER_EXTS, ".md"):
            continue
        source = originals.get(sha256_file(p))
        if not source:
            continue
        url = "/" + p.relative_to(site).as_posix()
        if corpus is None:
            corpus = "\n".join(_read(t) for t in text_files)
        if url in corpus:
            report.add(
                p.relative_to(site.parent).as_posix(),
                "error",
                reason=f"original {source} is published and referenced; it must be delivered as a derivative",
            )
        elif prune:
            p.unlink()
            report.add(
                p.relative_to(site.parent).as_posix(),
                "pruned",
                source=source,
                note="unreferenced original removed from the build output",
            )
        else:
            report.add(
                p.relative_to(site.parent).as_posix(),
                "error",
                reason=f"original {source} is in the build output. Run with --prune-originals",
            )

    # 5. Social images of published articles.
    origin = policy.p.site_origin
    for b in bundles:
        if eligibility(b.meta, now) != "published" or not isinstance(b.meta.get("slug"), str):
            continue
        page = site / _url_path(policy, b.lang, b.meta["slug"]) / "index.html"
        match = _OG_IMAGE_RE.search(_read(page))
        rel = b.rel(policy.root)
        if not match:
            report.add(rel, "error", reason="page has no og:image")
            continue
        url = match.group(1)
        parsed = urlparse(url)
        if f"{parsed.scheme}://{parsed.netloc}" != origin:
            report.add(rel, "error", reason=f"og:image is not on {origin}")
            continue
        target = site / parsed.path.lstrip("/")
        if not target.is_file():
            report.add(rel, "error", reason=f"og:image {parsed.path} does not exist in the build")
            continue
        try:
            with Image.open(target) as img:
                fmt, size = img.format, img.size
        except OSError:
            report.add(rel, "error", reason="og:image is not a readable image")
            continue
        if fmt not in ("JPEG", "PNG") or size != (policy.p.cards.width, policy.p.cards.height):
            report.add(
                rel,
                "error",
                reason=f"og:image is {fmt} {size[0]}x{size[1]}; expected JPEG or PNG at {policy.p.cards.width}x{policy.p.cards.height}",
            )
        else:
            report.add(rel, "ok", og_image=parsed.path, og_format=fmt)
    return report


# ---------- external links ----------


def check_links(policy: LoadedPolicy, client: Any | None = None, sleep: Any = time.sleep) -> Report:
    """Classify external links. Only a 404 or 410 counts as proven missing."""
    import httpx

    cfg = policy.p.external_links
    report = Report("external-links")
    urls: dict[str, list[str]] = {}
    for b in content.discover(policy):
        for link in mdscan.scan(b.body_text).links:
            if re.match(r"^https?://", link.dest):
                urls.setdefault(link.dest.split("#")[0], []).append(b.rel(policy.root))
    ordered = sorted(urls)
    for url in ordered[cfg.max_urls :]:
        report.add(url, "skipped", reason=f"over the per-run limit of {cfg.max_urls} URLs")
    own = client is None
    client = client or httpx.Client(
        timeout=cfg.timeout_seconds, follow_redirects=True, headers={"User-Agent": "bengt.no-link-check/1.0"}
    )
    last_hit: dict[str, float] = {}
    try:
        for url in ordered[: cfg.max_urls]:
            host = urlparse(url).netloc
            wait = cfg.per_host_delay_seconds - (time.monotonic() - last_hit.get(host, 0.0))
            if host in last_hit and wait > 0:
                sleep(wait)
            last_hit[host] = time.monotonic()
            used_by = sorted(set(urls[url]))
            try:
                response = client.head(url)
                if response.status_code in (403, 405, 501):
                    response = client.get(url)
                code = response.status_code
            except httpx.TimeoutException:
                report.add(url, "timeout", used_by=used_by)
                continue
            except httpx.HTTPError as exc:
                report.add(url, "unreachable", used_by=used_by, reason=type(exc).__name__)
                continue
            if code in (404, 410):
                report.add(url, "missing", used_by=used_by, http=code)
            elif code in (401, 403, 429) or code >= 500:
                report.add(url, "inconclusive", used_by=used_by, http=code)
            else:
                report.add(url, "ok", http=code)
    finally:
        if own:
            client.close()
    return report


def write_summary(path: Path, source: Report, overview: dict[str, Any]) -> None:
    lines = ["### Content report", "", "| Item | Count |", "|---|---|"]
    labels = {
        "published": "Published articles", "draft": "Drafts", "future": "Future-dated (excluded until a later deployment)",
        "expired": "Expired", "pending_enrichment": "Waiting for enrichment", "translation_requested": "Translations requested",
        "machine_translation_drafts": "Machine translations awaiting review", "missing_alt": "Articles with images lacking alt text",
        "social_regenerate": "Social draft regeneration requested",
    }  # fmt: skip
    for key, label in labels.items():
        lines.append(f"| {label} | {len(overview[key])} |")
    errors = [i for i in source.items if i["status"] == "error"]
    if errors:
        lines += ["", "**Blocking problems**", ""]
        for item in errors:
            for message in item.get("errors") or []:
                lines.append(f"- `{item['path']}`: {message}")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 valid; 1 problems found; 2 usage or policy error.",
    )
    parser.add_argument(
        "--allow-pending", action="store_true", help="report pending enrichment instead of failing on it"
    )
    parser.add_argument("--site", metavar="DIR", help="validate Hugo's output directory instead of the sources")
    parser.add_argument(
        "--prune-originals",
        action="store_true",
        help="with --site: delete unreferenced original images from the output",
    )
    parser.add_argument("--external-links", action="store_true", help="check external links over the network (opt-in)")
    parser.add_argument(
        "--summary", metavar="FILE", help="append a Markdown summary to FILE (e.g. $GITHUB_STEP_SUMMARY)"
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    policy = load_policy()

    if args.external_links:
        report = check_links(policy)
        report.emit(policy.root, json_out=args.json)
        return 1 if report.count("missing") else 0
    if args.site:
        site = Path(args.site) if Path(args.site).is_absolute() else policy.root / args.site
        report = check_site(policy, site, args.prune_originals)
        report.emit(policy.root, json_out=args.json)
        return 1 if report.count("error") else 0

    report, overview = check_source(policy, args.allow_pending)
    from translate_post import staleness

    stale = staleness(policy, content.discover(policy))
    for item in stale:
        report.add(
            item["path"],
            "stale-translation" if item["status"] == "stale" else "translation-source-missing",
            source=item.get("source"),
        )
    report.totals["stale_translations"] = len(stale)
    report.emit(policy.root, json_out=args.json)
    if args.summary:
        write_summary(Path(args.summary), report, overview)
    return 1 if report.count("error") else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
