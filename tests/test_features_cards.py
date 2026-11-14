from __future__ import annotations

import json
from pathlib import Path

import detect_features
import generate_cards
from lib import fm, mdscan
from lib.common import load_policy
from PIL import Image

from tests.conftest import write_bundle


def test_currency_and_code_do_not_count_as_math() -> None:
    assert not mdscan.scan("It cost $50 and then $75. Total: $125.\n").has_math
    assert not mdscan.scan(
        "Inline `$$x$$` and `\\(y\\)`.\n\n```latex\n$$a$$\n\\[b\\]\n```\n\n    $$indented code$$\n"
    ).has_math
    assert not mdscan.scan("Escaped \\\\(not math\\\\) here.\n").has_math
    assert mdscan.scan("Block:\n\n$$a^2$$\n").has_math
    assert mdscan.scan("Inline \\(a+b\\) here.\n").has_math
    assert mdscan.scan("Display \\[a+b\\] here.\n").has_math


def test_mermaid_is_detected_only_in_parsed_fences() -> None:
    assert mdscan.scan("```mermaid\nflowchart LR\n```\n").has_mermaid
    assert mdscan.scan("{{< mermaid >}}\ngraph TD\n{{< /mermaid >}}\n").has_mermaid
    assert not mdscan.scan("The word mermaid in prose and `mermaid` in code.\n").has_mermaid
    assert not mdscan.scan("````markdown\n```mermaid\nflowchart LR\n```\n````\n").has_mermaid


def test_image_syntax_inside_code_is_not_an_image() -> None:
    scan = mdscan.scan("![real](a.png)\n\n```md\n![fake](b.png)\n```\n\n`![fake2](c.png)`\n\n    ![fake3](d.png)\n")
    assert [i.dest for i in scan.images] == ["a.png"]


def test_flags_follow_content_and_overrides(repo: Path) -> None:
    math = write_bundle(repo, "en", "2026-10-01-math", "$$a$$\n\nPrice $5.\n")
    price = write_bundle(repo, "en", "2026-10-02-price", "Price $50.\n", math=True)
    forced = write_bundle(
        repo,
        "en",
        "2026-10-03-forced",
        "```mermaid\ngraph TD\n```\n",
        feature_overrides={"mermaid": False, "math": True},
    )
    before = math.read_bytes()
    assert detect_features.main(["--check"]) == 1 and math.read_bytes() == before
    assert detect_features.main([]) == 0
    assert fm.load(math).meta["math"] is True
    assert fm.load(price).meta["math"] is False
    assert fm.load(forced).meta["mermaid"] is False and fm.load(forced).meta["math"] is True
    changed = [a for a, b in zip(before.decode().split("\n"), math.read_text().split("\n"), strict=True) if a != b]
    assert changed == ["math: false"], "only the flag line is edited"
    assert detect_features.main(["--check"]) == 0


def cards(repo: Path) -> dict:
    return json.loads((repo / "data/card-manifest.json").read_text())["cards"]


def test_cards_render_for_both_languages_and_are_idempotent(repo: Path) -> None:
    no = write_bundle(repo, "no", "2026-10-01-norsk", title="Blåbærsyltetøy på Ærø: æ, ø og å")
    en = write_bundle(repo, "en", "2026-10-01-english", title="An English title")
    assert generate_cards.main([]) == 0
    for path in (no, en):
        with Image.open(path.parent / "feature.webp") as img:
            assert img.size == (1200, 630) and img.format == "WEBP"
    state = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and "reports" not in p.parts}
    assert generate_cards.main([]) == 0
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and "reports" not in p.parts} == state
    assert len(cards(repo)) == 2


def test_card_is_rerendered_when_its_inputs_change(repo: Path) -> None:
    path = write_bundle(repo, "en", "2026-10-01-change", title="First title")
    generate_cards.main([])
    first = (path.parent / "feature.webp").read_bytes()
    doc = fm.load(path)
    fm.save(doc, doc.set_scalars({"title": "A different title"}))
    assert generate_cards.main([]) == 0
    assert (path.parent / "feature.webp").read_bytes() != first
    doc = fm.load(path)
    fm.save(doc, doc.with_meta({**doc.meta, "categories": ["Personal"]}))
    second = (path.parent / "feature.webp").read_bytes()
    generate_cards.main([])
    assert (path.parent / "feature.webp").read_bytes() != second, "the primary category is part of the card"
    doc = fm.load(path)
    fm.save(doc, doc.with_meta({**doc.meta, "tags": ["Python"], "summary": "Other summary."}))
    third = (path.parent / "feature.webp").read_bytes()
    generate_cards.main([])
    assert (path.parent / "feature.webp").read_bytes() == third, "unrelated metadata does not cause a new binary"


def test_authored_images_are_preserved(repo: Path) -> None:
    authored = write_bundle(repo, "en", "2026-10-01-authored")
    Image.new("RGB", (800, 600), "navy").save(authored.parent / "feature.jpg")
    cover = write_bundle(repo, "en", "2026-10-02-cover")
    Image.new("RGB", (800, 600), "navy").save(cover.parent / "cover.png")
    late = write_bundle(repo, "en", "2026-10-03-late")
    edited = write_bundle(repo, "en", "2026-10-04-edited")
    assert generate_cards.main([]) == 0
    assert not (authored.parent / "feature.webp").exists() and not (cover.parent / "feature.webp").exists()
    assert (late.parent / "feature.webp").exists()

    Image.new("RGB", (800, 600), "olive").save(late.parent / "feature.png")
    own = b"author replaced this file"
    (edited.parent / "feature.webp").write_bytes(own)
    assert generate_cards.main([]) == 0
    assert not (late.parent / "feature.webp").exists(), "the generated card yields to an authored image"
    assert (late.parent / "feature.png").exists()
    assert (edited.parent / "feature.webp").read_bytes() == own, "an author-edited card is never overwritten"
    assert set(cards(repo)) == set()
    assert generate_cards.main([]) == 0
    assert (edited.parent / "feature.webp").read_bytes() == own


def test_long_titles_wrap_at_a_readable_size_and_odd_unicode_is_handled(repo: Path) -> None:
    policy = load_policy()
    fonts = generate_cards.Fonts(policy.root)
    probe = Image.new("RGB", (1200, 630))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(probe)
    long_title = "Hvordan vi flyttet et helt Kubernetes-cluster med GitOps uten nedetid " * 4
    font, lines, line_height = generate_cards.fit_title(draw, fonts, long_title, 1040, 350, policy.p.cards)
    assert font.size >= policy.p.cards.min_title_px, "type never shrinks below the readable minimum"
    assert lines[-1].endswith("…") and len(lines) * line_height <= 350
    assert all(draw.textlength(line, font=font) <= 1040 for line in lines)

    short_font, short_lines, _ = generate_cards.fit_title(draw, fonts, "Kort tittel", 1040, 350, policy.p.cards)
    assert short_font.size == policy.p.cards.max_title_px and short_lines == ["Kort tittel"]

    assert fonts.supported("Blåbær på Ærø — «æøå»") == "Blåbær på Ærø — «æøå»"
    assert fonts.supported("Deploy 🚀 to 日本 now") == "Deploy to now", (
        "glyphs the bundled font lacks are dropped, not drawn as boxes"
    )
    card = generate_cards.render(
        fonts, policy.p.cards, title="Supercalifragilisticexpialidocious" * 3, category="Cloud Native", lang="en"
    )
    assert card.size == (1200, 630)
