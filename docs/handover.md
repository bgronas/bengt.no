# Handover and reproduction brief

Written 2026-11-15 by the build session (Claude; the session was configured for the model id `claude-fable-5-2`) for whoever continues this work: a person, or another model such as Claude Opus 5.5. It records what was built, in which order, which decisions the original brief left open, and every defect that cost time. With it, the result can be reproduced without repeating the detours.

Evidence classes used here: **VERIFIED** (run or read in the build session), **AUTHOR** (stated by Bengt Grønås), **INFERENCE**, **ASSUMPTION**.

## 1. Two ways to use this

| Mode | Start from | When |
|---|---|---|
| **Resume** | The Git bundle (`git clone <bundle> bengt.no`), then this file, `BUILD_STATUS.md`, `docs/decisions.md` | Normal case. The repository is complete and tested; work continues from section 9 |
| **Rebuild** | The author's master prompt (`fable-5-2-blowfish-cms-master-prompt.md`, 20 sections; not stored in this repository) plus sections 3 to 7 of this file | Only if the repository is lost or a deliberately different result is wanted |

Ready-to-paste prompts for both modes are in section 10.

## 2. What exists

A Hugo Extended + Blowfish site with a Git-native editorial pipeline, for the repository `bgronas/bengt.no` and the domain `bengt.no`.

| Layer | Content |
|---|---|
| Site | Norwegian Bokmål at `/`, British English at `/en/`; custom homepage, design layer, render hooks, 404; three tracked theme overrides; theme submodule unmodified |
| CLI | `publish.sh` (Bash; `publish.cmd` forwards from cmd.exe/PowerShell): `setup`, `new`, `ready`, `draft`, `import`, `enrich`, `translate`, `social`, `cards`, `check`, `preview`, `ship`, `doctor`, `cms-sync`, `test` |
| Automation | 13 Python scripts and 11 library modules under `scripts/`: importer, enrichment, translation, feature detection, title cards, image audit, validation, publication manifest, social drafts, CMS schema generator, policy schema, doctor |
| CI/CD | `deploy.yml` (process → build → deploy → social, one run), `check.yml` (read-only, pull requests), composite setup action, Dependabot |
| CMS | Generated `.pages.yml` for Pages CMS: intake collections, article collections in tree view, two action buttons |
| Policy | `data/automation-policy.yaml`, `data/taxonomy-policy.yaml`, JSON schemas, three system prompts |
| Tests | 171 passing, 2 opt-in skipped (`api`, `browser`); browser smoke test with axe; Lighthouse figures recorded |
| Docs | `README.md`, ten files in `docs/` including this one, `BUILD_STATUS.md` |

Versions, all pinned (VERIFIED): Hugo Extended 0.169.0 (PyPI wheel `hugo==0.169.0`), Blowfish v3.10.0 at `3e4b25c4dc74` (declares Hugo 0.166.0 to 0.169.0), Python 3.12, uv 0.11.32 in CI, anthropic SDK 2.8.0, default model `claude-sonnet-5-5`. Action commits and the full table: `docs/acceptance-report.md`, section 2.

## 3. Author decisions

These are not derivable from the master prompt. A rebuild must take them as given.

| Topic | Decision | Date |
|---|---|---|
| Target repository | `bgronas/bengt.no`, a project Pages site with custom domain `bengt.no`. Not `bgronas/bgronas.github.io`, which the master prompt names | 2026-11-13 |
| `bgronas/bgronas.github.io` | Untouched, on GitHub and on disk | 2026-11-13, repeated 2026-11-14 |
| `bgronas/test666` | The Hugo source of the site `bengt.no` serves from Misshosting today. Untouched | 2026-11-14 |
| `bgronas/bengt.no` on GitHub | Placeholder with one README commit. May be overwritten: first push is a one-time `git push --force origin main` | 2026-11-14 |
| Biography | Minimal: name, one neutral topic line, GitHub and LinkedIn links. Nothing invented | 2026-11-13 |
| Windows | Git Bash, plus `publish.cmd` as a thin forwarder | 2026-11-13 |
| Delivery | Git bundle and Markdown runbook. No push from the build session | 2026-11-14 |
| Cutover | Deploy to GitHub Pages first, change DNS last | 2026-11-14 |
| Working copy | `~/Dropbox/HUGO/Sites/bengt.no` on the author's machine. Recommendation given: keep `.venv` outside the synced folder with `UV_PROJECT_ENVIRONMENT` | 2026-11-14 |

## 4. Order of work

The master prompt's six milestones were followed. Each has a gate; do not start the next before the gate passes.

| # | Milestone | What was done | Gate |
|---|---|---|---|
| 0 | Pre-flight | Probed tools and network; checked both GitHub repositories; asked four questions (section 3); sent a plan | Answers received |
| 1 | Skeleton | `git init`, Blowfish as submodule at the newest tag, `uv` project with Hugo as a dependency, `config/_default/*.toml`, two linked example bundles, fonts, colour scheme, homepage partial, manifest output format | `hugo --buildDrafts` builds both languages; Norwegian at root; no `/no/` pages |
| 2 | Pages CMS proof | Read the documentation (web fetch) and cloned upstream `pages-cms` 2.1.8 to read the source for the five compatibility questions | Each question answered with file-level evidence; fallback chosen |
| 3 | Design | `custom.css` tokens, render hooks (image, link, table, Mermaid, math), 404, social metadata partial, head override; screenshots at 375/768/1440 in both appearances reviewed | No horizontal overflow; screenshots reviewed |
| 4 | Content services | `lib/` (policy, front matter IO, Markdown scanner, LLM client, taxonomy, segments, X weighting), then importer, enrichment, translation, feature detection, cards, image audit, validation, manifest, social drafts, CMS generator | Each script smoke-tested by hand, then unit tests with a mocked API |
| 5 | CLI and workflows | `publish.sh`, secret scan, `publish.cmd`, `doctor`, composite action, `check.yml`, `deploy.yml`, dispatch validation, state branch logic | Workflow JSON schema valid; writeback step executed in a test against a local bare repository |
| 6 | Verification and docs | Ruff, mypy, pytest, browser smoke with axe, Lighthouse, fresh-clone run, bundle round trip; all documents; acceptance report | `./publish.sh test` green; fresh clone follows the README; bundle clone works |
| 7 | First run on the author's machine | Windows defects fixed (section 6, items 14 and 15); overwrite route documented | AUTHOR, 2026-11-15: `doctor` and `preview` "100% OK" from a clean clone |

Order inside milestone 4 that worked: policy and schemas first, then front matter IO, then the importer and enrichment (smallest loop that touches the API client), then translation, then cards, validation and social state last. Tests were written after each group, not at the end.

## 5. Decisions the master prompt leaves open

| Question | Choice | Reason |
|---|---|---|
| How to pin Hugo | As a Python dependency (`hugo==0.169.0` wheel) in `uv.lock` | One lockfile pins Python packages and Hugo for local use and CI; no administrator rights. Dependabot is told to ignore `hugo`; it moves with the theme |
| Locale for key `no` | `locale = "nb"`; public key and paths stay `no` | `nb-NO` does not resolve the theme's `i18n/nb.yaml`; `nb` does |
| Featured | `featured: true` plus optional `featured_weight`; order weight, date descending, path | Deterministic; no second mechanism |
| Series | Theme's `series` taxonomy and numeric `series_order` | Blowfish sorts numerically in `partials/series/series_base.html` |
| Images | Hugo is the only writer of derivatives; Pillow only inspects | Avoids two pipelines rewriting the same files |
| Originals | `publishResources = false` cascaded to pages, plus `validate_content.py --site … --prune-originals` | The cascade alone is not enough: an original is published whenever a template asks for its URL |
| Math | Goldmark passthrough and `transform.ToMath` at build time; `$$…$$`, `\[…\]`, `\(…\)` only | A single `$` is never a delimiter, so `$50` is text; only a stylesheet is loaded |
| Raw HTML | `unsafe = false` | Master prompt default |
| Structured output | `output_config.format` with `type: "json_schema"`; schema sent without length keywords; lengths validated locally with Pydantic | The API schema dialect does not enforce them |
| Front matter writes | Parse with `python-frontmatter`; re-render only the header; body is the original byte slice | Exact body preservation |
| What counts as published | Hugo output format `PublicationManifest` on the home page, merged by `build_manifest.py` | Only pages Hugo actually rendered for production can appear |
| Durable social state | Branch `automation-state` with `publications.json` and `social.json`; hashes and status only | Survives artifact expiry; never merged into `main` |
| Deployment verification | `<meta name="x-content-commit">` on each page must equal the deployed content commit | HTTP 200 from an older deployment is not proof |
| Pages CMS | Intake collections under `inbox/`, media in `inbox/media`, importer creates bundles; existing bundles edit-only in tree view; `settings.content.merge: true` | Per-entry media upload is not possible; bundle creation from a template is not reliable |
| `deploy-pages` | v5.0.1 instead of v4 | Current release, same inputs and `page_url` output |
| Default social image | Generated PNG (`generate_cards.py --brand`), no SVG | Crawlers need a raster image; one source instead of two |
| Reading measure | `--bn-measure: 58ch` | Measured 73 to 77 characters per line; see item 9 below |

Full reasoning: `docs/decisions.md` and `docs/architecture.md`.

## 6. Defects and traps, in the order they were met

Each of these was hit once. A rebuild that knows them saves most of the debugging time.

1. **YAML reads `no` as false.** PyYAML follows YAML 1.1. The language key `no` became a boolean. Fix: `scripts/lib/yamlx.py`, a loader where only `true`/`false` are booleans and timestamps stay strings.
2. **`locale = "nb-NO"` loses the theme's Norwegian strings.** Fix: `locale = "nb"`.
3. **The theme's `nb.yaml` lacks seven keys its `en.yaml` has** (`nav.*`, `error.404_home`, `article.reply_to`). Without `nav.main_menu` the mobile menu button has no accessible name. Found by axe. Fix: local `i18n/nb.yaml`.
4. **Search button fails WCAG 2.5.3 (label in name).** The visible shortcut hint must be part of the accessible name. Fix: `search.open_button_title` in both local i18n files.
5. **The theme's search index and RSS needed overrides.** `index.json` was not strictly per language; `rss.xml` linked original feature images. Fix: local copies, each recorded with the SHA-256 of its upstream original in `data/theme-overrides.json`; `doctor` and a test fail when upstream changes. `partials/head.html` is the third override (processed social image, keywords).
6. **Originals still reached the output** despite `publishResources = false`. Fix: prune step in site validation, and a test that compares hashes of every output file with the originals.
7. **Mermaid cost 28 Lighthouse points.** The theme's bundle is 5.5 MB; loading it on page load gave mobile performance 70 on the example article. Fix: load it when a diagram comes within 600 px of the viewport or before printing. Result: 98.
8. **Copy buttons were hover-only.** Fix: reachable by keyboard, always visible on touch screens.
9. **`72ch` is not 72 characters.** `ch` is the width of "0"; Roboto's average glyph is narrower. Measured 87 to 96 characters per line. Fix: 58ch, and a browser check that asserts 60 to 80.
10. **LCP 2.6 s on list pages** (target 2.5 s, simulated slow 4G). The theme renders list thumbnails with `loading="lazy"` and `fetchpriority="low"`. A preload link was tried and did not change the figure. Not fixed; the fix would be a fourth theme override.
11. **Pages CMS booleans have no "inherit" state** and coerce a missing value to `false`. Per-article `showTableOfContents` and `showZenMode` are therefore not form fields.
12. **`ship` secret refusal must also catch force-added key files.** A test failed until the staged-file guard covered them.
13. **`enrich` without an API key printed "nothing to do"** before the error. Fix: waiting articles are reported as backlog.
14. **CRLF on Windows broke three doctor checks.** Git for Windows checks the theme out with CRLF; hashes were recorded from LF files. The same flaw sat unobserved in the import manifest. Fix: `sha256_text` normalises CRLF to LF for every text hash compared across machines.
15. **Ctrl+C in `preview` printed a Python traceback on Windows.** The Hugo wheel's launcher runs Hugo as a child process. Fix: `publish.sh` starts the binary inside the wheel directly.
16. **A Git bundle made with `git bundle create f main` cannot be cloned** ("remote HEAD refers to nonexistent ref"). Fix: `git bundle create f HEAD main`.
17. **`/no/sitemap.xml` exists** and is correct: Hugo's sitemap index references one sitemap per language. No HTML page is under `/no/`.
18. **The project address looks broken before the custom domain is set** (INFERENCE): the site is built for the root of `bengt.no`, so its root-relative URLs miss at `bgronas.github.io/bengt.no/`. Judge by the local preview and the green run.
19. **The opt-in external link check had no test.** Added with a stub HTTP client.

## 7. Verification: exact commands and expected results

Run in the repository root. All offline except the theme fetch in `setup`.

| Command | Expected |
|---|---|
| `./publish.sh setup` | Ends with `doctor: 0 failure(s)`; warnings only for a missing `code` command or `origin` |
| `./publish.sh test` | Ruff clean, mypy "no issues found", two schema validations ok, `171 passed, 2 skipped` |
| `./publish.sh check` | "check passed" |
| `./publish.sh preview` | "Web Server is available at http://localhost:1313/"; both example drafts visible |
| Browser smoke (optional; commands in `docs/operations.md`, "Routine checks") | `201 passed, 0 failed`, including 40 axe runs with 0 violations |
| `./publish.sh new "x-test" en`, fill metadata, `ready`, production build | `/en/posts/x-test/`, no date in the URL, JPEG 1200×630 `og:image`, one entry in `publication-manifest.json` |

Reproduction of the Windows defect on Linux: clone, then check the theme out with `core.autocrlf=true`; `doctor` must still report 0 failures.

## 8. Constraints of the build environment

They shaped the delivery, not the code. Another environment may differ.

- `git push` to GitHub was blocked; `git clone`, `git ls-remote` and package registries worked. Hence the bundle.
- Shell access to `pagescms.org`, Google Fonts and `github.com` release downloads was blocked. Documentation was read through a web-fetch tool; Roboto came from npm (`@fontsource-variable/roboto` 5.3.0, `@fontsource-variable/roboto-mono` 5.3.0) and the `google/fonts` repository; Hugo came from PyPI.
- No Anthropic API key, no Windows, no macOS, no Firefox or Safari.
- The session lost its conversation context several times (a usage limit, then restarts). Each time the work was resumed from `BUILD_STATUS.md`, `docs/decisions.md`, the Git history and the session record. Keep `BUILD_STATUS.md` current; it is what makes this build resumable.

## 9. State and what is open

Repository state at handover: branch `main`, working tree clean, test suite green. Nothing has been pushed; `bgronas/bengt.no` on GitHub still holds its single README commit (VERIFIED with `git ls-remote`, 2026-11-15).

Next steps, in order (`docs/runbook.md`, section 2):

1. Pages source "GitHub Actions", then `git push --force origin main`.
2. Watch the first Publish run. **This is the first time any workflow runs on GitHub**, so it is the most likely place for a defect.
3. Domain verification, custom domain, DNS cutover, Enforce HTTPS.
4. `ANTHROPIC_API_KEY` secret, then the first article with `auto_enrich: true`: first live API call.
5. Pages CMS GitHub App, then the five checks in `docs/cms.md` against the hosted application.

Never exercised (full list with reasons: `docs/acceptance-report.md`, section 7): workflows on GitHub, live API calls, hosted Pages CMS, DNS and HTTPS, `publish.cmd`, macOS, non-Chromium browsers. Known miss: LCP on list pages (item 10).

Rules that must keep holding:

- Do not touch `bgronas/bgronas.github.io` or `bgronas/test666`.
- Do not modify `themes/blowfish`. Extend through `layouts/`, `assets/`, `i18n/`, and record every override in `data/theme-overrides.json`.
- Do not invent biography, credentials, model identifiers, action SHAs or test results. Report what was run.
- `.pages.yml` is generated: edit the policy or `scripts/sync_cms_schema.py`, then `./publish.sh cms-sync`.
- After the first push, no force push anywhere.

## 10. Prompts

### Resume

```text
You are continuing an existing, tested repository. Do not rebuild it.

1. Clone it: git clone <bundle or https://github.com/bgronas/bengt.no.git> bengt.no
2. Read, in this order: docs/handover.md, BUILD_STATUS.md, docs/decisions.md,
   docs/acceptance-report.md (sections 7 to 9).
3. Run ./publish.sh setup and ./publish.sh test. Stop and report if either fails;
   expected results are in docs/handover.md, section 7.
4. Task: <describe the task>.

Rules: keep themes/blowfish unmodified; do not touch bgronas/bgronas.github.io or
bgronas/test666; no force push; never invent versions, model identifiers, commit
SHAs or results. Verify current facts against official documentation. Classify
claims as VERIFIED, INFERENCE or ASSUMPTION. After the change: ./publish.sh test
and ./publish.sh check must pass; add or extend a test for every defect fixed;
update BUILD_STATUS.md and, for a design decision, docs/decisions.md.
```

### Rebuild

```text
Build the system specified in the attached master prompt
(fable-5-2-blowfish-cms-master-prompt.md). Apply docs/handover.md as an addendum
that overrides the master prompt where they differ:

- Section 3: author decisions (target repository bgronas/bengt.no, and the rest).
- Section 5: choices for questions the master prompt leaves open.
- Section 6: known defects and traps. Design around each of them from the start.
- Section 4: order of work and the gate for each milestone. Finish and verify one
  milestone before starting the next. Keep BUILD_STATUS.md current after each.
- Section 7: the verification the finished repository must pass.

Verify every version, action commit, model identifier and DNS value against
official sources at build time; the values in the handover were correct on
2026-11-15 and may have moved. Do not push, and do not change GitHub, Pages or
DNS settings, unless the author authorises it in the session.
```

### Effort level

ASSUMPTION, not measured: this build has not been run on Opus 5.5 at any effort level.

| Work | Suggested effort | Why |
|---|---|---|
| Resume: one scoped change (a field, a doc, a failing step in the first workflow run) | Medium | The gates in section 7 catch regressions; the context is in the repository |
| Resume: cross-cutting change (theme or Hugo update, new automation stage, workflow redesign) | High | Several files and invariants must stay consistent: policy, schema, generator, tests, docs |
| Rebuild from the master prompt | High or the highest available, one milestone per session | Roughly 12,500 lines across code, tests, templates and configuration; the traps in section 6 are interaction effects that shallow passes miss |

At any level, split the rebuild by the milestones in section 4 and paste the gate result into the next session. A lower effort level with strict gates is safer than a higher one without them.

## 11. Session chronology

Times in Europe/Oslo.

| When | What |
|---|---|
| 2026-11-13 16:50 | Master prompt received. Pre-flight, four questions, plan |
| 16:58 to 17:27 | Milestones 1 to 3 and most of 4: skeleton, CMS source study, design layer, libraries, importer, enrichment, translation, cards. First commit 17:12 |
| 22:08 to 22:33 | Rest of 4 and 5: image audit, validation, manifest, social drafts, CMS generator, doctor, CLI, workflows, tests. Stopped by a usage limit with one failing test |
| 2026-11-14 09:40 | Resumed from the workspace. `BUILD_STATUS.md` created. Failing test repaired. Browser smoke test with axe, accessibility fixes, lazy Mermaid, Lighthouse. Commits 09:45 and 10:05 |
| 10:40 to 11:20 | Second resume. Author confirmed resume, repository and delivery. Five documents, reading measure, link-check test, acceptance report, fresh-clone run, bundle v1 |
| 12:16 | Author's first Windows run reported. CRLF and launcher fixes. Bundle v2 |
| 16:55 | Author chose to overwrite `bgronas/bengt.no`. Runbook and DNS document rewritten. Bundle v3 |
| 2026-11-15 | Author confirmed `doctor` and `preview` on Windows. This brief. Bundle v4 |
