#!/usr/bin/env python3
"""Write LinkedIn and X drafts for articles that are confirmed live. Nothing is posted anywhere.

Subcommands
  run       (workflow) verify the deployment, record publications, generate missing drafts
  baseline  (workflow) mark every live article as handled without generating drafts
  local     (author)   regenerate one draft from a confirmed deployed publication
  clear     (workflow) reset social.regenerate in the listed source files
  status               show publication and draft state

What counts as published is the deployed manifest, never a local file or a Git
diff. Draft completion is tracked in a separate state directory (the
automation-state branch), independently of the publication record, so a failed
API call leaves the article retryable without redeploying anything.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lib import content, fm, llm, xweight
from lib.common import (
    LoadedPolicy,
    UserError,
    as_dict,
    atomic_write,
    content_hash,
    dump_json,
    load_policy,
    now_local,
    rfc3339,
    run_cli,
)

MAX_ATTEMPTS = 3
OUT_DIR = "social-drafts"
_HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_EMOJI_RE = re.compile("[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff️‍]")
_COMMIT_META_RE = re.compile(r"<meta\s+name=\"?x-content-commit\"?\s+content=\"?([0-9a-f]{40})", re.IGNORECASE)
LANG_NAMES = {"no": "Norwegian Bokmål", "en": "British English"}


# ---------- state ----------


class State:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.publications: dict[str, Any] = self._load("publications.json", "publications")
        self.drafts: dict[str, Any] = self._load("social.json", "drafts")

    def _load(self, name: str, key: str) -> dict[str, Any]:
        path = self.dir / name
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get(key), dict):
            raise UserError(f"{path} has an unexpected structure. Restore it from the automation-state branch history")
        return dict(data[key])

    def save(self) -> None:
        atomic_write(self.dir / "publications.json", dump_json({"version": 1, "publications": self.publications}))
        atomic_write(self.dir / "social.json", dump_json({"version": 1, "drafts": self.drafts}))


# ---------- deployment verification ----------


def verify_live(policy: LoadedPolicy, manifest: dict[str, Any], http: Any, sleep: Any = time.sleep) -> dict[str, str]:
    """Return {page id: "ok" | reason}. A page counts only when the live site
    serves this manifest's commit, not merely because the URL answers 200."""
    cfg = policy.p.social
    commit = manifest["content_commit"]
    results = {p["id"]: "not checked" for p in manifest["pages"]}
    live_ok = False
    for attempt in range(cfg.verify_attempts):
        try:
            response = http.get(f"{policy.p.site_origin}/publication-manifest.json")
            if response.status_code == 200 and response.json().get("content_commit") == commit:
                live_ok = True
                break
        except Exception:  # noqa: S110 - network errors are retried
            pass
        if attempt + 1 < cfg.verify_attempts:
            sleep(cfg.verify_delay_seconds)
    if not live_ok:
        return dict.fromkeys(results, "the live site does not serve this deployment's manifest yet")
    for page in manifest["pages"]:
        reason = "page not reachable"
        for attempt in range(cfg.verify_attempts):
            try:
                response = http.get(page["permalink"])
                if response.status_code == 200:
                    found = _COMMIT_META_RE.search(response.text)
                    if found and found.group(1) == commit:
                        reason = "ok"
                        break
                    reason = "page is served from a different build"
                else:
                    reason = f"HTTP {response.status_code}"
            except Exception as exc:
                reason = type(exc).__name__
            if attempt + 1 < cfg.verify_attempts:
                sleep(cfg.verify_delay_seconds)
        results[page["id"]] = reason
    return results


# ---------- drafting ----------


def check_texts(policy: LoadedPolicy, linkedin: str, x: str, url: str) -> tuple[list[str], dict[str, Any]]:
    cfg = policy.p.social
    problems: list[str] = []
    words = len(linkedin.split())
    weighted = xweight.weighted_length(f"{x} {url}")
    if not cfg.linkedin_min_words <= words <= cfg.linkedin_max_words:
        problems.append(
            f"the LinkedIn text is {words} words; it must be {cfg.linkedin_min_words} to {cfg.linkedin_max_words}"
        )
    if weighted > cfg.x_max_weighted_length:
        problems.append(
            f"the X text plus link weighs {weighted}; the limit is {cfg.x_max_weighted_length}. Shorten the X text"
        )
    for name, text in (("LinkedIn", linkedin), ("X", x)):
        if _HASHTAG_RE.search(text):
            problems.append(f"the {name} text contains a hashtag; remove it")
        if _EMOJI_RE.search(text):
            problems.append(f"the {name} text contains an emoji; remove it")
        if _URL_RE.search(text):
            problems.append(f"the {name} text contains a link; the link is appended separately")
        if not text.strip():
            problems.append(f"the {name} text is empty")
    checks = {
        "linkedin": {"words": words, "min_words": cfg.linkedin_min_words, "max_words": cfg.linkedin_max_words},
        "x": {
            "weighted_length": weighted,
            "limit": cfg.x_max_weighted_length,
            "method": "twitter-text v3 weights, URL = 23",
        },
    }
    return problems, checks


def make_draft(
    policy: LoadedPolicy, client: llm.Structured, page: dict[str, Any], meta: dict[str, Any], body: str, commit: str
) -> dict[str, Any]:
    social = as_dict(meta.get("social"))
    lang = str(social.get("language") if social.get("language") in policy.p.languages else page["lang"])
    schema = llm.load_schema("social-draft.schema.json", policy.root)
    system = llm.load_prompt("social-system.md", policy.root)
    url = page["permalink"]
    feedback = ""
    for _ in range(MAX_ATTEMPTS):
        request = "\n".join(
            [
                f"Language for both drafts: {LANG_NAMES[lang]} ({lang})",
                f"LinkedIn length: {policy.p.social.linkedin_min_words} to {policy.p.social.linkedin_max_words} words.",
                "X length: at most 230 characters; a 23-character link is appended afterwards.",
                *([f"Correction required from the previous attempt: {feedback}"] if feedback else []),
                "",
                llm.wrap_untrusted("ARTICLE", f"# {meta.get('title') or page['title']}\n\n{body}"),
            ]
        )
        result = client.call(
            purpose="social", system=system, user=request, schema=schema, max_tokens=policy.p.social.max_output_tokens
        )
        linkedin = str(result["linkedin"]).strip()
        x = " ".join(str(result["x"]).split())
        problems, checks = check_texts(policy, linkedin, x, url)
        if not problems:
            return {
                "id": page["id"],
                "title": page["title"],
                "url": url,
                "language": lang,
                "article_hash": page["content_hash"],
                "content_commit": commit,
                "generated_at": rfc3339(now_local(policy.tz())),
                "model": client.model,
                "platforms": {
                    "linkedin": {"text": f"{linkedin}\n\n{url}", "validation": {**checks["linkedin"], "valid": True}},
                    "x": {"text": f"{x} {url}", "validation": {**checks["x"], "valid": True}},
                },
            }
        feedback = "; ".join(problems)
    raise llm.InvalidOutput(f"social: no valid draft after {MAX_ATTEMPTS} attempts ({feedback})")


def write_draft(out: Path, draft: dict[str, Any]) -> str:
    name = str(draft["id"]).replace(":", "-")
    if not re.fullmatch(r"[a-z]{2}-[a-z0-9_-]+", name):
        raise UserError(f"unsafe draft name derived from {draft['id']!r}")
    folder = out / name
    header = f"<!-- Draft for manual review. Not posted anywhere. Article: {draft['url']} -->\n\n"
    atomic_write(folder / "linkedin.md", (header + draft["platforms"]["linkedin"]["text"] + "\n").encode("utf-8"))
    atomic_write(folder / "x.md", (header + draft["platforms"]["x"]["text"] + "\n").encode("utf-8"))
    atomic_write(folder / "draft.json", dump_json(draft))
    return name


def resolve_regenerate(manifest: dict[str, Any], targets: list[str]) -> set[str]:
    """Map ids, permalinks or source paths to page ids; unknown targets are an error."""
    wanted: set[str] = set()
    for target in targets:
        t = target.strip()
        if not t:
            continue
        match = next(
            (
                p["id"]
                for p in manifest["pages"]
                if t
                in (
                    p["id"],
                    p["permalink"],
                    p["permalink"].rstrip("/"),
                    p["source_path"],
                    str(Path(p["source_path"]).parent),
                )
            ),
            None,
        )
        if match is None:
            raise UserError(
                f"{t!r} is not a published article in the deployed manifest. Use a permalink or content/<lang>/posts/<bundle>/index.md"
            )
        wanted.add(match)
    return wanted


def run(
    policy: LoadedPolicy,
    manifest: dict[str, Any],
    state: State,
    out: Path,
    *,
    client: llm.Structured | None,
    http: Any,
    regenerate: list[str],
    artifact: dict[str, str],
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    commit = manifest["content_commit"]
    now = rfc3339(now_local(policy.tz()))
    forced = resolve_regenerate(manifest, regenerate)
    live = verify_live(policy, manifest, http, sleep)
    summary: dict[str, Any] = {
        "content_commit": commit,
        "generated": [],
        "failed": [],
        "backlog": [],
        "unverified": [],
        "skipped": [],
        "clear_flags": [],
    }

    candidates: list[tuple[dict[str, Any], fm.Doc, bool]] = []
    for page in manifest["pages"]:
        pid = page["id"]
        if live[pid] != "ok":
            summary["unverified"].append({"id": pid, "reason": live[pid]})
            continue
        pub = state.publications.setdefault(
            pid,
            {
                "permalink": page["permalink"],
                "first_published_at": now,
                "first_published_commit": commit,
                "first_content_hash": page["content_hash"],
            },
        )
        pub.update(
            {
                "permalink": page["permalink"],
                "source_path": page["source_path"],
                "last_seen_commit": commit,
                "last_content_hash": page["content_hash"],
            }
        )
        source = policy.root / page["source_path"]
        if not source.is_file():
            summary["failed"].append({"id": pid, "reason": "source file is not in this checkout"})
            continue
        doc = fm.load(source)
        if content_hash(doc.meta, doc.body) != page["content_hash"]:
            summary["failed"].append(
                {
                    "id": pid,
                    "reason": "checked-out source differs from the deployed content; check out the content commit",
                }
            )
            continue
        social = as_dict(doc.meta.get("social"))
        entry = state.drafts.get(pid, {})
        flag = social.get("regenerate") is True
        want_regen = pid in forced or (flag and entry.get("regenerated_hash") != page["content_hash"])
        if flag and not want_regen:
            summary["clear_flags"].append(
                {"path": page["source_path"], "content_hash": page["content_hash"]}
            )  # draft already durable
        if social.get("enabled") is False and pid not in forced:
            state.drafts[pid] = {**entry, "status": "disabled"}
            summary["skipped"].append({"id": pid, "reason": "social.enabled is false"})
            continue
        if entry.get("status") in ("done", "baseline") and not want_regen:
            continue
        if want_regen:
            entry = {**entry, "regenerate_requested": page["content_hash"]}
            state.drafts[pid] = entry
        candidates.append((page, doc, flag))
    state.save()

    if candidates and not policy.p.social.enabled:
        for page, _, _ in candidates:
            state.drafts[page["id"]] = {
                **state.drafts.get(page["id"], {}),
                "status": "pending",
                "last_error": "social drafting is disabled in the policy",
            }
            summary["backlog"].append(
                {"id": page["id"], "reason": "social drafting is disabled in the automation policy"}
            )
        state.save()
        return summary

    stop = ""
    for position, (page, doc, flag) in enumerate(candidates):
        pid = page["id"]
        entry = state.drafts.get(pid, {})
        if position >= policy.p.social.max_drafts_per_run or stop:
            state.drafts[pid] = {**entry, "status": "pending"}
            summary["backlog"].append({"id": pid, "reason": stop or "per-run draft cap reached"})
            continue
        try:
            if client is None:
                client = llm.StructuredClient(policy)
            draft = make_draft(policy, client, page, doc.meta, doc.body.decode("utf-8"), commit)
            name = write_draft(out, draft)
        except llm.BudgetExceeded as exc:
            stop = str(exc)
            state.drafts[pid] = {**entry, "status": "pending"}
            summary["backlog"].append({"id": pid, "reason": stop})
            continue
        except (llm.LLMError, UserError) as exc:
            state.drafts[pid] = {
                **entry,
                "status": "pending",
                "attempts": int(entry.get("attempts", 0)) + 1,
                "last_error": str(exc)[:300],
            }
            summary["failed"].append({"id": pid, "reason": str(exc)[:300]})
            state.save()
            if isinstance(exc, llm.MissingCredentials):
                stop = "ANTHROPIC_API_KEY is not available"
            continue
        done = {
            "status": "done",
            "content_hash": page["content_hash"],
            "content_commit": commit,
            "generated_at": draft["generated_at"],
            "model": draft["model"],
            "draft": name,
            "artifact": artifact,
        }
        if entry.get("regenerate_requested") or flag:
            done["regenerated_hash"] = page["content_hash"]
        state.drafts[pid] = done
        state.save()  # each draft is durable before the next API call
        summary["generated"].append({"id": pid, "draft": name, "language": draft["language"]})
        if flag:
            summary["clear_flags"].append({"path": page["source_path"], "content_hash": page["content_hash"]})
    state.save()
    if client is not None:
        summary["usage"] = client.usage.as_dict()
        summary["model"] = client.model
    summary["clear_flags"] = sorted({c["path"]: c for c in summary["clear_flags"]}.values(), key=lambda c: c["path"])
    if summary["generated"]:
        atomic_write(out / "index.json", dump_json({"content_commit": commit, "drafts": summary["generated"]}))
    return summary


def summary_markdown(policy: LoadedPolicy, summary: dict[str, Any], artifact: dict[str, str]) -> str:
    pending = len(summary["failed"]) + len(summary["backlog"])
    head = (
        "Site deployed; social drafts pending"
        if pending or summary["unverified"]
        else "Site deployed; social drafts up to date"
    )
    lines = [f"### {head}", "", f"Content commit: `{summary['content_commit']}`", "", "| Result | Count |", "|---|---|"]
    for key, label in (
        ("generated", "Drafts generated"),
        ("failed", "Failed (retried on the next run)"),
        ("backlog", "Backlog (cap or budget)"),
        ("unverified", "Not confirmed live"),
        ("skipped", "Skipped (social.enabled: false)"),
    ):
        lines.append(f"| {label} | {len(summary[key])} |")
    if summary["generated"] and artifact.get("name"):
        lines += [
            "",
            f"Drafts are in the workflow artifact **{artifact['name']}** (kept {policy.p.social.artifact_retention_days} days). They are not published on the site.",
        ]
    for key in ("failed", "backlog", "unverified"):
        for item in summary[key]:
            lines.append(f"- {key}: `{item['id']}`: {item['reason']}")
    return "\n".join(lines) + "\n"


# ---------- subcommands ----------


def _load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise UserError(f"{path} is not a final publication manifest (run scripts/build_manifest.py first)")
    return dict(data)


def _http(policy: LoadedPolicy) -> Any:
    import httpx

    return httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": "bengt.no-publication-check/1.0"})


def cmd_run(args: argparse.Namespace, policy: LoadedPolicy) -> int:
    manifest = _load_manifest(Path(args.manifest))
    state = State(Path(args.state_dir))
    artifact = {"name": args.artifact_name or "", "run_id": args.run_id or ""}
    regenerate = [t for t in (args.regenerate or "").replace(",", "\n").splitlines() if t.strip()]
    with _http(policy) as http:
        summary = run(
            policy,
            manifest,
            state,
            policy.root / OUT_DIR,
            client=None,
            http=http,
            regenerate=regenerate,
            artifact=artifact,
        )
    atomic_write(policy.root / "reports" / "social.json", dump_json(summary))
    text = summary_markdown(policy, summary, artifact)
    print(text)
    if args.summary:
        with Path(args.summary).open("a", encoding="utf-8") as fh:
            fh.write(text)
    return 4 if (summary["failed"] or summary["unverified"]) else 0


def cmd_baseline(args: argparse.Namespace, policy: LoadedPolicy) -> int:
    manifest = _load_manifest(Path(args.manifest))
    state = State(Path(args.state_dir))
    now = rfc3339(now_local(policy.tz()))
    added = 0
    for page in manifest["pages"]:
        state.publications.setdefault(
            page["id"],
            {"permalink": page["permalink"], "source_path": page["source_path"], "first_published_at": now,
             "first_published_commit": manifest["content_commit"], "first_content_hash": page["content_hash"]},
        )  # fmt: skip
        if state.drafts.get(page["id"], {}).get("status") not in ("done", "baseline"):
            state.drafts[page["id"]] = {"status": "baseline", "content_hash": page["content_hash"], "generated_at": now}
            added += 1
    state.save()
    print(f"baseline: {added} article(s) marked as handled without drafts")
    return 0


def cmd_clear(args: argparse.Namespace, policy: LoadedPolicy) -> int:
    """Reset social.regenerate, but only where the file still holds the text the draft was written for."""
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    changed = 0
    for item in report.get("clear_flags", []):
        try:
            bundle = content.resolve_bundle(policy, item["path"])
        except UserError:
            continue
        social = bundle.meta.get("social")
        if not (isinstance(social, dict) and social.get("regenerate") is True):
            continue
        if bundle.hash != item["content_hash"]:
            print(
                f"kept social.regenerate in {bundle.rel(policy.root)}: the article changed after the draft was written"
            )
            continue
        if fm.save(bundle.doc, bundle.doc.set_scalars({"social.regenerate": False})):
            changed += 1
            print(f"cleared social.regenerate in {bundle.rel(policy.root)}")
    print(f"clear: {changed} file(s) changed")
    return 0


def cmd_status(args: argparse.Namespace, policy: LoadedPolicy) -> int:
    state = State(Path(args.state_dir))
    rows = []
    for pid in sorted(set(state.publications) | set(state.drafts)):
        draft = state.drafts.get(pid, {})
        rows.append(
            f"{pid}: published={'yes' if pid in state.publications else 'no'} draft={draft.get('status', 'none')}"
            + (f" error={draft['last_error']}" if draft.get("last_error") else "")
        )
    print("\n".join(rows) or "no publications recorded")
    return 0


def cmd_local(
    args: argparse.Namespace, policy: LoadedPolicy, client: llm.Structured | None = None, http: Any = None
) -> int:
    """Regenerate one draft locally, but only for an article the live manifest confirms."""
    own = http is None
    http = http or _http(policy)
    try:
        response = http.get(f"{policy.p.site_origin}/publication-manifest.json")
    finally:
        if own:
            http.close()
    if response.status_code != 200:
        raise UserError(
            f"could not read {policy.p.site_origin}/publication-manifest.json (HTTP {response.status_code}). A draft is only generated for a confirmed deployment"
        )
    manifest = response.json()
    target = args.target
    if not re.match(r"^https?://", target):
        target = content.resolve_bundle(policy, target).rel(policy.root)
    pid = next(iter(resolve_regenerate(manifest, [target])))
    page = next(p for p in manifest["pages"] if p["id"] == pid)
    commit = manifest["content_commit"]
    shown = subprocess.run(
        ["git", "-C", str(policy.root), "show", f"{commit}:{page['source_path']}"], capture_output=True, check=False
    )
    if shown.returncode != 0:
        raise UserError(f"commit {commit[:12]} is not available locally. Run `git fetch origin` and try again")
    doc = fm.parse(shown.stdout, Path(page["source_path"]))
    if content_hash(doc.meta, doc.body) != page["content_hash"]:
        raise UserError("the deployed manifest and the content commit disagree; redeploy before regenerating")
    client = client or llm.StructuredClient(policy)
    draft = make_draft(policy, client, page, doc.meta, doc.body.decode("utf-8"), commit)
    name = write_draft(policy.root / OUT_DIR, draft)
    print(
        f"draft written to {OUT_DIR}/{name}/ (linkedin.md, x.md, draft.json). This folder is ignored by Git and never published."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 success; 2 usage or policy error; 4 site deployed but social drafts pending.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "baseline"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", required=True, help="final publication-manifest.json of the deployed build")
        p.add_argument("--state-dir", required=True, help="checkout of the automation-state branch")
        if name == "run":
            p.add_argument("--regenerate", help="ids, permalinks or source paths (comma or newline separated)")
            p.add_argument("--artifact-name", help="name of the workflow artifact that will hold the drafts")
            p.add_argument("--run-id", help="workflow run id, recorded as the artifact reference")
            p.add_argument("--summary", help="append a Markdown summary to this file")
    clear = sub.add_parser("clear")
    clear.add_argument("--report", default="reports/social.json")
    status = sub.add_parser("status")
    status.add_argument("--state-dir", required=True)
    local = sub.add_parser("local")
    local.add_argument("target", help="permalink or bundle path of a published article")
    args = parser.parse_args(argv)
    policy = load_policy()
    handlers = {"run": cmd_run, "baseline": cmd_baseline, "clear": cmd_clear, "status": cmd_status, "local": cmd_local}
    return handlers[args.command](args, policy)


if __name__ == "__main__":
    sys.exit(run_cli(main))
