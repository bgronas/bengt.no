# Operations

Recovery procedures, updates and the automation policy. Architecture and reasoning are in `docs/architecture.md`.

## Where to look first

| Question | Place |
|---|---|
| Did the last push deploy? | Repository → Actions → **Publish** → latest run. The run summary names the content commit. |
| What is live? | `https://bengt.no/publication-manifest.json`: published pages, hashes and the content commit. No drafts. |
| What is pending? | Run summary, and the artifact `processing-reports-<run id>` (14 days): `validate.json`, `enrich.json`, `import.json`, `cards.json`, `images.json`. |
| Social draft state | `git fetch origin automation-state && git worktree add .state origin/automation-state`, then `uv run python scripts/generate_social_drafts.py status --state-dir .state`. `.state/` is ignored by Git; remove it with `git worktree remove .state`. |
| Local health | `./publish.sh doctor` |

The build report in the run summary lists pending drafts by path, invalid metadata, missing assets and alt text, requested and stale translations, the social backlog and the deployed commit. Draft titles and text are in the restricted artifacts only, never in the public manifest.

## Recovery

### Failed enrichment

Symptom: warning "Enrichment did not complete" in the `process` job. If an article with `draft: false` still lacks metadata, "Final production validation" fails and nothing is deployed. The live site stays on the previous version.

1. Read the reason in the step log or in `enrich.json` from the reports artifact. Neither contains article text.
2. Missing or invalid key: set `ANTHROPIC_API_KEY` (`docs/dns-and-pages.md`, step 4).
3. Transient API error or budget reached: re-run the workflow. Nothing was written for the failed article, so the request is still set.
4. Rejected output (schema, description length, refusal, truncation): re-run, or fill the fields by hand and set `auto_enrich: false`.
5. To publish other work first: `./publish.sh draft <index.md>` on the blocked article, ship.

Local equivalent: `./publish.sh enrich --dry-run`, then `./publish.sh enrich`.

### Blocked writeback

Symptom: "Commit generated changes" fails.

| Message | Meaning | Action |
|---|---|---|
| "main advanced during processing" | Someone pushed while the run was processing. Nothing was deployed, nothing overwritten. | None. The newer push has its own run, which processes everything pending. |
| HTTP 403, "protected branch" or "permission denied" | Branch protection or workflow permissions block the bot. | See below. |

The workflow never bypasses branch protection, never force-pushes and uses no personal access token. If `main` must stay protected, use pull-request mode by hand. It needs no code change, because a run that finds nothing to generate commits nothing:

```bash
git switch -c content/my-article
./publish.sh import && ./publish.sh enrich
uv run python scripts/translate_post.py        # only if a translation was requested
./publish.sh check --fix-features && ./publish.sh cards
git add -A && git commit -m "Add my article with generated metadata"
git push -u origin content/my-article
gh pr create --fill                             # check.yml runs; merge when green
```

After the merge the Publish run finds no generated changes and deploys the merge commit. Limits of this mode: `social.regenerate` flags cannot be cleared on a protected `main` (the job warns and the recorded hash prevents duplicate drafts; clear the flag in a pull request), and browser intake through Pages CMS also needs a pull request for the import.

### Failed deployment

Symptom: `build` or `deploy` fails. The social job is skipped, so no drafts and no publication records are written.

- `build` failure: a Hugo error (the log names the file) or site validation (`site.json` in the reports). Fix, ship again.
- `deploy` failure: usually Pages settings or the `github-pages` environment (`docs/dns-and-pages.md`, troubleshooting). After fixing the setting, re-run the failed jobs from the Actions page, or `gh workflow run deploy.yml --ref main`.
- Generated files committed by `process` stay on `main`. That is safe: the next run finds them and has less to do.

### Failed social generation

Symptom: warning "Site deployed; social drafts pending" (exit code 4 inside the job). The site is live and is not rolled back. The publication is recorded; the draft status stays `pending`.

```bash
gh workflow run deploy.yml --ref main -f mode=social-only
```

`social-only` reads the live manifest, verifies each page and generates only the missing drafts. It does not rebuild or redeploy. Drafts that already succeeded are not repeated.

### Expired or deleted artifacts

Draft artifacts are kept 30 days. State records the article and its content hash, not the text.

```bash
# one article, in the workflow (permalink, source path or id):
gh workflow run deploy.yml --ref main -f mode=social-only -f regenerate="https://bengt.no/en/posts/my-post-slug/"

# or locally; works only for an article the live manifest confirms:
./publish.sh social https://bengt.no/en/posts/my-post-slug/
```

The local command writes to `social-drafts/` (ignored by Git) and needs `ANTHROPIC_API_KEY`.

### Lost or damaged state branch

If `automation-state` is deleted, the next run would treat every live article as newly published and write drafts for all of them, capped at 5 per run. To avoid that:

```bash
gh workflow run deploy.yml --ref main -f mode=social-baseline
```

`social-baseline` records every live article as handled without calling the API. Then request drafts for individual articles as above. Never merge `automation-state` into `main`, and do not edit it by hand.

### Import conflict

"source changed after import": the inbox file was edited after its bundle was created. The bundle was not touched. Edit the bundle instead; to accept the inbox version as the new baseline without changing the bundle, `./publish.sh import --acknowledge inbox/en/<file>.md`.

### A secret was committed

`ship` refuses common key formats and key files, but it cannot recognise every secret or sensitive prose. If a key reaches GitHub: revoke it at the issuer first, then replace the repository secret. Removing the commit afterwards does not make a pushed key safe.

## Automation policy

`data/automation-policy.yaml` is the single file for automation controls. Every script validates it against `schemas/policy.schema.json` before doing anything; unknown keys are rejected. The schema file is generated from the Pydantic model (`uv run python scripts/policy_schema.py`), and a test fails when the two differ.

| Section | Controls |
|---|---|
| `languages`, `content_roots`, `inbox_roots`, `site_origin`, `repository`, `branch`, `state_branch` | Site identity. `doctor` cross-checks them with the Hugo configuration. |
| `taxonomy` | Category and tag limits; `new_tags: report` keeps proposed tags out of the public taxonomy. The lists are in `data/taxonomy-policy.yaml`. |
| `metadata` | Description 150 to 160 characters, summary and title limits. |
| `limits` | Maximum Markdown and image sizes, 1920 px longest edge, remote images off. |
| `api` | Default model, timeout, retries, backoff. |
| `budgets` | Hard caps per script run: calls, total tokens, input size per call. |
| `enrichment`, `translation`, `social`, `cards` | On/off, per-run article caps, output token limits, glossary, word and length limits, retention, verification attempts, card geometry. |
| `external_links` | Timeout, URL cap and per-host delay for the opt-in link check. |
| `maintenance.scheduled_build` | `false`. See "Scheduled publication". |

When a cap is reached the remaining work is listed as backlog in the report and summary, no success flag is written for it, and the next run continues. Token usage is reported as the API returns it. No currency amounts are calculated: prices are not stored in this repository.

Changing taxonomy: edit `data/taxonomy-policy.yaml`, run `./publish.sh cms-sync`, ship.

## Updates

Dependabot (`.github/dependabot.yml`) opens weekly pull requests for GitHub Actions and for Python packages in `uv.lock`. Auto-merge is not configured anywhere. `check.yml` runs on each pull request; merge by hand when it is green. Dependabot is told to ignore `hugo`, and it does not handle the theme submodule or the fonts. Those three are updated by hand.

### Hugo and Blowfish (together)

Hugo must stay inside the range the theme declares in `themes/blowfish/config.toml` (`[module.hugoVersion]`); `doctor` and a test enforce it.

```bash
git switch -c update/theme
git -C themes/blowfish fetch --tags
git -C themes/blowfish tag --sort=-v:refname | head -5                 # choose a release
git -C themes/blowfish checkout v3.10.0                                # the chosen tag
grep -A3 "hugoVersion" themes/blowfish/config.toml                     # supported Hugo range

# set hugo==<version inside that range> in pyproject.toml, then:
uv lock --upgrade-package hugo
uv sync --frozen --all-groups

./publish.sh doctor
```

`doctor` now fails for each locally overridden theme file whose upstream original changed (`layouts/_default/index.json`, `layouts/_default/rss.xml`, `layouts/partials/head.html`). For each one: compare the upstream change (`git -C themes/blowfish diff <old tag> <new tag> -- <path>`), carry it into the local copy, and record the new hash and version in `data/theme-overrides.json`:

```bash
sha256sum themes/blowfish/layouts/_default/index.json themes/blowfish/layouts/_default/rss.xml themes/blowfish/layouts/partials/head.html
git -C themes/blowfish rev-parse HEAD
```

Then:

```bash
./publish.sh test && ./publish.sh check
git add themes/blowfish pyproject.toml uv.lock data/theme-overrides.json layouts
git commit -m "Update Blowfish and Hugo" && git push -u origin update/theme
```

Open a pull request, look at the preview artifact, merge. What was tested in the build session: the commands above with the current versions (a no-op). A real version change was not possible, because v3.10.0 and Hugo 0.169.0 were the newest compatible pair.

### Python packages by hand

```bash
uv lock --upgrade-package anthropic     # one package
uv lock --upgrade                       # everything inside the ranges in pyproject.toml
uv sync --frozen --all-groups && ./publish.sh test
```

After an `anthropic` SDK update, run the one-request live test once: `RUN_API_SMOKE=1 ANTHROPIC_API_KEY=... uv run pytest -m api`. It proves that the configured model accepts `output_config.format`.

### Model

Default: `api.default_model` in the policy. Override per environment with `ANTHROPIC_MODEL` (Actions variable or local `.env`). Check the identifier against <https://platform.claude.com/docs/en/about-claude/models/overview> before changing it. There is no automatic fallback to another model.

### GitHub Actions and uv

Actions are pinned to full commit SHAs with the version as a comment; Dependabot updates both. A test fails for any unpinned action. To verify a pin by hand: `git ls-remote https://github.com/actions/checkout refs/tags/v7.0.1`. The uv version is pinned in `.github/actions/setup/action.yml`.

### Fonts

Files and sources are listed in `assets/fonts/README.md`, hashes in `assets/fonts/SHA256SUMS`. To update: replace the files from the same sources, run `cd assets/fonts && sha256sum *.woff2 card/*.ttf > SHA256SUMS`, then `./publish.sh cards --brand` (default social image and favicons) and `./publish.sh test`.

### Pages CMS

The hosted application updates itself. `.pages.yml` was written against version 2.1.8. After a major Pages CMS release, re-check the five findings in `docs/cms.md`.

## Scheduled publication

Off. A push-only pipeline cannot publish at a set time: an article dated in the future goes live with the first deployment after that time. Redeploy by hand:

```bash
gh workflow run deploy.yml --ref main
```

To enable a daily build later, set `maintenance.scheduled_build: true` in the policy (documentation of intent; nothing reads it at run time) and add a trigger to `deploy.yml`:

```yaml
on:
  schedule:
    - cron: "15 5 * * *"   # 05:15 UTC = 06:15 in Oslo in winter (CET), 07:15 in summer (CEST)
```

GitHub evaluates cron in UTC only and does not follow daylight saving time. Scheduled runs use the same workflow, the same permissions and the same idempotent steps; a run with nothing new commits nothing and redeploys the current content. GitHub disables scheduled workflows in public repositories after 60 days without repository activity.

## Routine checks

```bash
./publish.sh doctor                    # tools, pins, configuration, Pages pitfalls
./publish.sh check                     # validation and a production build
./publish.sh check --external-links    # opt-in, uses the network
./publish.sh test                      # linters, type check, workflow schema, tests
```

Browser smoke test and design-review screenshots (optional, not part of CI):

```bash
uv sync --group browser && uv run playwright install chromium
uv run hugo --buildDrafts --baseURL http://127.0.0.1:8766/ --destination /tmp/bn-site
uv run python tests/browser/smoke.py /tmp/bn-site 8766 --article /en/posts/how-this-site-is-published/
```

Add `--axe <path to axe.min.js>` for the accessibility rules; axe-core is not vendored (`npm pack axe-core` or any copy of `axe.min.js`).
