"""Static guarantees of the workflows, plus the writeback step executed against a real Git remote."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import REPO

WORKFLOWS = REPO / ".github/workflows"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "init.defaultBranch", "GIT_CONFIG_VALUE_1": "main",
}  # fmt: skip


def load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the key `on` as a boolean
    return data


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def all_text() -> str:
    return "\n".join(p.read_text() for p in [*WORKFLOWS.glob("*.yml"), REPO / ".github/actions/setup/action.yml"])


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    uses = re.findall(r"uses:\s*(\S+)", all_text())
    assert uses
    for ref in uses:
        if ref.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{ref} is not pinned to a commit SHA"
    assert re.findall(r"@[0-9a-f]{40}(?! # v\d+\.\d+\.\d+)", all_text()) == [], (
        "each pin carries its version as a comment"
    )


def test_check_workflow_is_read_only_and_secret_free() -> None:
    wf = load("check.yml")
    text = (WORKFLOWS / "check.yml").read_text()
    assert wf["permissions"] == {"contents": "read"}
    assert "pull_request" in wf["on"] and "pull_request_target" not in text
    assert "secrets." not in text and "ANTHROPIC_API_KEY" not in text
    assert "git push" not in text and "git commit" not in text and "deploy-pages" not in text
    assert all("permissions" not in job for job in wf["jobs"].values())
    checkout = next(s for s in steps(wf["jobs"]["check"]) if "actions/checkout" in s.get("uses", ""))
    assert checkout["with"]["persist-credentials"] is False


def test_deploy_permissions_are_job_specific_and_minimal() -> None:
    wf = load("deploy.yml")
    assert wf["permissions"] == {}
    jobs = wf["jobs"]
    assert jobs["prepare"]["permissions"] == {"contents": "read"}
    assert jobs["process"]["permissions"] == {"contents": "write"}
    assert jobs["build"]["permissions"] == {"contents": "read"}
    assert jobs["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert jobs["social"]["permissions"] == {"contents": "write"}
    assert jobs["deploy"]["environment"]["name"] == "github-pages"
    for name, job in jobs.items():
        assert "timeout-minutes" in job, f"{name} has no timeout"
    text = (WORKFLOWS / "deploy.yml").read_text()
    uses_key = [name for name, job in jobs.items() if "secrets.ANTHROPIC_API_KEY" in yaml.safe_dump(job)]
    assert uses_key == ["process", "social"], "the API key reaches only the two jobs that call the API"
    assert "pull_request" not in text


def test_triggers_concurrency_and_main_only() -> None:
    wf = load("deploy.yml")
    assert wf["on"]["push"]["branches"] == ["main"] and "workflow_dispatch" in wf["on"]
    assert "schedule" not in wf["on"], "no recurring task is enabled"
    assert wf["concurrency"] == {"group": "publish-main", "cancel-in-progress": False}
    assert set(wf["on"]["workflow_dispatch"]["inputs"]) == {"mode", "regenerate", "payload"}
    prepare = yaml.safe_dump(wf["jobs"]["prepare"])
    assert "scripts/lib/dispatch.py" in prepare
    assert wf["jobs"]["process"]["needs"] == "prepare"


def test_dispatch_inputs_never_reach_a_shell_directly() -> None:
    for name in ("deploy.yml", "check.yml"):
        wf = load(name)
        for job in wf["jobs"].values():
            for step in steps(job):
                run = step.get("run", "")
                assert "${{ inputs." not in run and "${{ github.event." not in run, (
                    f"{name}: expression interpolated into a script"
                )
                assert "needs.prepare.outputs.regenerate }}" not in run


def test_writeback_is_scoped_unforced_and_does_not_recurse() -> None:
    text = (WORKFLOWS / "deploy.yml").read_text()
    assert not re.search(
        r"git add\s+(-A|\.|--all)(\s|$)(?!.*\.state)", text.replace("cd .state\n          git add -A", "")
    ), "never `git add .` on main"
    assert "git add -- content data/import-manifest.json data/card-manifest.json" in text
    assert "--force" not in text and "push -f" not in text and "+refs/heads/main" not in text
    assert text.count("[skip ci]") == 3, "every bot commit carries [skip ci]"
    wf = load("deploy.yml")
    build = wf["jobs"]["build"]
    checkout = next(s for s in steps(build) if "actions/checkout" in s.get("uses", ""))
    assert checkout["with"]["ref"] == "${{ needs.process.outputs.content_sha }}", (
        "the build uses the processed commit, not the event SHA"
    )
    assert wf["jobs"]["deploy"]["needs"] == ["process", "build"]
    hugo = next(s["run"] for s in steps(build) if "hugo --gc --minify" in s.get("run", ""))
    assert "--buildDrafts=false --buildFuture=false --buildExpired=false" in hugo
    assert 'test "$(git rev-parse HEAD)" = "$HUGO_PARAMS_BUILDCOMMIT"' in hugo


def test_social_job_runs_only_after_a_successful_deployment() -> None:
    wf = load("deploy.yml")
    social = wf["jobs"]["social"]
    assert social["needs"] == ["prepare", "process", "build", "deploy"]
    condition = " ".join(social["if"].split())
    assert "needs.prepare.outputs.mode == 'full' && needs.deploy.result == 'success'" in condition
    order = [s.get("name") for s in steps(social)]
    assert (
        order.index("Verify the deployment and write drafts")
        < order.index("Persist state")
        < order.index("Clear fulfilled regeneration requests on main")
    )
    upload = next(s for s in steps(social) if s.get("name", "").startswith("Upload social drafts"))
    assert upload["with"]["path"] == "social-drafts/" and upload["with"]["retention-days"] == 30
    pages = next(s for s in steps(wf["jobs"]["build"]) if "upload-pages-artifact" in s.get("uses", ""))
    assert pages["with"]["path"] == "public", "social drafts are a separate artifact, never part of the site"


def test_dependabot_never_auto_merges_and_leaves_hugo_alone() -> None:
    data = yaml.safe_load((REPO / ".github/dependabot.yml").read_text())
    ecosystems = {u["package-ecosystem"]: u for u in data["updates"]}
    assert set(ecosystems) == {"github-actions", "uv"}
    assert ecosystems["uv"]["ignore"] == [{"dependency-name": "hugo"}]
    assert "auto-merge" not in all_text() and "automerge" not in all_text()


# ---------- the writeback step, executed ----------


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def remote_and_ci(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote, author, ci = tmp_path / "remote.git", tmp_path / "author", tmp_path / "ci"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "clone", "-q", str(remote), str(author))
    (author / "content").mkdir()
    (author / "data").mkdir()
    (author / "content/a.md").write_text("a\n")
    (author / "data/import-manifest.json").write_text("{}\n")
    (author / "data/card-manifest.json").write_text("{}\n")
    git(author, "add", "-A")
    git(author, "commit", "-q", "-m", "initial")
    git(author, "push", "-q", "origin", "HEAD:main")
    git(tmp_path, "clone", "-q", str(remote), str(ci))
    return remote, author, ci


def run_commit_step(ci: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    wf = load("deploy.yml")
    script = next(s["run"] for s in steps(wf["jobs"]["process"]) if s.get("id") == "commit")
    env = {
        **os.environ, **GIT_ENV, "BOT_NAME": "github-actions[bot]", "BOT_EMAIL": "bot@example.com", "GITHUB_SHA": "event-sha",
        "GITHUB_OUTPUT": str(tmp_path / "output"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }  # fmt: skip
    return subprocess.run(["bash", "-c", script], cwd=ci, env=env, capture_output=True, text=True, check=False)


def test_writeback_commits_only_generated_paths_and_reports_the_content_commit(remote_and_ci, tmp_path: Path) -> None:
    remote, _, ci = remote_and_ci
    event_sha = git(ci, "rev-parse", "HEAD")
    (ci / "content/a.md").write_text("a\nenriched\n")
    (ci / "stray.txt").write_text("must not be committed\n")
    result = run_commit_step(ci, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    content_sha = (tmp_path / "output").read_text().strip().removeprefix("content_sha=")
    assert content_sha == git(remote, "rev-parse", "main") != event_sha, "the deployed commit is the processed one"
    assert git(remote, "show", "--name-only", "--format=%s", "main").splitlines() == [
        "Process content: generated metadata and assets [skip ci]",
        "",
        "content/a.md",
    ]
    assert "stray.txt" not in git(remote, "ls-tree", "-r", "--name-only", "main")


def test_writeback_without_changes_keeps_the_commit(remote_and_ci, tmp_path: Path) -> None:
    remote, _, ci = remote_and_ci
    head = git(ci, "rev-parse", "HEAD")
    assert run_commit_step(ci, tmp_path).returncode == 0
    assert (tmp_path / "output").read_text().strip() == f"content_sha={head}" and git(
        remote, "rev-parse", "main"
    ) == head


@pytest.mark.parametrize("generated", [True, False], ids=["with-generated-changes", "without-changes"])
def test_concurrent_user_push_stops_the_run_without_force(remote_and_ci, tmp_path: Path, generated: bool) -> None:
    remote, author, ci = remote_and_ci
    (author / "content/b.md").write_text("pushed by the author while CI was processing\n")
    git(author, "add", "-A")
    git(author, "commit", "-q", "-m", "author push")
    git(author, "push", "-q", "origin", "HEAD:main")
    author_sha = git(author, "rev-parse", "HEAD")
    if generated:
        (ci / "content/a.md").write_text("a\nenriched\n")
    result = run_commit_step(ci, tmp_path)
    assert result.returncode != 0, "the run must stop before deployment"
    assert "main advanced during processing" in result.stdout + result.stderr
    assert git(remote, "rev-parse", "main") == author_sha, "the author's commit is neither overwritten nor rewritten"
    assert not (tmp_path / "output").exists(), "no content commit is handed to the build job"
