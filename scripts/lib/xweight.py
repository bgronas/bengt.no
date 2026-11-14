"""Weighted length of a post on X.

Implements the published twitter-text v3 configuration instead of Python's len():
  * the text is NFC-normalised;
  * code points in U+0000-U+10FF, U+2000-U+200D, U+2010-U+201F and U+2032-U+2037
    weigh 1, every other code point weighs 2;
  * every URL weighs 23, whatever its real length.

Two deliberate simplifications, both on the safe side (they can only over-count):
an emoji sequence is charged per code point rather than once, and a bare domain
such as example.com, which X would turn into a link, is charged max(23, length).
The standard limit of 280 is used; no premium account limit is assumed.
"""

from __future__ import annotations

import re
import unicodedata

LIMIT = 280
URL_WEIGHT = 23
_LIGHT = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"(?<![\w@./-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?", re.IGNORECASE)


def _char_weight(ch: str) -> int:
    cp = ord(ch)
    return 1 if any(lo <= cp <= hi for lo, hi in _LIGHT) else 2


def weighted_length(text: str) -> int:
    text = unicodedata.normalize("NFC", text)
    total = 0
    pos = 0
    spans: list[tuple[int, int, int]] = [(m.start(), m.end(), URL_WEIGHT) for m in _URL_RE.finditer(text)]
    covered = [(s, e) for s, e, _ in spans]
    for m in _DOMAIN_RE.finditer(text):
        if not any(s <= m.start() < e for s, e in covered):
            spans.append((m.start(), m.end(), max(URL_WEIGHT, m.end() - m.start())))
    for start, end, weight in sorted(spans):
        if start < pos:
            continue
        total += sum(_char_weight(ch) for ch in text[pos:start]) + weight
        pos = end
    return total + sum(_char_weight(ch) for ch in text[pos:])


def fits(text: str, limit: int = LIMIT) -> bool:
    return weighted_length(text) <= limit
