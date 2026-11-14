#!/usr/bin/env python3
"""Turn Hugo's per-language page lists into the deployed publication manifest.

Hugo decides what is published: layouts/index.publicationmanifest.json lists the
posts it actually rendered for production (drafts, future and expired pages are
never in that list). This script merges the languages, adds a content hash
computed from the source file and the content commit, validates the result
against schemas/publication-manifest.schema.json and writes
<site>/publication-manifest.json. The manifest holds no draft data and no text.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
from lib import fm
from lib.common import LoadedPolicy, UserError, atomic_write, content_hash, dump_json, load_policy, run_cli

MANIFEST_NAME = "publication-manifest.json"


def git_head(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    return out.stdout.strip()


def build(policy: LoadedPolicy, site: Path, commit: str) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    hugo_version = ""
    for lang in policy.p.languages:
        raw_path = (site if lang == policy.p.default_language else site / lang) / MANIFEST_NAME
        if not raw_path.is_file():
            raise UserError(f"{raw_path} is missing. Build the site with Hugo first")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if raw.get("schema_version") == 1:
            raise UserError(
                f"{raw_path} is already a final manifest; rebuild the site before running this script again"
            )
        hugo_version = str(raw.get("hugo_version") or hugo_version)
        for page in raw.get("pages") or []:
            source_rel = f"{policy.p.content_roots[page['lang']]}/{page['content_path']}"
            source = policy.root / source_rel
            if not source.is_file():
                raise UserError(f"Hugo rendered {page['permalink']} but {source_rel} does not exist")
            doc = fm.load(source)
            if doc.meta.get("draft") is not False:
                raise UserError(
                    f"{source_rel} is a draft but appears in a production build. Was Hugo run with --buildDrafts?"
                )
            if not page["permalink"].startswith(policy.p.site_origin + "/"):
                raise UserError(
                    f"{page['permalink']} is not under {policy.p.site_origin}. Build with the production baseURL"
                )
            pages.append(
                {
                    "id": f"{page['lang']}:{page['translation_key']}",
                    "lang": page["lang"],
                    "translation_key": page["translation_key"],
                    "permalink": page["permalink"],
                    "source_path": source_rel,
                    "title": page["title"],
                    "date": page["date"],
                    "lastmod": page["lastmod"],
                    "content_hash": content_hash(doc.meta, doc.body),
                }
            )
    ids = [p["id"] for p in pages]
    if len(ids) != len(set(ids)):
        raise UserError("two published pages share a language and translationKey")
    if commit != "unknown" and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise UserError("--commit must be a full 40-character commit SHA")
    manifest = {
        "schema_version": 1,
        "site_origin": policy.p.site_origin,
        "content_commit": commit,
        "hugo_version": hugo_version,
        "pages": sorted(pages, key=lambda p: p["id"]),
    }
    schema = json.loads((policy.root / "schemas" / "publication-manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", default="public", help="Hugo output directory (default: public)")
    parser.add_argument("--commit", help="content commit the site was built from (default: git HEAD)")
    parser.add_argument(
        "--print", action="store_true", dest="show", help="print the manifest instead of a one-line summary"
    )
    args = parser.parse_args(argv)
    policy = load_policy()
    site = Path(args.site) if Path(args.site).is_absolute() else policy.root / args.site
    manifest = build(policy, site, args.commit or git_head(policy.root))
    atomic_write(site / MANIFEST_NAME, dump_json(manifest))
    for lang in policy.p.languages:
        if lang != policy.p.default_language:
            (site / lang / MANIFEST_NAME).unlink(missing_ok=True)
    if args.show:
        sys.stdout.write(dump_json(manifest).decode("utf-8"))
    else:
        print(f"manifest: {len(manifest['pages'])} published page(s), content commit {manifest['content_commit'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
