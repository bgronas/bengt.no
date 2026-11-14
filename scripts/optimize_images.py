#!/usr/bin/env python3
"""Audit article images against the image policy and state how each will be delivered.

Division of labour (one transformation path, never two):
  * Hugo is the only component that creates derivatives. The render hook
    layouts/_default/_markup/render-image.html resizes, converts and strips
    metadata at build time; results live in Hugo's resource cache (resources/_gen,
    not committed) and are keyed by source hash plus processing parameters, so
    reruns neither re-encode nor produce new binaries in Git.
  * This script uses Pillow to inspect the sources, never to rewrite them. It
    classifies every image, checks the limits Hugo cannot enforce by itself
    (pass-through formats, corrupt files, oversize originals) and reports what
    the build will do. Source images are left untouched.

Classes:
  photo        JPEG -> auto-oriented, max edge from policy, WebP (lossy) + JPEG
  lossless     PNG  -> max edge from policy, WebP (lossless) + PNG (screenshots, diagrams)
  photo-png    PNG listed in front matter `images_lossy` -> WebP (lossy) + PNG
  passthrough  GIF, WebP -> served unchanged so animation survives
  vector       SVG -> served unchanged, never rasterised
  feature      feature image -> resized list thumbnail, optional hero and 1200x630 social JPEG; original not published
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from lib import content, mdscan
from lib.common import LoadedPolicy, Report, load_policy, run_cli, sha256_file
from PIL import Image, UnidentifiedImageError

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def inspect(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    if path.suffix.lower() == ".svg":
        info["format"] = "SVG"
        return info
    with Image.open(path) as img:
        img.verify()
    with Image.open(path) as img:
        info.update(
            format=img.format,
            width=img.width,
            height=img.height,
            animated=bool(getattr(img, "is_animated", False)),
            alpha=img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info,
        )
        exif = img.getexif()
        orientation = exif.get(ORIENTATION)
        info["orientation"] = int(orientation) if orientation else 1
        info["gps"] = bool(exif.get_ifd(GPS_IFD)) if exif else False
        if img.format == "PNG" and not info["alpha"] and img.width * img.height >= 1_500_000:
            sample = img.convert("RGB").resize((96, 96), Image.Resampling.NEAREST)
            info["photo_like"] = len(set(sample.getdata())) > 3000
    return info


def classify(info: dict[str, Any], lossy_names: list[str], name: str) -> str:
    fmt = info.get("format")
    if fmt == "SVG":
        return "vector"
    if fmt in ("GIF", "WEBP"):
        return "passthrough"
    if fmt == "JPEG":
        return "photo"
    if fmt == "PNG":
        return "photo-png" if name in lossy_names else "lossless"
    return "unsupported"


def audit_bundle(policy: LoadedPolicy, bundle: content.Bundle, report: Report) -> None:
    limits = policy.p.limits
    scan = mdscan.scan(bundle.body_text)
    referenced = {i.dest.split("#")[0].split("?")[0].removeprefix("./") for i in scan.images if mdscan.is_local(i.dest)}
    lossy = (
        [str(x) for x in (bundle.meta.get("images_lossy") or [])]
        if isinstance(bundle.meta.get("images_lossy"), list)
        else []
    )
    feature = {c.name for c in content.feature_candidates(bundle.dir)} | {str(bundle.meta.get("featureimage") or "")}
    for path in sorted(bundle.dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in content.IMAGE_EXTS or path.is_symlink():
            continue
        name = path.relative_to(bundle.dir).as_posix()
        rel = path.relative_to(policy.root).as_posix()
        try:
            info = inspect(path)
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            report.add(rel, "error", reason=f"not a readable image ({type(exc).__name__}). Re-export the file")
            continue
        kind = classify(info, lossy, name)
        if name in feature and kind != "vector":
            kind = "feature"  # reaches the site only as resized thumbnails and the 1200x630 social JPEG
        notes: list[str] = []
        errors: list[str] = []
        if kind == "unsupported":
            errors.append(f"format {info.get('format')} is not supported. Use JPEG, PNG, WebP, GIF or SVG")
        if info["bytes"] > limits.max_image_bytes:
            errors.append(f"{info['bytes']} bytes exceeds the {limits.max_image_bytes} byte limit for source images")
        edge = max(info.get("width", 0), info.get("height", 0))
        if kind == "passthrough":
            if info["bytes"] > limits.max_passthrough_image_bytes:
                errors.append(
                    f"{info['format']} files are served unchanged and this one is {info['bytes']} bytes "
                    f"(limit {limits.max_passthrough_image_bytes}). Shorten or re-encode it"
                )
            if edge > limits.max_image_edge_px:
                errors.append(
                    f"{info['format']} files are served unchanged and this one is {edge} px on its longest edge (limit {limits.max_image_edge_px})"
                )
        elif edge > limits.max_image_edge_px:
            notes.append(f"will be delivered at {limits.max_image_edge_px} px (source {edge} px); never upscaled")
        if info.get("gps"):
            notes.append(
                "source contains GPS metadata; delivered derivatives do not, but the original is public if the repository is public"
            )
        if info.get("orientation", 1) != 1:
            notes.append(f"EXIF orientation {info['orientation']} will be applied")
        if info.get("photo_like") and kind == "lossless":
            notes.append(
                f"looks like a photograph stored as PNG; add `images_lossy: [{name}]` to the front matter for a much smaller file"
            )
        if name not in referenced and name not in feature:
            notes.append("not referenced by the article")
        report.add(
            rel,
            "error" if errors else "ok",
            delivery=kind,
            width=info.get("width"),
            height=info.get("height"),
            animated=info.get("animated") or None,
            source_sha256=info["sha256"],
            reason="; ".join(errors) or None,
            notes=notes or None,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 all images within policy; 1 at least one image violates it; 2 usage or policy error.",
    )
    parser.add_argument("bundle", nargs="*", help="bundle folders or index.md files; default: all bundles")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    policy = load_policy()
    report = Report("images")
    bundles = [content.resolve_bundle(policy, b) for b in args.bundle] if args.bundle else content.discover(policy)
    for bundle in bundles:
        audit_bundle(policy, bundle, report)
    report.emit(policy.root, json_out=args.json)
    return 1 if report.count("error") else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
