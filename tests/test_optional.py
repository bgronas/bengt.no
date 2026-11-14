"""Opt-in tests. They are skipped unless explicitly enabled, and never run in ordinary CI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REPO, hugo_bin


@pytest.mark.api
@pytest.mark.skipif(
    not (os.environ.get("RUN_API_SMOKE") == "1" and os.environ.get("ANTHROPIC_API_KEY")),
    reason="set RUN_API_SMOKE=1 and ANTHROPIC_API_KEY",
)
def test_live_structured_output_smoke() -> None:
    """One small paid request: proves the configured model accepts output_config.format."""
    from lib import llm
    from lib.common import load_policy

    client = llm.StructuredClient(load_policy(REPO))
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }
    assert client.call(purpose="smoke", system="Return ok=true.", user="ping", schema=schema, max_tokens=200) == {
        "ok": True
    }


@pytest.mark.browser
@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_SMOKE") != "1", reason="set RUN_BROWSER_SMOKE=1 (needs Playwright and Chromium)"
)
def test_browser_smoke(tmp_path: Path) -> None:
    out = tmp_path / "site"
    build = subprocess.run(
        [hugo_bin(), "--source", str(REPO), "--buildDrafts", "--baseURL", "http://127.0.0.1:8766/", "--destination", str(out), "--quiet"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert build.returncode == 0, build.stderr
    python = os.environ.get("BROWSER_PYTHON", sys.executable)
    result = subprocess.run(
        [python, str(REPO / "tests/browser/smoke.py"), str(out), "8766"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
