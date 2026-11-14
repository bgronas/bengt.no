# Design system

One direction: a quiet engineering publication. Graphite surfaces, warm off-white text, one teal accent, Roboto for reading, Roboto Mono for code and for the small `bengt.no` signature. No photographs, logos, gradients or decorative animation.

Everything is built on Blowfish v3.10.0 through its extension points. The theme submodule is unmodified.

## Where things live

| Concern | File |
|---|---|
| Colour scheme (Blowfish scheme named `bengt`) | `assets/css/schemes/bengt.css` |
| Typography, measure, local components | `assets/css/custom.css` |
| Theme parameters | `config/_default/params.toml` |
| Fonts, licences, hashes | `assets/fonts/` |
| Homepage | `layouts/partials/home/custom.html`, `layouts/partials/bn/featured-pages.html` |
| Font loading, Mermaid and KaTeX per page | `layouts/partials/extend-head.html`, `extend-head-uncached.html` |
| Images, links, tables, diagrams, math | `layouts/_default/_markup/render-*.html` |
| Social metadata, feature image selection | `layouts/partials/bn/social-meta.html`, `bn/feature-resource.html` |
| 404 page | `layouts/404.html` |
| Title cards, default social image, favicons | `scripts/generate_cards.py` |
| Interface strings | `i18n/nb.yaml`, `i18n/en.yaml` |

Three theme files are overridden, each recorded with the hash of its upstream original in `data/theme-overrides.json`: `layouts/_default/index.json`, `layouts/_default/rss.xml`, `layouts/partials/head.html`. `doctor` fails when an original changes.

## Colour

The scheme defines three ramps as RGB triplets, the format Blowfish composes with `rgba()`: neutral (warm off-white `250 248 244` to graphite `18 20 22`), primary (teal) and secondary (cyan). Components never use raw colour values; they use eight semantic tokens that switch with the appearance:

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--bn-bg` | neutral | neutral-800 | Page background |
| `--bn-surface` | neutral-100 | neutral-700 | Cards, chips, table header |
| `--bn-border` | neutral-300 | neutral-600 | Hairlines |
| `--bn-text` | neutral-900 | neutral | Body text, headings |
| `--bn-muted` | neutral-600 | neutral-300 | Dates, captions, secondary text |
| `--bn-accent` | primary-700 | primary-400 | Links, signature, focus ring |
| `--bn-accent-strong` | primary-800 | primary-300 | Hover |
| `--bn-code-bg` | neutral-100 | neutral-900 | Code blocks |

Contrast ratios, calculated from the token values with the WCAG 2 relative-luminance formula:

| Pair | Light | Dark | AA minimum |
|---|---|---|---|
| Text on background | 17.4 : 1 | 15.6 : 1 | 4.5 |
| Muted text on background | 7.6 : 1 | 9.5 : 1 | 4.5 |
| Muted text on surface | 6.7 : 1 | 7.2 : 1 | 4.5 |
| Accent on background | 6.6 : 1 | 7.2 : 1 | 4.5 |
| Accent on surface | 5.8 : 1 | 5.4 : 1 | 4.5 |
| Border on background | 1.7 : 1 | 2.1 : 1 | none for decorative lines |

Borders are decorative separators. No control depends on a border alone to be recognised: buttons and chips carry text, and focus is shown with a 2 px accent outline (6.6 : 1 and 7.2 : 1 against the background).

Appearance: dark by default (`defaultAppearance = "dark"`), a switcher in the header and footer, the reader's choice stored by the theme in `localStorage`. `autoSwitchAppearance` is off so that the default is the same for every first visit.

## Typography

| Token | Value | Use |
|---|---|---|
| `--font-sans` | Roboto, then system fonts | Interface and prose |
| `--font-mono` | Roboto Mono, then system monospace | Code, signature, eyebrow labels |
| `--bn-step--1` | 0.875 rem | Captions, labels, code blocks |
| `--bn-step-0` | 1.0625 rem (17 px) | Body |
| `--bn-step-1` | 1.25 rem | Lede, h3 |
| `--bn-step-2` | 1.5 rem | h2 |
| `--bn-step-3` | 1.9 rem | Section headings on landing pages |
| `--bn-step-4` | clamp(2.1 rem, 1.5 rem + 2.6 vw, 3 rem) | Wordmark, article title |
| `--bn-measure` | 58 ch | Prose column |
| `--bn-wide` | 96 ch | Code, tables, figures, diagrams |

Body line height is 1.65, prose 1.7. Paragraph spacing is 1.15 em; h2 has 2.2 em above it.

Reading measure: `58ch` at 17 px gives 73 to 77 characters per full line at 768 px and 1440 px, 67 to 71 at 1024 px where the table of contents takes a column, and 43 to 45 on a 375 px phone (measured in Chromium on the example articles; the browser smoke test asserts 60 to 80 at 1440 px). The `ch` unit is the width of "0", which is wider than Roboto's average glyph; that is why 58 ch holds about 75 characters. Code blocks, tables, figures and diagrams may extend to `--bn-wide` and scroll inside their own box beyond that.

Fonts are self-hosted variable WOFF2 files, subset into latin and latin-ext so that æ, ø and å come from the first file. `font-display: swap`; only the latin upright Roboto is preloaded. No request leaves the site's origin. Sources and licences (SIL OFL 1.1): `assets/fonts/README.md`.

Wordmark: the name in Roboto 700/800 with `bengt.no` beside it in Roboto Mono, accent colour. It is text, not an image.

## Components

| Component | Class | Notes |
|---|---|---|
| Introduction | `.bn-intro`, `.bn-eyebrow`, `.bn-wordmark`, `.bn-signature`, `.bn-lede` | Homepage only |
| Link buttons, topic chips | `.bn-links`, `.bn-chips`, `.bn-button`, `.bn-count` | 44 px minimum touch height |
| Section title | `.bn-section-title` | Mono, uppercase, hairline |
| Article rows | `.bn-rows` with the theme's article card | Title, summary, categories, tags, date, reading time, word count |
| Empty state | `.bn-empty` | Topics, featured, series and search with nothing to show |
| Table | `.bn-table` | Focusable scroll region with an accessible name (render hook) |
| Figure | `.bn-figure` | `<picture>` with WebP and fallback, width and height set, caption from the image title |
| Diagram | `.bn-diagram` | Mermaid; source stays readable without JavaScript |
| Code | theme's `.highlight-wrapper` | Chroma classes, no line wrapping, horizontal scroll, copy button reachable by keyboard and always visible on touch screens |

## Public surfaces

| Surface | Norwegian | English | Built from |
|---|---|---|---|
| Homepage | `/` | `/en/` | Custom homepage partial: introduction, topics, featured, recent, RSS link |
| Article index | `/posts/` | `/en/posts/` | Theme list with summaries; server-rendered pagination, no JavaScript needed |
| Article | `/posts/<slug>/` | `/en/posts/<slug>/` | Theme single: breadcrumbs, date and update, reading time, word count, Zen mode, table of contents (side column on desktop, collapsible on mobile), series navigation, related articles, sharing links, translation link |
| Topics | `/categories/`, `/tags/` | `/en/categories/`, `/en/tags/` | Theme taxonomy and term pages |
| Series | `/series/` | `/en/series/` | Theme series taxonomy; parts ordered by numeric `series_order` |
| Search | header button, `/` or Ctrl+K | same | Theme's client-side Fuse.js search over `/index.json` and `/en/index.json` |
| About | `/om/` | `/en/about/` | Supplied identity and the two confirmed profile links only |
| 404 | `/404.html` | same file | Navigation and search; lists no article titles |

Featured: `featured: true` is the only switch. The section appears on the homepage when at least one published article has it; order is `featured_weight` ascending, then date descending, then path. Recent articles follow and exclude the featured ones.

Sharing links: `linkedin`, `twitter`, `bluesky`, `email`, all identifiers present in the pinned theme's `data/sharing.json`. They are plain links; no third-party script is loaded. `showEdit` is off.

## Motion

Transitions are the theme's short hover and menu transitions. `prefers-reduced-motion: reduce` sets smooth scrolling to `auto` and all animation and transition durations to 0.01 ms. Images and embeds have explicit dimensions, so nothing shifts while loading.

## JavaScript

Without JavaScript every article, list, taxonomy page and the navigation work; search, the appearance switcher, copy buttons and Mermaid rendering need it. Mermaid (5.5 MB in the theme) is requested only on pages that contain a diagram, and only when the diagram comes within 600 px of the viewport or before printing. KaTeX is rendered at build time; only its stylesheet is loaded, and only on pages with math. No analytics, cookies, comments or third-party requests.

## Social images

Every article has a 1200 × 630 image. An authored `feature.*` is used when present; otherwise `scripts/generate_cards.py` writes `feature.webp` from the title, the first category, the language and `bengt.no`, in bundled Roboto. `og:image` and `twitter:image` point to a JPEG derivative made by Hugo, because WebP and SVG are not accepted by every crawler. Pages without an article image use `assets/img/default-social.png`. The site build check verifies that each referenced image exists, is JPEG or PNG and measures 1200 × 630.

## Measured results

Local preview build, 2026-11-14, Chromium 1243 (Playwright), served by `python -m http.server` on localhost. These are lab figures from a development container, not production or real-user data. INP cannot be measured in a lab run; Total Blocking Time is reported instead.

### Lighthouse 13.6.0, mobile preset

Simulated throttling (slow 4G: 150 ms RTT, 1.6 Mbit/s; CPU slowdown 4×), one run per page, build made with `hugo --gc --minify --buildDrafts` so that the example articles exist.

| Page | Performance | Accessibility | Best practices | SEO | LCP | CLS | TBT |
|---|---|---|---|---|---|---|---|
| `/` | 95 | 100 | 100 | 100 | 2.6 s | 0 | 110 ms |
| `/en/` | 96 | 100 | 100 | 100 | 2.6 s | 0 | 0 ms |
| `/posts/` | 96 | 100 | 100 | 100 | 2.6 s | 0 | 40 ms |
| `/en/posts/` | 96 | 100 | 100 | 100 | 2.6 s | 0 | 0 ms |
| `/en/posts/how-this-site-is-published/` | 98 | 100 | 100 | 100 | 2.0 s | 0 | 0 ms |
| `/posts/slik-publiseres-dette-nettstedet/` | 98 | 100 | 100 | 100 | 2.0 s | 0 | 50 ms |
| `/en/about/` | 99 | 100 | 100 | 100 | 1.7 s | 0 | 40 ms |
| `/om/` | 99 | 100 | 100 | 100 | 1.7 s | 0 | 10 ms |

Against the targets: accessibility, best practices and SEO ≥ 95 and mobile performance ≥ 90 are met on all eight pages. CLS ≤ 0.1 is met. LCP ≤ 2.5 s is met on articles and About and **missed by 0.1 s on the homepage and the article lists** under simulated slow 4G.

Cause of the miss (from Lighthouse's own LCP analysis): on a phone the largest element of a list page is the first article card's thumbnail, and the pinned theme renders list thumbnails with `loading="lazy"` and `fetchpriority="low"`. A preload link for that image was tried and removed again, because it did not change the simulated figure. The remaining fix is a fourth theme override (`partials/article-link/simple.html`) to load the first thumbnail eagerly; it was not made, to keep the override surface small. The unthrottled LCP observed in the same runs was about 0.2 s.

The SEO score is from a preview build; production adds nothing that would lower it, but it was not measured on the deployed site.

### axe-core 4.14.0

Rule tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`; ten pages (both homepages, both article lists, both About pages, series, tags, 404, the example article) at 375 px and 1440 px in both appearances: 40 runs, 0 violations.

### Browser smoke test

`tests/browser/smoke.py`: 201 checks, 0 failures. It covers horizontal overflow at 375, 768 and 1440 px in both appearances (0 px on every page), table of contents on desktop and mobile, copy buttons by mouse and keyboard, Mermaid loading and re-rendering on appearance change, SVG delivery, the table scroll region, series navigation, language switching to the real translation, per-language search with empty results, focus order and visibility, reduced motion, and the 404 page.

## Limits of the checks

- axe-core finds a subset of WCAG failures. It does not judge alt-text quality, reading order, or whether headings describe their sections. Those were reviewed by eye on the example articles only.
- Keyboard order, visible focus, search, copy buttons, language switching and reduced motion are covered by the scripted smoke test in Chromium. Firefox, Safari and screen readers were not tested.
- Screenshots at 375, 768 and 1440 px in both appearances were reviewed during the build. They are not part of the repository; regenerate them with `tests/browser/shots.py`.
