"""Shared paths, policy loading, hashing, atomic writes and reports."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import yamlx

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = "data/automation-policy.yaml"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BUNDLE_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)$")


class PolicyError(Exception):
    """The policy files are missing, malformed or inconsistent."""


class UserError(Exception):
    """An actionable problem with input; printed without a traceback."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaxonomySettings(_Strict):
    source: str
    categories_min: int = Field(ge=0)
    categories_max: int = Field(ge=1)
    tags_max: int = Field(ge=1)
    keywords_max: int = Field(ge=1)
    new_tags: Literal["report", "reject"]


class MetadataSettings(_Strict):
    description_min_chars: int = Field(ge=1)
    description_max_chars: int = Field(ge=1)
    summary_max_chars: int = Field(ge=1)
    title_max_chars: int = Field(ge=1)


class Limits(_Strict):
    max_markdown_bytes: int = Field(ge=1)
    max_image_bytes: int = Field(ge=1)
    max_image_edge_px: int = Field(ge=1)
    max_passthrough_image_bytes: int = Field(ge=1)
    allow_remote_images: bool


class ApiSettings(_Strict):
    default_model: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0, le=10)
    backoff_base_seconds: float = Field(gt=0)
    backoff_max_seconds: float = Field(gt=0)


class Budgets(_Strict):
    max_calls_per_run: int = Field(ge=1)
    max_total_tokens_per_run: int = Field(ge=1)
    max_input_chars_per_call: int = Field(ge=1)


class EnrichmentSettings(_Strict):
    enabled: bool
    max_articles_per_run: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)


class TranslationSettings(_Strict):
    enabled: bool
    max_articles_per_run: int = Field(ge=1)
    chunk_chars: int = Field(ge=500)
    max_chunks_per_article: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    metadata_max_output_tokens: int = Field(ge=1)
    glossary: tuple[str, ...]


class SocialSettings(_Strict):
    enabled: bool
    max_drafts_per_run: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    linkedin_min_words: int = Field(ge=1)
    linkedin_max_words: int = Field(ge=1)
    x_max_weighted_length: int = Field(ge=1)
    artifact_retention_days: int = Field(ge=1, le=90)
    verify_attempts: int = Field(ge=1)
    verify_delay_seconds: float = Field(ge=0)


class CardSettings(_Strict):
    enabled: bool
    width: int = Field(ge=600)
    height: int = Field(ge=315)
    min_title_px: int = Field(ge=24)
    max_title_px: int = Field(ge=24)
    max_title_lines: int = Field(ge=1)


class ExternalLinkSettings(_Strict):
    timeout_seconds: float = Field(gt=0)
    max_urls: int = Field(ge=1)
    per_host_delay_seconds: float = Field(ge=0)


class Maintenance(_Strict):
    scheduled_build: bool


class TagPolicy(_Strict):
    canonical: tuple[str, ...]
    aliases: dict[str, str] = Field(default_factory=dict)
    ambiguous: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class TaxonomyPolicy(_Strict):
    version: Literal[1]
    categories: tuple[str, ...]
    tags: TagPolicy

    @model_validator(mode="after")
    def _consistent(self) -> TaxonomyPolicy:
        canon = {t.casefold(): t for t in self.tags.canonical}
        if len(canon) != len(self.tags.canonical):
            raise ValueError("tags.canonical contains duplicates that differ only by case")
        if len({c.casefold() for c in self.categories}) != len(self.categories):
            raise ValueError("categories contains duplicates")
        for alias, target in self.tags.aliases.items():
            if target not in self.tags.canonical:
                raise ValueError(f"alias {alias!r} points to {target!r}, which is not a canonical tag")
            if alias.casefold() in self.tags.ambiguous:
                raise ValueError(f"{alias!r} is listed as both an alias and an ambiguous abbreviation")
        for key in self.tags.ambiguous:
            if key.casefold() in canon:
                raise ValueError(f"ambiguous abbreviation {key!r} is also a canonical tag")
        return self


class Policy(_Strict):
    version: Literal[1]
    languages: tuple[str, ...]
    default_language: str
    timezone: str
    posts_section: str
    content_roots: dict[str, str]
    inbox_roots: dict[str, str]
    intake_media_dir: str
    site_origin: str
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    branch: str = Field(min_length=1)
    state_branch: str = Field(min_length=1)
    taxonomy: TaxonomySettings
    metadata: MetadataSettings
    limits: Limits
    api: ApiSettings
    budgets: Budgets
    enrichment: EnrichmentSettings
    translation: TranslationSettings
    social: SocialSettings
    cards: CardSettings
    external_links: ExternalLinkSettings
    maintenance: Maintenance

    @model_validator(mode="after")
    def _consistent(self) -> Policy:
        langs = set(self.languages)
        if self.default_language not in langs:
            raise ValueError("default_language must be one of languages")
        if set(self.content_roots) != langs or set(self.inbox_roots) != langs:
            raise ValueError("content_roots and inbox_roots must define exactly the configured languages")
        if self.metadata.description_min_chars > self.metadata.description_max_chars:
            raise ValueError("description_min_chars exceeds description_max_chars")
        if not self.site_origin.startswith("https://") or self.site_origin.endswith("/"):
            raise ValueError("site_origin must be an https origin without a trailing slash")
        return self


class LoadedPolicy:
    """Automation policy plus the taxonomy policy it references."""

    def __init__(self, root: Path, policy: Policy, taxonomy: TaxonomyPolicy) -> None:
        self.root = root
        self.p = policy
        self.taxonomy = taxonomy

    def content_root(self, lang: str) -> Path:
        return self.root / self.p.content_roots[lang]

    def posts_root(self, lang: str) -> Path:
        return self.content_root(lang) / self.p.posts_section

    def inbox_root(self, lang: str) -> Path:
        return self.root / self.p.inbox_roots[lang]

    def other_language(self, lang: str) -> str:
        others = [x for x in self.p.languages if x != lang]
        if len(others) != 1:
            raise PolicyError("translation requires exactly two configured languages")
        return others[0]

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.p.timezone)


def _read_yaml(path: Path) -> Any:
    try:
        return yamlx.load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"missing policy file: {path}") from exc
    except yaml.YAMLError as exc:
        raise PolicyError(f"{path} is not valid YAML: {exc}") from exc


def load_policy(root: Path | None = None) -> LoadedPolicy:
    # BN_ROOT lets the test suite point every script at a temporary repository.
    root = (root or Path(os.environ.get("BN_ROOT") or ROOT)).resolve()
    try:
        policy = Policy.model_validate(_read_yaml(root / POLICY_FILE))
        taxonomy = TaxonomyPolicy.model_validate(_read_yaml(root / policy.taxonomy.source))
    except ValidationError as exc:
        lines = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise PolicyError(f"policy validation failed: {lines}") from exc
    return LoadedPolicy(root, policy, taxonomy)


# ---------- hashing ----------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_hash(meta: dict[str, Any], body: bytes) -> str:
    """Hash of what a reader sees: title, summary, description and the exact body bytes."""
    head = {k: str(meta.get(k) or "") for k in ("title", "summary", "description")}
    blob = json.dumps(head, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\0" + body
    return "sha256:" + sha256_bytes(blob)


# ---------- slugs ----------

_TRANSLIT = str.maketrans(
    {"æ": "ae", "ø": "o", "å": "a", "Æ": "ae", "Ø": "o", "Å": "a", "ß": "ss", "đ": "d", "ł": "l", "þ": "th"}
)


def slugify(text: str, max_length: int = 80) -> str:
    """Portable ASCII slug. Documented rule: æ→ae, ø→o, å→a, other accents are
    stripped (é→e), everything else non-alphanumeric becomes a single hyphen."""
    text = text.translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    if len(text) > max_length:
        text = text[:max_length].rsplit("-", 1)[0] if "-" in text[:max_length] else text[:max_length]
    return text.strip("-")


def title_from_slug(slug: str) -> str:
    words = slug.replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else ""


# ---------- time ----------


def now_local(tz: ZoneInfo) -> datetime:
    """Current time in the site time zone. BN_NOW (RFC 3339) overrides it for tests."""
    override = os.environ.get("BN_NOW")
    if override:
        return datetime.fromisoformat(override).astimezone(tz)
    return datetime.now(tz)


def rfc3339(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


# ---------- filesystem ----------


def as_dict(value: Any) -> dict[str, Any]:
    """The value when it is a mapping, otherwise an empty one."""
    return dict(value) if isinstance(value, dict) else {}


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def safe_child(parent: Path, relative: str) -> Path:
    """Resolve `relative` under `parent`, rejecting absolute paths, traversal and symlink escapes."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or relative.startswith(("~", "\\")) or "\\" in relative:
        raise UserError(f"unsafe path {relative!r}: must be a plain relative path without '..'")
    candidate = parent / rel
    if not is_within(candidate, parent):
        raise UserError(f"path {relative!r} escapes {parent}")
    return candidate


def atomic_write(path: Path, data: bytes) -> None:
    """Write through a temporary file in the same directory, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            Path(tmp).chmod(path.stat().st_mode & 0o777)
        else:
            Path(tmp).chmod(0o644)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def dump_json(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


# ---------- reporting ----------


class Report:
    """Deterministic JSON and text report. No article text, secrets or request bodies."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.items: list[dict[str, Any]] = []
        self.totals: dict[str, Any] = {}

    def add(self, path: str, status: str, **fields: Any) -> None:
        self.items.append({"path": path, "status": status, **fields})

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i["status"] == status)

    def as_dict(self) -> dict[str, Any]:
        items = sorted(self.items, key=lambda i: (i["path"], i["status"]))
        summary: dict[str, int] = {}
        for item in items:
            summary[item["status"]] = summary.get(item["status"], 0) + 1
        return {"report": self.name, "summary": dict(sorted(summary.items())), "totals": self.totals, "items": items}

    def as_text(self) -> str:
        data = self.as_dict()
        lines = [f"{self.name}: " + (", ".join(f"{k}={v}" for k, v in data["summary"].items()) or "nothing to do")]
        for item in data["items"]:
            detail = "; ".join(
                f"{k}={v}" for k, v in sorted(item.items()) if k not in ("path", "status") and v not in (None, "", [])
            )
            lines.append(f"  [{item['status']}] {item['path']}" + (f" ({detail})" if detail else ""))
        return "\n".join(lines)

    def emit(self, root: Path, *, json_out: bool = False, save: bool = True) -> None:
        if save:
            atomic_write(root / "reports" / f"{self.name}.json", dump_json(self.as_dict()))
        if json_out:
            sys.stdout.write(dump_json(self.as_dict()).decode("utf-8"))
        else:
            print(self.as_text())


def run_cli(main: Any) -> int:
    """Run a script entry point with uniform error handling."""
    try:
        return int(main() or 0)
    except (UserError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
