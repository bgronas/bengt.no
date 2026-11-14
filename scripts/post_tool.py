#!/usr/bin/env python3
"""Create a new article bundle from the archetype, or mark an article ready.

  post_tool.py new SLUG LANG [--key TRANSLATION_KEY] [--title TITLE]
  post_tool.py ready PATH
  post_tool.py draft PATH

`new` runs `hugo new content` with archetypes/posts/index.md, so the file is a
real archetype instance. `ready` and `draft` change only the `draft` line.
Neither command uses the network.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from lib import content, fm
from lib.common import SLUG_RE, UserError, load_policy, now_local, rfc3339, run_cli, slugify, title_from_slug
from lib.taxonomy import Taxonomy


def cmd_new(args: argparse.Namespace) -> int:
    policy = load_policy()
    if args.lang not in policy.p.languages:
        raise UserError(f"language {args.lang!r} is not configured. Use one of: {', '.join(policy.p.languages)}")
    slug = slugify(args.slug)
    if not slug or not SLUG_RE.match(slug):
        raise UserError(f"{args.slug!r} cannot be turned into a slug. Use lower-case words separated by hyphens")
    if slug != args.slug:
        print(f"note: slug normalised to {slug!r}", file=sys.stderr)
    key = args.key or slug
    if not content.KEY_RE.match(key):
        raise UserError(f"translation key {key!r} must be lower-case letters, digits, hyphens or underscores")
    bundles = content.discover(policy)
    for b in bundles:
        if b.lang == args.lang and b.meta.get("slug") == slug:
            raise UserError(f"slug {slug!r} is already used by {b.rel(policy.root)}")
        if b.lang == args.lang and b.meta.get("translationKey") == key:
            raise UserError(f"translation key {key!r} is already used in {args.lang} by {b.rel(policy.root)}")
    now = now_local(policy.tz())
    target = policy.posts_root(args.lang) / f"{now:%Y-%m-%d}-{slug}"
    if target.exists():
        raise UserError(f"{target.relative_to(policy.root).as_posix()} already exists; nothing was overwritten")
    hugo = shutil.which("hugo")
    if not hugo:
        raise UserError("hugo was not found on PATH. Run ./publish.sh setup")
    env = {
        **os.environ,
        "HUGO_PARAMS_NEW_TITLE": args.title or title_from_slug(slug),
        "HUGO_PARAMS_NEW_DATE": rfc3339(now),
        "HUGO_PARAMS_NEW_SLUG": slug,
        "HUGO_PARAMS_NEW_KEY": key,
    }
    bundle_rel = target.relative_to(policy.root).as_posix()
    rel = f"{bundle_rel}/index.md"
    proc = subprocess.run(
        [hugo, "new", "content", bundle_rel, "--kind", "posts", "--source", str(policy.root)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    index = target / "index.md"
    if proc.returncode != 0 or not index.is_file():
        raise UserError(
            f"hugo new failed: {(proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout).strip() else 'unknown error'}"
        )
    doc = fm.load(index)
    problems = [i for i in content.validate_meta(policy, Taxonomy(policy.taxonomy), doc.meta) if i.severity == "error"]
    if problems:
        shutil.rmtree(target, ignore_errors=True)
        raise UserError("the archetype produced invalid front matter: " + "; ".join(p.message for p in problems))
    print(rel)
    return 0


def _set_draft(path: str, value: bool) -> int:
    policy = load_policy()
    bundle = content.resolve_bundle(policy, path)
    rel = bundle.rel(policy.root)
    if not isinstance(bundle.meta.get("draft"), bool):
        raise UserError(f"{rel}: `draft` must be true or false before it can be changed")
    if not value:
        title = bundle.meta.get("title")
        if not isinstance(title, str) or not title.strip():
            raise UserError(f"{rel}: `title` is empty; add a title before marking the article ready")
        slug = bundle.meta.get("slug")
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            raise UserError(f"{rel}: `slug` is missing or invalid")
        if content.parse_date(bundle.meta.get("date")) is None:
            raise UserError(f"{rel}: `date` is not a valid RFC 3339 timestamp")
        if content.is_unreviewed_translation(bundle.meta):
            raise UserError(
                f"{rel}: this is an unreviewed machine translation. After reviewing it, set "
                "`translation_reviewed: true` in the front matter, then run ready again"
            )
        if not bundle.doc.body.strip():
            raise UserError(f"{rel}: the article body is empty")
    if bundle.meta["draft"] is value:
        print(f"{rel}: already {'a draft' if value else 'ready'} (draft: {str(value).lower()}); nothing changed")
        return 0
    fm.save(bundle.doc, bundle.doc.set_scalars({"draft": value}))
    print(f"{rel}: draft: {str(value).lower()}")
    if not value and content.is_true(bundle.meta.get("auto_enrich")):
        print("note: auto_enrich is true; the deployment workflow will generate missing metadata before publishing.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="create content/<lang>/posts/<today>-<slug>/index.md")
    new.add_argument("slug")
    new.add_argument("lang")
    new.add_argument("--key", help="shared translationKey when this article is a translation of an existing one")
    new.add_argument("--title", help="title; default is derived from the slug")
    ready = sub.add_parser("ready", help="set draft: false (the publication gate)")
    ready.add_argument("path")
    draft = sub.add_parser("draft", help="set draft: true")
    draft.add_argument("path")
    args = parser.parse_args(argv)
    if args.command == "new":
        return cmd_new(args)
    return _set_draft(args.path, args.command == "draft")


if __name__ == "__main__":
    sys.exit(run_cli(main))
