"""Shared fixtures: a throwaway repository, a scripted model and a real Hugo build."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from lib import llm  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
NOW = "2026-11-13T10:00:00+01:00"


def text_of_length(n: int, seed: str = "A factual description of the article for search results") -> str:
    out = seed
    while len(out) < n:
        out += " and more detail"
    out = out[:n].rstrip()
    return out + "x" * (n - len(out))


BASE_META: dict[str, Any] = {
    "title": "A test article",
    "date": "2026-10-01T09:00:00+02:00",
    "lastmod": "2026-10-01T09:00:00+02:00",
    "draft": False,
    "slug": "a-test-article",
    "translationKey": "a-test-article",
    "auto_enrich": False,
    "auto_translate": False,
    "summary": "What the reader learns from this article, in one sentence.",
    "math": False,
    "mermaid": False,
    "featured": False,
    "description": text_of_length(155),
    "keywords": ["hugo pipeline", "page bundles"],
    "categories": ["Technology"],
    "tags": ["Hugo", "Markdown"],
    "series": [],
    "series_order": None,
    "social": {"enabled": True, "language": "inherit", "regenerate": False},
}


def make_meta(**overrides: Any) -> dict[str, Any]:
    meta = copy.deepcopy(BASE_META)
    meta.update(overrides)
    return meta


def write_bundle(root: Path, lang: str, name: str, body: str = "Body text.\n", **overrides: Any) -> Path:
    slug = name[11:]
    meta = make_meta(**{"slug": slug, "translationKey": slug, **overrides})
    folder = root / "content" / lang / "posts" / name
    folder.mkdir(parents=True, exist_ok=True)
    header = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    (folder / "index.md").write_bytes(b"---\n" + header.encode() + b"---\n" + body.encode())
    return folder / "index.md"


def seed_repo(root: Path) -> Path:
    for rel in (
        "data/automation-policy.yaml",
        "data/taxonomy-policy.yaml",
        "data/theme-overrides.json",
        "pyproject.toml",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, root / rel)
    for rel in ("schemas", "prompts", "archetypes", "assets/fonts/card"):
        shutil.copytree(REPO / rel, root / rel)
    (root / "data/import-manifest.json").write_text('{"version": 1, "entries": {}}\n')
    (root / "data/card-manifest.json").write_text('{"version": 1, "cards": {}}\n')
    for rel in ("content/no/posts", "content/en/posts", "inbox/no", "inbox/en", "inbox/media"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = seed_repo(tmp_path / "repo")
    monkeypatch.setenv("BN_ROOT", str(root))
    monkeypatch.setenv("BN_NOW", NOW)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    return root


class FakeLLM:
    """Scripted stand-in for lib.llm.StructuredClient. Validates against the schema like the real one."""

    model = "fake-model-1"

    def __init__(self, responses: list[Any] | None = None, default: Any = None) -> None:
        self.responses = list(responses or [])
        self.default = default
        self.calls: list[dict[str, Any]] = []
        self.usage = llm.Usage()

    def call(self, *, purpose: str, system: str, user: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        self.calls.append({"purpose": purpose, "system": system, "user": user, "schema": schema})
        self.usage.calls += 1
        if self.responses:
            item = self.responses.pop(0)
        elif self.default is not None:
            item = self.default
        else:
            raise AssertionError(f"unexpected model call ({purpose})")
        if callable(item):
            item = item(purpose, user)
        if isinstance(item, Exception):
            raise item
        try:
            jsonschema.validate(item, schema)
        except jsonschema.ValidationError as exc:
            raise llm.InvalidOutput(f"{purpose}: response does not match the schema") from exc
        return copy.deepcopy(item)


def good_metadata(**overrides: Any) -> dict[str, Any]:
    data = {
        "title": "Generated title",
        "description": text_of_length(156, "Generated description that states what the article covers"),
        "summary": "A generated summary with a different angle.",
        "keywords": ["one phrase", "two phrase", "three phrase", "four phrase", "five phrase"],
        "categories": ["Technology"],
        "tags": ["Hugo", "k8s", "Brand New Tag"],
        "series": "",
        "series_order": 0,
    }
    data.update(overrides)
    return data


def hugo_bin() -> str:
    candidate = Path(sys.executable).parent / "hugo"
    found = str(candidate) if candidate.exists() else shutil.which("hugo")
    if not found:
        pytest.skip("hugo is not installed")
    return found


def run_script(
    name: str, *args: str, root: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "BN_ROOT": str(root), "BN_NOW": NOW, **(env or {})}
    full_env.pop("ANTHROPIC_API_KEY", None)
    full_env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{full_env['PATH']}"
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / name), *args], capture_output=True, text=True, env=full_env, check=False
    )


def copy_site_skeleton(root: Path) -> Path:
    """A buildable copy of this repository without its articles."""
    seed_repo(root)
    for rel in ("config", "layouts", "i18n", "static"):
        shutil.copytree(REPO / rel, root / rel)
    shutil.copytree(REPO / "assets", root / "assets", dirs_exist_ok=True)
    (root / "themes").mkdir()
    (root / "themes" / "blowfish").symlink_to(REPO / "themes" / "blowfish", target_is_directory=True)
    for lang in ("no", "en"):
        for path in (REPO / "content" / lang).rglob("*.md"):
            rel = path.relative_to(REPO)
            if "posts" in rel.parts and path.name == "index.md":
                continue
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, root / rel)
    return root


@pytest.fixture(scope="session")
def built_site(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Build the fixture site once: cards, production build, manifest, site validation."""
    if not (REPO / "themes/blowfish/theme.toml").exists():
        pytest.skip("theme submodule not initialised")
    from tests.fixtures.site import populate

    root = copy_site_skeleton(tmp_path_factory.mktemp("site"))
    populate(root)
    cards = run_script("generate_cards.py", root=root)
    assert cards.returncode == 0, cards.stdout + cards.stderr
    env = {**os.environ, "HUGO_PARAMS_BUILDCOMMIT": COMMIT, "HUGO_ENVIRONMENT": "production"}
    build = subprocess.run(
        [
            hugo_bin(),
            "--gc",
            "--minify",
            "--buildDrafts=false",
            "--buildFuture=false",
            "--buildExpired=false",
            "--source",
            str(root),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    public = root / "public"
    before = {p.relative_to(public).as_posix() for p in public.rglob("*") if p.is_file()}
    manifest = run_script("build_manifest.py", "--site", "public", "--commit", COMMIT, root=root)
    assert manifest.returncode == 0, manifest.stdout + manifest.stderr
    check = run_script("validate_content.py", "--site", "public", "--prune-originals", "--json", root=root)
    return {
        "root": root,
        "public": public,
        "files_before_prune": before,
        "site_check": check,
        "site_report": json.loads(check.stdout) if check.stdout.strip().startswith("{") else {},
        "manifest": json.loads((public / "publication-manifest.json").read_text()),
    }
