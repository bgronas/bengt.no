"""Validate workflow_dispatch input before any other step uses it.

Input arrives from a person in the Actions UI or as a JSON `payload` from a
Pages CMS action button. Nothing from it is ever interpolated into a shell
command: this module reads environment variables, accepts only known values and
writes the validated result to $GITHUB_OUTPUT.
"""

from __future__ import annotations

import json
import os
import re
import sys

MODES = ("full", "social-only", "social-baseline")
CMS_ACTIONS = {"process-and-deploy": "full", "run-checks": "full"}
_PATH_RE = re.compile(r"^content/[a-z]{2}/posts/\d{4}-\d{2}-\d{2}-[a-z0-9-]+(?:/index\.md)?$")
_ID_RE = re.compile(r"^[a-z]{2}:[a-z0-9_-]+$")
MAX_TARGETS = 20


class DispatchError(Exception):
    pass


def parse(
    mode: str, regenerate: str, payload: str, *, repository: str, ref: str, origin: str, branch: str = "main"
) -> dict[str, str]:
    if ref != f"refs/heads/{branch}":
        raise DispatchError(f"publishing runs only from {branch}; this run was started on {ref or 'an unknown ref'}")
    mode = (mode or "full").strip()
    if payload.strip():
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DispatchError("payload is not valid JSON") from exc
        if not isinstance(data, dict) or data.get("source") != "pages-cms":
            raise DispatchError("payload was not produced by Pages CMS")
        repo = data.get("repository") or {}
        if f"{repo.get('owner')}/{repo.get('repo')}".lower() != repository.lower():
            raise DispatchError("payload was issued for a different repository")
        if repo.get("ref") != branch:
            raise DispatchError(f"Pages CMS actions are accepted from branch {branch} only")
        action = (data.get("action") or {}).get("name")
        if action not in CMS_ACTIONS:
            raise DispatchError(f"unknown Pages CMS action {action!r}")
        mode = CMS_ACTIONS[action]
        regenerate = ""
    if mode not in MODES:
        raise DispatchError(f"mode must be one of {', '.join(MODES)}")
    targets = [t.strip() for t in re.split(r"[,\n]", regenerate or "") if t.strip()]
    if len(targets) > MAX_TARGETS:
        raise DispatchError(f"at most {MAX_TARGETS} regenerate targets per run")
    for target in targets:
        ok = (
            _PATH_RE.match(target)
            or _ID_RE.match(target)
            or (target.startswith(origin + "/") and re.fullmatch(r"[A-Za-z0-9:/._~%-]+", target) and len(target) <= 300)
        )
        if not ok:
            raise DispatchError(
                "regenerate accepts permalinks on the site origin, content/<lang>/posts/<bundle>/index.md paths or page ids"
            )
    return {"mode": mode, "regenerate": ",".join(targets)}


def main() -> int:
    env = os.environ
    try:
        result = parse(
            env.get("INPUT_MODE", ""),
            env.get("INPUT_REGENERATE", ""),
            env.get("INPUT_PAYLOAD", ""),
            repository=env.get("GITHUB_REPOSITORY", ""),
            ref=env.get("GITHUB_REF", ""),
            origin=env.get("SITE_ORIGIN", "https://bengt.no"),
        )
    except DispatchError as exc:
        print(f"::error::{exc}")
        return 1
    out = env.get("GITHUB_OUTPUT")
    lines = [f"{k}={v}" for k, v in result.items()]
    if out:
        with open(out, "a", encoding="utf-8") as fh:  # noqa: PTH123
            fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
