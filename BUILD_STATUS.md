# Build status

Engineering notes for resuming the build. No credentials, no draft text.

## Fixed decisions (author answers, 2026-11-13)

| Topic | Decision |
|---|---|
| Target repository | `bgronas/bengt.no` (project Pages site, custom domain `bengt.no`). `bgronas/bgronas.github.io` is not touched. |
| Bio text | Minimal: name, neutral topic line, GitHub and LinkedIn links. |
| `bengt.no` DNS today | Another host or parked. Runbook covers replacing A/AAAA/CNAME, leaving MX/TXT. |
| Windows shell | Git Bash, with `publish.cmd` forwarding to `publish.sh`. |

## Verified versions

| Component | Version | Where pinned |
|---|---|---|
| Hugo Extended | 0.169.0 | `pyproject.toml` (`hugo==0.169.0`), `uv.lock` |
| Blowfish | v3.10.0 | submodule `themes/blowfish` |
| Python | 3.12 | `.python-version` |
| uv | 0.11.32 (build session) | `.github/actions/setup/action.yml` |

## Session constraints (build sandbox)

- `git push` to GitHub is blocked by the sandbox egress policy. Delivery is an archive plus push commands.
- No GitHub, Pages or DNS setting was changed.

## Milestones

| # | Milestone | State |
|---|---|---|
| M1 | Skeleton, pins, bilingual routes, example bundles | Done |
| M2 | Pages CMS proof and `.pages.yml` | Done (inbox-intake fallback for media) |
| M3 | Design system and public surfaces | Done, first browser review 2026-11-13 |
| M4 | Python content services and tests | Done |
| M5 | CLI, workflows, durable state | Done; one CLI test being repaired |
| M6 | Verification, acceptance report, docs, packaging | In progress |

## Log

- 2026-11-13 16:50–22:33: M1–M5 implemented. Interrupted by a usage limit with one failing test
  (`tests/test_publish_sh.py::test_ship_refuses_key_material_and_secrets_without_printing_them`).
- 2026-11-14 09:40: Resumed from the workspace. This file created.
