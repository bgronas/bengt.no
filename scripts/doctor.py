#!/usr/bin/env python3
"""Check the local setup: tools, pins, configuration consistency and common GitHub Pages mistakes.

Read-only. Prints whether a credential is present, never its value, and does
not contact GitHub or any other account.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from lib import content
from lib.common import PolicyError, load_policy, run_cli, sha256_file


class Doctor:
    def __init__(self) -> None:
        self.fails = 0
        self.warns = 0

    def ok(self, msg: str) -> None:
        print(f"[ ok ] {msg}")

    def warn(self, msg: str) -> None:
        self.warns += 1
        print(f"[warn] {msg}")

    def fail(self, msg: str) -> None:
        self.fails += 1
        print(f"[FAIL] {msg}")


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(x) for x in match.groups()) if match else ()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    d = Doctor()
    try:
        policy = load_policy()
    except PolicyError as exc:
        d.fail(f"policy: {exc}")
        return 1
    root = policy.root
    d.ok("policy files load and validate (data/automation-policy.yaml, data/taxonomy-policy.yaml)")

    # Tools
    d.ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    for tool, hint in (("git", "install Git"), ("uv", "install uv: https://docs.astral.sh/uv/")):
        if shutil.which(tool):
            d.ok(f"{tool}: {_run([tool, '--version'], root)[1].splitlines()[0]}")
        else:
            d.fail(f"{tool} not found on PATH ({hint})")
    code, out = _run(["hugo", "version"], root)
    theme_cfg = root / "themes/blowfish/config.toml"
    if code != 0:
        d.fail("hugo not found. Run ./publish.sh setup (Hugo is installed into .venv from uv.lock)")
    else:
        line = next((ln for ln in out.splitlines() if ln.startswith("hugo v")), out)
        have = _version_tuple(line)
        if "+extended" not in line:
            d.fail("Hugo is not the extended edition")
        if theme_cfg.is_file():
            limits = tomllib.loads(theme_cfg.read_text(encoding="utf-8"))["module"]["hugoVersion"]
            low, high = _version_tuple(limits["min"]), _version_tuple(limits["max"])
            if low <= have <= high:
                d.ok(
                    f"Hugo {'.'.join(map(str, have))} extended, within the theme's supported range {limits['min']} to {limits['max']}"
                )
            else:
                d.fail(
                    f"Hugo {'.'.join(map(str, have))} is outside the theme's supported range {limits['min']} to {limits['max']}"
                )
    if shutil.which("code"):
        d.ok("VS Code command `code` found")
    else:
        d.warn("VS Code command `code` not found; new articles will not be opened automatically")

    # Theme submodule and overrides
    overrides = json.loads((root / "data/theme-overrides.json").read_text(encoding="utf-8"))
    if not theme_cfg.is_file():
        d.fail("themes/blowfish is empty. Run: git submodule update --init --recursive")
    else:
        code, head = _run(["git", "-C", "themes/blowfish", "rev-parse", "HEAD"], root)
        if code == 0 and head == overrides["theme_commit"]:
            d.ok(f"Blowfish submodule at {overrides['theme_version']} ({head[:12]})")
        else:
            d.fail(
                f"Blowfish submodule is at {head[:12] or 'unknown'}; the repository pins {overrides['theme_version']} ({overrides['theme_commit'][:12]}). Run: git submodule update --init --recursive"
            )
        for item in overrides["overrides"]:
            upstream = root / item["upstream"]
            if upstream.is_file() and sha256_file(upstream) == item["upstream_sha256"]:
                d.ok(f"theme override {item['local']} matches the upstream file it was derived from")
            else:
                d.fail(
                    f"{item['upstream']} changed upstream. Re-apply the documented edits to {item['local']} (docs/operations.md)"
                )
        code, status = _run(["git", "status", "--porcelain", "themes/blowfish"], root)
        if status:
            d.fail("the theme submodule has local modifications; the theme must stay unmodified")

    # Configuration consistency
    cfg_dir = root / "config/_default"
    for stray in ("hugo.toml", "hugo.yaml", "hugo.json", "config.toml", "config.yaml", "config.json"):
        if (root / stray).exists():
            d.fail(f"{stray} at the repository root competes with config/_default/. Remove it")
    hugo_cfg = tomllib.loads((cfg_dir / "hugo.toml").read_text(encoding="utf-8"))
    params = tomllib.loads((cfg_dir / "params.toml").read_text(encoding="utf-8"))
    if hugo_cfg.get("baseURL") == policy.p.site_origin + "/":
        d.ok(f"baseURL is {hugo_cfg['baseURL']}")
    else:
        d.fail(f"baseURL {hugo_cfg.get('baseURL')!r} must be {policy.p.site_origin}/")
    if hugo_cfg.get("defaultContentLanguage") != policy.p.default_language or hugo_cfg.get(
        "defaultContentLanguageInSubdir"
    ):
        d.fail(
            "defaultContentLanguage / defaultContentLanguageInSubdir do not match the policy (default language at the site root)"
        )
    for lang in policy.p.languages:
        lang_file = cfg_dir / f"languages.{lang}.toml"
        if (
            not lang_file.is_file()
            or tomllib.loads(lang_file.read_text(encoding="utf-8")).get("contentDir") != policy.p.content_roots[lang]
        ):
            d.fail(f"config/_default/languages.{lang}.toml must set contentDir = {policy.p.content_roots[lang]!r}")
    if params.get("bn", {}).get("imageMaxEdge") == policy.p.limits.max_image_edge_px:
        d.ok(f"image size limit is {policy.p.limits.max_image_edge_px} px in both Hugo parameters and the policy")
    else:
        d.fail("params.toml [bn] imageMaxEdge differs from limits.max_image_edge_px in the policy")
    host = urlparse(policy.p.site_origin).hostname or ""
    cname = root / "static/CNAME"
    if cname.is_file() and cname.read_text(encoding="utf-8") == host + "\n":
        d.ok(f"static/CNAME contains exactly {host}")
    else:
        d.fail(f"static/CNAME must contain exactly {host} followed by a newline")
    code, out = _run([sys.executable, "scripts/sync_cms_schema.py", "--check"], root)
    (d.ok if code == 0 else d.fail)(
        ".pages.yml matches the policy" if code == 0 else ".pages.yml is out of date. Run ./publish.sh cms-sync"
    )
    sums = root / "assets/fonts/SHA256SUMS"
    bad = [
        ln.split()[1]
        for ln in sums.read_text(encoding="utf-8").splitlines()
        if ln.strip() and sha256_file(root / "assets/fonts" / ln.split()[1]) != ln.split()[0]
    ]
    (d.fail if bad else d.ok)(
        f"font files differ from SHA256SUMS: {', '.join(bad)}"
        if bad
        else "self-hosted font files match assets/fonts/SHA256SUMS"
    )
    for wf in ("deploy.yml", "check.yml"):
        if not (root / ".github/workflows" / wf).is_file():
            d.fail(f".github/workflows/{wf} is missing")

    # Git state and Pages pitfalls
    code, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    if code != 0:
        d.warn("not a Git repository yet (git init, then add the remote; see docs/dns-and-pages.md)")
    else:
        (d.ok if branch == policy.p.branch else d.warn)(
            f"current branch is {branch}"
            + ("" if branch == policy.p.branch else f"; publishing requires {policy.p.branch}")
        )
        code, url = _run(["git", "remote", "get-url", "origin"], root)
        expected = policy.p.repository.lower()
        if code != 0:
            d.warn(f"no `origin` remote. Add it: git remote add origin https://github.com/{policy.p.repository}.git")
        elif re.search(rf"github\.com[:/]{re.escape(expected)}(\.git)?/?$", url.lower()):
            d.ok(f"origin points to github.com/{policy.p.repository}")
        else:
            d.warn(f"origin is {url}; this project is configured for github.com/{policy.p.repository}")
        code, tracked = _run(["git", "ls-files", "public", "resources/_gen", ".env", "social-drafts", "reports"], root)
        if tracked:
            d.fail(
                "generated output or secrets are tracked by Git: "
                + ", ".join(tracked.splitlines()[:5])
                + ". Remove them with `git rm --cached`"
            )
        else:
            d.ok("no build output, reports, social drafts or .env tracked by Git")
    if (root / "docs/index.html").exists():
        d.fail("docs/index.html exists: this project deploys with GitHub Actions, not from a docs/ folder")

    # Credentials: presence only
    needs = [
        b
        for b in content.discover(policy)
        if content.is_true(b.meta.get("auto_enrich")) or content.is_true(b.meta.get("auto_translate"))
    ]
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if needs and not has_key:
        d.warn(
            f"{len(needs)} article(s) request enrichment or translation and ANTHROPIC_API_KEY is not set locally. The workflow uses the repository secret; locally, export the key only if you want to run these steps yourself"
        )
    else:
        d.ok(f"ANTHROPIC_API_KEY: {'set' if has_key else 'not set (not needed right now)'}")
    model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    d.ok(
        f"model: {model or policy.p.api.default_model}" + (" (from ANTHROPIC_MODEL)" if model else " (policy default)")
    )

    print(f"\ndoctor: {d.fails} failure(s), {d.warns} warning(s)")
    return 1 if d.fails else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
