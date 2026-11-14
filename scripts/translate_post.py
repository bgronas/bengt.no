#!/usr/bin/env python3
"""Create a review draft of an article in the other language (no <-> en).

Translation is requested explicitly: by naming a bundle on the command line or
by setting auto_translate: true in its front matter. The result is always a new
bundle with draft: true and translation.state: machine-draft. An existing
translation is never overwritten; --refresh writes a candidate and a diff to
translation-review/ instead.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from lib import content, fm, llm, mdscan, segments
from lib.common import (
    SLUG_RE,
    LoadedPolicy,
    Report,
    UserError,
    as_dict,
    atomic_write,
    is_within,
    load_policy,
    now_local,
    rfc3339,
    run_cli,
    slugify,
)
from lib.taxonomy import Taxonomy

LANG_NAMES = {"no": "Norwegian Bokmål", "en": "British English"}
MAX_ATTEMPTS = 3
COPY_EXTS = (*content.IMAGE_EXTS, ".pdf", ".zip", ".csv", ".txt", ".json", ".yaml", ".yml", ".drawio")
REVIEW_DIR = "translation-review"
CARD_MANIFEST = "data/card-manifest.json"


class TranslationError(Exception):
    """This request failed; the source stays requested so a later run retries it."""


def find_translation(bundles: list[content.Bundle], source: content.Bundle, target_lang: str) -> content.Bundle | None:
    key = source.meta.get("translationKey")
    return next((b for b in bundles if b.lang == target_lang and b.meta.get("translationKey") == key), None)


def staleness(policy: LoadedPolicy, bundles: list[content.Bundle]) -> list[dict[str, str]]:
    """Translations whose recorded source hash no longer matches their source."""
    by_key = {(b.lang, b.meta.get("translationKey")): b for b in bundles}
    out = []
    for b in bundles:
        info = b.meta.get("translation")
        if not isinstance(info, dict) or not info.get("source_hash"):
            continue
        src = by_key.get((str(info.get("source_lang")), b.meta.get("translationKey")))
        if src is None:
            out.append({"path": b.rel(policy.root), "status": "source-missing"})
        elif src.hash != info["source_hash"]:
            out.append(
                {
                    "path": b.rel(policy.root),
                    "status": "stale",
                    "source": src.rel(policy.root),
                    "state": str(info.get("state")),
                }
            )
    return out


def translate_metadata(
    policy: LoadedPolicy, client: llm.Structured, source: content.Bundle, target_lang: str
) -> dict[str, Any]:
    m = policy.p.metadata
    schema = llm.load_schema("translation-metadata.schema.json", policy.root)
    system = llm.load_prompt("translation-system.md", policy.root)
    payload = {
        k: source.meta.get(k) or ("" if k != "keywords" else [])
        for k in ("title", "summary", "description", "keywords")
    }
    feedback = ""
    for _ in range(MAX_ATTEMPTS):
        request = "\n".join(
            [
                "Request type: metadata",
                f"Translate from {LANG_NAMES[source.lang]} to {LANG_NAMES[target_lang]}.",
                f"Terminology to keep consistent: {', '.join(policy.p.translation.glossary)}",
                f"Description length: {m.description_min_chars} to {m.description_max_chars} characters.",
                *([f"Correction required from the previous attempt: {feedback}"] if feedback else []),
                "",
                llm.wrap_untrusted("METADATA", json.dumps(payload, ensure_ascii=False, indent=2)),
            ]
        )
        result = client.call(
            purpose="translation-metadata",
            system=system,
            user=request,
            schema=schema,
            max_tokens=policy.p.translation.metadata_max_output_tokens,
        )
        result["description"] = " ".join(str(result["description"]).split())
        length = len(result["description"])
        if not payload["description"] or m.description_min_chars <= length <= m.description_max_chars:
            return result
        feedback = f"the description was {length} characters; it must be {m.description_min_chars} to {m.description_max_chars}"
    raise llm.InvalidOutput(
        f"translation-metadata: description length still outside policy after {MAX_ATTEMPTS} attempts"
    )


def translate_body(policy: LoadedPolicy, client: llm.Structured, source: content.Bundle, target_lang: str) -> str:
    try:
        plan = segments.build_plan(source.body_text)
    except segments.SegmentationError as exc:
        raise TranslationError(f"unsupported construct: {exc}") from exc
    t = policy.p.translation
    chunks = segments.chunk_segments(plan.segments, t.chunk_chars)
    if len(chunks) > t.max_chunks_per_article:
        raise TranslationError(
            f"article needs {len(chunks)} chunks; the policy allows {t.max_chunks_per_article}. "
            "Nothing was translated (the text is never truncated). Raise translation.max_chunks_per_article or split the article"
        )
    schema = llm.load_schema("translation.schema.json", policy.root)
    system = llm.load_prompt("translation-system.md", policy.root)
    translated: dict[str, str] = {}
    for number, chunk in enumerate(chunks, start=1):
        payload = {"segments": [{"id": s.id, "text": s.text} for s in chunk]}
        feedback = ""
        for attempt in range(MAX_ATTEMPTS):
            request = "\n".join(
                [
                    "Request type: segments",
                    f"Translate from {LANG_NAMES[source.lang]} to {LANG_NAMES[target_lang]}.",
                    f"Article title for context: {source.meta.get('title') or ''}",
                    f"Terminology to keep consistent: {', '.join(t.glossary)}",
                    f"Chunk {number} of {len(chunks)}.",
                    *([f"Correction required from the previous attempt: {feedback}"] if feedback else []),
                    "",
                    llm.wrap_untrusted("SEGMENTS", json.dumps(payload, ensure_ascii=False, indent=2)),
                ]
            )
            result = client.call(
                purpose="translation", system=system, user=request, schema=schema, max_tokens=t.max_output_tokens
            )
            got = {str(s["id"]): str(s["text"]) for s in result["segments"]}
            try:
                if [str(s["id"]) for s in result["segments"]] != [s.id for s in chunk]:
                    raise segments.TokenMismatch("segment ids were dropped, duplicated or reordered")
                for seg in chunk:
                    segments.verify_segment(seg, got[seg.id])
            except segments.TokenMismatch as exc:
                feedback = str(exc)
                if attempt == MAX_ATTEMPTS - 1:
                    raise TranslationError(
                        f"protected syntax was not preserved after {MAX_ATTEMPTS} attempts: {exc}"
                    ) from exc
                continue
            translated.update(got)
            break

    # Internal section links: map source heading anchors to target heading anchors by position.
    draft = segments.reassemble(plan, translated)
    src_scan, dst_scan = mdscan.scan(source.body_text), mdscan.scan(draft)
    src_anchors, dst_anchors = mdscan.heading_anchors(src_scan.headings), mdscan.heading_anchors(dst_scan.headings)
    explicit = {h.explicit_id for h in src_scan.headings if h.explicit_id}
    replacements: dict[str, str] = {}
    for name in plan.dest_tokens:
        original = plan.originals[name]
        dest = original.strip().strip("<>")
        if not dest.startswith("#") or len(dest) == 1:
            continue
        anchor = dest[1:]
        if anchor in explicit:
            continue
        if len(src_anchors) != len(dst_anchors):
            raise TranslationError(
                "the translated text has a different number of headings; internal links cannot be mapped"
            )
        if src_anchors.count(anchor) != 1:
            raise TranslationError(
                f"internal link {dest!r} does not match exactly one heading in the source. "
                "Give the target heading an explicit ID, e.g. `## Heading {#my-id}`, and link to that"
            )
        replacements[name] = original.replace(dest, "#" + dst_anchors[src_anchors.index(anchor)])
    return segments.reassemble(plan, translated, replacements)


def generated_cards(root: Path) -> set[str]:
    path = root / CARD_MANIFEST
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")).get("cards", {}))


def copy_resources(policy: LoadedPolicy, source: content.Bundle, dest: Path) -> list[str]:
    """Copy validated bundle resources. Generated cards, hidden files and symlinks are left out."""
    skipped_cards = generated_cards(policy.root)
    copied: list[str] = []
    for path in sorted(source.dir.rglob("*")):
        rel = path.relative_to(source.dir)
        if path.is_dir() or rel.as_posix() == "index.md":
            continue
        if any(part.startswith(".") for part in rel.parts) or path.is_symlink() or not is_within(path, source.dir):
            continue
        if path.suffix.lower() not in COPY_EXTS or path.stat().st_size > policy.p.limits.max_image_bytes:
            continue
        if f"{source.dir.relative_to(policy.root).as_posix()}/{rel.as_posix()}" in skipped_cards:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(rel.as_posix())
    return copied


def build_target_meta(
    policy: LoadedPolicy, tax: Taxonomy, source: content.Bundle, target_lang: str, meta_tr: dict[str, Any], model: str
) -> dict[str, Any]:
    meta = copy.deepcopy(source.meta)
    slug = slugify(str(meta_tr["slug"]), 60) or slugify(str(meta_tr["title"]), 60)
    if not SLUG_RE.match(slug):
        raise TranslationError("no usable slug could be derived for the translation")
    social = as_dict(meta.get("social"))
    meta.update(
        {
            "title": str(meta_tr["title"]).strip(),
            "lastmod": rfc3339(now_local(policy.tz())),
            "draft": True,
            "slug": slug,
            "auto_translate": False,
            "summary": " ".join(str(meta_tr["summary"]).split()),
            "featured": False,
            "description": meta_tr["description"],
            "keywords": [k.strip() for k in meta_tr["keywords"] if str(k).strip()][: policy.p.taxonomy.keywords_max],
            "social": {"enabled": bool(social.get("enabled", True)), "language": "inherit", "regenerate": False},
            "translation": {
                "state": "machine-draft",
                "source_lang": source.lang,
                "source_path": source.rel(policy.root),
                "source_hash": source.hash,
                "model": model,
                "generated": rfc3339(now_local(policy.tz())),
            },
        }
    )
    meta.pop("featured_weight", None)
    # auto_enrich stays off only when the translated record would pass the publication checks.
    probe = {**meta, "draft": False, "auto_enrich": False, "translation_reviewed": True}
    meta["auto_enrich"] = any(i.severity == "error" for i in content.validate_meta(policy, tax, probe))
    return meta


def translate_one(
    policy: LoadedPolicy,
    tax: Taxonomy,
    client: llm.Structured,
    source: content.Bundle,
    bundles: list[content.Bundle],
    *,
    refresh: bool,
) -> dict[str, Any]:
    target_lang = policy.other_language(source.lang)
    existing = find_translation(bundles, source, target_lang)
    if existing and not refresh:
        return {
            "status": "exists",
            "target": existing.rel(policy.root),
            "reason": "translation exists; explicit refresh required",
        }
    if content.is_unreviewed_translation(source.meta):
        raise TranslationError(
            "this bundle is itself an unreviewed machine translation; translate the original instead"
        )

    meta_tr = translate_metadata(policy, client, source, target_lang)
    body = translate_body(policy, client, source, target_lang)
    meta = build_target_meta(policy, tax, source, target_lang, meta_tr, client.model)
    data = b"---\n" + fm.dump_header(meta).encode("utf-8") + b"---\n" + body.encode("utf-8")

    if existing:
        review = policy.root / REVIEW_DIR / target_lang / existing.dir.name
        candidate = review / "index.candidate.md"
        current = existing.doc.raw.decode("utf-8")
        diff = "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                data.decode("utf-8").splitlines(keepends=True),
                fromfile=existing.rel(policy.root),
                tofile=candidate.relative_to(policy.root).as_posix(),
            )
        )
        atomic_write(candidate, data)
        atomic_write(review / "index.diff", diff.encode("utf-8"))
        return {
            "status": "candidate",
            "target": existing.rel(policy.root),
            "candidate": candidate.relative_to(policy.root).as_posix(),
        }

    posts = policy.posts_root(target_lang)
    target = posts / f"{source.dir.name[:10]}-{meta['slug']}"
    if target.exists() or any(b.lang == target_lang and b.meta.get("slug") == meta["slug"] for b in bundles):
        raise TranslationError(
            f"target slug {meta['slug']!r} is already in use in {target_lang}; nothing was overwritten"
        )
    posts.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-translate-", dir=posts))
    try:
        (tmp / "index.md").write_bytes(data)
        copied = copy_resources(policy, source, tmp)
        tmp.chmod(0o755)
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {
        "status": "translated",
        "target": f"{target.relative_to(policy.root).as_posix()}/index.md",
        "resources": len(copied),
        "auto_enrich": meta["auto_enrich"],
    }


def clear_request(source: content.Bundle) -> None:
    if content.is_true(source.meta.get("auto_translate")):
        fm.save(source.doc, source.doc.set_scalars({"auto_translate": False}))


def main(argv: list[str] | None = None, client: llm.Structured | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exit codes: 0 success or nothing to do; 2 usage or policy error;
3 at least one request failed (it stays requested and is retried on the next run).

Article text of requested translations is sent to the Anthropic API.""",
    )
    parser.add_argument(
        "bundle", nargs="?", help="bundle folder or index.md to translate; default: all with auto_translate: true"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="write a review candidate and diff for an existing translation"
    )
    parser.add_argument("--status", action="store_true", help="report requested and stale translations; no API calls")
    parser.add_argument("--dry-run", action="store_true", help="list what would be translated; no API calls, no writes")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    if args.refresh and not args.bundle:
        parser.error("--refresh requires a bundle")

    policy = load_policy()
    tax = Taxonomy(policy.taxonomy)
    bundles = content.discover(policy)
    report = Report("translate")
    if args.bundle:
        requested = [content.resolve_bundle(policy, args.bundle)]
    else:
        requested = [b for b in bundles if content.is_true(b.meta.get("auto_translate"))]

    if args.status or args.dry_run:
        for b in requested:
            report.add(b.rel(policy.root), "requested", target_lang=policy.other_language(b.lang))
        for item in staleness(policy, bundles):
            report.add(item.pop("path"), item.pop("status"), **item)
        report.emit(policy.root, json_out=args.json, save=False)
        return 0

    if not requested:
        report.emit(policy.root, json_out=args.json)
        return 0
    if not policy.p.translation.enabled:
        for b in requested:
            report.add(b.rel(policy.root), "backlog", reason="translation is disabled in the automation policy")
        report.emit(policy.root, json_out=args.json)
        return 0

    client = client or llm.StructuredClient(policy)
    failed = 0
    stop_reason = ""
    for position, source in enumerate(requested):
        path = source.rel(policy.root)
        if position >= policy.p.translation.max_articles_per_run or stop_reason:
            report.add(path, "backlog", reason=stop_reason or "per-run article cap reached")
            continue
        try:
            result = translate_one(policy, tax, client, source, bundles, refresh=args.refresh)
        except llm.MissingCredentials as exc:
            report.add(path, "failed", reason=str(exc))
            failed += 1
            break
        except llm.BudgetExceeded as exc:
            stop_reason = str(exc)
            report.add(path, "backlog", reason=stop_reason)
            continue
        except (llm.LLMError, TranslationError, UserError) as exc:
            failed += 1
            report.add(path, "failed", reason=str(exc))
            continue
        clear_request(source)
        report.add(path, result.pop("status"), **result)
        bundles = content.discover(policy)
    report.totals = {"usage": client.usage.as_dict(), "model": client.model}
    report.emit(policy.root, json_out=args.json)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
