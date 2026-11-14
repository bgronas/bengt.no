"""Category and tag policy: normalisation without silent sprawl."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import TaxonomyPolicy


def _key(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass
class TagResult:
    tags: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)


class Taxonomy:
    def __init__(self, policy: TaxonomyPolicy) -> None:
        self.categories = list(policy.categories)
        self._categories = {_key(c): c for c in policy.categories}
        self.canonical_tags = list(policy.tags.canonical)
        self._canonical = {_key(t): t for t in policy.tags.canonical}
        self._aliases = {_key(a): t for a, t in policy.tags.aliases.items()}
        self._ambiguous = {_key(a): tuple(v) for a, v in policy.tags.ambiguous.items()}

    def category(self, value: str) -> str | None:
        """Canonical category for an exact (case-insensitive) match, else None."""
        return self._categories.get(_key(value))

    def normalise_tags(self, values: list[str]) -> TagResult:
        """Map tags to canonical spellings. Ambiguous abbreviations and unknown
        tags are reported, never guessed. Order is kept; duplicates collapse."""
        result = TagResult()
        for raw in values:
            key = _key(str(raw))
            if not key:
                continue
            if key in self._ambiguous:
                result.ambiguous[str(raw)] = self._ambiguous[key]
                continue
            tag = self._canonical.get(key) or self._aliases.get(key)
            if tag is None:
                if str(raw) not in result.unknown:
                    result.unknown.append(str(raw))
            elif tag not in result.tags:
                result.tags.append(tag)
        return result
