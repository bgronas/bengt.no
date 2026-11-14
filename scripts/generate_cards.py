#!/usr/bin/env python3
"""Render typographic 1200x630 title cards for articles without an authored feature image.

The card is written as `feature.webp` (lossless) inside the bundle, where the
theme picks it up for list thumbnails and the head partial derives the JPEG
social image from it. Provenance lives in data/card-manifest.json, separate from
the image: an input hash (title, category, language, generator version) and the
hash of the file that was written.

Rules:
  * An authored feature image always wins. A generated card is removed when the
    author adds one; a card the author has edited is treated as authored.
  * A card is re-rendered only when its inputs change or the file is missing.
  * `--brand` regenerates the site-wide default social image and the favicons.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lib import content
from lib.common import LoadedPolicy, Report, atomic_write, dump_json, load_policy, run_cli, sha256_bytes, sha256_file
from PIL import Image, ImageDraw, ImageFont

GENERATOR = "cards-1"
MANIFEST = "data/card-manifest.json"
FONT = "assets/fonts/card/Roboto-Variable.ttf"
BG = (28, 31, 33)
SURFACE = (49, 52, 54)
TEXT = (250, 248, 244)
MUTED = (156, 157, 153)
ACCENT = (45, 190, 178)
MARGIN = 80
AUTHOR = "Bengt Grønås"
SIGNATURE = "bengt.no"


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == 1 and isinstance(data.get("cards"), dict):
            return dict(data)
    return {"version": 1, "cards": {}}


class Fonts:
    def __init__(self, root: Path) -> None:
        self.path = root / FONT
        if not self.path.is_file():
            raise FileNotFoundError(f"{FONT} is missing; cards cannot be rendered")
        self.sha = sha256_file(self.path)
        self._cache: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}
        probe = self.get(40, 400)
        self._notdef = (
            probe.getmask("￿").tobytes() if hasattr(probe.getmask("￿"), "tobytes") else bytes(probe.getmask("￿"))
        )

    def get(self, size: int, weight: int) -> ImageFont.FreeTypeFont:
        key = (size, weight)
        if key not in self._cache:
            font = ImageFont.truetype(str(self.path), size)
            axes = font.get_variation_axes()
            values: list[float] = []
            for axis in axes:
                name = axis.get("name")
                tag = (name.decode() if isinstance(name, bytes) else str(name)).lower()
                if "weight" in tag:
                    values.append(weight)
                elif "width" in tag:
                    values.append(100)
                else:
                    values.append(float(axis.get("default") or 0))
            font.set_variation_by_axes(values)
            self._cache[key] = font
        return self._cache[key]

    def supported(self, text: str) -> str:
        """Drop characters the bundled font cannot draw (they would render as boxes)."""
        probe = self.get(40, 400)
        out = []
        for ch in text:
            if ch.isspace():
                out.append(" ")
                continue
            mask = probe.getmask(ch)
            data = mask.tobytes() if hasattr(mask, "tobytes") else bytes(mask)
            if data and data != self._notdef:
                out.append(ch)
        return " ".join("".join(out).split())


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        while draw.textlength(word, font=font) > width and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and draw.textlength(word[:cut] + "-", font=font) > width:
                cut -= 1
            lines.append(word[:cut] + "-")
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


def fit_title(
    draw: ImageDraw.ImageDraw, fonts: Fonts, title: str, width: int, height: int, cfg: Any
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Largest size at which the title fits; at the minimum size the last line is ellipsised."""
    size = cfg.max_title_px
    while True:
        font = fonts.get(size, 700)
        lines = wrap(draw, title, font, width)
        line_height = int(size * 1.16)
        if (len(lines) <= cfg.max_title_lines and len(lines) * line_height <= height) or size <= cfg.min_title_px:
            break
        size = max(cfg.min_title_px, size - 4)
    max_lines = max(1, min(cfg.max_title_lines, height // line_height))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return font, lines, line_height


def render(fonts: Fonts, cfg: Any, *, title: str, category: str, lang: str) -> Image.Image:
    w, h = cfg.width, cfg.height
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 12, h], fill=ACCENT)
    label_font = fonts.get(26, 500)
    if category:
        draw.text(
            (MARGIN, MARGIN - 6), fonts.supported(category).upper(), font=label_font, fill=ACCENT, features=["-liga"]
        )
    tag = lang.upper()
    tag_w = draw.textlength(tag, font=label_font)
    draw.rounded_rectangle([w - MARGIN - tag_w - 28, MARGIN - 16, w - MARGIN, MARGIN + 34], radius=8, fill=SURFACE)
    draw.text((w - MARGIN - tag_w - 14, MARGIN - 6), tag, font=label_font, fill=TEXT)

    top, bottom = MARGIN + 70, h - MARGIN - 70
    font, lines, line_height = fit_title(
        draw, fonts, fonts.supported(title) or SIGNATURE, w - 2 * MARGIN, bottom - top, cfg
    )
    y = top + max(0, (bottom - top - len(lines) * line_height) // 2)
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=TEXT)
        y += line_height

    draw.line([MARGIN, h - MARGIN - 44, w - MARGIN, h - MARGIN - 44], fill=SURFACE, width=2)
    name_font, sig_font = fonts.get(30, 600), fonts.get(28, 500)
    draw.text((MARGIN, h - MARGIN - 22), AUTHOR, font=name_font, fill=TEXT)
    sig_w = draw.textlength(SIGNATURE, font=sig_font)
    draw.text((w - MARGIN - sig_w, h - MARGIN - 21), SIGNATURE, font=sig_font, fill=ACCENT)
    return img


def encode_webp(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="WEBP", lossless=True, quality=100, method=6, exact=True)
    return buf.getvalue()


def card_inputs(fonts: Fonts, cfg: Any, bundle: content.Bundle) -> dict[str, Any]:
    cats = bundle.meta.get("categories") or []
    return {
        "generator": GENERATOR,
        "font": fonts.sha,
        "size": [cfg.width, cfg.height],
        "type": [cfg.min_title_px, cfg.max_title_px, cfg.max_title_lines],
        "title": str(bundle.meta.get("title") or ""),
        "category": str(cats[0]) if cats else "",
        "lang": bundle.lang,
    }


def process(policy: LoadedPolicy, *, check: bool) -> tuple[Report, bool]:
    report = Report("cards")
    cfg = policy.p.cards
    manifest = load_manifest(policy.root)
    cards: dict[str, Any] = manifest["cards"]
    fonts = Fonts(policy.root)
    dirty = False
    live: set[str] = set()
    for bundle in content.discover(policy):
        card = bundle.dir / content.GENERATED_CARD
        key = card.relative_to(policy.root).as_posix()
        entry = cards.get(key)
        ours = entry is not None and card.is_file() and sha256_file(card) == entry["output_sha256"]
        if entry and card.is_file() and not ours:
            report.add(
                key, "author-edited", note="file differs from the generated card; treated as authored from now on"
            )
            if not check:
                cards.pop(key)
                dirty = True
            entry = None
        authored = [c for c in content.feature_candidates(bundle.dir) if not (c == card and ours)]
        if authored or bundle.meta.get("featureimage"):
            if ours:
                report.add(
                    key,
                    "removed",
                    note=f"authored feature image present ({', '.join(c.name for c in authored) or bundle.meta.get('featureimage')})",
                )
                if not check:
                    card.unlink()
                    cards.pop(key)
                    dirty = True
            continue
        if not cfg.enabled or not str(bundle.meta.get("title") or "").strip():
            continue
        inputs = card_inputs(fonts, cfg, bundle)
        input_hash = "sha256:" + sha256_bytes(dump_json(inputs))
        live.add(key)
        if ours and entry and entry["input_hash"] == input_hash:
            continue
        status = "rendered" if not entry else "re-rendered"
        if not check:
            data = encode_webp(
                render(fonts, cfg, title=inputs["title"], category=inputs["category"], lang=inputs["lang"])
            )
            atomic_write(card, data)
            cards[key] = {"input_hash": input_hash, "output_sha256": sha256_bytes(data), "generator": GENERATOR}
            dirty = True
        report.add(key, status if not check else "would-render")
    for key in sorted(set(cards) - live):
        if not (policy.root / key).exists():
            report.add(key, "forgotten", note="card file no longer exists")
            if not check:
                cards.pop(key)
                dirty = True
    if dirty:
        atomic_write(policy.root / MANIFEST, dump_json(manifest))
    return report, dirty


def brand(policy: LoadedPolicy) -> None:
    """Site-wide default social image (PNG) and favicons. Committed; rerun after a design change."""
    import io

    fonts, cfg = Fonts(policy.root), policy.p.cards
    card = render(fonts, cfg, title="Engineering notes on platforms, automation and operations.", category="", lang="")
    draw = ImageDraw.Draw(card)
    draw.rectangle([cfg.width - MARGIN - 120, MARGIN - 20, cfg.width - MARGIN, MARGIN + 40], fill=BG)
    buf = io.BytesIO()
    card.save(buf, format="PNG", optimize=True)
    atomic_write(policy.root / "assets/img/default-social.png", buf.getvalue())

    def icon(size: int) -> Image.Image:
        scale = 4
        big = Image.new("RGB", (size * scale, size * scale), BG)
        d = ImageDraw.Draw(big)
        font = fonts.get(int(size * scale * 0.56), 800)
        text = "BG"
        box = d.textbbox((0, 0), text, font=font)
        x = (size * scale - (box[2] - box[0])) / 2 - box[0]
        y = (size * scale - (box[3] - box[1])) / 2 - box[1] - size * scale * 0.04
        d.text((x, y), text, font=font, fill=TEXT)
        d.rectangle([size * scale * 0.2, size * scale * 0.80, size * scale * 0.8, size * scale * 0.86], fill=ACCENT)
        return big.resize((size, size), Image.Resampling.LANCZOS)

    static = policy.root / "static"
    for name, size in (
        ("favicon-16x16.png", 16),
        ("favicon-32x32.png", 32),
        ("apple-touch-icon.png", 180),
        ("android-chrome-192x192.png", 192),
        ("android-chrome-512x512.png", 512),
    ):
        buf = io.BytesIO()
        icon(size).save(buf, format="PNG", optimize=True)
        atomic_write(static / name, buf.getvalue())
    buf = io.BytesIO()
    icon(48).save(buf, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    atomic_write(static / "favicon.ico", buf.getvalue())
    webmanifest = {
        "name": "Bengt Grønås",
        "short_name": "bengt.no",
        "icons": [
            {"src": "/android-chrome-192x192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/android-chrome-512x512.png", "sizes": "512x512", "type": "image/png"},
        ],
        "theme_color": "#1c1f21",
        "background_color": "#1c1f21",
        "display": "browser",
    }
    atomic_write(static / "site.webmanifest", dump_json(webmanifest))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--check", action="store_true", help="report what would change and exit 1 if anything would; change nothing"
    )
    parser.add_argument(
        "--brand", action="store_true", help="regenerate assets/img/default-social.png and the favicons, then exit"
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    policy = load_policy()
    if args.brand:
        brand(policy)
        print(
            "brand assets written: assets/img/default-social.png, static/favicon*, static/*-icon*.png, static/site.webmanifest"
        )
        return 0
    report, _ = process(policy, check=args.check)
    report.emit(policy.root, json_out=args.json, save=not args.check)
    return 1 if (args.check and report.items) else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
