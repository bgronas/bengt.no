# Self-hosted fonts

| File | Family | Source | Licence |
|---|---|---|---|
| `roboto-latin-wght-normal.woff2`, `roboto-latin-ext-wght-normal.woff2`, `roboto-latin-wght-italic.woff2` | Roboto (variable, wght 100–900) | npm `@fontsource-variable/roboto` 5.3.0 | SIL OFL 1.1, `LICENSE-Roboto.txt` |
| `roboto-mono-latin-wght-normal.woff2`, `roboto-mono-latin-ext-wght-normal.woff2` | Roboto Mono (variable, wght 100–700) | npm `@fontsource-variable/roboto-mono` 5.3.0 | SIL OFL 1.1, `LICENSE-RobotoMono.txt` |
| `card/Roboto-Variable.ttf` | Roboto (variable, wdth + wght) | `google/fonts` repository, `ofl/roboto/Roboto[wdth,wght].ttf` | SIL OFL 1.1, `LICENSE-Roboto.txt` |

The WOFF2 files are served to browsers through `layouts/partials/extend-head.html`.
The TTF is read only by `scripts/generate_cards.py` (Pillow) and is never published:
Hugo publishes an asset only when a template requests its URL.

`SHA256SUMS` records the files as downloaded on 2026-11-13. Update procedure: `docs/operations.md`.
