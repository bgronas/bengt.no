from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import generate_social_drafts as social
import pytest
from lib import fm, llm, xweight
from lib.common import UserError, content_hash, load_policy

from tests.conftest import COMMIT, FakeLLM, write_bundle

ORIGIN = "https://bengt.no"
LINKEDIN = " ".join(["Concrete"] + ["word"] * 119) + "."
X_TEXT = "A concise statement of the most useful point in the article."


def good_draft(**overrides: Any) -> dict[str, str]:
    return {"linkedin": LINKEDIN, "x": X_TEXT, **overrides}


class FakeHTTP:
    """Serves the manifest and pages of a 'live' site; can be told to be stale or down."""

    def __init__(
        self,
        manifest: dict[str, Any],
        *,
        commit: str | None = None,
        down: bool = False,
        stale_pages: set[str] | None = None,
    ) -> None:
        self.manifest, self.commit, self.down = manifest, commit or manifest["content_commit"], down
        self.stale_pages = stale_pages or set()
        self.requests: list[str] = []

    def get(self, url: str) -> SimpleNamespace:
        self.requests.append(url)
        if self.down:
            return SimpleNamespace(status_code=503, text="", json=dict)
        if url.endswith("/publication-manifest.json"):
            live = {**self.manifest, "content_commit": self.commit}
            return SimpleNamespace(status_code=200, text=json.dumps(live), json=lambda: live)
        commit = "f" * 40 if url in self.stale_pages else self.commit
        return SimpleNamespace(status_code=200, text=f'<meta name="x-content-commit" content="{commit}">', json=dict)

    def close(self) -> None:
        pass


def page_for(repo: Path, path: Path, lang: str = "en") -> dict[str, Any]:
    doc = fm.load(path)
    key = doc.meta["translationKey"]
    prefix = "" if lang == "no" else f"{lang}/"
    return {
        "id": f"{lang}:{key}",
        "lang": lang,
        "translation_key": key,
        "permalink": f"{ORIGIN}/{prefix}posts/{doc.meta['slug']}/",
        "source_path": path.relative_to(repo).as_posix(),
        "title": doc.meta["title"],
        "date": doc.meta["date"],
        "lastmod": doc.meta["lastmod"],
        "content_hash": content_hash(doc.meta, doc.body),
    }


def manifest_for(repo: Path, *pages: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "site_origin": ORIGIN,
        "content_commit": COMMIT,
        "hugo_version": "0.169.0",
        "pages": list(pages),
    }


def run(
    repo: Path, manifest: dict[str, Any], client: Any, http: Any = None, regenerate: list[str] | None = None
) -> tuple[dict[str, Any], social.State]:
    state = social.State(repo / ".state")
    summary = social.run(
        load_policy(), manifest, state, repo / "social-drafts", client=client, http=http or FakeHTTP(manifest),
        regenerate=regenerate or [], artifact={"name": "social-drafts-1", "run_id": "1"}, sleep=lambda _s: None,
    )  # fmt: skip
    return summary, social.State(repo / ".state")


@pytest.fixture
def article(repo: Path) -> Path:
    return write_bundle(
        repo, "en", "2026-10-01-first", "The article body with qualifications.\n", title="First article"
    )


# ---------- weighted length ----------


def test_weighted_length_follows_twitter_text_rules() -> None:
    assert xweight.weighted_length("hello") == 5
    assert xweight.weighted_length("blåbær på Ærø") == 13, "Latin-1 letters weigh 1"
    assert xweight.weighted_length("日本語") == 6, "CJK weighs 2"
    assert (
        xweight.weighted_length("a https://bengt.no/posts/a-very-long-slug-that-goes-on-and-on-for-a-while/ b")
        == 2 + 23 + 2
    )
    assert xweight.weighted_length("https://t.co/a") == 23, "short URLs are charged 23 as well"
    assert xweight.weighted_length("see bengt.no now") == 4 + 23 + 4, "a bare domain is charged as a link"
    assert xweight.weighted_length("x" * 280) == 280 and xweight.fits("x" * 280) and not xweight.fits("x" * 281)
    assert len("é" * 280) == 280 and xweight.fits("é" * 280)
    assert not xweight.fits("語" * 141), "plain len() would wrongly accept this"


# ---------- publication and draft state ----------


def test_drafts_are_written_for_confirmed_pages_in_both_languages(repo: Path, article: Path) -> None:
    norsk = write_bundle(repo, "no", "2026-10-01-forste", "Norsk tekst om et cluster.\n", title="Første artikkel")
    manifest = manifest_for(repo, page_for(repo, article), page_for(repo, norsk, "no"))
    client = FakeLLM(default=good_draft())
    summary, state = run(repo, manifest, client)
    assert [g["id"] for g in summary["generated"]] == ["en:first", "no:forste"]
    assert [g["language"] for g in summary["generated"]] == ["en", "no"]
    assert "Norwegian Bokmål" in client.calls[1]["user"] and "British English" in client.calls[0]["user"]
    assert 'always write "cluster"' in client.calls[1]["system"]

    draft = json.loads((repo / "social-drafts/en-first/draft.json").read_text())
    assert draft["url"] == "https://bengt.no/en/posts/first/" and draft["content_commit"] == COMMIT
    assert draft["model"] == "fake-model-1" and draft["article_hash"].startswith("sha256:")
    assert draft["platforms"]["linkedin"]["text"].endswith(draft["url"])
    assert draft["platforms"]["x"]["text"].endswith(draft["url"])
    assert draft["platforms"]["x"]["validation"]["weighted_length"] <= 280
    assert 100 <= draft["platforms"]["linkedin"]["validation"]["words"] <= 180
    assert (repo / "social-drafts/no-forste/linkedin.md").is_file() and (
        repo / "social-drafts/no-forste/x.md"
    ).is_file()
    assert (
        state.drafts["en:first"]["status"] == "done"
        and state.drafts["en:first"]["artifact"]["name"] == "social-drafts-1"
    )
    assert "linkedin" not in json.dumps(state.drafts) and LINKEDIN not in json.dumps(state.drafts), (
        "state holds no draft text"
    )
    assert not list((repo / "content").rglob("*draft.json")) and not list((repo / "content").rglob("linkedin.md"))


def test_unconfirmed_deployment_creates_no_drafts_and_no_publication_records(repo: Path, article: Path) -> None:
    manifest = manifest_for(repo, page_for(repo, article))
    for http in (
        FakeHTTP(manifest, down=True),
        FakeHTTP(manifest, commit="a" * 40),
        FakeHTTP(manifest, stale_pages={"https://bengt.no/en/posts/first/"}),
    ):
        client = FakeLLM()
        summary, state = run(repo, manifest, client, http)
        assert client.calls == [] and summary["generated"] == [] and len(summary["unverified"]) == 1
        assert state.publications == {} and state.drafts == {}
        assert not (repo / "social-drafts").exists()


def test_verification_is_bounded(repo: Path, article: Path) -> None:
    manifest = manifest_for(repo, page_for(repo, article))
    http = FakeHTTP(manifest, down=True)
    run(repo, manifest, FakeLLM(), http)
    assert len(http.requests) == load_policy().p.social.verify_attempts


def test_failed_generation_is_recoverable_without_duplicates(repo: Path, article: Path) -> None:
    second = write_bundle(repo, "en", "2026-10-02-second", "Second body.\n", title="Second article")
    manifest = manifest_for(repo, page_for(repo, article), page_for(repo, second))
    client = FakeLLM([good_draft(), llm.Unavailable("social: API unavailable")])
    summary, state = run(repo, manifest, client)
    assert [g["id"] for g in summary["generated"]] == ["en:first"] and [f["id"] for f in summary["failed"]] == [
        "en:second"
    ]
    assert set(state.publications) == {"en:first", "en:second"}, (
        "publication is recorded independently of draft success"
    )
    assert state.drafts["en:second"]["status"] == "pending" and state.drafts["en:second"]["attempts"] == 1
    assert "pending" in social.summary_markdown(load_policy(), summary, {"name": "a"}).splitlines()[0]

    retry = FakeLLM([good_draft()])
    summary, state = run(repo, manifest, retry)
    assert [g["id"] for g in summary["generated"]] == ["en:second"], "only the missing draft is retried"
    assert len(retry.calls) == 1 and state.drafts["en:second"]["status"] == "done"

    idle = FakeLLM()
    summary, _ = run(repo, manifest, idle)
    assert idle.calls == [] and summary["generated"] == [] and summary["failed"] == []


def test_ordinary_edit_does_not_regenerate_but_explicit_request_does(repo: Path, article: Path) -> None:
    run(repo, manifest_for(repo, page_for(repo, article)), FakeLLM([good_draft()]))
    article.write_bytes(article.read_bytes() + b"\nAn ordinary edit.\n")
    edited = manifest_for(repo, page_for(repo, article))
    idle = FakeLLM()
    summary, state = run(repo, edited, idle)
    assert idle.calls == [] and summary["generated"] == []
    assert state.publications["en:first"]["last_content_hash"] != state.publications["en:first"]["first_content_hash"]

    doc = fm.load(article)
    fm.save(doc, doc.set_scalars({"social.regenerate": True}))
    flagged = manifest_for(repo, page_for(repo, article))
    summary, state = run(repo, flagged, FakeLLM([good_draft()]))
    assert [g["id"] for g in summary["generated"]] == ["en:first"]
    assert state.drafts["en:first"]["content_hash"] == flagged["pages"][0]["content_hash"], (
        "the state records which text the draft represents"
    )
    assert summary["clear_flags"] == [
        {"path": "content/en/posts/2026-10-01-first/index.md", "content_hash": flagged["pages"][0]["content_hash"]}
    ]

    # The flag is still set (not cleared yet): no duplicate draft, only the pending clear.
    again = FakeLLM()
    summary, _ = run(repo, flagged, again)
    assert again.calls == [] and len(summary["clear_flags"]) == 1

    (repo / "reports").mkdir(exist_ok=True)
    (repo / "reports/social.json").write_text(json.dumps(summary))
    args = SimpleNamespace(report=str(repo / "reports/social.json"))
    assert social.cmd_clear(args, load_policy()) == 0
    assert fm.load(article).meta["social"]["regenerate"] is False
    assert fm.load(article).body == doc.body


def test_flag_is_kept_when_the_article_changed_after_the_draft(repo: Path, article: Path) -> None:
    doc = fm.load(article)
    fm.save(doc, doc.set_scalars({"social.regenerate": True}))
    manifest = manifest_for(repo, page_for(repo, article))
    summary, _ = run(repo, manifest, FakeLLM([good_draft()]))
    article.write_bytes(article.read_bytes() + b"\nNewer text.\n")
    (repo / "reports").mkdir(exist_ok=True)
    (repo / "reports/social.json").write_text(json.dumps(summary))
    social.cmd_clear(SimpleNamespace(report=str(repo / "reports/social.json")), load_policy())
    assert fm.load(article).meta["social"]["regenerate"] is True, (
        "the request now refers to newer text and must survive"
    )


def test_failed_regeneration_keeps_the_request_pending(repo: Path, article: Path) -> None:
    manifest = manifest_for(repo, page_for(repo, article))
    run(repo, manifest, FakeLLM([good_draft()]))
    summary, state = run(
        repo, manifest, FakeLLM([llm.Unavailable("down")]), regenerate=["https://bengt.no/en/posts/first/"]
    )
    assert state.drafts["en:first"]["status"] == "pending" and state.drafts["en:first"]["regenerate_requested"]
    summary, state = run(repo, manifest, FakeLLM([good_draft()]))
    assert [g["id"] for g in summary["generated"]] == ["en:first"] and state.drafts["en:first"]["status"] == "done"


def test_missing_artifact_is_recovered_by_permalink_path_or_id(repo: Path, article: Path) -> None:
    manifest = manifest_for(repo, page_for(repo, article))
    run(repo, manifest, FakeLLM([good_draft()]))
    for target in ("https://bengt.no/en/posts/first/", "content/en/posts/2026-10-01-first/index.md", "en:first"):
        import shutil

        shutil.rmtree(repo / "social-drafts")
        summary, _ = run(repo, manifest, FakeLLM([good_draft()]), regenerate=[target])
        assert (repo / "social-drafts/en-first/draft.json").is_file() and len(summary["generated"]) == 1
    with pytest.raises(UserError, match="not a published article"):
        run(repo, manifest, FakeLLM(), regenerate=["https://bengt.no/en/posts/unknown/"])


def test_invalid_drafts_are_corrected_or_rejected(repo: Path, article: Path) -> None:
    manifest = manifest_for(repo, page_for(repo, article))
    bad = [
        good_draft(x=X_TEXT + " #kubernetes"),
        good_draft(linkedin="Too short."),
        good_draft(x="x" * 270),
    ]
    client = FakeLLM([*bad])
    summary, state = run(repo, manifest, client)
    assert summary["generated"] == [] and len(client.calls) == 3
    assert "hashtag" in client.calls[1]["user"] and "words" in client.calls[2]["user"]
    assert state.drafts["en:first"]["status"] == "pending" and not (repo / "social-drafts/en-first").exists()

    for text, problem in ((X_TEXT + " 🚀", "emoji"), (X_TEXT + " https://example.com", "link"), ("語" * 130, "weighs")):
        problems, _ = social.check_texts(load_policy(), LINKEDIN, text, "https://bengt.no/en/posts/first/")
        assert any(problem in p for p in problems)


def test_disabled_articles_cap_and_baseline(repo: Path, article: Path) -> None:
    off = write_bundle(
        repo, "en", "2026-10-02-off", social={"enabled": False, "language": "inherit", "regenerate": False}
    )
    third = write_bundle(repo, "en", "2026-10-03-third")
    policy_file = repo / "data/automation-policy.yaml"
    policy_file.write_text(policy_file.read_text().replace("max_drafts_per_run: 5", "max_drafts_per_run: 1"))
    manifest = manifest_for(repo, page_for(repo, article), page_for(repo, off), page_for(repo, third))
    summary, state = run(repo, manifest, FakeLLM([good_draft()]))
    assert len(summary["generated"]) == 1 and [b["id"] for b in summary["backlog"]] == ["en:third"]
    assert state.drafts["en:off"]["status"] == "disabled" and state.drafts["en:third"]["status"] == "pending"

    args = SimpleNamespace(manifest=str(repo / "m.json"), state_dir=str(repo / ".state"))
    (repo / "m.json").write_text(json.dumps(manifest))
    assert social.cmd_baseline(args, load_policy()) == 0
    idle = FakeLLM()
    summary, state = run(repo, manifest, idle)
    assert idle.calls == [] and state.drafts["en:third"]["status"] == "baseline"


def test_checked_out_source_must_match_the_deployed_hash(repo: Path, article: Path) -> None:
    manifest = manifest_for(repo, page_for(repo, article))
    article.write_bytes(article.read_bytes() + b"\nLocal change that was never deployed.\n")
    client = FakeLLM()
    summary, _ = run(repo, manifest, client)
    assert client.calls == [] and "differs from the deployed content" in summary["failed"][0]["reason"]


def test_local_command_requires_a_confirmed_deployment(repo: Path, article: Path) -> None:
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "add", "content"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "content"], check=True)
    commit = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    manifest = {**manifest_for(repo, page_for(repo, article)), "content_commit": commit}
    policy = load_policy()

    unpublished = write_bundle(repo, "en", "2026-10-09-local-only", title="Only local, draft false")
    with pytest.raises(UserError, match="not a published article"):
        social.cmd_local(SimpleNamespace(target=str(unpublished)), policy, FakeLLM(), FakeHTTP(manifest))
    with pytest.raises(UserError, match="confirmed deployment"):
        social.cmd_local(SimpleNamespace(target=str(article)), policy, FakeLLM(), FakeHTTP(manifest, down=True))

    article.write_bytes(article.read_bytes() + b"\nUncommitted local edit.\n")
    client = FakeLLM([good_draft()])
    assert (
        social.cmd_local(SimpleNamespace(target="https://bengt.no/en/posts/first/"), policy, client, FakeHTTP(manifest))
        == 0
    )
    assert "Uncommitted local edit" not in client.calls[0]["user"], (
        "the draft is written from the deployed commit, not the working tree"
    )
    assert json.loads((repo / "social-drafts/en-first/draft.json").read_text())["content_commit"] == commit


def test_missing_api_key_keeps_everything_retryable(repo: Path, article: Path) -> None:
    manifest = manifest_for(repo, page_for(repo, article))
    summary, state = run(repo, manifest, None)
    assert "ANTHROPIC_API_KEY" in summary["failed"][0]["reason"]
    assert set(state.publications) == {"en:first"} and state.drafts["en:first"]["status"] == "pending"
