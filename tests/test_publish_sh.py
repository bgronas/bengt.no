"""publish.sh against a real local Git remote. No network, no API."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import NOW, REPO

pytestmark = pytest.mark.skipif(shutil.which("uv") is None or shutil.which("bash") is None, reason="needs uv and bash")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "init.defaultBranch", "GIT_CONFIG_VALUE_1": "main",
}  # fmt: skip


def env() -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k not in ("BN_ROOT", "ANTHROPIC_API_KEY")}
    return {
        **base, **GIT_ENV, "BN_NOW": NOW, "BN_ALLOW_ANY_REMOTE": "1",
        "UV_PROJECT_ENVIRONMENT": str(Path(sys.executable).parent.parent), "UV_OFFLINE": "1",
    }  # fmt: skip


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env(), capture_output=True, text=True, check=True).stdout.strip()


def publish(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "./publish.sh", *args], cwd=cwd, env=env(), capture_output=True, text=True, check=False
    )


@pytest.fixture
def work(tmp_path: Path) -> tuple[Path, Path]:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    work.mkdir()
    for rel in (
        "publish.sh",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        ".gitignore",
        ".gitattributes",
        ".pages.yml",
    ):
        shutil.copyfile(REPO / rel, work / rel)
    for rel in ("scripts", "data", "schemas", "prompts", "archetypes", "config", "assets/fonts/card"):
        shutil.copytree(REPO / rel, work / rel, ignore=shutil.ignore_patterns("__pycache__"))
    (work / "data/import-manifest.json").write_text('{"version": 1, "entries": {}}\n')
    (work / "data/card-manifest.json").write_text('{"version": 1, "cards": {}}\n')
    (work / "themes/blowfish").mkdir(parents=True)
    (work / "themes/blowfish/theme.toml").write_text('name = "stub"\n')
    for rel in ("content/no/posts", "content/en/posts", "inbox/no", "inbox/en", "inbox/media"):
        (work / rel).mkdir(parents=True)
        (work / rel / ".gitkeep").write_text("")
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "initial")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "origin", "HEAD:main")
    return work, remote


def test_ship_imports_validates_commits_and_pushes(work: tuple[Path, Path]) -> None:
    repo, remote = work
    (repo / "inbox/en/first-notes.md").write_text("# First notes\n\nSome rough text.\n")
    result = publish(repo, "ship", "Add first notes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    files = git(remote, "ls-tree", "-r", "--name-only", "main")
    assert "content/en/posts/2026-11-13-first-notes/index.md" in files
    assert "content/en/posts/2026-11-13-first-notes/feature.webp" in files, (
        "the title card is rendered locally, no API involved"
    )
    assert "inbox/en/first-notes.md" in files, "the inbox source is kept"
    assert git(repo, "log", "-1", "--format=%s") == "Add first notes"
    assert "draft: true" in (repo / "content/en/posts/2026-11-13-first-notes/index.md").read_text()

    head = git(repo, "rev-parse", "HEAD")
    again = publish(repo, "ship", "Nothing new")
    assert again.returncode == 0 and "Nothing to ship" in again.stdout
    assert git(repo, "rev-parse", "HEAD") == head, "a no-change ship never manufactures a commit"


def test_ready_changes_only_the_draft_flag_and_needs_no_api(work: tuple[Path, Path]) -> None:
    repo, _ = work
    (repo / "inbox/en/note.md").write_text("# A note\n\nText.\n")
    assert publish(repo, "import").returncode == 0
    index = repo / "content/en/posts/2026-11-13-a-note/index.md"
    before = index.read_text().split("\n")
    result = publish(repo, "ready", "content/en/posts/2026-11-13-a-note/index.md")
    assert result.returncode == 0, result.stderr
    after = index.read_text().split("\n")
    assert [(a, b) for a, b in zip(before, after, strict=True) if a != b] == [("draft: true", "draft: false")]
    assert "auto_enrich: true" in index.read_text(), "ready does not enrich and does not change the enrichment flag"
    assert publish(repo, "ready", "../outside/index.md").returncode != 0


def test_ship_requires_main(work: tuple[Path, Path]) -> None:
    repo, remote = work
    git(repo, "switch", "-q", "-c", "feature")
    (repo / "inbox/en/x.md").write_text("# X\n")
    result = publish(repo, "ship", "From a branch")
    assert result.returncode != 0 and "Publishing happens from 'main'" in result.stderr
    assert not (repo / "content/en/posts/2026-11-13-x").exists()
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "main")


def test_ship_refuses_key_material_and_secrets_without_printing_them(work: tuple[Path, Path]) -> None:
    repo, remote = work
    head = git(repo, "rev-parse", "HEAD")
    secret = "sk-ant-" + "Q9x7" * 12
    (repo / "notes.txt").write_text(f"api key: {secret}\n")
    (repo / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")
    (repo / ".env").write_text(f"ANTHROPIC_API_KEY={secret}\n")
    (repo / "id_ed25519").write_text("not ignored by .gitignore, still key material\n")
    git(repo, "add", "-f", "server.pem")  # force-added past .gitignore: the accidentally tracked case
    result = publish(repo, "ship", "Oops")
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "notes.txt: Anthropic API key" in output
    assert "server.pem (key material)" in output and "id_ed25519 (key material)" in output
    assert secret not in output, "matching secret values are never printed"
    assert git(repo, "rev-parse", "HEAD") == head == git(remote, "rev-parse", "main")
    assert git(repo, "diff", "--cached", "--name-only") == "", "the index is left clean"
    assert (repo / "notes.txt").exists() and (repo / "server.pem").exists(), "work is never discarded"
    assert ".env" not in git(repo, "status", "--porcelain", "--untracked-files=all"), ".env is ignored"


def test_ship_fast_forwards_bot_commits_and_stops_on_divergence(work: tuple[Path, Path], tmp_path: Path) -> None:
    repo, remote = work
    bot = tmp_path / "bot"
    git(tmp_path, "clone", "-q", str(remote), str(bot))
    (bot / "data/note.txt").write_text("generated by the workflow\n")
    git(bot, "add", "-A")
    git(bot, "commit", "-q", "-m", "Process content [skip ci]")
    git(bot, "push", "-q", "origin", "HEAD:main")

    (repo / "inbox/en/after-bot.md").write_text("# After bot\n")
    result = publish(repo, "ship", "After the bot commit")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Fast-forwarding" in result.stdout
    assert git(remote, "log", "--format=%s", "main").splitlines()[:2] == [
        "After the bot commit",
        "Process content [skip ci]",
    ]

    (bot / "data/note.txt").write_text("another remote commit\n")
    git(bot, "pull", "-q", "--ff-only", "origin", "main")
    (bot / "data/note2.txt").write_text("x\n")
    git(bot, "add", "-A")
    git(bot, "commit", "-q", "-m", "remote change")
    git(bot, "push", "-q", "origin", "HEAD:main")
    (repo / "local.txt").write_text("local commit\n")
    git(repo, "add", "local.txt")
    git(repo, "commit", "-q", "-m", "local commit")
    local_head, remote_head = git(repo, "rev-parse", "HEAD"), git(remote, "rev-parse", "main")
    (repo / "dirty.txt").write_text("uncommitted work\n")
    result = publish(repo, "ship", "Diverged")
    assert result.returncode != 0 and "diverged" in result.stderr and "git pull --rebase" in result.stderr
    assert git(repo, "rev-parse", "HEAD") == local_head and git(remote, "rev-parse", "main") == remote_head
    assert (repo / "dirty.txt").read_text() == "uncommitted work\n", "no reset, no stash, no force"
    assert git(repo, "stash", "list") == ""


def test_new_validates_arguments_and_is_collision_safe(work: tuple[Path, Path]) -> None:
    repo, _ = work
    assert publish(repo, "new", "my-post", "de").returncode != 0
    assert publish(repo, "new", "!!!", "en").returncode != 0
    assert publish(repo, "new").returncode != 0
    assert publish(repo, "bogus-command").returncode == 2
    assert not list((repo / "content/en/posts").glob("2026-*"))
