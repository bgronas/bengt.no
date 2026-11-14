from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import post_tool
import pytest
import translate_post
from lib import fm, llm, segments
from lib.common import UserError, load_policy

from tests.conftest import FakeLLM, text_of_length, write_bundle

SOURCE = """Innledning med `kubectl get pods`, en [lenke](https://example.com/a?b=1) og en [intern lenke](#to-flagg).

## To flagg {.wide}

Et bilde: ![Diagram av flyten](flyt.svg "Flyten") og matematikk \\(a+b\\).

| Felt | Verdi |
|:---|---:|
| `draft` | true |

1. Første punkt med `kode`
2. Andre punkt

```bash
# denne kommentaren skal ikke oversettes
echo "![ikke et bilde](x.png)"
```

{{< alert >}}
Tekst i en shortcode.
{{< /alert >}}

```mermaid
flowchart LR
  A[Start] --> B[Slutt]
```

## Egen anker {#fast-id}

Se [fast lenke](#fast-id). Pris: $50.

$$
E = mc^2
$$
"""

META_TR = {
    "title": "Two flags",
    "slug": "Two Flags!",
    "summary": "A translated summary.",
    "description": text_of_length(155, "A translated description of the article for search results"),
    "keywords": ["flags", "pipeline"],
}


def translator(mutate: Any = None) -> Any:
    """Answers a segment request by upper-casing prose while copying placeholders."""

    def respond(purpose: str, user: str) -> dict[str, Any]:
        if purpose == "translation-metadata":
            return dict(META_TR)
        payload = json.loads(user.split("============\n", 1)[1].rsplit("\n============ END", 1)[0])
        out = []
        for seg in payload["segments"]:
            parts = re.split(r"(⟦P\d+⟧)", seg["text"])
            text = "".join(p if p.startswith("⟦P") else p.upper() for p in parts)
            out.append({"id": seg["id"], "text": text})
        result = {"segments": out}
        return mutate(result) if mutate else result

    return respond


def source_bundle(repo: Path, **overrides: Any) -> Path:
    path = write_bundle(repo, "no", "2026-10-01-to-flagg", SOURCE, title="To flagg", auto_translate=True, **overrides)
    (path.parent / "flyt.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>")
    (path.parent / ".hidden").write_text("secret")
    (path.parent / "state.env").write_text("X=1")
    return path


def target(repo: Path) -> Path:
    return repo / "content/en/posts/2026-10-01-two-flags/index.md"


def test_segmentation_reassembles_exactly_and_protects_literals() -> None:
    plan = segments.build_plan(SOURCE)
    assert segments.reassemble(plan, {s.id: s.text for s in plan.segments}) == SOURCE
    sent = "\n".join(s.text for s in plan.segments)
    for literal in (
        "kubectl",
        "https://example.com",
        "flyt.svg",
        "echo",
        "flowchart",
        "mc^2",
        "a+b",
        "alert",
        "#fast-id",
        ".wide",
        ":---",
    ):
        assert literal not in sent, f"{literal!r} must never be sent for translation"
    assert "Diagram av flyten" in sent and "Tekst i en shortcode." in sent, (
        "prose, alt text and captions are translated"
    )


def test_translation_creates_a_linked_review_draft_with_exact_protected_syntax(repo: Path) -> None:
    src = source_bundle(repo)
    client = FakeLLM(default=translator())
    assert translate_post.main([], client=client) == 0
    doc = fm.load(target(repo))
    body = doc.body.decode()
    for literal in (
        "`kubectl get pods`", "(https://example.com/a?b=1)", "(flyt.svg ", "\\(a+b\\)", "| `draft` |", "|:---|---:|",
        '```bash\n# denne kommentaren skal ikke oversettes\necho "![ikke et bilde](x.png)"\n```',
        "{{< alert >}}", "{{< /alert >}}", "```mermaid\nflowchart LR\n  A[Start] --> B[Slutt]\n```", "{#fast-id}", "{.wide}",
        "(#fast-id)", "$$\nE = mc^2\n$$",
    ):  # fmt: skip
        assert literal in body, f"{literal!r} was not preserved"
    assert "INNLEDNING MED" in body and "![DIAGRAM AV FLYTEN]" in body and "PRIS: $50." in body
    assert "(#to-flagg)" in body, (
        "the translated heading keeps its text here, so the mapped anchor is the same word in lower case"
    )

    meta = doc.meta
    assert meta["draft"] is True and meta["auto_translate"] is False and meta["featured"] is False
    assert meta["translationKey"] == fm.load(src).meta["translationKey"]
    assert meta["slug"] == "two-flags" and meta["title"] == "Two flags"
    assert meta["categories"] == ["Technology"] and meta["tags"] == ["Hugo", "Markdown"], (
        "taxonomy values stay canonical"
    )
    assert meta["auto_enrich"] is False, "all generated metadata validates, so no enrichment is requested"
    info = meta["translation"]
    assert info["state"] == "machine-draft" and info["source_lang"] == "no" and info["model"] == "fake-model-1"
    assert info["source_hash"].startswith("sha256:")
    assert fm.load(src).meta["auto_translate"] is False, "the request is cleared once the target exists"
    assert fm.load(src).body == SOURCE.encode()
    names = sorted(p.name for p in target(repo).parent.iterdir())
    assert names == ["flyt.svg", "index.md"], "hidden files and non-allowlisted files are not copied"


def test_internal_links_follow_translated_headings(repo: Path) -> None:
    source_bundle(repo)

    def rename(result: dict[str, Any]) -> dict[str, Any]:
        for seg in result["segments"]:
            seg["text"] = seg["text"].replace("## TO FLAGG", "## Two flags")
        return result

    assert translate_post.main([], client=FakeLLM(default=translator(rename))) == 0
    body = fm.load(target(repo)).body.decode()
    assert "## Two flags {.wide}" in body and "(#two-flags)" in body and "(#to-flagg)" not in body
    assert "(#fast-id)" in body, "explicit IDs are never rewritten"


def test_unmappable_internal_link_fails_with_an_actionable_report(repo: Path, capsys) -> None:
    path = write_bundle(
        repo, "no", "2026-10-01-anker", "Se [her](#finnes-ikke).\n\n## Overskrift\n", auto_translate=True
    )
    assert translate_post.main([], client=FakeLLM(default=translator())) == 3
    assert "explicit ID" in capsys.readouterr().out
    assert not (repo / "content/en/posts").exists() or not list((repo / "content/en/posts").iterdir())
    assert fm.load(path).meta["auto_translate"] is True, "the request stays retryable"


@pytest.mark.parametrize(
    "damage",
    [
        lambda t: re.sub(r"⟦P\d+⟧", "", t, count=1),
        lambda t: re.sub(r"(⟦P\d+⟧)", r"\1\1", t, count=1),
        lambda t: re.sub(r"⟦P(\d+)⟧", lambda m: f"⟦P{int(m.group(1)) + 500}⟧", t, count=1),
        lambda t: re.sub(r"(⟦P\d+⟧)(.*?)(⟦P\d+⟧)", r"\3\2\1", t, count=1, flags=re.S),
    ],
    ids=["missing", "duplicated", "altered", "reordered"],
)
def test_damaged_placeholders_are_rejected_and_nothing_is_written(repo: Path, damage: Any) -> None:
    src = source_bundle(repo)

    def mutate(result: dict[str, Any]) -> dict[str, Any]:
        for seg in result["segments"]:
            if len(re.findall(r"⟦P\d+⟧", seg["text"])) >= 2:
                seg["text"] = damage(seg["text"])
                break
        return result

    client = FakeLLM(default=translator(mutate))
    assert translate_post.main([], client=client) == 3
    assert not target(repo).exists()
    assert not list((repo / "content/en/posts").glob(".tmp-*")), "no partial bundle is left behind"
    assert fm.load(src).meta["auto_translate"] is True
    assert sum(c["purpose"] == "translation" for c in client.calls) == 3, "retries are bounded"


def test_dropped_segment_is_rejected(repo: Path) -> None:
    source_bundle(repo)

    def drop(result: dict[str, Any]) -> dict[str, Any]:
        result["segments"] = result["segments"][:-1]
        return result

    assert translate_post.main([], client=FakeLLM(default=translator(drop))) == 3
    assert not target(repo).exists()


def test_api_failure_leaves_request_retryable_and_no_target(repo: Path) -> None:
    src = source_bundle(repo)
    assert translate_post.main([], client=FakeLLM([llm.Unavailable("down")])) == 3
    assert not target(repo).exists() and fm.load(src).meta["auto_translate"] is True
    assert translate_post.main([], client=FakeLLM(default=translator())) == 0
    assert target(repo).exists()


def test_existing_translation_is_never_overwritten_and_there_is_no_ping_pong(repo: Path, capsys) -> None:
    src = source_bundle(repo)
    assert translate_post.main([], client=FakeLLM(default=translator())) == 0
    edited = target(repo).read_bytes() + b"\nHuman edit.\n"
    target(repo).write_bytes(edited)

    idle = FakeLLM()
    assert translate_post.main([], client=idle) == 0 and idle.calls == [], "nothing is requested any more"
    fm.save(fm.load(src), fm.load(src).set_scalars({"auto_translate": True}))
    capsys.readouterr()
    assert translate_post.main([], client=idle) == 0
    assert "translation exists; explicit refresh required" in capsys.readouterr().out
    assert idle.calls == [] and target(repo).read_bytes() == edited
    assert fm.load(src).meta["auto_translate"] is False


def test_refresh_writes_a_candidate_and_diff_outside_content(repo: Path) -> None:
    src = source_bundle(repo)
    assert translate_post.main([], client=FakeLLM(default=translator())) == 0
    edited = target(repo).read_bytes() + b"\nHuman edit.\n"
    target(repo).write_bytes(edited)
    assert translate_post.main([str(src), "--refresh"], client=FakeLLM(default=translator())) == 0
    review = repo / "translation-review/en/2026-10-01-two-flags"
    assert (review / "index.candidate.md").is_file() and "-Human edit." in (review / "index.diff").read_text()
    assert target(repo).read_bytes() == edited, "the reviewed translation is preserved"
    assert not list((repo / "content").rglob("*.candidate.md"))


def test_stale_translation_is_reported_after_a_source_edit(repo: Path, capsys) -> None:
    src = source_bundle(repo)
    assert translate_post.main([], client=FakeLLM(default=translator())) == 0
    assert translate_post.staleness(load_policy(), translate_post.content.discover(load_policy())) == []
    src.write_bytes(src.read_bytes() + b"\nNy setning.\n")
    stale = translate_post.staleness(load_policy(), translate_post.content.discover(load_policy()))
    assert [s["status"] for s in stale] == ["stale"]
    capsys.readouterr()
    assert translate_post.main(["--status"]) == 0
    assert "[stale]" in capsys.readouterr().out


def test_machine_draft_cannot_be_published_until_reviewed(repo: Path, capsys) -> None:
    source_bundle(repo)
    assert translate_post.main([], client=FakeLLM(default=translator())) == 0
    with pytest.raises(UserError, match="unreviewed machine translation"):
        post_tool.main(["ready", str(target(repo))])
    assert fm.load(target(repo)).meta["draft"] is True
    doc = fm.load(target(repo))
    fm.save(doc, doc.set_scalars({"translation_reviewed": True}))
    assert post_tool.main(["ready", str(target(repo))]) == 0
    assert fm.load(target(repo)).meta["draft"] is False


def test_generated_title_card_is_not_copied_to_the_translation(repo: Path) -> None:
    src = source_bundle(repo)
    card = src.parent / "feature.webp"
    card.write_bytes(b"RIFF....WEBP")
    key = card.relative_to(repo).as_posix()
    (repo / "data/card-manifest.json").write_text(
        json.dumps({"version": 1, "cards": {key: {"input_hash": "x", "output_sha256": "y"}}})
    )
    assert translate_post.main([], client=FakeLLM(default=translator())) == 0
    assert not (target(repo).parent / "feature.webp").exists()


def test_long_articles_are_chunked_and_never_truncated(repo: Path, capsys) -> None:
    body = "\n\n".join(f"Avsnitt nummer {i} med litt tekst som fyller opp plassen i segmentet." * 6 for i in range(60))
    src = write_bundle(repo, "no", "2026-10-01-lang", body + "\n", auto_translate=True)
    client = FakeLLM(default=translator())
    assert translate_post.main([], client=client) == 0
    chunks = sum(c["purpose"] == "translation" for c in client.calls)
    assert chunks > 1
    out = fm.load(repo / "content/en/posts/2026-10-01-two-flags/index.md").body.decode()
    assert out == body.upper() + "\n"

    policy_file = repo / "data/automation-policy.yaml"
    policy_file.write_text(policy_file.read_text().replace("max_chunks_per_article: 14", "max_chunks_per_article: 1"))
    src2 = write_bundle(repo, "no", "2026-10-02-lang-to", body + "\n", auto_translate=True)
    capsys.readouterr()
    assert translate_post.main([str(src2)], client=FakeLLM(default=translator())) == 3
    assert "never truncated" in capsys.readouterr().out
    assert fm.load(src).meta["auto_translate"] is False and fm.load(src2).meta["auto_translate"] is True


def test_reserved_characters_in_source_are_rejected(repo: Path) -> None:
    write_bundle(repo, "no", "2026-10-01-rar", "Tekst med ⟦P1⟧ i kilden.\n", auto_translate=True)
    assert translate_post.main([], client=FakeLLM(default=translator())) == 3
