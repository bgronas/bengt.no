"""Markdown-aware segmentation for translation.

The body is split into top-level blocks with a CommonMark parser. Code blocks,
HTML blocks, rules and blank lines never leave the machine. Inside translatable
blocks every literal fragment (inline code, link and image destinations, URLs,
shortcodes, math, HTML tags, attribute blocks, reference labels, table rule
rows, nested code fences) is replaced by a numbered placeholder such as ⟦P7⟧.
After translation the placeholder sequence of each segment must be identical to
the source; then the originals are put back. A model instruction alone is never
relied on to keep code intact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

from . import mdscan

_MD = MarkdownIt("commonmark").enable("table")
TOKEN_RE = re.compile(r"⟦P(\d+)⟧")
_STRAY_RE = re.compile(r"[⟦⟧]")
_TRANSLATABLE = {
    "paragraph_open",
    "heading_open",
    "blockquote_open",
    "bullet_list_open",
    "ordered_list_open",
    "table_open",
}

_NESTED_FENCE_RE = re.compile(
    r"^(?P<pre>[ \t>]*)(?P<fence>`{3,}|~{3,})[^\n]*\n(?:.*\n)*?(?P=pre)(?P=fence)[ \t]*$", re.MULTILINE
)
_LITERAL_SHORTCODE_RE = re.compile(
    r"\{\{[<%]\s*(mermaid|katex|chart|highlight|codeimporter)\b.*?[%>]\}\}.*?\{\{[<%]\s*/\s*\1\s*[%>]\}\}", re.DOTALL
)
_SHORTCODE_RE = re.compile(r"\{\{[<%].*?[%>]\}\}", re.DOTALL)
_MATH_RES = (
    re.compile(r"(?<!\\)\$\$.+?(?<!\\)\$\$", re.DOTALL),
    re.compile(r"(?<!\\)\\\[.+?(?<!\\)\\\]", re.DOTALL),
    re.compile(r"(?<!\\)\\\(.+?(?<!\\)\\\)", re.DOTALL),
)
_REF_DEF_RE = re.compile(r"^[ \t>]{0,3}\[[^\]\n]+\]:[ \t]+\S.*$", re.MULTILINE)
_TABLE_RULE_RE = re.compile(r"^[ \t>]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$", re.MULTILINE)
_DEST_RE = re.compile(r"(?<=\]\()[ \t]*(<[^>\n]*>|[^\s()]+(?:\([^\s()]*\)[^\s()]*)*)")
_REF_LABEL_RE = re.compile(r"(?<=\])\[[^\]\n]*\]")
_FOOTNOTE_RE = re.compile(r"\[\^[^\]\n]+\]")
_AUTOLINK_RE = re.compile(r"<(?:https?://|mailto:)[^>\s]+>")
_URL_RE = re.compile(r"https?://[^\s<>()\[\]⟦⟧]+[^\s<>()\[\].,;:!?⟦⟧]")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^<>\n]*>")
_ATTR_RE = re.compile(r"\{[ \t]*[#.:][^{}\n]*\}")


class SegmentationError(Exception):
    """The source uses a construct that cannot be protected safely."""


class TokenMismatch(Exception):
    """A translated segment lost, duplicated, reordered or altered a placeholder."""


@dataclass
class Segment:
    id: str
    kind: str
    text: str  # with placeholders
    tokens: list[str]  # placeholder names in source order


@dataclass
class Plan:
    parts: list[str | Segment] = field(default_factory=list)
    originals: dict[str, str] = field(default_factory=dict)
    dest_tokens: set[str] = field(default_factory=set)

    @property
    def segments(self) -> list[Segment]:
        return [p for p in self.parts if isinstance(p, Segment)]


def _inline_code_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run, k, closed = j - i, j, False
        while k < n:
            if text[k] != "`":
                k += 1
                continue
            m = k
            while m < n and text[m] == "`":
                m += 1
            if m - k == run:
                spans.append((i, m))
                i, closed = m, True
                break
            k = m
        if not closed:
            i = j
    return spans


class _Protector:
    def __init__(self, plan: Plan, ref_labels: set[str]) -> None:
        self.plan = plan
        self.ref_labels = ref_labels

    def _token(self, original: str, dest: bool = False) -> str:
        name = f"⟦P{len(self.plan.originals) + 1}⟧"
        self.plan.originals[name] = original
        if dest:
            self.plan.dest_tokens.add(name)
        return name

    def _sub(self, pattern: re.Pattern[str], text: str, dest: bool = False) -> str:
        return pattern.sub(lambda m: self._token(m.group(0), dest), text)

    def protect(self, text: str) -> str:
        if _STRAY_RE.search(text):
            raise SegmentationError("the source contains the reserved characters ⟦ or ⟧")
        text = self._sub(_NESTED_FENCE_RE, text)
        text = self._sub(_LITERAL_SHORTCODE_RE, text)
        for pattern in _MATH_RES:
            text = self._sub(pattern, text)
        out, last = [], 0
        for start, end in _inline_code_spans(text):
            out.append(text[last:start])
            out.append(self._token(text[start:end]))
            last = end
        text = "".join(out) + text[last:]
        text = self._sub(_SHORTCODE_RE, text)
        text = self._sub(_REF_DEF_RE, text)
        text = self._sub(_TABLE_RULE_RE, text)
        text = _DEST_RE.sub(lambda m: self._token(m.group(0), dest=True), text)
        text = self._sub(_REF_LABEL_RE, text)
        text = self._sub(_FOOTNOTE_RE, text)
        text = self._sub(_AUTOLINK_RE, text)
        text = self._sub(_URL_RE, text)
        text = self._sub(_HTML_TAG_RE, text)
        text = self._sub(_ATTR_RE, text)
        if self.ref_labels:

            def shortcut(m: re.Match[str]) -> str:
                return self._token(m.group(0)) if m.group(1).casefold() in self.ref_labels else m.group(0)

            text = re.sub(r"(?<!\])\[([^\]\n⟦⟧]+)\](?![\[(:])", shortcut, text)
        return text


def build_plan(body: str) -> Plan:
    """Split a Markdown body into literal parts and translatable segments."""
    body = body.replace("\r\n", "\n")
    lines = body.split("\n")
    tokens = _MD.parse(body)
    ref_labels = {
        m.group(0).split("]:")[0].strip(" \t>[").casefold()
        for m in _REF_DEF_RE.finditer(mdscan.strip_code(body, tokens))
    }
    plan = Plan()
    protector = _Protector(plan, ref_labels)
    cursor = 0
    counter = 0
    for tok in tokens:
        if tok.level != 0 or not tok.map or tok.nesting == -1:
            continue
        start, end = tok.map
        if start < cursor:
            continue
        if start > cursor:
            plan.parts.append("\n".join(lines[cursor:start]) + "\n")
        chunk = "\n".join(lines[start:end])
        while chunk.endswith("\n"):
            chunk = chunk[:-1]
            end -= 1
        if tok.type in _TRANSLATABLE and chunk.strip():
            counter += 1
            text = protector.protect(chunk)
            if not TOKEN_RE.sub("", text).strip(" \t\n#>*_-|+.0123456789"):
                plan.parts.append(chunk)  # nothing but literals and markers
                for name in TOKEN_RE.findall(text):
                    plan.originals.pop(f"⟦P{name}⟧", None)
                    plan.dest_tokens.discard(f"⟦P{name}⟧")
                counter -= 1
            else:
                plan.parts.append(
                    Segment(
                        id=f"s{counter:04d}",
                        kind=tok.type.removesuffix("_open"),
                        text=text,
                        tokens=[f"⟦P{n}⟧" for n in TOKEN_RE.findall(text)],
                    )
                )
        else:
            plan.parts.append(chunk)
        cursor = end
        if cursor < len(lines):
            plan.parts.append("\n")
    if cursor < len(lines):
        plan.parts.append("\n".join(lines[cursor:]))
    if reassemble(plan, {s.id: s.text for s in plan.segments}) != body:
        raise SegmentationError("internal check failed: the segmented body does not reassemble to the source")
    return plan


def verify_segment(segment: Segment, translated: str) -> None:
    """Raise TokenMismatch unless placeholders and block markers survived exactly."""
    got = [f"⟦P{n}⟧" for n in TOKEN_RE.findall(translated)]
    if got != segment.tokens:
        missing = [t for t in segment.tokens if t not in got]
        extra = [t for t in got if t not in segment.tokens]
        dup = sorted({t for t in got if got.count(t) > 1})
        detail = (
            "reordered" if not (missing or extra or dup) else f"missing={missing} unexpected={extra} duplicated={dup}"
        )
        raise TokenMismatch(f"segment {segment.id}: placeholders changed ({detail})")
    if _STRAY_RE.search(TOKEN_RE.sub("", translated)):
        raise TokenMismatch(f"segment {segment.id}: malformed placeholder in the translation")
    if not translated.strip():
        raise TokenMismatch(f"segment {segment.id}: empty translation")
    if segment.kind == "heading":
        src = re.match(r"^(#{1,6})[ \t]", segment.text)
        if src and not translated.startswith(src.group(1) + " "):
            raise TokenMismatch(f"segment {segment.id}: heading level changed")
    if segment.kind in ("table", "bullet_list", "ordered_list", "blockquote") and translated.count(
        "\n"
    ) != segment.text.count("\n"):
        raise TokenMismatch(f"segment {segment.id}: the number of lines in a {segment.kind.replace('_', ' ')} changed")
    if segment.kind == "table" and [ln.count("|") for ln in translated.split("\n")] != [
        ln.count("|") for ln in segment.text.split("\n")
    ]:
        raise TokenMismatch(f"segment {segment.id}: table columns changed")


def reassemble(plan: Plan, translated: dict[str, str], replacements: dict[str, str] | None = None) -> str:
    """Rebuild the document. `replacements` overrides the original of specific placeholders."""
    originals = {**plan.originals, **(replacements or {})}
    out: list[str] = []
    for part in plan.parts:
        if isinstance(part, Segment):
            out.append(TOKEN_RE.sub(lambda m: originals[m.group(0)], translated[part.id]))
        else:
            out.append(part)
    return "".join(out)


def chunk_segments(segments: list[Segment], chunk_chars: int) -> list[list[Segment]]:
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0
    for seg in segments:
        if current and size + len(seg.text) > chunk_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(seg)
        size += len(seg.text)
    if current:
        chunks.append(current)
    return chunks
