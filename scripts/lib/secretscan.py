"""Scan a unified diff on stdin for secret-shaped strings in added lines.

Prints `<file>: <kind>` per finding and never the matching text. This catches
well-known key formats only; it cannot recognise sensitive prose.
"""

from __future__ import annotations

import re
import sys

PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "assigned API key": re.compile(
        r"(?i)\b(?:ANTHROPIC_API_KEY|API_KEY|SECRET_KEY|ACCESS_TOKEN)\s*[=:]\s*[\"']?[A-Za-z0-9_\-/+]{24,}"
    ),
}


def scan(diff: str) -> list[str]:
    findings: list[str] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for kind, pattern in PATTERNS.items():
            entry = f"  {current}: {kind}"
            if pattern.search(line) and entry not in findings:
                findings.append(entry)
    return findings


if __name__ == "__main__":
    out = scan(sys.stdin.read())
    if out:
        print("\n".join(out))
        sys.exit(1)
