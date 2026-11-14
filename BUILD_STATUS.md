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
| M3 | Design system and public surfaces | Done; second browser review 2026-11-14 (reading measure corrected) |
| M4 | Python content services and tests | Done |
| M5 | CLI, workflows, durable state | Done |
| M6 | Verification, acceptance report, docs, packaging | Done 2026-11-14 |

## Log

- 2026-11-13 16:50–22:33: M1–M5 implemented. Interrupted by a usage limit with one failing test
  (`tests/test_publish_sh.py::test_ship_refuses_key_material_and_secrets_without_printing_them`).
- 2026-11-14 09:40: Resumed from the workspace. This file created.
- 2026-11-14 10:40–11:20: Second resume. Author confirmed: continue this build, target `bgronas/bengt.no`,
  delivery as an archive, earlier answers unchanged. Wrote `docs/cms.md`, `operations.md`,
  `dns-and-pages.md`, `design-system.md`, `acceptance-report.md`. Full verification pass: commands and
  results in `docs/acceptance-report.md`.

## Open after this build (external, not code)

1. Push and activate: `docs/dns-and-pages.md`. Nothing has been pushed.
2. First workflow run on GitHub, first live API call, Pages CMS in the hosted application: untested until then.
3. LCP 2.6 s on list pages in the lab (target 2.5 s): `docs/design-system.md`.
