# Editorial workflow

## Daily

```bash
./publish.sh new "my-post-slug" en
./publish.sh preview
./publish.sh ship "Publish my post"
```

From cmd.exe or PowerShell: `publish new my-post-slug en`, `publish preview`, `publish ship "Publish my post"`.

## The article bundle

```text
content/en/posts/2026-11-14-my-post-slug/
├── index.md        article and front matter
├── diagram.svg     images live next to the article
└── feature.webp    generated title card (or your own feature.jpg/png/webp)
```

- The date prefix is the creation date in Europe/Oslo. It orders folders on disk only.
- The public address comes from `slug`: `https://bengt.no/en/posts/my-post-slug/`, or `https://bengt.no/posts/min-artikkel/` for Norwegian. URLs from the real build are in `docs/acceptance-report.md`.
- `slug` and the folder never change after creation. Editing the title does not touch either.
- Norwegian lives at the site root, English under `/en/`. There is no `/no/`.

### Front matter

| Field | Purpose |
|---|---|
| `title` | Authored titles are never replaced. Left empty with `auto_enrich: true`, one is proposed. |
| `date`, `lastmod` | RFC 3339 with the Oslo offset. `lastmod` is the last meaningful update; automation does not bump it. |
| `draft` | Publication gate. |
| `slug`, `translationKey` | Address and translation link. Set once. |
| `auto_enrich`, `auto_translate` | Requests to automation. Each clears itself after success. |
| `summary` | One or two sentences for article cards. |
| `description` | SEO description, 150 to 160 characters (editorial policy, validated locally). |
| `keywords`, `categories`, `tags` | 1 to 2 categories from the allowlist; tags from the canonical list. |
| `series`, `series_order` | One series name and a positive whole number. Parts are ordered numerically. |
| `featured`, `featured_weight` | Homepage "Featured". Lower weight first, then newest. |
| `math`, `mermaid` | Set by detection. Override with `feature_overrides: {math: true}`. |
| `featureimage` | Only needed when a bundle holds several feature candidates. |
| `images_lossy` | PNG file names to encode as photographs instead of losslessly. |
| `expiryDate` | Optional Hugo field; an expired article leaves the site at the next deployment. |
| `social.enabled`, `social.language`, `social.regenerate` | Social draft control. |

Unknown fields are preserved by every script.

## Publishing

```bash
./publish.sh ready content/en/posts/2026-11-14-my-post-slug/index.md
./publish.sh ship "Publish my post"
```

What `ship` does, in order: requires branch `main` and the expected `origin`; fetches; fast-forwards when the remote only has bot commits and your worktree allows it; imports inbox files; detects features; renders missing title cards; validates; checks `.pages.yml` drift; stages all changes; refuses secrets, key files and generated output; shows the diff summary; commits; pushes. No confirmation prompt. With nothing to commit and nothing unpushed it does nothing and prints how to redeploy.

`ship` stages broadly. It recognises file types and key formats (`.env`, `*.pem`, `*.key`, `sk-ant-…`, GitHub tokens, private key blocks). It cannot recognise sensitive prose.

Local validation is structural. The workflow additionally requires completed enrichment for every `draft: false` article, runs the full test suite and validates the built site.

### Future dates

An article dated in the future stays out of the build until a deployment happens after that time. There is no timer. Redeploy by hand when the date has passed:

```bash
gh workflow run deploy.yml --ref main
```

## Inbox

Drop a rough Markdown file into `inbox/en/` or `inbox/no/`, with or without front matter, then `ship`.

- The body is copied byte for byte. Front matter is added or completed mechanically: title from the first heading or the file name, slug from the title (`æ→ae`, `ø→o`, `å→a`, other accents stripped), date now.
- Images: reference them by file name and put them in a folder named like the file without `.md` (`inbox/en/my-notes/diagram.png`), or in `inbox/media/` for CMS uploads. Missing or ambiguous files stop the import with a message.
- The inbox file stays. Editing it later is reported as a conflict; the bundle is never overwritten. Continue editing in the bundle. To accept the inbox version as the new baseline: `./publish.sh import --acknowledge inbox/en/my-notes.md`.
- Imported articles are always drafts.

## Metadata enrichment

```bash
./publish.sh enrich --dry-run    # what would be processed
./publish.sh enrich              # needs ANTHROPIC_API_KEY
./publish.sh enrich --force content/en/posts/2026-11-14-my-post-slug/index.md
```

With `auto_enrich: true` the article text is sent to the Anthropic API. Generated: description, summary, about 5 to 8 keywords, 1 to 2 categories, about 3 to 7 tags, optional series. Authored values are kept. `--force` regenerates description, summary, keywords, categories and tags for named files; never title or slug.

Validation instead of silent repair:

- A category outside the allowlist, or an unknown tag you wrote, fails validation.
- A tag the model proposes that is not in the policy goes into the report and is not added.
- An authored description outside 150 to 160 characters is reported, not replaced.
- `ha` and `ci` are ambiguous and must be written in full.

Add a tag or category by editing `data/taxonomy-policy.yaml`, then `./publish.sh cms-sync`.

## Translation

```bash
./publish.sh translate content/en/posts/2026-11-14-my-post-slug
```

or set `auto_translate: true` and ship. The result is a new bundle in the other language with `draft: true`, the same `translationKey`, its own slug, and `translation.state: machine-draft` with the source hash and model. Code, commands, URLs, image paths, shortcodes, math and Mermaid are protected by tokens and verified byte for byte; a mismatch rejects the output.

Review the draft, then:

1. Set `translation_reviewed: true`.
2. `./publish.sh ready <translated index.md>` and ship.

Until then the source article publishes alone and the language switcher shows no link.

- An existing translation is never overwritten. `./publish.sh translate <bundle> --refresh` writes a candidate and a diff to `translation-review/` (ignored by Git).
- When the source changes later, `uv run python scripts/translate_post.py --status` and the workflow summary list the translation as stale.
- Internal `#section` links are remapped to the translated headings. When that is ambiguous the run stops and asks for an explicit ID: `## Heading {#my-id}`.

## Images

| Source | Delivered as |
|---|---|
| JPEG | Auto-oriented, at most 1920 px, WebP plus JPEG fallback, metadata stripped |
| PNG | At most 1920 px, lossless WebP plus PNG (screenshots, diagrams stay sharp) |
| PNG in `images_lossy` | Lossy WebP plus PNG |
| GIF, WebP | Unchanged, animation intact |
| SVG | Unchanged, never rasterised |
| `feature.*` | List thumbnail and 1200×630 JPEG social image; original not published |

Write `![Alt text](file.png "Optional caption")`. Alt text is required. Raw `<img>` HTML is not rendered (raw HTML is off); local images in shortcodes are rejected by validation with a pointer to Markdown syntax. Originals are never uploaded to the site, but they are in the Git repository; in a public repository they are public.

Hero: put `feature.jpg`, `feature.png` or `feature.webp` in the bundle. `cover.*` and `thumbnail.*` are picked up by the theme as well. A lone `hero.*` is not; validation asks you to rename it or to set `featureimage: <file>`. With several candidates, choose with `featureimage: <file>`. An authored image is never deleted or overwritten. Without one, a typographic card is generated and kept up to date with title and category.

## Social drafts

After a successful deployment the workflow writes one LinkedIn draft (about 100 to 180 words) and one X draft (at most 280 weighted characters, links counted as 23) per newly published article, in the article's language. No hashtags, no emojis. Nothing is posted.

Retrieve: repository → Actions → latest "Publish" run → Artifacts → `social-drafts-<run id>`. Each article has `linkedin.md`, `x.md` and `draft.json`. Artifacts expire after 30 days and are readable by anyone who can read the repository's Actions.

- Editing a published article does not create a new draft.
- New draft on purpose: set `social.regenerate: true` and ship, or run the workflow with the `regenerate` input, or locally `./publish.sh social https://bengt.no/en/posts/my-post-slug/`. The local command works only for an article the live manifest confirms.
- No draft for one article: `social.enabled: false`.
- At most 5 drafts per run; the rest is listed as backlog and picked up by the next run.

## Checks

```bash
./publish.sh check                    # validation and a production build, no network
./publish.sh check --external-links   # opt-in: bounded, rate-limited link check
./publish.sh doctor
```

The link check reports timeouts and 403 responses as "unverified", not as broken.
