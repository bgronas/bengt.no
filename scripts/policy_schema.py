#!/usr/bin/env python3
"""Export the JSON Schema of data/automation-policy.yaml and data/taxonomy-policy.yaml.

The schema is derived from the models every script validates the policy with
(scripts/lib/common.py), so documentation and enforcement cannot drift apart.
`--check` exits 1 when schemas/policy.schema.json is out of date.
"""

from __future__ import annotations

import argparse
import sys

from lib.common import ROOT, Policy, TaxonomyPolicy, atomic_write, dump_json, run_cli

TARGET = "schemas/policy.schema.json"


def build() -> bytes:
    return dump_json(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://bengt.no/schemas/policy.schema.json",
            "title": "Automation policy",
            "description": "automation: data/automation-policy.yaml. taxonomy: data/taxonomy-policy.yaml.",
            "automation": Policy.model_json_schema(),
            "taxonomy": TaxonomyPolicy.model_json_schema(),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    path = ROOT / TARGET
    wanted = build()
    if args.check:
        if not path.exists() or path.read_bytes() != wanted:
            print(f"{TARGET} is out of date. Run: uv run python scripts/policy_schema.py", file=sys.stderr)
            return 1
        return 0
    atomic_write(path, wanted)
    print(f"{TARGET} written")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
