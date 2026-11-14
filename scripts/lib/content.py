"""Bundle discovery and the metadata contract shared by every script."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import fm, mdscan
from .common import BUNDLE_DIR_RE, SLUG_RE, LoadedPolicy, UserError, content_hash, is_within
from .taxonomy import Taxonomy

FEATURE_STEMS = ("feature", "cover", "hero", "thumbnail")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")
RASTER_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
GENERATED_CARD = "feature.webp"
TRANSLATION_STATES = ("machine-draft", "reviewed")
KEY_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")

# Order in which missing keys are appended when a header is rewritten.
ARCHETYPE_ORDER = (
    "title", "date", "lastmod", "draft", "slug", "translationKey", "auto_enrich", "auto_translate", "summary",
    "math", "mermaid", "featured", "description", "keywords", "categories", "tags", "series", "series_order", "social",
)  # fmt: skip


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning" | "pending"
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class Bundle:
    lang: str
    dir: Path
    doc: fm.Doc

    @property
    def index(self) -> Path:
        return self.dir / "index.md"

    @property
    def meta(self) -> dict[str, Any]:
        return self.doc.meta

    @property
    def body_text(self) -> str:
        return self.doc.body.decode("utf-8")

    @property
    def hash(self) -> str:
        return content_hash(self.doc.meta, self.doc.body)

    def rel(self, root: Path) -> str:
        return self.index.resolve().relative_to(root.resolve()).as_posix()

    def identity(self) -> str:
        return f"{self.lang}:{self.meta.get('translationKey') or self.dir.name}"


def is_unreviewed_translation(meta: dict[str, Any]) -> bool:
    """A machine translation that no person has signed off yet."""
    info = meta.get("translation")
    return (
        isinstance(info, dict) and info.get("state") == "machine-draft" and meta.get("translation_reviewed") is not True
    )


def is_true(value: Any) -> bool:
    """Only the literal boolean true opts in. Strings such as "true" do not."""
    return value is True


def discover(policy: LoadedPolicy, langs: tuple[str, ...] | None = None) -> list[Bundle]:
    """All post bundles, sorted by path. Symlinked directories are skipped."""
    bundles: list[Bundle] = []
    for lang in langs or policy.p.languages:
        root = policy.posts_root(lang)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            index = child / "index.md"
            if child.name.startswith(".") or child.is_symlink() or not child.is_dir() or not index.is_file():
                continue
            if index.is_symlink() or not is_within(index, root):
                continue
            bundles.append(Bundle(lang=lang, dir=child, doc=fm.load(index)))
    return bundles


def resolve_bundle(policy: LoadedPolicy, target: str | Path) -> Bundle:
    """Accept a bundle directory or its index.md; reject anything outside the posts roots."""
    path = Path(target)
    if not path.is_absolute():
        path = policy.root / path
    if path.name != "index.md":
        path = path / "index.md"
    for lang in policy.p.languages:
        root = policy.posts_root(lang)
        if is_within(path, root) and path.parent.parent.resolve() == root.resolve():
            if path.is_symlink() or path.parent.is_symlink():
                raise UserError(f"{target}: symlinks are not accepted")
            if not path.is_file():
                raise UserError(f"{target}: no index.md found in that bundle")
            return Bundle(lang=lang, dir=path.parent, doc=fm.load(path))
    roots = ", ".join(policy.p.content_roots[lang] + "/" + policy.p.posts_section for lang in policy.p.languages)
    raise UserError(f"{target}: not a post bundle. Expected <{roots}>/<YYYY-MM-DD-slug>/index.md")


def parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def feature_candidates(bundle_dir: Path) -> list[Path]:
    """Files an author or the card generator may have placed as the feature image."""
    found = []
    for child in sorted(bundle_dir.iterdir()):
        if child.is_file() and child.suffix.lower() in IMAGE_EXTS and child.stem.lower().split(".")[0] in FEATURE_STEMS:
            found.append(child)
    return found


def _check_bool(meta: dict[str, Any], key: str, issues: list[Issue], required: bool = True) -> None:
    if key not in meta:
        if required:
            issues.append(Issue("error", "missing-field", f"`{key}` is missing; add `{key}: false`"))
        return
    if not isinstance(meta[key], bool):
        issues.append(
            Issue("error", "not-boolean", f"`{key}` must be the YAML boolean true or false, not {meta[key]!r}")
        )


def validate_meta(
    policy: LoadedPolicy, taxonomy: Taxonomy, meta: dict[str, Any], *, allow_pending: bool = False
) -> list[Issue]:
    """Check one article's metadata. Rules that only matter for publication are
    errors when `draft: false` and warnings while the article is a draft."""
    issues: list[Issue] = []
    m, t = policy.p.metadata, policy.p.taxonomy
    published = meta.get("draft") is False
    pending = is_true(meta.get("auto_enrich"))
    gate = "error" if published else "warning"
    if published and pending:
        gate = "pending" if allow_pending else "error"

    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        issues.append(Issue(gate if pending else "error", "title", "`title` is empty"))
    elif len(title) > m.title_max_chars:
        issues.append(Issue("error", "title", f"`title` is {len(title)} characters; the limit is {m.title_max_chars}"))

    for key in ("date", "lastmod"):
        if parse_date(meta.get(key)) is None:
            issues.append(
                Issue(
                    "error", key, f"`{key}` must be an RFC 3339 timestamp with offset, e.g. 2026-11-13T09:00:00+01:00"
                )
            )
    if meta.get("expiryDate") not in (None, "") and parse_date(meta.get("expiryDate")) is None:
        issues.append(Issue("error", "expiryDate", "`expiryDate` must be an RFC 3339 timestamp with offset"))

    for key in ("draft", "auto_enrich", "auto_translate"):
        _check_bool(meta, key, issues)
    for key in ("math", "mermaid", "featured"):
        _check_bool(meta, key, issues, required=False)

    slug = meta.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        issues.append(Issue("error", "slug", "`slug` must be lower-case letters, digits and single hyphens"))
    tkey = meta.get("translationKey")
    if not isinstance(tkey, str) or not KEY_RE.match(tkey):
        issues.append(
            Issue(
                "error", "translationKey", "`translationKey` must be lower-case letters, digits, hyphens or underscores"
            )
        )

    description = meta.get("description") or ""
    if not isinstance(description, str):
        issues.append(Issue("error", "description", "`description` must be a string"))
    elif description:
        if not m.description_min_chars <= len(description) <= m.description_max_chars:
            issues.append(
                Issue(
                    "error" if published else "warning",
                    "description-length",
                    f"`description` is {len(description)} characters; the policy is "
                    f"{m.description_min_chars}-{m.description_max_chars}. Edit it, or clear it and set auto_enrich: true",
                )
            )
    else:
        issues.append(Issue(gate, "description", "`description` is empty"))

    summary = meta.get("summary") or ""
    if not isinstance(summary, str):
        issues.append(Issue("error", "summary", "`summary` must be a string"))
    elif not summary.strip():
        issues.append(Issue(gate, "summary", "`summary` is empty"))
    elif len(summary) > m.summary_max_chars:
        issues.append(
            Issue("error", "summary", f"`summary` is {len(summary)} characters; the limit is {m.summary_max_chars}")
        )

    categories = meta.get("categories") or []
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        issues.append(Issue("error", "categories", "`categories` must be a list of strings"))
    else:
        for cat in categories:
            canonical = taxonomy.category(cat)
            if canonical is None:
                issues.append(
                    Issue(
                        "error",
                        "category-not-allowed",
                        f"category {cat!r} is not in data/taxonomy-policy.yaml. Allowed: {', '.join(taxonomy.categories)}",
                    )
                )
            elif canonical != cat:
                issues.append(Issue("error", "category-spelling", f"category {cat!r} must be written {canonical!r}"))
        if len(categories) > t.categories_max:
            issues.append(
                Issue("error", "categories", f"{len(categories)} categories; at most {t.categories_max} are allowed")
            )
        if len(categories) < t.categories_min:
            issues.append(Issue(gate, "categories", f"at least {t.categories_min} category is required"))

    tags = meta.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
        issues.append(Issue("error", "tags", "`tags` must be a list of strings"))
    else:
        result = taxonomy.normalise_tags(tags)
        for raw, options in result.ambiguous.items():
            issues.append(
                Issue(
                    "error",
                    "tag-ambiguous",
                    f"tag {raw!r} is ambiguous ({' or '.join(options)}). Write the intended tag in full",
                )
            )
        for raw in result.unknown:
            issues.append(
                Issue(
                    "error",
                    "tag-not-allowed",
                    f"tag {raw!r} is not in data/taxonomy-policy.yaml. Use an existing tag or add it to the policy first",
                )
            )
        for raw in tags:
            single = taxonomy.normalise_tags([raw])
            if single.tags and single.tags[0] != raw:
                issues.append(Issue("error", "tag-spelling", f"tag {raw!r} must be written {single.tags[0]!r}"))
        if len(tags) != len(set(tags)):
            issues.append(Issue("error", "tags", "`tags` contains duplicates"))
        if len(tags) > t.tags_max:
            issues.append(Issue("error", "tags", f"{len(tags)} tags; at most {t.tags_max} are allowed"))
        if not tags:
            issues.append(Issue(gate, "tags", "at least one tag is required"))

    keywords = meta.get("keywords") or []
    if not isinstance(keywords, list) or not all(isinstance(x, str) and x.strip() for x in keywords):
        issues.append(Issue("error", "keywords", "`keywords` must be a list of non-empty strings"))
    elif len(keywords) > t.keywords_max:
        issues.append(Issue("error", "keywords", f"{len(keywords)} keywords; at most {t.keywords_max} are allowed"))
    elif not keywords:
        issues.append(Issue(gate, "keywords", "`keywords` is empty"))

    series = meta.get("series") or []
    order = meta.get("series_order")
    if not isinstance(series, list) or not all(isinstance(x, str) and x.strip() for x in series):
        issues.append(Issue("error", "series", "`series` must be a list with at most one series name"))
    elif len(series) > 1:
        issues.append(Issue("error", "series", "an article belongs to at most one series"))
    elif series and (isinstance(order, bool) or not isinstance(order, int) or order < 1):
        issues.append(
            Issue("error", "series_order", "`series_order` must be a positive whole number when `series` is set")
        )
    elif not series and order is not None:
        issues.append(Issue("error", "series_order", "`series_order` is set but `series` is empty; set it to null"))

    weight = meta.get("featured_weight")
    if weight is not None and (isinstance(weight, bool) or not isinstance(weight, int)):
        issues.append(Issue("error", "featured_weight", "`featured_weight` must be a whole number"))

    social = meta.get("social")
    if social is None:
        issues.append(Issue("error", "social", "`social` is missing; add the block from the archetype"))
    elif not isinstance(social, dict):
        issues.append(Issue("error", "social", "`social` must be a mapping with enabled, language and regenerate"))
    else:
        for field in ("enabled", "regenerate"):
            if not isinstance(social.get(field), bool):
                issues.append(Issue("error", "social", f"`social.{field}` must be true or false"))
        if social.get("language") not in ("inherit", *policy.p.languages):
            issues.append(
                Issue("error", "social", f"`social.language` must be inherit or one of {', '.join(policy.p.languages)}")
            )

    translation = meta.get("translation")
    if translation is not None and (
        not isinstance(translation, dict) or translation.get("state") not in TRANSLATION_STATES
    ):
        issues.append(
            Issue("error", "translation", f"`translation.state` must be one of {', '.join(TRANSLATION_STATES)}")
        )
    elif published and is_unreviewed_translation(meta):
        issues.append(
            Issue(
                "error",
                "translation-unreviewed",
                "this is a machine translation draft. Review it, then set `translation_reviewed: true` "
                "(or translation.state: reviewed) before publishing",
            )
        )
    if "translation_reviewed" in meta and not isinstance(meta["translation_reviewed"], bool):
        issues.append(Issue("error", "translation_reviewed", "`translation_reviewed` must be true or false"))

    if published and pending and not allow_pending:
        issues.append(
            Issue(
                "error",
                "enrichment-pending",
                "draft: false with auto_enrich: true. Enrichment has not completed for this article",
            )
        )
    elif published and pending:
        issues.append(Issue("pending", "enrichment-pending", "metadata will be generated by the deployment workflow"))
    return issues


def validate_bundle_files(policy: LoadedPolicy, bundle: Bundle) -> list[Issue]:
    """Check local references, images and feature-image rules for one bundle."""
    issues: list[Issue] = []
    published = bundle.meta.get("draft") is False
    limits = policy.p.limits
    if not BUNDLE_DIR_RE.match(bundle.dir.name):
        issues.append(Issue("error", "bundle-name", f"folder {bundle.dir.name!r} must be named YYYY-MM-DD-slug"))
    if len(bundle.doc.raw) > limits.max_markdown_bytes:
        issues.append(
            Issue(
                "error",
                "too-large",
                f"index.md is {len(bundle.doc.raw)} bytes; the limit is {limits.max_markdown_bytes}",
            )
        )
    try:
        scan = mdscan.scan(bundle.body_text)
    except UnicodeDecodeError:
        return [*issues, Issue("error", "encoding", "index.md is not valid UTF-8")]

    for image in scan.images:
        if mdscan.is_local(image.dest):
            target = bundle.dir / image.dest.split("#")[0].split("?")[0].removeprefix("./")
            if ".." in Path(image.dest).parts or not is_within(target, bundle.dir):
                issues.append(
                    Issue(
                        "error",
                        "image-outside-bundle",
                        f"line {image.line}: image {image.dest!r} must live inside the page bundle",
                    )
                )
            elif not target.is_file():
                issues.append(
                    Issue(
                        "error",
                        "image-missing",
                        f"line {image.line}: image {image.dest!r} does not exist in the bundle",
                    )
                )
            elif target.suffix.lower() not in IMAGE_EXTS:
                issues.append(
                    Issue(
                        "error", "image-type", f"line {image.line}: {image.dest!r} is not JPEG, PNG, WebP, GIF or SVG"
                    )
                )
        elif image.dest.startswith("/"):
            issues.append(
                Issue(
                    "error",
                    "image-absolute",
                    f"line {image.line}: image {image.dest!r} uses a site-absolute path. Put the file in the bundle and reference it by name",
                )
            )
        elif re.match(r"^https?://", image.dest):
            if not limits.allow_remote_images:
                issues.append(
                    Issue(
                        "error",
                        "image-remote",
                        f"line {image.line}: remote image {image.dest!r}. Download it into the bundle; remote images are disabled by policy",
                    )
                )
        else:
            issues.append(
                Issue("error", "image-scheme", f"line {image.line}: unsupported image reference {image.dest!r}")
            )
        if not image.alt.strip():
            issues.append(
                Issue(
                    "error" if published else "warning",
                    "alt-missing",
                    f"line {image.line}: image {image.dest!r} has no alt text",
                )
            )

    for src in scan.html_images:
        issues.append(
            Issue(
                "error",
                "html-image",
                f"raw HTML <img src={src!r}> is not supported (raw HTML is disabled). Use Markdown image syntax: ![alt]({src})",
            )
        )
    if scan.html and not scan.html_images:
        issues.append(
            Issue(
                "warning",
                "raw-html",
                f"line {scan.html[0][0]}: raw HTML is not rendered on this site. Use Markdown or a shortcode",
            )
        )
    for sc in scan.shortcodes:
        if (
            sc.name in ("figure", "img", "image", "gallery", "carousel", "screenshot")
            and sc.src
            and mdscan.is_local(sc.src)
        ):
            issues.append(
                Issue(
                    "error",
                    "shortcode-image",
                    f"shortcode {sc.name!r} with local image {sc.src!r} bypasses the image pipeline. Use Markdown image syntax",
                )
            )

    for link in scan.links:
        if mdscan.is_local(link.dest):
            rel_path = link.dest.split("#")[0].split("?")[0].removeprefix("./")
            target = bundle.dir / rel_path
            if rel_path and (".." in Path(rel_path).parts or not target.exists()):
                issues.append(
                    Issue(
                        "error",
                        "link-missing",
                        f"line {link.line}: relative link {link.dest!r} does not resolve to a file in the bundle",
                    )
                )

    candidates = feature_candidates(bundle.dir)
    chosen = bundle.meta.get("featureimage")
    if chosen:
        if not isinstance(chosen, str) or not (bundle.dir / chosen).is_file():
            issues.append(
                Issue("error", "featureimage", f"`featureimage: {chosen!r}` does not match a file in the bundle")
            )
    elif len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        issues.append(
            Issue(
                "error",
                "feature-conflict",
                f"several feature image candidates ({names}). Choose one with `featureimage: <file>` in the front matter",
            )
        )
    elif len(candidates) == 1 and candidates[0].stem.lower() == "hero":
        issues.append(
            Issue(
                "error",
                "feature-hero",
                f"{candidates[0].name} is not picked up by the theme. Rename it to feature{candidates[0].suffix} or set `featureimage: {candidates[0].name}`",
            )
        )

    overrides = bundle.meta.get("feature_overrides") or {}
    if not isinstance(overrides, dict) or any(
        k not in ("math", "mermaid") or not isinstance(v, bool) for k, v in overrides.items()
    ):
        issues.append(
            Issue("error", "feature_overrides", "`feature_overrides` may only contain math and mermaid booleans")
        )
    else:
        for name, detected in (("math", scan.has_math), ("mermaid", scan.has_mermaid)):
            want = overrides.get(name, detected)
            if bool(bundle.meta.get(name, False)) != want:
                issues.append(
                    Issue(
                        "warning",
                        f"{name}-flag",
                        f"`{name}` should be {str(want).lower()}; run ./publish.sh check --fix-features or let the workflow set it",
                    )
                )
    return issues


def find_collisions(bundles: list[Bundle]) -> dict[str, list[Issue]]:
    """Duplicate slugs or translation keys within one language."""
    out: dict[str, list[Issue]] = {}
    for field, code in (("slug", "slug-collision"), ("translationKey", "translation-key-collision")):
        seen: dict[tuple[str, str], Bundle] = {}
        for b in bundles:
            value = b.meta.get(field)
            if not isinstance(value, str) or not value:
                continue
            key = (b.lang, value)
            if key in seen:
                msg = f"`{field}: {value}` is also used by {seen[key].dir.name} in language {b.lang}"
                out.setdefault(str(b.index), []).append(Issue("error", code, msg))
            else:
                seen[key] = b
    return out
