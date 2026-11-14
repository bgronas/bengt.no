"""Markdown-aware scanning. Nothing here uses regular expressions across code:
fenced and indented code blocks and inline code spans are located with a real
CommonMark parser (markdown-it-py) and excluded before any pattern is applied."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from markdown_it.token import Token

_MD = MarkdownIt("commonmark").enable("table")

_SHORTCODE_RE = re.compile(r"\{\{(?P<open>[<%])\s*(?P<close>/)?\s*(?P<name>[\w./-]+)(?P<args>.*?)[%>]\}\}", re.DOTALL)
# Goldmark attribute block at the end of a heading: {#id .class key="value"}
_HEADING_ATTR_RE = re.compile(
    r"\s*\{(?P<attrs>\s*(?:[#.][\w:.-]+|[\w-]+=(?:\"[^\"]*\"|[^\s{}]+))(?:\s+(?:[#.][\w:.-]+|[\w-]+=(?:\"[^\"]*\"|[^\s{}]+)))*\s*)\}\s*$"
)
_ATTR_ID_RE = re.compile(r"(?:^|\s)#(?P<id>[A-Za-z][\w:.-]*)")
_MATH_PATTERNS = (
    re.compile(r"(?<!\\)\$\$.+?(?<!\\)\$\$", re.DOTALL),
    re.compile(r"(?<!\\)\\\[.+?(?<!\\)\\\]", re.DOTALL),
    re.compile(r"(?<!\\)\\\(.+?(?<!\\)\\\)", re.DOTALL),
)
_HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']?([^\"'\s>]+)", re.IGNORECASE)
_SC_SRC_RE = re.compile(r"\b(?:src|link)\s*=\s*[\"']([^\"']+)[\"']")


@dataclass(frozen=True)
class Image:
    dest: str
    alt: str
    title: str
    line: int


@dataclass(frozen=True)
class Link:
    dest: str
    text: str
    line: int


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    explicit_id: str | None
    line: int


@dataclass(frozen=True)
class Fence:
    info: str
    content: str
    line: int


@dataclass(frozen=True)
class Shortcode:
    name: str
    raw: str
    src: str | None


@dataclass
class Scan:
    images: list[Image] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    fences: list[Fence] = field(default_factory=list)
    html: list[tuple[int, str]] = field(default_factory=list)
    html_images: list[str] = field(default_factory=list)
    shortcodes: list[Shortcode] = field(default_factory=list)
    has_math: bool = False
    has_mermaid: bool = False
    prose: str = ""


def _inline_text(token: Token) -> str:
    parts: list[str] = []
    for child in token.children or []:
        if child.type in ("text", "code_inline", "text_special"):
            parts.append(child.content)
        elif child.type == "softbreak":
            parts.append(" ")
        elif child.type == "image":
            parts.append(child.content)
    return "".join(parts)


def _mask_inline_code(text: str) -> str:
    """Replace inline code spans with spaces, following CommonMark backtick-run rules."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n and text[i + 1] == "`":
            i += 2
            continue
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run = j - i
        k = j
        closed = False
        while k < n:
            if text[k] != "`":
                k += 1
                continue
            m = k
            while m < n and text[m] == "`":
                m += 1
            if m - k == run:
                for x in range(i, m):
                    if out[x] != "\n":
                        out[x] = " "
                i = m
                closed = True
                break
            k = m
        if not closed:
            i = j
    return "".join(out)


def strip_code(body: str, tokens: list[Token] | None = None) -> str:
    """Return the body with code blocks and inline code spans blanked out (line count kept)."""
    tokens = tokens if tokens is not None else _MD.parse(body)
    lines = body.split("\n")
    for tok in tokens:
        if tok.type in ("fence", "code_block") and tok.map:
            for i in range(tok.map[0], min(tok.map[1], len(lines))):
                lines[i] = ""
    return _mask_inline_code("\n".join(lines))


def scan(body: str) -> Scan:
    tokens = _MD.parse(body)
    result = Scan()
    for tok in tokens:
        line = (tok.map[0] + 1) if tok.map else 0
        if tok.type == "fence":
            info = tok.info.strip()
            result.fences.append(Fence(info=info, content=tok.content, line=line))
            if info.split(maxsplit=1)[:1] == ["mermaid"]:
                result.has_mermaid = True
        elif tok.type == "html_block":
            result.html.append((line, tok.content.strip().splitlines()[0][:80] if tok.content.strip() else ""))
            result.html_images.extend(_HTML_IMG_RE.findall(tok.content))
        elif tok.type == "inline":
            for child in tok.children or []:
                if child.type == "image":
                    result.images.append(
                        Image(
                            dest=str(child.attrGet("src") or ""),
                            alt=child.content,
                            title=str(child.attrGet("title") or ""),
                            line=line,
                        )
                    )
                elif child.type == "html_inline":
                    result.html.append((line, child.content[:80]))
                    result.html_images.extend(_HTML_IMG_RE.findall(child.content))
            children = tok.children or []
            for idx, child in enumerate(children):
                if child.type == "link_open":
                    text = []
                    for nxt in children[idx + 1 :]:
                        if nxt.type == "link_close":
                            break
                        text.append(nxt.content)
                    result.links.append(Link(dest=str(child.attrGet("href") or ""), text="".join(text), line=line))
    for idx, tok in enumerate(tokens):
        if tok.type == "heading_open":
            inline = tokens[idx + 1]
            heading_text = _inline_text(inline)
            match = _HEADING_ATTR_RE.search(heading_text)
            explicit = None
            if match:
                found = _ATTR_ID_RE.search(match.group("attrs"))
                explicit = found.group("id") if found else None
                heading_text = heading_text[: match.start()]
            result.headings.append(
                Heading(
                    level=int(tok.tag[1]),
                    text=heading_text.strip(),
                    explicit_id=explicit,
                    line=(tok.map[0] + 1) if tok.map else 0,
                )
            )
    result.prose = strip_code(body, tokens)
    result.has_math = any(p.search(result.prose) for p in _MATH_PATTERNS)
    for match in _SHORTCODE_RE.finditer(result.prose):
        if match.group("close"):
            continue
        src = _SC_SRC_RE.search(match.group("args") or "")
        result.shortcodes.append(
            Shortcode(name=match.group("name"), raw=match.group(0), src=src.group(1) if src else None)
        )
        if match.group("name") == "mermaid":
            result.has_mermaid = True
        if match.group("name") == "katex":
            result.has_math = True
    return result


def github_anchor(text: str) -> str:
    """Goldmark's `github` auto heading ID: lower-case, drop everything except
    letters, digits, spaces, hyphens and underscores, then spaces become hyphens."""
    kept = [ch for ch in text.strip().lower() if ch.isalnum() or ch in " -_"]
    return "".join(kept).replace(" ", "-")


def heading_anchors(headings: list[Heading]) -> list[str]:
    """Anchor per heading, in document order, with Goldmark's -1, -2 de-duplication."""
    seen: dict[str, int] = {}
    anchors: list[str] = []
    for h in headings:
        if h.explicit_id:
            anchors.append(h.explicit_id)
            seen.setdefault(h.explicit_id, 0)
            continue
        base = github_anchor(h.text) or "heading"
        if base in seen:
            seen[base] += 1
            anchor = f"{base}-{seen[base]}"
        else:
            seen[base] = 0
            anchor = base
        anchors.append(anchor)
    return anchors


def is_local(dest: str) -> bool:
    """True for a reference that should resolve inside the page bundle."""
    if not dest or dest.startswith(("#", "/", "mailto:", "tel:")):
        return False
    return not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", dest)
