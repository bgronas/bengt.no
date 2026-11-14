# bengt.no

Source of the engineering publication at <https://bengt.no/>: Hugo Extended with the Blowfish theme, Markdown page bundles in Git, a Python automation layer, GitHub Actions for processing and deployment, and Pages CMS for browser and mobile editing. Git is the source of truth. There is no database and no application server.

## Setup (once per machine)

Needs Git, Bash and [uv](https://docs.astral.sh/uv/getting-started/installation/). Nothing is installed system-wide; Hugo Extended and Python packages come from `uv.lock` into `.venv/`.

```bash
git clone --recurse-submodules https://github.com/bgronas/bengt.no.git
cd bengt.no
./publish.sh setup     # locked dependencies, theme submodule, then doctor
```

On Windows run the same commands in Git Bash, or use `publish.cmd` from cmd.exe or PowerShell (`publish new my-post-slug en`). It forwards to `publish.sh` through Git Bash. WSL2 works as on Linux. A native PowerShell port does not exist.

## The three daily commands

```bash
./publish.sh new "my-post-slug" en        # or: no
./publish.sh preview                      # http://localhost:1313/, drafts included
./publish.sh ship "Publish my post"       # import, validate, commit, push to main
```

`new` creates `content/<lang>/posts/<today>-<slug>/index.md` from the archetype and opens it in VS Code when `code` is on the PATH. A rough Markdown file dropped into `inbox/en/` or `inbox/no/` is turned into a bundle by `ship` as well.

## The publication gate

Every new or imported article is a draft. Nothing goes live until you say so:

```bash
./publish.sh ready content/en/posts/2026-11-14-my-post-slug/index.md
./publish.sh ship "Publish my post"
```

`ready` changes one line (`draft: false`). It uses no API and does not enrich. Two flags stay independent:

| Flag | Meaning |
|---|---|
| `draft: false` | Authorises publication. |
| `auto_enrich: true` | Authorises metadata generation through the Anthropic API. |

A ready article with incomplete metadata stops the deployment at validation instead of going out with gaps.

## What happens after a push

One workflow run (`.github/workflows/deploy.yml`): import inbox files, validate, enrich opted-in metadata, create requested translation drafts, detect math and Mermaid, render title cards, commit generated files with `[skip ci]`, build and deploy exactly that commit, then write LinkedIn and X drafts as a workflow artifact. Nothing is posted to either platform.

Social drafts: repository → Actions → the run → Artifacts → `social-drafts-<run id>` (kept 30 days).

## All commands

| Command | Purpose | Uses the API |
|---|---|---|
| `./publish.sh setup` | Install locked dependencies and the theme, run `doctor` | No |
| `./publish.sh new <slug> <no\|en> [--key KEY] [--title TITLE]` | New draft bundle | No |
| `./publish.sh ready <index.md>` / `draft <index.md>` | Set or clear the publication gate | No |
| `./publish.sh import [--dry-run]` | Inbox files to bundles | No |
| `./publish.sh enrich [--dry-run\|--check\|--force] [PATH]` | Generate metadata for `auto_enrich: true` | Yes (not for `--dry-run`, `--check`) |
| `./publish.sh translate <bundle> [--refresh]` | Review draft in the other language | Yes |
| `./publish.sh social <permalink-or-bundle>` | Regenerate drafts for a confirmed deployed article | Yes |
| `./publish.sh check [--external-links] [--fix-features]` | Validation plus a production build | No |
| `./publish.sh preview` | Local preview with drafts, bound to localhost | No |
| `./publish.sh ship "<message>"` | Import, validate, commit, push | No |
| `./publish.sh doctor` | Tools, pins, configuration consistency | No |
| `./publish.sh cards` / `cms-sync` / `test` | Title cards, regenerate `.pages.yml`, linters and tests | No |

API commands need `ANTHROPIC_API_KEY` in the environment or in a local `.env` (ignored by Git). API usage is billed to the key's account, separately from any Claude subscription.

## Documentation

| Topic | File |
|---|---|
| One-time GitHub, Pages and DNS activation | [docs/dns-and-pages.md](docs/dns-and-pages.md) |
| Daily authoring, flags, translation, social drafts | [docs/editorial-workflow.md](docs/editorial-workflow.md) |
| Browser and mobile editing with Pages CMS | [docs/cms.md](docs/cms.md) |
| Ownership of inputs and outputs, state, idempotency, races | [docs/architecture.md](docs/architecture.md) |
| Recovery procedures, updates, policy file | [docs/operations.md](docs/operations.md) |
| Design tokens, typography, measured accessibility and performance | [docs/design-system.md](docs/design-system.md) |
| Design decisions and verified versions | [docs/decisions.md](docs/decisions.md) |
| Commands run, results, untested external behaviour | [docs/acceptance-report.md](docs/acceptance-report.md) |

## Troubleshooting

| Symptom | Where to look |
|---|---|
| `ship` refuses to push | [operations.md, "Blocked ship"](docs/operations.md#blocked-ship) |
| Run failed at "Final production validation" | [operations.md, "Failed enrichment"](docs/operations.md#failed-enrichment) |
| Run failed at "Commit generated changes" | [operations.md, "Blocked writeback"](docs/operations.md#blocked-writeback) |
| "site deployed; social drafts pending" | [operations.md, "Failed social generation"](docs/operations.md#failed-social-generation) |
| Domain or certificate problems | [dns-and-pages.md, "Troubleshooting"](docs/dns-and-pages.md#troubleshooting) |

## Versions

Hugo Extended 0.169.0, Blowfish v3.10.0, Python 3.12, uv 0.11.32. Exact pins and the update procedure: [docs/operations.md](docs/operations.md#updating-pinned-versions).
