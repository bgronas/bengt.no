# Operator runbook

The short path from the delivered bundle to a live site and a daily routine. Each step links to the document with the detail.

## 1. Unpack (once)

The repository is delivered as one Git bundle file with full history. Needs Git, Bash (Git Bash on Windows) and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone 2026-11-14_bengt-no-site.bundle bengt.no
cd bengt.no
git remote set-url origin https://github.com/bgronas/bengt.no.git
./publish.sh setup          # locked dependencies, Hugo, the Blowfish submodule from GitHub, then doctor
./publish.sh preview        # http://localhost:1313/ with the two example drafts
```

On Windows use Git Bash for these commands, or `publish setup` and `publish preview` from cmd.exe or PowerShell. `setup` installs nothing system-wide.

Keep the working copy outside Dropbox, OneDrive and similar synced folders: it holds more than 12,000 small files (`.venv/`, the theme, `.git/`). Reasons and a workaround: [operations.md](operations.md#working-copy-on-windows-and-in-synced-folders).

## 2. Activate (once)

Full detail, DNS table and troubleshooting: [dns-and-pages.md](dns-and-pages.md). Order:

1. `git fetch origin && git push origin main:blowfish-site` and review the branch on GitHub.
2. Repository Settings → Pages → Source: **GitHub Actions**.
3. Repository Settings → Secrets and variables → Actions → secret `ANTHROPIC_API_KEY` (only needed for enrichment, translation and social drafts).
4. Account Settings → Pages → **Add a domain** `bengt.no`, create the TXT record GitHub shows, **Verify**.
5. Repository Settings → Pages → Custom domain `bengt.no`.
6. DNS: four A records (and optionally four AAAA) on `@`, CNAME `www` → `bgronas.github.io`; remove the old A/AAAA/CNAME records; leave MX and TXT.
7. Go live: `git merge --allow-unrelated-histories -s ours origin/main -m "Adopt the Blowfish site; keep the earlier commit as history"`, then `git push origin main`.
8. When GitHub offers it: **Enforce HTTPS**.
9. Optional, for browser editing: install the Pages CMS GitHub App on this repository only ([cms.md](cms.md)).

## 3. Daily

```bash
./publish.sh new "my-post-slug" en        # or: no
./publish.sh preview
./publish.sh ship "Publish my post"
```

A new article is a draft. To publish it:

```bash
./publish.sh ready content/en/posts/<date>-my-post-slug/index.md
./publish.sh ship "Publish my post"
```

With `auto_enrich: true` (the default for new articles) the workflow fills in description, summary, keywords, categories and tags through the Anthropic API before it deploys. Without an API key, fill those fields yourself and set `auto_enrich: false`. Everything else: [editorial-workflow.md](editorial-workflow.md).

## 4. Social drafts

After each successful deployment: repository → **Actions** → latest **Publish** run → **Artifacts** → `social-drafts-<run id>`. One folder per newly published article with `linkedin.md`, `x.md` and `draft.json`. Kept 30 days. Nothing is posted anywhere.

Again for one article: `gh workflow run deploy.yml --ref main -f mode=social-only -f regenerate="https://bengt.no/en/posts/my-post-slug/"`.

## 5. When something fails

| Symptom | Go to |
|---|---|
| `ship` stops | [operations.md, "Blocked ship"](operations.md#blocked-ship) |
| Run fails at "Final production validation" | [operations.md, "Failed enrichment"](operations.md#failed-enrichment) |
| Run fails at "Commit generated changes" | [operations.md, "Blocked writeback"](operations.md#blocked-writeback) |
| Build or deploy job fails | [operations.md, "Failed deployment"](operations.md#failed-deployment) |
| "Site deployed; social drafts pending" | [operations.md, "Failed social generation"](operations.md#failed-social-generation) |
| Domain, certificate, 404 | [dns-and-pages.md, "Troubleshooting"](dns-and-pages.md#troubleshooting) |
| Anything local | `./publish.sh doctor` |

## 6. What has and has not been proven

Built and tested locally: [acceptance-report.md](acceptance-report.md). Not yet exercised, because they need your accounts: the first workflow run on GitHub, the first live Anthropic API call, the hosted Pages CMS, DNS and HTTPS.
