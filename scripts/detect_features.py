#!/usr/bin/env python3
"""Set the `math` and `mermaid` front matter flags from the article content.

Detection is structural, not textual: Mermaid means a fenced code block whose
info string is `mermaid` (or the mermaid shortcode); math means $$...$$, \\[...\\]
or \\(...\\) outside code. A single dollar sign is never math, so prices such as
$50 do not enable it. `feature_overrides: {math: true|false, mermaid: true|false}`
in the front matter overrides detection. Only the two flag lines are edited.
"""

from __future__ import annotations

import argparse
import sys

from lib import content, fm, mdscan
from lib.common import Report, load_policy, run_cli


def desired(bundle: content.Bundle) -> dict[str, bool]:
    scan = mdscan.scan(bundle.body_text)
    overrides = bundle.meta.get("feature_overrides")
    overrides = overrides if isinstance(overrides, dict) else {}
    out = {}
    for name, detected in (("math", scan.has_math), ("mermaid", scan.has_mermaid)):
        value = overrides.get(name)
        out[name] = value if isinstance(value, bool) else detected
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report differences and exit 1; change nothing")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    policy = load_policy()
    report = Report("features")
    for bundle in content.discover(policy):
        want = desired(bundle)
        changes = {k: v for k, v in want.items() if bundle.meta.get(k, False) is not v}
        if not changes:
            continue
        if not args.check:
            fm.save(bundle.doc, bundle.doc.set_scalars(dict(changes)))
        report.add(bundle.rel(policy.root), "would-change" if args.check else "changed", **changes)
    report.emit(policy.root, json_out=args.json, save=not args.check)
    return 1 if (args.check and report.items) else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
