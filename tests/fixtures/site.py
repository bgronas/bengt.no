"""Content for the integration build: every publication state and every image class."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from tests.conftest import text_of_length, write_bundle

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120" viewBox="0 0 320 120">'
    '<rect width="320" height="120" fill="#1c1f21"/><circle cx="60" cy="60" r="30" fill="#2dbeb2"/></svg>\n'
)

LINKED_BODY_NO = """Innledning med et bilde.

![Foto med EXIF-rotasjon](photo.jpg "Et foto")

![Lite foto](small.jpg)

![Skjermbilde med gjennomsiktighet](shot.png)

![Animasjon](anim.gif)

![Vektordiagram](diagram.svg)

## En tabell

| Felt | Verdi |
|---|---|
| draft | false |

## Kode med bildesyntaks

```markdown
![ikke et bilde](finnes-ikke.png)
```

Lenke til [seksjonen over](#en-tabell) og et [vedlegg](notes.txt).
"""

MATH_BODY = """Prisen var $50 og senere $75, uten at det er matematikk.

Inline-kode som `$x$` og `\\(y\\)` er heller ikke matematikk.

$$a^2 + b^2 = c^2$$

Og inline: \\(e^{i\\pi} + 1 = 0\\).
"""

MERMAID_BODY = """Et diagram:

```mermaid
flowchart LR
  A[Start] --> B[Slutt]
```
"""


def _images(folder: Path) -> None:
    photo = Image.new("RGB", (4000, 3000), (200, 30, 30))
    photo.paste((30, 30, 200), (2000, 0, 4000, 3000))
    exif = Image.Exif()
    exif[0x0112] = 6
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (59.0, 55.0, 0.0)
    gps[3] = "E"
    gps[4] = (10.0, 45.0, 0.0)
    exif[0x010F] = "TestCam"
    photo.save(folder / "photo.jpg", quality=85, exif=exif)
    Image.new("RGB", (400, 300), (40, 120, 90)).save(folder / "small.jpg", quality=85)
    shot = Image.new("RGBA", (1200, 800), (0, 0, 0, 0))
    shot.paste((250, 248, 244, 255), (100, 100, 1100, 700))
    shot.paste((28, 31, 33, 255), (140, 140, 1060, 180))
    shot.save(folder / "shot.png")
    frames = [Image.new("RGB", (120, 80), color) for color in ("red", "blue", "green")]
    frames[0].save(folder / "anim.gif", save_all=True, append_images=frames[1:], duration=200, loop=0)
    (folder / "diagram.svg").write_text(SVG)
    (folder / "notes.txt").write_text("An attachment that is published only because the article links to it.\n")
    (folder / "unlinked.txt").write_text("An attachment nobody links to. It must not be published.\n")


def populate(root: Path) -> None:
    d = text_of_length
    linked = write_bundle(
        root, "no", "2026-10-01-lenket-artikkel", LINKED_BODY_NO,
        title="Lenket artikkel", translationKey="linked", featured=True, featured_weight=2,
        description=d(155, "Norsk beskrivelse av den lenkede artikkelen for søkeresultater"),
        summary="Et sammendrag som er formulert annerledes enn beskrivelsen.",
    )  # fmt: skip
    _images(linked.parent)
    write_bundle(
        root, "en", "2026-10-01-linked-article", "English body with an [internal page](/en/about/).\n",
        title="Linked article", translationKey="linked",
        description=d(152, "English description of the linked article for search results"),
    )  # fmt: skip
    write_bundle(
        root, "no", "2026-10-02-bare-norsk", MATH_BODY, title="Bare norsk med matematikk", math=True,
        featured=True, featured_weight=1, series=["Serie A"], series_order=2,
    )  # fmt: skip
    write_bundle(
        root, "no", "2026-10-03-serie-del-en", MERMAID_BODY, title="Serie del en", mermaid=True,
        featured=True, series=["Serie A"], series_order=1,
    )  # fmt: skip
    write_bundle(
        root,
        "no",
        "2026-10-05-serie-del-ti",
        "Tiende del.\n",
        title="Serie del ti",
        series=["Serie A"],
        series_order=10,
    )
    write_bundle(
        root, "no", "2026-10-04-hemmelig-utkast", "Utkast.\n", title="HEMMELIG UTKAST", draft=True, featured=True
    )
    write_bundle(
        root, "no", "2026-10-06-fremtidig", "Fremtid.\n", title="FREMTIDIG ARTIKKEL",
        date="2099-01-01T09:00:00+01:00", lastmod="2099-01-01T09:00:00+01:00", featured=True,
    )  # fmt: skip
    write_bundle(
        root, "no", "2026-09-01-utlopt", "Utløpt.\n", title="UTLØPT ARTIKKEL",
        date="2026-09-01T09:00:00+02:00", lastmod="2026-09-01T09:00:00+02:00", expiryDate="2026-10-01T00:00:00+02:00",
    )  # fmt: skip
