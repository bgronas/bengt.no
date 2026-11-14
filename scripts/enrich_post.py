#!/usr/bin/env python3
"""Generate missing publication metadata for articles that opted in with auto_enrich: true.

Guarantees:
  * The Markdown body is never modified; the header is replaced and the original
    body bytes are re-attached (see scripts/lib/fm.py).
  * A file is written only after the complete record validates locally, in one
    atomic rename. Any failure leaves the file byte-identical.
  * Authored values are kept. --force is the only way to regenerate them.
  * With no eligible work the script exits 0 and never asks for an API key.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

from lib import content, fm, llm
from lib.common import LoadedPolicy, Report, UserError, is_within, load_policy, run_cli, sha256_bytes
from lib.taxonomy import Taxonomy

MAX_ATTEMPTS = 3
GENERATED_FIELDS = ("description", "summary", "keywords", "categories", "tags")


def collect(policy: LoadedPolicy, targets: list[str]) -> list[content.Bundle]:
    """Resolve targets to bundles. A target is a bundle, its index.md, or a content root."""
    if not targets:
        return content.discover(policy)
    bundles: list[content.Bundle] = []
    for target in targets:
        path = Path(target) if Path(target).is_absolute() else policy.root / target
        matched_root = False
        for lang in policy.p.languages:
            if path.resolve() in (policy.content_root(lang).resolve(), policy.posts_root(lang).resolve()):
                bundles.extend(content.discover(policy, (lang,)))
                matched_root = True
        if matched_root:
            continue
        if path.is_dir() and not any(is_within(path, policy.posts_root(lang)) for lang in policy.p.languages):
            raise UserError(f"{target}: not a configured content root ({', '.join(policy.p.content_roots.values())})")
        bundles.append(content.resolve_bundle(policy, target))
    unique = {b.index.resolve(): b for b in bundles}
    return [unique[k] for k in sorted(unique)]


def build_request(policy: LoadedPolicy, tax: Taxonomy, bundle: content.Bundle, feedback: str = "") -> str:
    meta = bundle.meta
    existing = {k: meta.get(k) for k in ("title", *GENERATED_FIELDS, "series", "series_order") if meta.get(k)}
    lines = [
        f"Article language: {'Norwegian Bokmål' if bundle.lang == 'no' else 'British English'} ({bundle.lang})",
        f"Title is empty: {'yes' if not str(meta.get('title') or '').strip() else 'no'}",
        f"Allowed categories: {', '.join(tax.categories)}",
        f"Canonical tags: {', '.join(tax.canonical_tags)}",
        f"Description length: {policy.p.metadata.description_min_chars} to {policy.p.metadata.description_max_chars} characters",
        f"Existing metadata decided by the author: {existing if existing else 'none'}",
    ]
    if feedback:
        lines.append(f"Correction required from the previous attempt: {feedback}")
    lines.append("")
    lines.append(llm.wrap_untrusted("ARTICLE", f"# {meta.get('title') or ''}\n\n{bundle.body_text}"))
    return "\n".join(lines)


def merge(
    policy: LoadedPolicy, tax: Taxonomy, bundle: content.Bundle, result: dict[str, Any], force: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Combine authored metadata with the model's proposal. Returns (meta, notes)."""
    meta = copy.deepcopy(bundle.meta)
    notes: dict[str, Any] = {"written": []}
    t = policy.p.taxonomy

    def take(field: str, value: Any) -> None:
        if value in ("", [], None):
            return
        if force or not meta.get(field):
            if meta.get(field) != value:
                notes["written"].append(field)
            meta[field] = value

    if not str(meta.get("title") or "").strip():
        take("title", str(result["title"]).strip())
    take("description", " ".join(str(result["description"]).split()))
    take("summary", " ".join(str(result["summary"]).split()))
    keywords = list(dict.fromkeys(k.strip() for k in result["keywords"] if k.strip()))[: t.keywords_max]
    take("keywords", keywords)
    cats = list(dict.fromkeys(c for c in (tax.category(x) for x in result["categories"]) if c))[: t.categories_max]
    take("categories", cats)
    tag_result = tax.normalise_tags(list(result["tags"]))
    take("tags", tag_result.tags[: t.tags_max])
    if tag_result.unknown:
        notes["proposed_tags"] = sorted(tag_result.unknown)
    if tag_result.ambiguous:
        notes["ambiguous_tags_dropped"] = sorted(tag_result.ambiguous)

    series = str(result.get("series") or "").strip()
    order = int(result.get("series_order") or 0)
    if series and not meta.get("series"):
        haystack = f"{meta.get('title') or ''}\n{bundle.body_text}".casefold()
        if order >= 1 and series.casefold() in haystack:
            meta["series"] = [series]
            meta["series_order"] = order
            notes["written"].extend(["series", "series_order"])
        else:
            notes["series_proposal_ignored"] = series
    return meta, notes


def enrich_one(
    policy: LoadedPolicy, tax: Taxonomy, client: llm.Structured, bundle: content.Bundle, *, force: bool
) -> dict[str, Any]:
    pre = [
        i
        for i in content.validate_meta(policy, tax, bundle.meta, allow_pending=True)
        if i.severity == "error" and not i.code.startswith(("enrichment", "translation-unreviewed"))
    ]
    if pre and not force:
        raise UserError("; ".join(i.message for i in pre))
    schema = llm.load_schema("metadata.schema.json", policy.root)
    schema["properties"]["categories"]["items"] = {"type": "string", "enum": list(tax.categories)}
    system = llm.load_prompt("metadata-system.md", policy.root)
    m = policy.p.metadata
    feedback = ""
    last_error = ""
    for _attempt in range(MAX_ATTEMPTS):
        result = client.call(
            purpose="metadata",
            system=system,
            user=build_request(policy, tax, bundle, feedback),
            schema=schema,
            max_tokens=policy.p.enrichment.max_output_tokens,
        )
        meta, notes = merge(policy, tax, bundle, result, force)
        meta["auto_enrich"] = False
        problems = [
            i
            for i in content.validate_meta(policy, tax, {**meta, "draft": False})
            if i.severity == "error" and i.code != "translation-unreviewed"
        ]
        if not problems:
            if meta.get("summary") and meta.get("summary") == meta.get("description"):
                problems = [content.Issue("error", "summary", "summary must differ from the description")]
            else:
                notes["meta"] = meta
                return notes
        last_error = "; ".join(p.message for p in problems)
        authored = bundle.meta.get("description")
        if any(p.code == "description-length" for p in problems) and authored and not force:
            raise UserError(last_error)
        length = len(str(result.get("description", "")))
        feedback = (
            f"the description was {length} characters; it must be between {m.description_min_chars} and "
            f"{m.description_max_chars}. Other problems: {last_error}"
        )
    raise llm.InvalidOutput(f"metadata: no valid result after {MAX_ATTEMPTS} attempts ({last_error})")


def main(argv: list[str] | None = None, client: llm.Structured | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exit codes: 0 success or nothing to do; 1 --check found pending work;
2 usage or policy error; 3 at least one article failed (files left unchanged).

Draft text of opted-in articles is sent to the Anthropic API. API usage is
billed to the API key's account, separately from any Claude subscription.""",
    )
    parser.add_argument("targets", nargs="*", help="index.md, bundle folder or content root; default: all bundles")
    parser.add_argument("--dry-run", action="store_true", help="list what would be processed; no API calls, no writes")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if any article is waiting for enrichment; no API calls"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="process the named targets even without auto_enrich: true and overwrite description, summary, "
        "keywords, categories and tags. Title and slug are never overwritten. Requires explicit targets.",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    if args.force and not args.targets:
        parser.error("--force requires explicit targets")

    policy = load_policy()
    tax = Taxonomy(policy.taxonomy)
    report = Report("enrich")
    bundles = collect(policy, args.targets)
    eligible = [b for b in bundles if content.is_true(b.meta.get("auto_enrich")) or args.force]
    for b in bundles:
        value = b.meta.get("auto_enrich")
        if value is not True and value is not False and value is not None and not args.force:
            report.add(b.rel(policy.root), "skipped", reason=f"auto_enrich is {value!r}; only the boolean true opts in")

    if args.check or args.dry_run:
        for b in eligible:
            report.add(b.rel(policy.root), "pending", source_hash=sha256_bytes(b.doc.raw))
        report.emit(policy.root, json_out=args.json, save=False)
        return 1 if (args.check and eligible) else 0

    if not eligible:
        report.emit(policy.root, json_out=args.json)
        return 0
    if not policy.p.enrichment.enabled:
        for b in eligible:
            report.add(b.rel(policy.root), "backlog", reason="enrichment is disabled in the automation policy")
        report.emit(policy.root, json_out=args.json)
        return 0

    client = client or llm.StructuredClient(policy)
    failed = 0
    stop_reason = ""
    for position, bundle in enumerate(eligible):
        path = bundle.rel(policy.root)
        source_hash = sha256_bytes(bundle.doc.raw)
        if position >= policy.p.enrichment.max_articles_per_run or stop_reason:
            report.add(path, "backlog", reason=stop_reason or "per-run article cap reached", source_hash=source_hash)
            continue
        try:
            notes = enrich_one(policy, tax, client, bundle, force=args.force)
        except llm.MissingCredentials as exc:
            for waiting in eligible[position:]:
                report.add(
                    waiting.rel(policy.root),
                    "backlog",
                    reason="ANTHROPIC_API_KEY is not set",
                    source_hash=sha256_bytes(waiting.doc.raw),
                )
            report.emit(policy.root, json_out=args.json)
            print(f"error: {exc}", file=sys.stderr)
            return 3
        except llm.BudgetExceeded as exc:
            stop_reason = str(exc)
            report.add(path, "backlog", reason=stop_reason, source_hash=source_hash)
            continue
        except (llm.LLMError, UserError) as exc:
            failed += 1
            report.add(path, "failed", reason=str(exc), source_hash=source_hash)
            continue
        meta = notes.pop("meta")
        changed = fm.save(bundle.doc, bundle.doc.with_meta(meta))
        report.add(path, "enriched" if changed else "unchanged", source_hash=source_hash, model=client.model, **notes)
    report.totals = {"usage": client.usage.as_dict(), "model": client.model}
    report.emit(policy.root, json_out=args.json)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
