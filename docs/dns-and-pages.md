# One-time activation: GitHub, Pages and DNS

Nothing in this document was executed by the build session. No push, no repository setting, no DNS record and no HTTPS state was changed or observed. Every "expected" value below is what the official documentation specifies, not a measured result.

Target: repository `bgronas/bengt.no`, a project Pages site of the account `bgronas`, served on the custom domain `bengt.no`. The repository `bgronas/bgronas.github.io` keeps the previous site and is not touched by any step here.

Sources, read 2026-11-14: GitHub Docs "Managing a custom domain for your GitHub Pages site", "Verifying your custom domain for GitHub Pages", "Securing your GitHub Pages site with HTTPS", "Configuring a publishing source for your GitHub Pages site", "Managing GitHub Actions settings for a repository"; GitHub CLI manual `gh secret set`, `gh variable set`. Links are at the end.

## Order matters

1. Push the code to a review branch (step 1).
2. Configure the repository (steps 2 to 4).
3. Verify the domain and set it on the repository **before** touching DNS (steps 5 and 6). GitHub's documentation gives the reason: with DNS pointing at GitHub and no site claiming the domain, someone else could claim it.
4. Change DNS (step 7).
5. Make the review branch `main`, which starts the first deployment (step 8).
6. Enforce HTTPS when the certificate exists (step 9).

## 1. Push without overwriting anything

`bgronas/bengt.no` exists and its `main` holds one commit with a `README.md` (observed with `git ls-remote` on 2026-11-14: `979d479`). The steps below add to it and never force-push.

```bash
# in the project folder cloned from the delivered bundle (docs/runbook.md)
git remote set-url origin https://github.com/bgronas/bengt.no.git   # `git remote add origin …` if there is no origin yet
git fetch origin
git push origin main:blowfish-site          # review branch; starts no workflow
```

Pushing to `blowfish-site` starts nothing: `deploy.yml` reacts to `main` only, `check.yml` to pull requests. Review the branch on GitHub.

## 2. Pages source

Repository → **Settings** → **Pages** (sidebar section "Code, planning, and automation") → under "Build and deployment", **Source**: select **GitHub Actions**.

GitHub creates the `github-pages` environment automatically if it does not exist. GitHub recommends a deployment protection rule that lets only the default branch deploy to it: Settings → Environments → `github-pages` → Deployment branches and tags → Selected branches → `main`. The workflow enforces `main` itself as well.

## 3. Actions permissions

The workflow needs to push generated commits to `main` and to the `automation-state` branch. It requests that per job with the `permissions` key (`contents: write` in `process` and `social`, `pages: write` and `id-token: write` in `deploy`, nothing by default).

Repository → **Settings** → **Actions** → **General**:

- "Actions permissions": actions must be allowed. The workflows use only `actions/*` and `astral-sh/setup-uv`, each pinned to a commit.
- "Workflow permissions": the documentation states that anyone with write access can change the token's permissions through the `permissions` key in the workflow file. INFERENCE: the restricted (read-only) default is therefore sufficient, because the jobs ask for what they need. This was not tested against the real repository. If the "Commit generated changes" step fails with HTTP 403, select the read and write option here and re-run.
- "Allow GitHub Actions to create and approve pull requests": leave off. Nothing here creates pull requests.

Branch protection: if `main` gets a rule that requires pull requests or blocks the `github-actions[bot]` push, the writeback step fails and nothing is deployed. The workflow does not bypass protection and no personal access token is used. The alternative is a pull-request mode, described in `docs/operations.md` ("Blocked writeback"); it is not enabled.

## 4. Secret and variable

The API key is needed only when an article asks for enrichment, translation or social drafts. The site builds and deploys without it.

Web: repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** → name `ANTHROPIC_API_KEY`.

CLI, without the key appearing in shell history or on screen:

```bash
read -rs -p "Anthropic API key: " KEY && printf '%s' "$KEY" | gh secret set ANTHROPIC_API_KEY --repo bgronas/bengt.no; unset KEY
```

`gh secret set` reads the value from standard input when `--body` is not given. Never pass the key with `--body` on the command line.

Optional model override (default `claude-sonnet-5-5`, from `data/automation-policy.yaml`): the **Variables** tab → **New repository variable** → `ANTHROPIC_MODEL`, or

```bash
gh variable set ANTHROPIC_MODEL --repo bgronas/bengt.no --body "claude-sonnet-5-5"
```

API usage is billed to the API key's account. It is separate from a Claude chat subscription.

## 5. Verify the domain for the account

Verification is done on the account, not on the repository. It stops other GitHub accounts from using `bengt.no`.

1. GitHub → profile picture → **Settings** → **Pages** → **Add a domain** → `bengt.no`.
2. GitHub shows a TXT record: host `_github-pages-challenge-bgronas.bengt.no` and a value unique to your account. The value cannot be generated by this repository; copy it from that screen.
3. Create the TXT record at the DNS provider, then press **Verify**. Keep the record afterwards.

```bash
dig _github-pages-challenge-bgronas.bengt.no +nostats +nocomments +nocmd TXT
```

```powershell
Resolve-DnsName -Name _github-pages-challenge-bgronas.bengt.no -Type TXT
```

## 6. Custom domain on the repository

Repository → **Settings** → **Pages** → **Custom domain**: `bengt.no` → **Save**.

`static/CNAME` contains exactly `bengt.no` and the build copies it to the site root (`doctor` and the test suite check both). It is there for consistency and for other hosts. With a custom Actions workflow GitHub ignores a `CNAME` file and does not need one, so the file alone configures nothing: the setting above and the DNS records do.

`bgronas.github.io` is the Pages host that DNS points to. It is not a second address for these articles: every page declares `https://bengt.no/...` as canonical. ASSUMPTION, not checked in the build session: once the custom domain is saved, GitHub redirects the project path `bgronas.github.io/bengt.no/` to `bengt.no`.

## 7. DNS records

Create these at the DNS provider for `bengt.no`:

| Type | Host | Value |
|---|---|---|
| A | `@` | `185.199.108.153` |
| A | `@` | `185.199.109.153` |
| A | `@` | `185.199.110.153` |
| A | `@` | `185.199.111.153` |
| AAAA (optional) | `@` | `2606:50c0:8000::153` |
| AAAA (optional) | `@` | `2606:50c0:8001::153` |
| AAAA (optional) | `@` | `2606:50c0:8002::153` |
| AAAA (optional) | `@` | `2606:50c0:8003::153` |
| CNAME | `www` | `bgronas.github.io` |
| TXT | `_github-pages-challenge-bgronas` | the value from step 5 |

The `www` value is the host name only: no `https://`, no path, no repository name. Some providers want a trailing dot (`bgronas.github.io.`). With the apex as the custom domain, GitHub redirects `www.bengt.no` to `bengt.no`.

Remove, because they conflict:

- Every other A, AAAA, ALIAS or ANAME record on `@` (the current host or parking page).
- Any other CNAME or A record on `www`.
- A wildcard record (`*`), if one exists. GitHub warns against wildcards.
- URL forwarding or "web redirect" services on `@` or `www`.

Leave alone: MX records, SPF/DKIM/DMARC and other TXT records, and any records for unrelated host names. E-mail is not affected by the records above.

Verification, after the provider has published the change (the documentation says up to 24 hours):

```bash
dig bengt.no +noall +answer -t A
dig bengt.no +noall +answer -t AAAA
dig www.bengt.no +nostats +nocomments +nocmd
```

```powershell
Resolve-DnsName -Name bengt.no -Type A
Resolve-DnsName -Name bengt.no -Type AAAA
Resolve-DnsName -Name www.bengt.no -Type CNAME
```

Expected: exactly the four A addresses, exactly the four AAAA addresses if you created them, and `www.bengt.no` as a CNAME to `bgronas.github.io`. Any additional address means an old record is still present.

## 8. Go live

The review branch becomes `main` through a merge that keeps the existing commit as history. No force push.

```bash
git merge --allow-unrelated-histories -s ours origin/main -m "Adopt the Blowfish site; keep the earlier commit as history"
git push origin main
git push origin --delete blowfish-site      # optional
```

`-s ours` keeps this project's files exactly and records the old commit as a parent; the old `README.md` remains reachable in history. The push to `main` starts the Publish workflow. The two example articles are drafts, so the first deployment publishes the homepage, About and empty article lists.

Then:

```bash
./publish.sh doctor
gh run list --workflow deploy.yml --limit 3
```

## 9. HTTPS

When the DNS check passes, GitHub requests a certificate. Repository → **Settings** → **Pages** → tick **Enforce HTTPS** once it becomes available; the documentation says that can take up to 24 hours.

## Troubleshooting

| Symptom | Cause and action |
|---|---|
| Pages settings show a DNS check error | An old A/AAAA record on `@` or a wrong `www` target is still published. Compare `dig` output with the table. |
| "Enforce HTTPS" stays unavailable | Certificate not issued yet. Extra records on `@` or `www` prevent issuance. If nothing happens, remove the custom domain in Pages settings, save, enter it again and save: that restarts provisioning. |
| Certificate warning in the browser | DNS still resolves to the previous host, or the certificate is pending. Check `dig`, then wait. |
| Mixed-content warnings | A page references `http://` assets. The site's own templates use relative and `https://bengt.no/` URLs only. Search the articles: `grep -rn "http://" content/`. |
| Site shows the README or a 404 | Pages source is not "GitHub Actions", or no Publish run has succeeded yet. |
| Deploy job fails with an environment protection message | The `github-pages` environment does not allow `main`. See step 2. |
| "Commit generated changes" fails with 403 | Workflow permissions or branch protection. See step 3. |
| The site works on `bgronas.github.io/bengt.no/` but not on `bengt.no` | Custom domain not saved (step 6) or DNS not changed (step 7). |
| The domain is "already taken" | Another repository of yours, or another account, has `bengt.no` as custom domain. Remove it there; step 5 prevents other accounts from claiming it. |

GitHub Pages sets its own response headers. There is no `_headers` file or similar mechanism, and nothing in this repository configures security headers.

## References

- <https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site>
- <https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages>
- <https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https>
- <https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site>
- <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository>
- <https://cli.github.com/manual/gh_secret_set>
- <https://cli.github.com/manual/gh_variable_set>
