"""Front matter IO that never touches the Markdown body.

python-frontmatter parses the metadata. Its own serialiser is not used, because
it normalises the body (strips leading and trailing whitespace). Instead the file
is split at the closing delimiter and the body is kept as the exact byte slice
that followed it. Rewrites replace the header only and re-attach those bytes.

Two write paths exist:
  * set_scalars(): textual, line-level edit of top-level scalar keys. Every other
    header byte, including comments and quoting, is preserved. Used for flag flips.
  * with_meta(): re-serialises the whole YAML header (key order kept, comments in
    the header are lost). Used when structured values change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
import yaml
from frontmatter.default_handlers import YAMLHandler

from . import yamlx
from .common import UserError, atomic_write

_BOM = b"\xef\xbb\xbf"
_HEADER_RE = re.compile(rb"\A---[ \t]*(\r?\n)(.*?)(?<=\n)---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


class _Handler(YAMLHandler):
    def load(self, fm: str, **kwargs: Any) -> Any:
        return yamlx.load(fm)


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def _represent_none(dumper: yaml.SafeDumper, _value: None) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


_Dumper.add_representer(type(None), _represent_none)


@dataclass(frozen=True)
class Doc:
    path: Path
    raw: bytes
    bom: bytes
    newline: str
    header: str
    meta: dict[str, Any]
    body: bytes

    def render(self, header: str | None = None) -> bytes:
        text = self.header if header is None else header
        nl = self.newline
        text = text.replace("\r\n", "\n").replace("\n", nl)
        if text and not text.endswith(nl):
            text += nl
        return self.bom + f"---{nl}{text}---{nl}".encode() + self.body

    def with_meta(self, meta: dict[str, Any]) -> bytes:
        return self.render(dump_header(meta))

    def set_scalars(self, changes: dict[str, bool | int | str | None]) -> bytes:
        return self.render(_edit_scalars(self.header, changes))


def dump_header(meta: dict[str, Any]) -> str:
    return yaml.dump(meta, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100000)


def parse(raw: bytes, path: Path) -> Doc:
    bom = _BOM if raw.startswith(_BOM) else b""
    data = raw[len(bom) :]
    head = data.lstrip()[:3]
    if head == b"+++":
        raise UserError(
            f"{path}: TOML front matter (+++) is not supported. Convert the header to YAML between --- lines."
        )
    if head[:1] == b"{":
        raise UserError(f"{path}: JSON front matter is not supported. Convert the header to YAML between --- lines.")
    match = _HEADER_RE.match(data)
    if not match:
        raise UserError(f"{path}: no YAML front matter found. The file must start with a --- line.")
    newline = match.group(1).decode()
    try:
        header = match.group(2).decode("utf-8")
        text = data[: match.end()].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserError(f"{path}: front matter is not valid UTF-8") from exc
    try:
        meta = frontmatter.loads(text, handler=_Handler()).metadata
    except yaml.YAMLError as exc:
        raise UserError(f"{path}: front matter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise UserError(f"{path}: front matter must be a YAML mapping")
    return Doc(path=path, raw=raw, bom=bom, newline=newline, header=header, meta=dict(meta), body=data[match.end() :])


def load(path: Path) -> Doc:
    return parse(path.read_bytes(), path)


def has_front_matter(raw: bytes) -> bool:
    data = raw[len(_BOM) :] if raw.startswith(_BOM) else raw
    return _HEADER_RE.match(data) is not None


def save(doc: Doc, data: bytes) -> bool:
    """Atomically write `data` to the document path. Returns False when nothing changed."""
    if data == doc.raw:
        return False
    atomic_write(doc.path, data)
    return True


def _scalar(value: bool | int | str | None) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return yaml.dump(value, Dumper=_Dumper, default_style='"', allow_unicode=True, width=100000).strip()


def _edit_scalars(header: str, changes: dict[str, bool | int | str | None]) -> str:
    """Replace or append top-level `key: scalar` lines. Dotted keys address one nested level."""
    lines = header.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for key, value in changes.items():
        parent, _, child = key.rpartition(".")
        rendered = _scalar(value)
        if not parent:
            pattern = re.compile(rf"^({re.escape(key)}:)([ \t]*)(.*?)([ \t]+#.*)?$")
            for i, line in enumerate(lines):
                m = pattern.match(line)
                if m:
                    lines[i] = f"{m.group(1)} {rendered}{m.group(4) or ''}"
                    break
            else:
                lines.append(f"{key}: {rendered}")
            continue
        start = next(
            (i for i, line in enumerate(lines) if re.match(rf"^{re.escape(parent)}:[ \t]*(#.*)?$", line)), None
        )
        if start is None:
            lines.extend([f"{parent}:", f"  {child}: {rendered}"])
            continue
        end = start + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
            end += 1
        pattern = re.compile(rf"^([ \t]+{re.escape(child)}:)([ \t]*)(.*?)([ \t]+#.*)?$")
        for i in range(start + 1, end):
            m = pattern.match(lines[i])
            if m:
                lines[i] = f"{m.group(1)} {rendered}{m.group(4) or ''}"
                break
        else:
            found = re.match(r"^[ \t]+", lines[start + 1]) if end > start + 1 else None
            indent = found.group(0) if found else "  "
            lines.insert(start + 1, f"{indent}{child}: {rendered}")
    return "\n".join(lines) + "\n"
