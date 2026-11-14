#!/usr/bin/env python3
"""Turn rough Markdown files in inbox/<lang>/ into page bundles.

  inbox/en/my-notes.md  ->  content/en/posts/<YYYY-MM-DD>-<slug>/index.md

The inbox file is never modified or removed. data/import-manifest.json records
source path, source hash and target bundle, which makes reruns a no-op and turns
a later edit of an already imported source into a reported conflict instead of
an overwrite. Imported articles are always draft: true.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from lib import content, fm, mdscan
from lib.common import (
    SLUG_RE,
    LoadedPolicy,
    Report,
    UserError,
    as_dict,
    atomic_write,
    dump_json,
    is_within,
    load_policy,
    now_local,
    rfc3339,
    run_cli,
    sha256_file,
    sha256_text,
    sha256_text_file,
    slugify,
    title_from_slug,
)

MANIFEST = "data/import-manifest.json"
ASSET_EXTS = (*content.IMAGE_EXTS, ".pdf", ".zip", ".csv", ".txt", ".json", ".yaml", ".yml", ".drawio")
_H1_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    if not path.exists():
        return {"version": 1, "entries": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("entries"), dict):
        raise UserError(f"{MANIFEST} has an unexpected structure; restore it from Git")
    return dict(data)


def inbox_files(policy: LoadedPolicy, report: Report) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for lang in policy.p.languages:
        root = policy.inbox_root(lang)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            rel = child.relative_to(policy.root).as_posix()
            if child.name.startswith(".") or child.is_dir():
                continue
            if child.is_symlink() or not is_within(child, root):
                report.add(rel, "rejected", reason="symlinks are not imported")
                continue
            if child.suffix.lower() != ".md":
                report.add(rel, "rejected", reason="only .md files are imported from the inbox")
                continue
            found.append((lang, child))
    return found


def normalise_date(value: Any, fallback: datetime, tz: Any) -> str:
    if isinstance(value, str) and _DATE_ONLY_RE.match(value.strip()):
        y, m, d = (int(x) for x in value.strip().split("-"))
        return rfc3339(datetime(y, m, d, 0, 0, 0, tzinfo=tz))
    parsed = content.parse_date(value)
    return str(value).strip() if parsed else rfc3339(fallback)


def build_meta(
    policy: LoadedPolicy, lang: str, source: Path, meta: dict[str, Any], body: str, notes: list[str]
) -> dict[str, Any]:
    """Mechanical metadata only. Nothing here calls an API."""
    now = now_local(policy.tz())
    title = str(meta.get("title") or "").strip()
    if not title:
        heading = _H1_RE.search(mdscan.strip_code(body))
        if heading:
            title = heading.group(1).strip()
            notes.append("title taken from the first heading; that heading is still in the body")
        else:
            title = title_from_slug(slugify(source.stem))
            notes.append("title derived from the file name")
    slug = meta.get("slug")
    if not (isinstance(slug, str) and SLUG_RE.match(slug)):
        if slug:
            notes.append(f"supplied slug {slug!r} was not portable and has been regenerated")
        slug = slugify(title) or slugify(source.stem)
    if not slug:
        raise UserError("cannot derive a slug: give the file a title or a plain file name")
    date = normalise_date(meta.get("date"), now, policy.tz())
    key = meta.get("translationKey")
    if not (isinstance(key, str) and content.KEY_RE.match(key)):
        key = slug
    if meta.get("draft") is False:
        notes.append("draft: false in the source was ignored; imported articles start as drafts")

    def boolean(name: str, default: bool) -> bool:
        return meta[name] if isinstance(meta.get(name), bool) else default

    def listing(name: str) -> list[Any]:
        value = meta.get(name)
        return list(value) if isinstance(value, list) else []

    social = as_dict(meta.get("social"))
    out: dict[str, Any] = {
        "title": title,
        "date": date,
        "lastmod": normalise_date(meta.get("lastmod"), datetime.fromisoformat(date), policy.tz()),
        "draft": True,
        "slug": slug,
        "translationKey": key,
        "auto_enrich": boolean("auto_enrich", True),
        "auto_translate": boolean("auto_translate", False),
        "summary": str(meta.get("summary") or ""),
        "math": boolean("math", False),
        "mermaid": boolean("mermaid", False),
        "featured": boolean("featured", False),
        "description": str(meta.get("description") or ""),
        "keywords": listing("keywords"),
        "categories": listing("categories"),
        "tags": listing("tags"),
        "series": listing("series"),
        "series_order": meta.get("series_order") if isinstance(meta.get("series_order"), int) else None,
        "social": {
            "enabled": social.get("enabled") if isinstance(social.get("enabled"), bool) else True,
            "language": social.get("language")
            if social.get("language") in ("inherit", *policy.p.languages)
            else "inherit",
            "regenerate": False,
        },
    }
    for key_name, value in meta.items():
        if key_name not in out and key_name not in ("hero", "media"):
            out[key_name] = value
    return out


def resolve_asset(policy: LoadedPolicy, source: Path, ref: str) -> Path:
    """Find a referenced file in the adjacent folder or the intake media area."""
    clean = ref.split("#")[0].split("?")[0].removeprefix("./")
    parts = Path(clean).parts
    if not clean or Path(clean).is_absolute() or ".." in parts or "\\" in clean:
        raise UserError(f"asset {ref!r}: only plain relative paths inside the article folder are imported")
    if Path(clean).suffix.lower() not in ASSET_EXTS or Path(clean).name.startswith("."):
        raise UserError(f"asset {ref!r}: file type is not on the import allowlist ({', '.join(ASSET_EXTS)})")
    adjacent_dir = source.with_suffix("")
    media_dir = policy.root / policy.p.intake_media_dir
    candidates = [adjacent_dir / clean]
    if len(parts) == 1:
        candidates.append(media_dir / clean)
    found = []
    for cand, base in zip(candidates, (adjacent_dir, media_dir), strict=False):
        if cand.is_symlink() or any(p.is_symlink() for p in cand.parents if is_within(p, base) and p != base):
            raise UserError(f"asset {ref!r}: symlinks are not imported")
        if cand.is_file() and is_within(cand, base):
            found.append(cand)
    if not found:
        where = f"{adjacent_dir.relative_to(policy.root).as_posix()}/"
        extra = f" or {policy.p.intake_media_dir}/" if len(parts) == 1 else ""
        raise UserError(f"asset {ref!r} was not found. Put it in {where}{extra} and run the import again")
    if len(found) == 2 and sha256_file(found[0]) != sha256_file(found[1]):
        raise UserError(
            f"asset {ref!r} exists in both the adjacent folder and {policy.p.intake_media_dir}/ with different content. Remove one"
        )
    if found[0].stat().st_size > policy.p.limits.max_image_bytes:
        raise UserError(f"asset {ref!r} is larger than {policy.p.limits.max_image_bytes} bytes")
    return found[0]


def import_one(policy: LoadedPolicy, lang: str, source: Path, dry_run: bool) -> dict[str, Any]:
    raw = source.read_bytes()
    if len(raw) > policy.p.limits.max_markdown_bytes:
        raise UserError(f"file is {len(raw)} bytes; the limit is {policy.p.limits.max_markdown_bytes}")
    notes: list[str] = []
    stripped = raw.lstrip(b"\xef\xbb\xbf").lstrip()
    if stripped.startswith((b"+++", b"{")) or fm.has_front_matter(raw):
        doc = fm.parse(raw, source)
        meta_in, body = doc.meta, doc.body
    else:
        meta_in, body = {}, raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserError("file is not valid UTF-8") from exc
    meta = build_meta(policy, lang, source, meta_in, text, notes)

    assets: list[tuple[str, Path]] = []
    scan = mdscan.scan(text)
    refs = [i.dest for i in scan.images if mdscan.is_local(i.dest)] + [
        link.dest for link in scan.links if mdscan.is_local(link.dest) and Path(link.dest.split("#")[0]).suffix
    ]
    for ref in dict.fromkeys(refs):
        target_rel = ref.split("#")[0].split("?")[0].removeprefix("./")
        assets.append((target_rel, resolve_asset(policy, source, ref)))
    hero = meta_in.get("hero")
    if isinstance(hero, str) and hero.strip():
        hero_src = resolve_asset(policy, source, Path(hero).name)
        if hero_src.suffix.lower() not in content.RASTER_EXTS:
            raise UserError(f"hero {hero!r} must be a JPEG, PNG or WebP image")
        assets.append((f"feature{hero_src.suffix.lower()}", hero_src))
        notes.append(f"hero image copied as feature{hero_src.suffix.lower()}")

    bundle_name = f"{meta['date'][:10]}-{meta['slug']}"
    posts = policy.posts_root(lang)
    target = posts / bundle_name
    if target.exists():
        raise UserError(
            f"target bundle {target.relative_to(policy.root).as_posix()} already exists; nothing was overwritten. Change the slug in the source"
        )
    for existing in content.discover(policy, (lang,)):
        if existing.meta.get("slug") == meta["slug"]:
            raise UserError(
                f"slug {meta['slug']!r} is already used by {existing.rel(policy.root)}; change the slug in the source"
            )

    result = {
        "bundle": f"{target.relative_to(policy.root).as_posix()}/index.md",
        "source_sha256": sha256_text(raw),
        "assets": [
            {"source": src.relative_to(policy.root).as_posix(), "target": rel, "sha256": sha256_file(src)}
            for rel, src in sorted(assets, key=lambda a: a[0])
        ],
        "notes": notes,
    }
    if dry_run:
        return result

    posts.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-import-", dir=posts))
    try:
        header = fm.dump_header(meta)
        (tmp / "index.md").write_bytes(b"---\n" + header.encode("utf-8") + b"---\n" + body)
        for rel, src in assets:
            dest = tmp / rel
            if not is_within(dest, tmp):
                raise UserError(f"asset target {rel!r} escapes the bundle")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        tmp.chmod(0o755)
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 success or nothing to do; 1 conflicts or rejected files; 2 usage or policy error.",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would be imported; change nothing")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--acknowledge",
        metavar="INBOX_FILE",
        action="append",
        default=[],
        help="accept the current content of an already imported inbox file as the new baseline. "
        "The bundle is not touched. Use this after copying the changes into the bundle by hand.",
    )
    args = parser.parse_args(argv)
    policy = load_policy()
    manifest = load_manifest(policy.root)
    entries: dict[str, Any] = manifest["entries"]
    report = Report("import")
    changed = False
    acknowledged = {Path(a).as_posix().lstrip("./") for a in args.acknowledge}

    for lang, source in inbox_files(policy, report):
        rel = source.relative_to(policy.root).as_posix()
        digest = sha256_text_file(source)
        known = entries.get(rel)
        if known:
            if known["source_sha256"] == digest:
                status = "unchanged" if (policy.root / known["bundle"]).exists() else "unchanged-bundle-removed"
                report.add(rel, status, bundle=known["bundle"])
            elif rel in acknowledged:
                if not args.dry_run:
                    known["source_sha256"] = digest
                    changed = True
                report.add(rel, "acknowledged", bundle=known["bundle"])
            else:
                report.add(
                    rel,
                    "conflict",
                    bundle=known["bundle"],
                    reason="the inbox file changed after it was imported. Edit the bundle instead; then run "
                    f"./publish.sh import --acknowledge {rel}",
                )
            continue
        try:
            result = import_one(policy, lang, source, args.dry_run)
        except UserError as exc:
            report.add(rel, "rejected", reason=str(exc))
            continue
        notes = result.pop("notes")
        if not args.dry_run:
            entries[rel] = result
            changed = True
        report.add(
            rel,
            "would-import" if args.dry_run else "imported",
            bundle=result["bundle"],
            assets=len(result["assets"]),
            notes=notes,
        )

    if changed:
        atomic_write(policy.root / MANIFEST, dump_json(manifest))
    report.emit(policy.root, json_out=args.json, save=not args.dry_run)
    return 1 if (report.count("conflict") or report.count("rejected")) else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
