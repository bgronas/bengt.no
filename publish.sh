#!/usr/bin/env bash
# Local command line for bengt.no. Bash on Linux, macOS, WSL or Git Bash.
# From cmd.exe or PowerShell use publish.cmd, which forwards to this script.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# uv renamed this variable; avoid the deprecation warning without changing behaviour.
if [[ -n "${UV_NATIVE_TLS:-}" && -z "${UV_SYSTEM_CERTS:-}" ]]; then
  export UV_SYSTEM_CERTS="$UV_NATIVE_TLS"
  unset UV_NATIVE_TLS
fi

# Python reads and prints UTF-8 on every platform, including Windows consoles.
export PYTHONUTF8=1

EXPECTED_REPO="${BN_EXPECTED_REPO:-bgronas/bengt.no}"
EXPECTED_BRANCH="main"

say() { printf '%s\n' "$*"; }
err() { printf 'error: %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

usage() {
  cat <<'EOF'
Usage: ./publish.sh <command> [arguments]

Daily
  new <slug> <no|en> [--key KEY] [--title TITLE]   create a draft article bundle and open it
  preview                                          local preview with drafts and live reload
  ship "<commit message>"                          import, validate, commit and push to main

Publication gate
  ready <path/to/index.md>                         set draft: false
  draft <path/to/index.md>                         set draft: true

Automation (the workflow runs these too)
  import [--dry-run] [--acknowledge FILE]          turn inbox/<lang>/*.md into page bundles
  enrich [--dry-run] [--check] [--force] [PATH]    generate metadata for auto_enrich: true (uses the API)
  translate <bundle> [--refresh]                   create a review draft in the other language (uses the API)
  social <permalink-or-bundle>                     regenerate drafts for a confirmed deployed article (uses the API)
  cards                                            render missing title cards

Checks and maintenance
  check [--external-links] [--fix-features]        validation, CMS drift check and a production build
  doctor                                           tool versions, pins and configuration consistency
  setup                                            install locked dependencies and the theme submodule
  cms-sync                                         regenerate .pages.yml from the policy files
  test                                             linters, type check and the test suite
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 was not found on PATH. $2"
}

py() {
  need uv "Install uv (https://docs.astral.sh/uv/getting-started/installation/), then run ./publish.sh setup"
  uv run --frozen --quiet python "$@"
}

# Path of the Hugo binary installed from uv.lock. The `hugo` launcher in .venv is a
# Python wrapper; on Windows it answers Ctrl+C with a traceback, so the binary is
# started directly. Empty when it cannot be located; hugo_cmd then uses the launcher.
hugo_binary() {
  local dir
  dir="$(uv run --frozen --quiet python -c 'import hugo.cli, pathlib; print((pathlib.Path(hugo.cli.__file__).parent / "binaries").as_posix())' 2>/dev/null)" || return 0
  if [[ -f "$dir/hugo.exe" ]]; then
    printf '%s\n' "$dir/hugo.exe"
  elif [[ -f "$dir/hugo" ]]; then
    printf '%s\n' "$dir/hugo"
  fi
}

hugo_cmd() {
  need uv "Install uv, then run ./publish.sh setup"
  local bin
  bin="$(hugo_binary)"
  if [[ -n "$bin" ]]; then
    "$bin" "$@"
  else
    uv run --frozen --quiet hugo "$@"
  fi
}

require_theme() {
  [[ -f themes/blowfish/theme.toml ]] || die "themes/blowfish is empty. Run ./publish.sh setup"
}

cmd_setup() {
  need git "Install Git: https://git-scm.com/downloads"
  need uv "Install uv: https://docs.astral.sh/uv/getting-started/installation/ (no administrator rights needed)"
  say "Installing locked Python dependencies and Hugo into .venv ..."
  uv sync --frozen --all-groups
  if git rev-parse --git-dir >/dev/null 2>&1; then
    say "Fetching the pinned Blowfish theme ..."
    git submodule update --init --recursive
  else
    err "this folder is not a Git repository; the theme submodule cannot be fetched"
  fi
  py scripts/doctor.py || die "setup finished, but doctor reported failures (see above)"
}

cmd_new() {
  [[ $# -ge 2 ]] || die "usage: ./publish.sh new <slug> <no|en> [--key KEY] [--title TITLE]"
  require_theme
  local created
  created="$(py scripts/post_tool.py new "$@")"
  say "created $created"
  if command -v code >/dev/null 2>&1; then
    code "$created" || true
  else
    say "VS Code (code) not found; open the file in your editor."
  fi
}

cmd_preview() {
  require_theme
  say "Preview with drafts at http://localhost:1313/ (Ctrl+C to stop). Nothing is published."
  say "The address is live once Hugo prints \"Web Server is available\"."
  # Ctrl+C stops Hugo; this script then ends normally instead of being killed with it.
  trap ':' INT
  hugo_cmd server --buildDrafts --buildFuture --bind 127.0.0.1 --port 1313 \
    --baseURL "http://localhost:1313/" --disableFastRender --navigateToChanged "$@" || true
  trap - INT
  say "Preview stopped."
}

cmd_check() {
  local links=0 fix=0 arg
  for arg in "$@"; do
    case "$arg" in
      --external-links) links=1 ;;
      --fix-features) fix=1 ;;
      *) die "unknown option for check: $arg" ;;
    esac
  done
  require_theme
  if [[ $fix -eq 1 ]]; then py scripts/detect_features.py; fi
  py scripts/validate_content.py --allow-pending
  py scripts/optimize_images.py >/dev/null || { py scripts/optimize_images.py; exit 1; }
  py scripts/sync_cms_schema.py --check
  local out
  out="$(mktemp -d "${TMPDIR:-/tmp}/bn-check.XXXXXX")"
  # shellcheck disable=SC2064
  trap "rm -rf '$out'" EXIT
  say "Building the production site (drafts, future and expired pages excluded) ..."
  HUGO_PARAMS_BN_CIPLACEHOLDERS=true hugo_cmd --gc --minify --buildDrafts=false --buildFuture=false --buildExpired=false \
    --destination "$out/public" --quiet
  py scripts/build_manifest.py --site "$out/public"
  py scripts/validate_content.py --site "$out/public" --prune-originals
  if [[ $links -eq 1 ]]; then py scripts/validate_content.py --external-links; fi
  say "check passed. The workflow additionally requires enrichment to be complete for every article with draft: false."
}

# Refuse to commit files that must never be in the repository. Prints names, never contents.
guard_staged() {
  local bad=0 file
  while IFS= read -r -d '' file; do
    case "$file" in
      .env|.env.*|*/.env|*/.env.*)
        [[ "$file" == ".env.example" ]] || { err "refusing to commit $file (environment file)"; bad=1; } ;;
      *.pem|*.key|*.p12|*.pfx|id_rsa|id_ed25519|*/id_rsa|*/id_ed25519)
        err "refusing to commit $file (key material)"; bad=1 ;;
      public/*|resources/_gen/*|social-drafts/*|reports/*|translation-review/*|.venv/*|node_modules/*|.state/*)
        err "refusing to commit $file (generated output)"; bad=1 ;;
    esac
  done < <(git diff --cached --name-only -z --diff-filter=ACMR)
  # Secret patterns in added lines. Only the file name and the kind are printed.
  local hits
  hits="$(git diff --cached -U0 --diff-filter=ACMR | py scripts/lib/secretscan.py || true)"
  if [[ -n "$hits" ]]; then
    err "possible secrets in staged changes:"
    printf '%s\n' "$hits" >&2
    bad=1
  fi
  return $bad
}

cmd_ship() {
  local message="${1:-}"
  [[ -n "$message" ]] || die 'usage: ./publish.sh ship "<commit message>"'
  need git "Install Git"
  git rev-parse --git-dir >/dev/null 2>&1 || die "not a Git repository"
  require_theme

  local branch url
  branch="$(git rev-parse --abbrev-ref HEAD)"
  [[ "$branch" == "$EXPECTED_BRANCH" ]] || die "you are on '$branch'. Publishing happens from '$EXPECTED_BRANCH': git switch $EXPECTED_BRANCH"
  url="$(git remote get-url origin 2>/dev/null)" || die "no 'origin' remote. Add it: git remote add origin https://github.com/$EXPECTED_REPO.git"
  if [[ -z "${BN_ALLOW_ANY_REMOTE:-}" ]]; then
    shopt -s nocasematch
    [[ "$url" =~ github\.com[:/]${EXPECTED_REPO//./\\.}(\.git)?/?$ ]] || die "origin is '$url', expected github.com/$EXPECTED_REPO. Fix the remote, or set BN_EXPECTED_REPO for a fork"
    shopt -u nocasematch
  fi

  say "Fetching origin/$EXPECTED_BRANCH ..."
  git fetch --quiet origin "$EXPECTED_BRANCH" || die "could not fetch from origin. Check your network and credentials"
  local local_sha remote_sha base_sha
  local_sha="$(git rev-parse HEAD)"
  if remote_sha="$(git rev-parse --verify --quiet "origin/$EXPECTED_BRANCH")"; then
    base_sha="$(git merge-base HEAD "origin/$EXPECTED_BRANCH" || true)"
    if [[ "$remote_sha" == "$local_sha" || "$base_sha" == "$remote_sha" ]]; then
      :
    elif [[ "$base_sha" == "$local_sha" ]]; then
      say "origin/$EXPECTED_BRANCH has new commits (for example generated metadata). Fast-forwarding ..."
      git merge --ff-only --quiet "origin/$EXPECTED_BRANCH" || die "cannot fast-forward because your uncommitted changes touch the same files.
Nothing was changed. Resolve it yourself, for example:
  git stash          # set your changes aside
  git merge --ff-only origin/$EXPECTED_BRANCH
  git stash pop      # bring them back and resolve any conflict"
    else
      die "your branch and origin/$EXPECTED_BRANCH have diverged. Nothing was changed. Integrate the remote commits first:
  git pull --rebase origin $EXPECTED_BRANCH
then run ship again."
    fi
  fi

  py scripts/import_drafts.py || die "import reported conflicts or rejected files (see above). Nothing was committed"
  py scripts/detect_features.py
  py scripts/generate_cards.py
  py scripts/validate_content.py --allow-pending || die "validation failed (see above). Nothing was committed"
  py scripts/sync_cms_schema.py --check || die "run ./publish.sh cms-sync, then ship again"

  git add -A -- .
  if ! guard_staged; then
    git reset --quiet
    die "nothing was committed. Your files are untouched; remove or ignore the files listed above.
Note: this check recognises file types and key formats, not sensitive prose."
  fi

  if git diff --cached --quiet; then
    if [[ -n "${remote_sha:-}" && "$(git rev-parse HEAD)" == "$remote_sha" ]]; then
      say "Nothing to ship: no changes and nothing unpushed. No commit was created."
      say "To redeploy the current content: gh workflow run deploy.yml --ref $EXPECTED_BRANCH"
      return 0
    fi
    say "No new changes; pushing existing local commits."
  else
    git diff --cached --stat
    git commit --quiet -m "$message"
    say "committed $(git rev-parse --short HEAD): $message"
  fi

  git push origin "HEAD:$EXPECTED_BRANCH" || die "push was rejected; origin/$EXPECTED_BRANCH moved while you were working.
Your commit is safe locally. Integrate and try again:
  git pull --rebase origin $EXPECTED_BRANCH
  ./publish.sh ship \"$message\""
  say "pushed. Follow the run: https://github.com/$EXPECTED_REPO/actions/workflows/deploy.yml"
}

cmd_test() {
  uv run --frozen --quiet ruff check scripts tests
  uv run --frozen --quiet ruff format --check scripts tests
  uv run --frozen --quiet mypy
  uv run --frozen --quiet check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/*.yml
  uv run --frozen --quiet check-jsonschema --builtin-schema vendor.dependabot .github/dependabot.yml
  uv run --frozen --quiet pytest "$@"
}

main() {
  local command="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "$command" in
    setup) cmd_setup "$@" ;;
    new) cmd_new "$@" ;;
    ready|draft)
      [[ $# -eq 1 ]] || die "usage: ./publish.sh $command <path/to/index.md>"
      py scripts/post_tool.py "$command" "$1" ;;
    import) py scripts/import_drafts.py "$@" ;;
    enrich) py scripts/enrich_post.py "$@" ;;
    translate)
      [[ $# -ge 1 ]] || die "usage: ./publish.sh translate <bundle-path> [--refresh]"
      py scripts/translate_post.py "$@" ;;
    social)
      [[ $# -eq 1 ]] || die "usage: ./publish.sh social <permalink-or-bundle-path>"
      py scripts/generate_social_drafts.py local "$1" ;;
    cards) py scripts/generate_cards.py "$@" ;;
    check) cmd_check "$@" ;;
    preview) cmd_preview "$@" ;;
    ship) cmd_ship "$@" ;;
    doctor) py scripts/doctor.py "$@" ;;
    cms-sync) py scripts/sync_cms_schema.py "$@" ;;
    test) cmd_test "$@" ;;
    help|-h|--help) usage ;;
    *) err "unknown command: $command"; usage >&2; exit 2 ;;
  esac
}

main "$@"
