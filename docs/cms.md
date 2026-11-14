# Pages CMS: browser and mobile authoring

Pages CMS is the editing front end. GitHub stores the content, GitHub Actions processes it, GitHub Pages serves the static result. There is no content database and no application server in this repository.

The hosted Pages CMS at `app.pagescms.org` is an external service that acts on the repository through a GitHub App. It is not hosted by GitHub Pages, and it is not part of this repository. If it is unavailable, the Git and CLI workflow is unaffected.

## What you can do in the browser

| Task | Where in Pages CMS | Result in Git |
|---|---|---|
| Start a new article | **New article (Norsk)** or **New article (English)** | `inbox/<lang>/<title>.md`. The next workflow run imports it into a page bundle, always as a draft. |
| Upload images for a new article | **Intake media** | `inbox/media/<file>`. The importer copies the files an article references into its bundle. |
| Edit an existing article | **Articles (Norsk)** or **Articles (English)** | `content/<lang>/posts/<bundle>/index.md` is updated in place. |
| Publish | Articles → switch **Publication · Draft** off → save | `draft: false`. The push starts the workflow, which deploys. |
| Edit the About page | **About page (Norsk / English)** | `content/<lang>/about/index.md` |
| Run checks without deploying | **Run checks** button | Starts `check.yml` on the open branch. Read-only. |
| Reprocess and deploy | **Process drafts and deploy** button | Starts `deploy.yml` on `main`. |

Saving in the CMS is a commit. It is not a deployment and does not mean one succeeded. A save to `main` starts the Publish workflow; follow it under the repository's **Actions** tab.

## One-time setup

1. Push this repository to GitHub first (`docs/dns-and-pages.md`).
2. Open <https://app.pagescms.org> and sign in with GitHub.
3. Install the Pages CMS GitHub App on the account `bgronas`. On GitHub's installation screen choose **Only select repositories** and select `bengt.no` only. This screen is GitHub's standard app installation dialog; the Pages CMS documentation does not describe it, so the option names are GitHub's.
4. Open the repository in Pages CMS. `.pages.yml` is already in the repository; no secrets are stored in it.
5. Later changes to the app's repository access: GitHub → Settings → Applications → Installed GitHub Apps → Pages CMS → Configure.

Permissions the app requests (from the Pages CMS GitHub App guide): repository Administration, Actions and Contents read and write; Checks, Commit statuses and Metadata read; account email read. The Actions permission is what the two buttons use.

Self-hosting is optional and not set up here. It needs PostgreSQL, a GitHub App of your own and a Node.js host; see <https://pagescms.org/docs/guides/installing/self-host/>.

## Compatibility proof

Evidence classes: **VERIFIED (source)** means read in the upstream source at tag `2.1.8` (commit `6f4e860`, 2026-06-08). **VERIFIED (docs)** means stated in the documentation at pagescms.org, read 2026-11-13. **UNTESTED** means not exercised against the hosted application. No part of this configuration was run end to end in the hosted CMS: that needs the GitHub App installed on the real repository. A YAML parse of `.pages.yml` is not proof that the hosted CMS behaves as described.

| Question | Finding | Evidence |
|---|---|---|
| Can two language collections discover nested `index.md` entries? | Yes, with `view.layout: tree` and `view.node.filename: index.md`. The collection route fetches `<dir>/index.md` for every subfolder and lists each as one entry. | VERIFIED (source): `lib/github-cache-file.ts` (node entries), `app/api/.../collections/[name]/route.ts`. VERIFIED (docs): tree view example. UNTESTED in the hosted app. |
| Can creating an entry reliably create `YYYY-MM-DD-slug/index.md`? | Not reliably enough to depend on. The filename template is a plain string substitution, so a `/` in the template would pass through, but the documentation does not describe folders in templates, the date tokens use the browser's clock rather than Europe/Oslo, and the slug comes from the title with the CMS's own slugifier, not from this repository's transliteration rule. | VERIFIED (source): `generateFilename` in `lib/schema.ts`, `components/entry/entry.tsx`. Docs silent. |
| Can media upload land inside the current entry's bundle? | No. A media source has one fixed `input` folder; uploads outside it are rejected, and the image field's `path` is only a default browsing folder. There is no per-entry variable. | VERIFIED (source): `app/api/.../files/[path]/route.ts`, `fields/core/image/index.tsx`. VERIFIED (docs): media page lists no dynamic variables. |
| Does the editor preserve fenced code, shortcodes and unexposed front matter? | The `code` field with `format: markdown` stores the body as typed. The rich-text editor converts through an HTML model and is not used. Front matter fields the form does not show survive only with `settings.content.merge: true`, which is set. Front matter is re-serialised on save: key order and quoting can change, values do not. | VERIFIED (source): `lib/serialization.ts`, merge branch in the files route. VERIFIED (docs): settings page. Byte-exact body round trip UNTESTED in the hosted app. |
| Can a save be committed without renaming a published bundle when its title changes? | Yes. A rename happens only when the filename field is shown, unlocked and changed. Here `filename.field: false` hides it and `operations.rename: false` blocks renames on the server side as well. | VERIFIED (source): `components/entry/entry.tsx`, `lib/operations.ts`. VERIFIED (docs): operations page. |

### Consequence: intake collections instead of direct bundle creation

Two of the five answers are "no" or "not reliably", so the documented fallback is implemented:

- New articles are created in `inbox/no` or `inbox/en` through the intake collections. `operations.create` is off for the article collections.
- Uploads go to `inbox/media`, which Hugo never reads and the site never publishes.
- The importer (`scripts/import_drafts.py`, the same code the CLI uses) turns each intake file into `content/<lang>/posts/<date>-<slug>/index.md`, generates slug, date with the Oslo offset and translation key, and copies exactly the images the article references, plus the hero as `feature.<ext>`.
- The intake file stays in the inbox and is recorded with its hash in `data/import-manifest.json`. Editing it again in the CMS is reported as a conflict; the bundle is never overwritten. Continue editing under **Articles**.

The extra step: an article created in the browser is not visible under **Articles** until one workflow run has imported it. That takes one run of the Publish workflow after the save, or one press of **Process drafts and deploy**.

Bundles created by the CLI and bundles created through the CMS come from the same importer or the same archetype, pass the same validator and have the same front matter contract. `tests/test_cms_and_pins.py` and `tests/test_import.py` cover this.

## Fields

Field labels carry their group as a prefix, because Pages CMS has no field-group element for top-level fields other than nested objects, and nesting would change the front matter.

| Group | Fields | Notes |
|---|---|---|
| Content | Title, Body, Summary, Description, Keywords, Slug, Translation key | Slug and translation key are read-only after creation. The body editor is Markdown source. |
| Publication | Draft, Date, Last meaningful update, Expiry, Featured, Featured order | A future date keeps the article out until a deployment after that time. |
| Taxonomy | Categories (at most 2), Tags (at most 7), Series, Part number | Choices are generated from `data/taxonomy-policy.yaml`. |
| Automation | Generate missing metadata, Request a translation draft, Machine translation reviewed | Both requests send the article text to the Anthropic API, billed to the API key. A translation is always a draft and stays marked as an unreviewed machine translation until you switch **reviewed** on. That flag is separate from **Draft**. |
| Media | Show the feature image, Feature image file; Hero image on intake | Image files of an existing article are added through Git or the CLI, see below. |
| Social drafts | Enabled, Language, Regenerate | Drafts are workflow artifacts: Actions → Publish → the run → Artifacts. Nothing is posted. |

Not exposed, on purpose: `math` and `mermaid` (set by detection; override in the file with `feature_overrides`), content hashes, translation provenance and any social completion state. Social completion lives in the `automation-state` branch, not in front matter. Table of contents and Zen mode are on site-wide in `config/_default/params.toml`. The pinned theme accepts `showTableOfContents` and `showZenMode` per article, but they are not form fields: a Pages CMS boolean has no "inherit" state and coerces a missing value to `false` (VERIFIED (source): `fields/core/boolean/index.tsx`), so exposing them would switch both off on the first save of every article. Write the key in the file when one article needs an exception; merge mode keeps it across CMS saves.

## Editor limits

- Body editing is source-mode Markdown. There is no rendered preview inside the CMS.
- Raw HTML in an article is not rendered by the site (`unsafe = false`), whatever the editor accepts.
- Adding an image to an article that already exists as a bundle cannot be done from the CMS, because uploads cannot target the bundle. Add the file with Git (`content/<lang>/posts/<bundle>/<file>`), or on the GitHub website with **Add file → Upload files** inside the bundle folder.
- A new tag or category must be added to `data/taxonomy-policy.yaml` first. Then run `./publish.sh cms-sync` and commit; `.pages.yml` is generated and CI fails when it drifts from the policy.
- Deleting and renaming articles is switched off in the CMS. Do both in Git.

## Preview: three different things

| Capability | What it is | Access |
|---|---|---|
| Local Hugo preview | `./publish.sh preview`, drafts included, live reload, bound to localhost | Your machine only |
| CMS editor | Form and Markdown source. No page rendering | Anyone you grant access in Pages CMS |
| Static preview artifact | `check.yml` builds the site with drafts and uploads it as the artifact `draft-preview-<run id>`, kept 5 days. Download, unzip, `python -m http.server 8000` | Anyone who can read the repository's Actions. In a public repository that is every signed-in GitHub user |

GitHub Pages has no per-pull-request or authenticated preview. Draft output is never uploaded to the production site; a `noindex` tag would not be access control.

## Action buttons

Both buttons start a `workflow_dispatch` run with a JSON `payload` input, as the Pages CMS actions documentation specifies.

| Button | Workflow | What it really does |
|---|---|---|
| Run checks | `check.yml`, on the branch open in the CMS | Lint, tests, validation, a production build and the preview artifact. Reads only. The payload is not used by any step. |
| Process drafts and deploy | `deploy.yml` | The full Publish run on `main`: import, enrich, translate, build, deploy, social drafts. |

Server-side validation (`scripts/lib/dispatch.py`): the run must be on `main`; the payload must be JSON produced by Pages CMS, issued for this repository and branch, naming a known action. Values are read from environment variables by Python and are never placed into a shell command. Anything else stops the run before a job with write permission starts.

## Regenerating the configuration

```bash
./publish.sh cms-sync            # rewrite .pages.yml from the policy files
./publish.sh cms-sync --check    # exit 1 when the checked-in file differs
```

`check.yml`, `deploy.yml` and `./publish.sh ship` all run the check.
