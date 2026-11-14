# Acceptance report

Date: 2026-11-14. Environment: Linux x86-64 build container, Python 3.12.3, uv 0.11.32, Git 2.43.0, Hugo 0.169.0 extended, Blowfish v3.10.0, Chromium 1243 (Playwright), Node 22.23.4 for Lighthouse 13.6.0 and axe-core 4.14.0.

Everything below was run locally in that container. **Nothing was pushed to GitHub. No workflow has run on GitHub. No Pages, DNS or HTTPS setting was changed or observed. No request was sent to the Anthropic API.** There is no deployed URL and no CI run to point to.

Result classes: **PASS** (run here, passed), **PASS (simulated)** (run here against a local stand-in for GitHub or with a mocked API), **UNTESTED** (needs something this environment does not have).

## 1. Commands run

| # | Command | Result |
|---|---|---|
| 1 | `./publish.sh test` (Ruff check, Ruff format check, mypy on 25 files, check-jsonschema for both workflows and Dependabot, pytest) | PASS: 171 passed, 2 skipped (after the Windows fixes of section 9; 168 before). The two skipped tests are the opt-in live API test and the opt-in browser test. |
| 2 | `./publish.sh doctor` | PASS: 0 failures, 2 warnings (`code` not installed; no `origin` remote in the build folder) |
| 3 | `./publish.sh check` | PASS |
| 4 | `python tests/browser/smoke.py <site> 8768 --axe axe.min.js --article /en/posts/how-this-site-is-published/` | PASS: 201 checks, 0 failures; 40 axe runs, 0 violations |
| 5 | `python tests/browser/shots.py …` for 8 pages × 3 widths × 2 appearances, screenshots reviewed | PASS: horizontal overflow 0 px on all 48 |
| 6 | Lighthouse 13.6.0 mobile on 8 pages | See section 5. One target missed by 0.1 s (LCP on list pages) |
| 7 | Fresh clone: `git clone --recurse-submodules`, `./publish.sh setup` | PASS: 52 packages from `uv.lock`, theme at v3.10.0, doctor 0 failures |
| 8 | Push procedure of `docs/dns-and-pages.md` (steps 1 and 5) against a local bare repository holding one README commit: `git push --force origin main`, then `new` and `ship` | PASS (simulated): the placeholder commit is replaced, remote `main` equals the local commit, the following `ship` pushes without force. The earlier route (review branch and `-s ours` merge) was also run and passed before the author chose to overwrite |
| 9 | Fresh clone: `new` (en and no), `ready`, `ship`, `ship` again, inbox file + `ship`, `import` again, `enrich --dry-run`, `enrich` without a key, `check`, `preview` | PASS (simulated remote). Details in section 3 |
| 10 | Fresh clone: production build exactly as `deploy.yml` runs it, `build_manifest.py`, `validate_content.py --site public --prune-originals` | PASS |
| 11 | Fresh clone: update commands of `docs/operations.md` with the current versions | PASS as a no-op (0 files changed). No newer compatible theme or Hugo version existed to update to |
| 12 | `git ls-remote` of every pinned action tag against its pinned commit | PASS: 7 of 7 match |
| 13 | Delivery check: `git clone <bundle>`, `./publish.sh setup`, the push procedure against a local stand-in remote, `./publish.sh test`, `check`, `new`, `ship` | PASS (simulated remote): 168 passed, 2 skipped. Run on the commit before this row was added; that commit differs from the delivered one by this row only |

## 2. Versions

| Component | Version | Pinned in |
|---|---|---|
| Hugo Extended | 0.169.0 | `pyproject.toml` (`hugo==0.169.0`), `uv.lock` |
| Blowfish | v3.10.0, commit `3e4b25c4dc74` (supports Hugo 0.166.0 to 0.169.0) | submodule `themes/blowfish`, `data/theme-overrides.json` |
| Python | 3.12 (tested on 3.12.3) | `.python-version` |
| uv | 0.11.32 | `.github/actions/setup/action.yml` |
| anthropic SDK | 2.8.0 | `uv.lock` |
| pydantic 2.14.3, python-frontmatter 1.3.0, Pillow 13.0.0, markdown-it-py 4.3.0, PyYAML 6.0.3, jsonschema 4.26.0, httpx 0.28.1 | | `uv.lock` |
| pytest 9.2.0, Ruff 0.17.5, mypy 2.4.1, check-jsonschema 0.39.0, Playwright 1.65.1 (optional group) | | `uv.lock` |
| Default model | `claude-sonnet-5-5` (listed as a Claude API ID in the official models overview, read 2026-11-14) | `data/automation-policy.yaml`, override `ANTHROPIC_MODEL` |
| actions/checkout v7.0.1, cache v6.1.0, upload-artifact v7.0.2, download-artifact v8.0.2, upload-pages-artifact v5.0.0, deploy-pages v5.0.1; astral-sh/setup-uv v10.3.3 | | commit SHAs in the workflow files |
| Pages CMS | configuration written against 2.1.8 | not a dependency of this repository |
| Fonts | `@fontsource-variable/roboto` 5.3.0, `@fontsource-variable/roboto-mono` 5.3.0, Roboto variable TTF from `google/fonts` | `assets/fonts/SHA256SUMS` |

`actions/deploy-pages`: the brief asks for the v4 interface. v5.0.1 is used because it is the current release, it is the version in Hugo's own GitHub Pages guide, and the workflow uses only the action's default inputs and its `page_url` output, which are the same. Update procedure for every row: `docs/operations.md`.

## 3. URLs from the real build

Fresh clone, one English article created with `./publish.sh new "my-post-slug" en`, metadata filled by hand, `ready`, production build with drafts excluded. HTML pages written:

```text
/                              /en/
/om/                           /en/about/
/posts/                        /en/posts/
/categories/                   /en/posts/my-post-slug/
/series/                       /en/categories/        /en/categories/technology/
/tags/                         /en/tags/   /en/tags/gitops/   /en/tags/hugo/   /en/tags/markdown/
/404.html                      /en/series/
```

- Source folder `content/en/posts/2026-11-14-my-post-slug/` became `https://bengt.no/en/posts/my-post-slug/`: the date prefix is not in the URL.
- The only file under `/no/` is `no/sitemap.xml`, which Hugo's sitemap index at `/sitemap.xml` references; the URLs inside it are root URLs. There is no HTML page under `/no/`.
- `…/page/1/index.html` files are Hugo's redirects from page 1 of a paginated list to the list itself.
- The four draft articles in that clone appeared nowhere in the output (searched for their titles and slugs).
- `public/CNAME` is exactly `bengt.no` followed by a newline.
- The article's head: `canonical` `https://bengt.no/en/posts/my-post-slug/`, `og:image` `…/feature_hu_….jpg` with `og:image:type image/jpeg`, width 1200, height 630 (file inspected: JPEG 1200×630), `twitter:card summary_large_image`, `x-content-commit` equal to the built commit.
- `publication-manifest.json`: one page, id `en:my-post-slug`, the permalink above, content hash and commit.
- The generated `feature.webp` original was copied by Hugo and removed again by `--prune-originals`; the output held only the 600 px WebP thumbnail and the 1200×630 JPEG.

## 4. Acceptance criteria of the brief

Tests are named `file::test`. "Fresh clone" refers to commands 7 to 10 above.

| # | Criterion | Evidence | Result |
|---|---|---|---|
| 1 | Fresh clone builds both languages without an API key | Fresh clone; `test_site_build::test_draft_build_is_possible_without_an_api_key` | PASS |
| 2 | Norwegian at root, English under `/en/`, no duplicate `/no/` | `test_site_build::test_norwegian_at_root_english_under_en_and_no_duplicate_no_tree`; section 3 | PASS |
| 3 | Linked translations give valid language-switch links; single-language posts stay valid | `test_site_build::test_translations_are_linked_and_single_language_posts_are_not`; browser smoke | PASS |
| 4 | Inbox draft imports once; rerun is a no-op; changed source is a conflict | `test_import::test_rough_draft_imports_once_then_is_a_noop_then_conflicts`; fresh clone | PASS |
| 5 | Enrichment keeps body bytes, unknown metadata, authored title, slug, draft status | `test_enrich::test_enrichment_preserves_body_unknown_fields_title_slug_and_draft`; `test_frontmatter::*` | PASS (mocked API) |
| 6 | Invalid output, bad description length, refusal, truncation, missing keys never partially rewrite | `test_enrich::test_bad_api_output_never_partially_rewrites` (5 cases), `…description_length_is_validated_locally…`, `…missing_credentials…` | PASS (mocked API) |
| 7 | Tag aliases normalise; taxonomies cannot sprawl | `test_taxonomy::*`, `test_enrich::test_tags_are_normalised_and_new_tags_only_reported` | PASS |
| 8 | Second enrichment scan: zero API calls, zero changed files | `test_enrich::test_second_scan_makes_no_api_calls_and_changes_nothing` | PASS (mocked API) |
| 9 | No upscaling; orientation and transparency kept; screenshots legible; animations and SVG deliberate; originals excluded | `test_site_build::test_originals_are_excluded_and_derivatives_follow_the_policy`, `…originals_were_pruned…`, `test_validate::test_image_audit_classifies_and_enforces_limits`; browser smoke (SVG served as SVG) | PASS. "Legible" is asserted as lossless encoding, not judged by eye |
| 10 | Code fence containing image syntax is untouched | `test_site_build::test_code_fence_with_image_syntax_is_rendered_as_code`, `test_features_cards::test_image_syntax_inside_code_is_not_an_image`; section 3 build | PASS |
| 11 | Draft, future and expired pages never enter search, RSS, featured, manifest or social candidates | `test_site_build::test_unpublished_pages_are_absent_everywhere`, `…featured_section_is_deterministic_and_excludes_unpublished`, `…manifest_lists_exactly_the_published_pages` | PASS |
| 12 | Search and RSS per language; featured order deterministic; copy and TOC in a browser | `test_site_build::test_search_index_and_rss_are_per_language`; browser smoke | PASS |
| 13 | Deployed artifact corresponds to the processed content commit | `test_workflows::test_writeback_commits_only_generated_paths_and_reports_the_content_commit`, `test_site_build::test_pages_carry_the_content_commit_not_some_other_sha` | PASS (simulated): the workflow's shell steps run against a local bare repository. Not run on GitHub |
| 14 | Concurrent user push prevents stale writeback and deployment, no force push | `test_workflows::test_concurrent_user_push_stops_the_run_without_force`, `…writeback_is_scoped_unforced_and_does_not_recurse` | PASS (simulated) |
| 15 | Deployment failure creates no social drafts or publication records | `test_workflows::test_social_job_runs_only_after_a_successful_deployment`, `test_social::test_unconfirmed_deployment_creates_no_drafts_and_no_publication_records` | PASS (simulated) |
| 16 | Deploy success plus social failure is recoverable without redeploy or duplicates | `test_social::test_failed_generation_is_recoverable_without_duplicates`, `…missing_api_key_keeps_everything_retryable` | PASS (mocked API) |
| 17 | Ordinary edit does not regenerate; explicit request does | `test_social::test_ordinary_edit_does_not_regenerate_but_explicit_request_does`, `…flag_is_kept_when_the_article_changed_after_the_draft` | PASS (mocked API) |
| 18 | X weighted length, canonical links, both languages, missing-artifact recovery | `test_social::test_weighted_length_follows_twitter_text_rules`, `…drafts_are_written_for_confirmed_pages_in_both_languages`, `…missing_artifact_is_recovered_by_permalink_path_or_id` | PASS (mocked API) |
| 19 | Built site has no secrets, social drafts or inbox sources | `test_site_build::test_no_repository_internals_in_the_output`; section 3 build | PASS |

## 5. Extended acceptance (section 19 of the brief)

| Point | Evidence | Result |
|---|---|---|
| CMS configuration matches the documented schema | Keys checked against the Pages CMS documentation and the 2.1.8 source; `test_cms_and_pins::*` | PASS for structure. **Bundle discovery, intake creation, media upload and the two action buttons were not exercised in the hosted CMS: UNTESTED external integration.** Findings and evidence class per question: `docs/cms.md` |
| CMS and CLI produce identical valid bundles | Both paths end in the same importer or archetype and the same validator; `test_cms_and_pins::test_browser_intake_uses_the_inbox_and_a_media_area_outside_published_paths`, `test_import::test_intake_media_and_hero_are_copied` | PASS for the repository side; the CMS's own file writing is UNTESTED |
| No title edit changes a published slug or bundle path | `test_site_build::test_title_edit_changes_neither_url_nor_bundle_path`, `test_cms_and_pins::test_existing_bundles_are_edit_only_and_never_renamed` | PASS |
| Published source plus new translation deploys only the source | `test_translate::test_machine_draft_cannot_be_published_until_reviewed`, `…creates_a_linked_review_draft…` | PASS (mocked API) |
| Translation keeps protected syntax, handles collisions, staleness and refresh | `test_translate::*` (14 tests) | PASS (mocked API) |
| Math ignores currency and code; Mermaid loads only where needed | `test_features_cards::test_currency_and_code_do_not_count_as_math`, `test_site_build::test_math_and_mermaid_assets_load_only_where_needed`; browser smoke; `$50` in the section 3 build | PASS |
| Cards: long titles, both languages, changed metadata, authored images kept | `test_features_cards::*` | PASS |
| `description` and `summary` both present and distinct | `test_validate::test_summary_and_description_are_both_required_for_publication`, `test_site_build::test_social_metadata_uses_a_real_jpeg_and_separate_description` | PASS |
| Distinct concepts not conflated; `ha` not converted | `test_taxonomy::test_ambiguous_ha_is_never_converted`, `…distinct_concepts_are_not_conflated` | PASS |
| Social drafts outside all published bundle resources | Drafts are written to `social-drafts/` at the repository root, which Hugo does not read; `test_site_build::test_no_repository_internals_in_the_output` | PASS |
| Mobile/desktop, light/dark, keyboard, accessibility, search, metadata reviewed | Browser smoke, axe, screenshots, Lighthouse, section 3 | PASS with the limits below |
| Fresh clone follows the README without hidden state | Commands 7 to 11 | PASS on Linux. Windows with Git Bash: section 9. `publish.cmd` and macOS: UNTESTED |

### Lighthouse (mobile preset, simulated slow 4G, preview build with the example articles)

| Page | Performance | Accessibility | Best practices | SEO | LCP | CLS | TBT |
|---|---|---|---|---|---|---|---|
| `/` | 95 | 100 | 100 | 100 | 2.6 s | 0 | 110 ms |
| `/en/` | 96 | 100 | 100 | 100 | 2.6 s | 0 | 0 ms |
| `/posts/` | 96 | 100 | 100 | 100 | 2.6 s | 0 | 40 ms |
| `/en/posts/` | 96 | 100 | 100 | 100 | 2.6 s | 0 | 0 ms |
| `/en/posts/how-this-site-is-published/` | 98 | 100 | 100 | 100 | 2.0 s | 0 | 0 ms |
| `/posts/slik-publiseres-dette-nettstedet/` | 98 | 100 | 100 | 100 | 2.0 s | 0 | 50 ms |
| `/en/about/` | 99 | 100 | 100 | 100 | 1.7 s | 0 | 40 ms |
| `/om/` | 99 | 100 | 100 | 100 | 1.7 s | 0 | 10 ms |

Targets: accessibility, SEO, best practices ≥ 95: met. Mobile performance ≥ 90: met. CLS ≤ 0.1: met. LCP ≤ 2.5 s: met on articles and About, **missed by 0.1 s on the homepage and the article lists**. INP: not measurable in a lab run; TBT is given instead. These are single lab runs on a development container, not production or real-user figures. Cause of the LCP miss and the fix that was not made: `docs/design-system.md`.

## 6. Found and fixed in this pass

| Finding | Fix |
|---|---|
| Prose lines held 87 to 96 characters at 768 and 1440 px; the brief asks for 65 to 78 | `--bn-measure` 72ch → 58ch (73 to 77 characters measured); the smoke test now asserts 60 to 80 |
| `enrich` without an API key printed "nothing to do" before the error | Waiting articles are now reported as backlog; test extended |
| The opt-in external link check had no test | Test added |

## 7. Not tested, and why

| Behaviour | Reason |
|---|---|
| Any run of `deploy.yml` or `check.yml` on GitHub: runner setup, caches, permissions, the Pages deployment, the `github-pages` environment, artifact upload and retention, concurrency queueing | No push from this environment. Workflow files pass GitHub's workflow JSON schema, and the writeback and state shell logic is exercised against local repositories |
| Whether the restricted default token permission suffices for the `permissions:` declarations | Inferred from GitHub's documentation, not run |
| Anthropic API: enrichment, translation, social drafts, token accounting against a real response | No API key. All tests use a mocked client. The opt-in test `pytest -m api` sends one small request once a key exists |
| Live-page verification after deployment (`x-content-commit` on `https://bengt.no/…`) | No deployed site. Logic tested with a stub HTTP client (`test_social::test_verification_is_bounded`, `…unconfirmed_deployment…`) |
| Pages CMS hosted application: listing, intake creation, media upload, merge-mode saves, action buttons | Needs the GitHub App on the real repository |
| DNS, domain verification, certificate, Enforce HTTPS | Not changed, not observed |
| `publish.cmd`, WSL, macOS | Not run. Git Bash on Windows: see section 9 |
| Opening VS Code from `new` | `code` not installed; the fallback message was seen |
| `check --external-links` against real sites | Network egress from this container is restricted. Classification, GET fallback and per-host delay are tested with a stub client (`test_validate::test_external_link_check_separates_missing_from_inconclusive_and_is_rate_limited`) |
| Dependabot behaviour (uv ecosystem, ignore rule) | Configuration passes the Dependabot schema; no pull request was observed |
| Firefox, Safari, screen readers | Chromium only |
| Social platform crawlers reading the cards | Image format, size and metadata verified; no crawler involved |

## 8. Known deviations from the brief

| Brief | Repository | Reason |
|---|---|---|
| Repository `bgronas/bgronas.github.io` | `bgronas/bengt.no` | Author decision. The previous site stays in `bgronas.github.io`, untouched |
| `assets/img/default-social.svg` | `assets/img/default-social.png`, generated | `docs/decisions.md` |
| `deploy-pages` v4 | v5.0.1 | Section 2 |
| Direct bundle creation and bundle-relative upload in the CMS | Intake collections and importer | Not supported reliably by Pages CMS; the brief's documented fallback |
| LCP ≤ 2.5 s everywhere | 2.6 s on list pages in the lab | Section 5 |
| `schemas/translation.schema.json` only | plus `schemas/translation-metadata.schema.json` and `schemas/policy.schema.json` | Translation uses one schema for segments and one for metadata |

Additional entry points beyond the brief: `publish.cmd`, `./publish.sh draft`, `cards`, `cms-sync`, `test`; scripts `detect_features.py`, `post_tool.py`, `sync_cms_schema.py`, `policy_schema.py`.

## 9. First run on Windows (author's machine, 2026-11-14)

Source: the author's terminal output from Git Bash (MINGW64), Git 2.55.0.windows.3, uv 0.12.18, Python 3.12.14, working copy in a Dropbox folder. Not run by the build session.

| Step | Observed | Status |
|---|---|---|
| `git clone <bundle>`, `./publish.sh setup` | 53 packages installed, theme checked out at `3e4b25c4dc74`, Hugo 0.169.0 extended found, VS Code found, 17 doctor checks ok | Worked |
| `doctor`, theme override checks | 3 failures: "changed upstream" for all three overridden theme files | Defect. Cause: CRLF checkout of the theme. Reproduced on Linux with `core.autocrlf=true`, fixed (hashes on LF-normalised bytes), verified in that reproduction: 0 failures |
| `./publish.sh preview` | Hugo started and printed "Start building sites"; the output ends with Ctrl+C and a Python traceback before any build result | The traceback is the Hugo wheel's launcher reacting to Ctrl+C on Windows, not a build error; `preview` now starts the binary directly. **Whether the first build was slow or stalled is not known**: the output does not say how long it ran. The same build takes under 1 s on Linux with empty caches, also with a CRLF theme. Not reproduced, not explained |

Found by reasoning from the first defect, not observed: the import manifest had the same line-ending dependency and would have reported a conflict on the runner for an inbox file saved with CRLF. Fixed and tested (`test_import::test_windows_line_endings_do_not_turn_into_a_conflict_on_the_runner`).

The fixes were verified on Linux only. They have not been run on Windows.

## 10. Repository tree

Theme submodule contents omitted.

```text
.env.example
.gitattributes
.github/actions/setup/action.yml
.github/dependabot.yml
.github/workflows/check.yml
.github/workflows/deploy.yml
.gitignore
.gitmodules
.pages.yml
.python-version
BUILD_STATUS.md
README.md
archetypes/default.md
archetypes/posts/index.md
assets/css/custom.css
assets/css/schemes/bengt.css
assets/fonts/LICENSE-Roboto.txt
assets/fonts/LICENSE-RobotoMono.txt
assets/fonts/README.md
assets/fonts/SHA256SUMS
assets/fonts/card/Roboto-Variable.ttf
assets/fonts/roboto-latin-ext-wght-normal.woff2
assets/fonts/roboto-latin-wght-italic.woff2
assets/fonts/roboto-latin-wght-normal.woff2
assets/fonts/roboto-mono-latin-ext-wght-normal.woff2
assets/fonts/roboto-mono-latin-wght-normal.woff2
assets/img/default-social.png
config/_default/hugo.toml
config/_default/languages.en.toml
config/_default/languages.no.toml
config/_default/markup.toml
config/_default/menus.en.toml
config/_default/menus.no.toml
config/_default/params.toml
content/en/_index.md
content/en/about/index.md
content/en/categories/_index.md
content/en/posts/2026-11-13-how-this-site-is-published/feature.webp
content/en/posts/2026-11-13-how-this-site-is-published/index.md
content/en/posts/2026-11-13-how-this-site-is-published/pipeline.svg
content/en/posts/_index.md
content/en/series/_index.md
content/en/tags/_index.md
content/no/_index.md
content/no/about/index.md
content/no/categories/_index.md
content/no/posts/2026-11-13-slik-publiseres-dette-nettstedet/feature.webp
content/no/posts/2026-11-13-slik-publiseres-dette-nettstedet/index.md
content/no/posts/2026-11-13-slik-publiseres-dette-nettstedet/pipeline.svg
content/no/posts/_index.md
content/no/series/_index.md
content/no/tags/_index.md
data/automation-policy.yaml
data/card-manifest.json
data/import-manifest.json
data/taxonomy-policy.yaml
data/theme-overrides.json
docs/acceptance-report.md
docs/architecture.md
docs/cms.md
docs/decisions.md
docs/design-system.md
docs/dns-and-pages.md
docs/editorial-workflow.md
docs/operations.md
docs/runbook.md
i18n/en.yaml
i18n/nb.yaml
inbox/en/.gitkeep
inbox/media/.gitkeep
inbox/no/.gitkeep
layouts/404.html
layouts/_default/_markup/render-codeblock-mermaid.html
layouts/_default/_markup/render-image.html
layouts/_default/_markup/render-link.html
layouts/_default/_markup/render-passthrough.html
layouts/_default/_markup/render-table.html
layouts/_default/index.json
layouts/_default/rss.xml
layouts/index.publicationmanifest.json
layouts/partials/bn/feature-resource.html
layouts/partials/bn/featured-pages.html
layouts/partials/bn/inline.html
layouts/partials/bn/social-meta.html
layouts/partials/extend-head-uncached.html
layouts/partials/extend-head.html
layouts/partials/head.html
layouts/partials/home/custom.html
prompts/metadata-system.md
prompts/social-system.md
prompts/translation-system.md
publish.cmd
publish.sh
pyproject.toml
schemas/metadata.schema.json
schemas/policy.schema.json
schemas/publication-manifest.schema.json
schemas/social-draft.schema.json
schemas/translation-metadata.schema.json
schemas/translation.schema.json
scripts/build_manifest.py
scripts/detect_features.py
scripts/doctor.py
scripts/enrich_post.py
scripts/generate_cards.py
scripts/generate_social_drafts.py
scripts/import_drafts.py
scripts/lib/__init__.py
scripts/lib/common.py
scripts/lib/content.py
scripts/lib/dispatch.py
scripts/lib/fm.py
scripts/lib/llm.py
scripts/lib/mdscan.py
scripts/lib/secretscan.py
scripts/lib/segments.py
scripts/lib/taxonomy.py
scripts/lib/xweight.py
scripts/lib/yamlx.py
scripts/optimize_images.py
scripts/policy_schema.py
scripts/post_tool.py
scripts/sync_cms_schema.py
scripts/translate_post.py
scripts/validate_content.py
static/CNAME
static/android-chrome-192x192.png
static/android-chrome-512x512.png
static/apple-touch-icon.png
static/favicon-16x16.png
static/favicon-32x32.png
static/favicon.ico
static/site.webmanifest
tests/__init__.py
tests/browser/shots.py
tests/browser/smoke.py
tests/conftest.py
tests/fixtures/__init__.py
tests/fixtures/site.py
tests/test_cms_and_pins.py
tests/test_enrich.py
tests/test_features_cards.py
tests/test_frontmatter.py
tests/test_import.py
tests/test_optional.py
tests/test_publish_sh.py
tests/test_site_build.py
tests/test_social.py
tests/test_taxonomy.py
tests/test_translate.py
tests/test_validate.py
tests/test_workflows.py
themes/blowfish/   (Git submodule, v3.10.0)
uv.lock
```
