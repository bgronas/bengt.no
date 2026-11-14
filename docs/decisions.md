# Decisions

Engineering notes. Each entry states the decision, the evidence class and the reason. Evidence classes: **VERIFIED** (run or read in the build session), **INFERENCE** (follows from verified facts), **ASSUMPTION** (not checked).

## Author decisions (2026-11-13)

| Topic | Decision |
|---|---|
| Repository | `bgronas/bengt.no`. It held only a `README.md`. `bgronas/bgronas.github.io` keeps the previous site and is not touched. |
| Biography | Minimal: name, a neutral topic line, GitHub and LinkedIn links. No employer, role or history. |
| DNS today | `bengt.no` points to another host (Misshosting, see the 2026-11-14 decisions). The runbook replaces A/AAAA/CNAME and leaves MX/TXT alone. |
| Windows | Git Bash, plus `publish.cmd` as a forwarder. |

Consequence of the repository choice (INFERENCE): the site is a *project* Pages site of the account `bgronas`, served on the custom domain `bengt.no`. The `www` CNAME still targets `bgronas.github.io`, the account's Pages host. Section 12 of the brief names `bgronas/bgronas.github.io`; every instruction was adapted to `bgronas/bengt.no`.

## Author decisions (2026-11-14)

| Topic | Decision |
|---|---|
| `bgronas/bengt.no` | Placeholder. May be overwritten or deleted; the first push is a one-time `git push --force origin main`. The earlier non-destructive route (review branch, `-s ours` merge) is no longer documented. |
| `bgronas/bgronas.github.io` | Untouched, on GitHub and on disk. |
| `bengt.no` today | Served from Misshosting; its Hugo source is the `test666` folder and repository. Untouched. The DNS change is the cutover and the only step visitors notice. |
| Activation order | Deploy to GitHub Pages first, change DNS last, so the domain never points at an empty site. |

## Versions

| Component | Version | Evidence |
|---|---|---|
| Hugo Extended | 0.169.0 | VERIFIED: installed from PyPI wheel `hugo==0.169.0`, `hugo version` reports `+extended`. |
| Blowfish | v3.10.0 (`3e4b25c4dc74`) | VERIFIED: newest tag on 2026-11-14. Its `config.toml` supports Hugo 0.166.0 to 0.169.0. |
| Hugo 0.170.0 | Not used | VERIFIED that the tag exists; outside the range the pinned theme declares. |
| Python | 3.12 | VERIFIED: `.python-version`, tests run on 3.12.3. |
| uv | 0.11.32 | VERIFIED locally; same version pinned in `.github/actions/setup`. |
| anthropic SDK | 2.8.0 | VERIFIED from `uv.lock`; mocked in tests, no live call made. |
| Actions | checkout v7.0.1, cache v6.1.0, upload-artifact v7.0.2, download-artifact v8.0.2, upload-pages-artifact v5.0.0, deploy-pages v5.0.1, setup-uv v10.3.3 | VERIFIED: each pinned SHA equals its tag (`git ls-remote`, 2026-11-14). |

`actions/deploy-pages`: the brief asks for the v4 interface. v5.0.1 is the current release, is what Hugo's official GitHub Pages guide uses, and takes the same inputs and `page_url` output used here. Pinned to v5.0.1.

## Hugo as a Python dependency

Hugo Extended is installed by `uv` from the `hugo` wheel (`hugo-python-distributions`), pinned exactly in `pyproject.toml` and hashed in `uv.lock`. One lockfile then pins Python packages and Hugo for local use and CI, and nothing needs administrator rights. Dependabot ignores `hugo`; it moves together with the theme (`docs/operations.md`).

## Language keys and locale

Public keys stay `no` and `en`. `languages.no.toml` sets `locale = "nb"`. VERIFIED: with `locale = "nb-NO"` Hugo does not resolve the theme's `i18n/nb.yaml`; with `nb` it does. The theme's `nb.yaml` lacks seven keys that its `en.yaml` has (`nav.*`, `error.404_home`, `article.reply_to`). They are supplied in the local `i18n/nb.yaml`, because without `nav.main_menu` the mobile menu button has no accessible name on Norwegian pages (found by axe).

`defaultContentLanguageInSubdir = false` and `disableDefaultSiteRedirect = true`: Norwegian is served at the root and no `/no/` alias exists.

## Theme extension points

The submodule is unmodified. Local additions:

- `layouts/partials/home/custom.html` (Blowfish `homepage.layout = "custom"`): introduction, topics, featured, recent.
- `layouts/partials/extend-head.html` and `extend-head-uncached.html`: fonts, per-page Mermaid and KaTeX.
- Render hooks for images, links, tables, Mermaid fences and math passthrough.
- Three overridden theme files, each tracked with the upstream hash in `data/theme-overrides.json`; `doctor` fails when upstream changes: `_default/index.json` (per-language search index), `_default/rss.xml` (no links to original images), `partials/head.html` (processed social image, keywords).

## Featured and series

`featured: true` is the only switch. Ordering is `featured_weight` ascending (missing = 1000), then date descending, then path. Series use the theme's own `series` taxonomy and `series_order`, which Blowfish sorts numerically in `partials/series/series_base.html` (VERIFIED in the pinned source). No `groups` taxonomy.

## Images

Hugo is the only component that writes derivatives; Pillow only inspects. `publishResources = false` is cascaded to all pages, so an original is published only when a template asks for its URL. `validate_content.py --site` proves that no original bytes are in the output.

## Math and raw HTML

Goldmark `unsafe = false`. Math uses the passthrough extension and `transform.ToMath` at build time (`$$…$$`, `\[…\]`, `\(…\)`). A single `$` is never a delimiter, so `$50` is text. Only the KaTeX stylesheet is loaded, and only on pages with math.

## Mermaid loading

The theme's Mermaid bundle is 5.5 MB. VERIFIED: loading it on page load gave a Lighthouse mobile performance score of 70 for the example article (TBT 1,010 ms). It is now requested when a diagram comes within 600 px of the viewport or before printing; the same page scores 98. Without JavaScript the diagram source stays readable.

## Structured output and model

`output_config.format` with `type: "json_schema"` (GA, no beta header; VERIFIED in the official structured-outputs page on 2026-11-13). Default model `claude-sonnet-5-5`, taken from the official models overview; override with `ANTHROPIC_MODEL`. The schema sent to the API carries no length keywords; lengths are validated locally with Pydantic. No live API call was made in the build session.

## Pages CMS

Direct bundle creation and per-entry media upload are not used; browser authoring goes through intake collections and the importer. Evidence and reasoning: `docs/cms.md`.

## Social state

A dedicated `automation-state` branch holds publication identities, hashes, draft status and artifact references. It never holds draft text and is never merged into `main`. Reasoning and recovery: `docs/architecture.md`.

## Reading measure

`--bn-measure` is `58ch`, not a number close to the 65 to 78 characters the brief asks for, because `ch` is the width of "0" and Roboto's average glyph is narrower. VERIFIED in Chromium: 72ch gave 87 to 96 characters per line at 768 and 1440 px; 58ch gives 73 to 77. The browser smoke test asserts 60 to 80.

## Default social image

The brief lists `assets/img/default-social.svg`. The repository has `assets/img/default-social.png` only, written by `scripts/generate_cards.py --brand` with the same renderer and font as the article title cards. Reasons: social crawlers need a raster image, and a hand-drawn SVG next to a generated PNG would be two sources that drift. The editable source is the generator.

## Largest Contentful Paint on list pages

VERIFIED with Lighthouse 13.6.0 (mobile, simulated slow 4G): 2.6 s on the homepage and article lists, 0.1 s over the 2.5 s target; articles 2.0 s. The pinned theme renders list thumbnails lazily with low fetch priority. Overriding `partials/article-link/simple.html` would fix it and was not done, to keep the number of theme overrides at three. Figures and conditions: `docs/design-system.md`.

## Re-verified on 2026-11-14

- Model identifier `claude-sonnet-5-5`: listed as a Claude API ID on the official models overview. Structured output through `output_config.format` with `type: "json_schema"`, no beta header.
- GitHub Pages apex A and AAAA addresses and the `www` CNAME rule: read again from GitHub Docs; values in `docs/dns-and-pages.md`.
- `bgronas/bengt.no`: `main` at `979d479`, one file (`README.md`).

## Line endings and hashes (2026-11-14, after the first run on Windows)

VERIFIED from the author's Git Bash run and reproduced on Linux with `core.autocrlf=true`: `doctor` reported all three theme overrides as "changed upstream", because Git for Windows had checked the theme out with CRLF and the recorded hashes are of the LF blobs. Text hashes that are compared across machines now normalise CRLF to LF (`lib.common.sha256_text`, `content_hash`). The same defect existed, unobserved, in the import manifest: a CRLF inbox file hashed on Windows would have been reported as a conflict by the Linux runner. Fixed with the same function and covered by a test. Binary files and the bytes written to articles are unaffected.

## Hugo launcher

`publish.sh` starts the Hugo binary inside the `hugo` wheel directly. VERIFIED in the wheel's `cli.py`: on Windows the Python launcher runs Hugo as a child process, so Ctrl+C in `preview` ended in a Python traceback. The launcher remains the fallback when the binary cannot be located, and the workflows still use `uv run hugo`.

## Not done, by design

- No posting to LinkedIn or X, no OAuth for either.
- No scheduled workflow. Future-dated articles go live with the next deployment after their date.
- No analytics, comments, cookies or third-party requests.
- No migration of the previous site.
