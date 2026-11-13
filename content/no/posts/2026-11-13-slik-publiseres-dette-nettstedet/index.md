---
title: "Slik publiseres dette nettstedet"
date: "2026-11-13T09:00:00+01:00"
lastmod: "2026-11-13T09:00:00+01:00"
draft: true
slug: "slik-publiseres-dette-nettstedet"
translationKey: "site-pipeline-overview"
auto_enrich: false
auto_translate: false
summary: "En gjennomgang av publiseringsflyten bak dette nettstedet: Markdown-bundles i Git, to eksplisitte flagg og én workflow som behandler, bygger og deployer."
math: false
mermaid: true
featured: false
description: "Slik gjør dette Hugo- og Blowfish-nettstedet en Markdown page bundle i Git om til en publisert artikkel, med to eksplisitte flagg og én GitHub Actions-workflow."
keywords:
  - Hugo publiseringsflyt
  - Blowfish-tema
  - GitHub Actions deploy
  - Markdown page bundles
  - GitOps for innhold
categories:
  - Technology
tags:
  - Hugo
  - Blowfish
  - GitHub Actions
  - Markdown
  - GitOps
series:
  - Site Pipeline
series_order: 1
social:
  enabled: true
  language: "inherit"
  regenerate: false
---

Denne artikkelen beskriver systemet som publiserer den. Hver artikkel på nettstedet er en mappe i et Git-repository. Mappen inneholder én Markdown-fil og bildene som hører til. Ingenting lagres i en database.

## Én mappe per artikkel

Hugo kaller mappen en leaf page bundle. Datoprefikset holder mappene sortert på disk, mens den offentlige adressen kommer fra feltet `slug`. De to kan derfor være forskjellige.

```text
content/no/posts/2026-11-13-slik-publiseres-dette-nettstedet/
├── index.md       artikkelen og front matter
├── pipeline.svg   et bilde som artikkelen refererer til
└── feature.webp   generert tittelkort, lagt til av pipelinen
```

Norske artikler ligger under `content/no/` og leveres fra roten av nettstedet. Engelske artikler ligger under `content/en/` og leveres under `/en/`. To artikler lenkes som oversettelser når de har samme `translationKey`.

## To flagg, to beslutninger

Publisering og automasjon er to forskjellige beslutninger, og derfor to forskjellige felt.

| Felt | Når det er `true` | Endres av |
|---|---|---|
| `draft` | Artikkelen holdes utenfor produksjonsbygget | Forfatteren, med `./publish.sh ready` |
| `auto_enrich` | Manglende metadata kan genereres gjennom Anthropic API | Forfatteren; pipelinen setter det til `false` etter et gyldig resultat |
| `auto_translate` | Et utkast på det andre språket er bestilt | Forfatteren; nullstilles når utkastet finnes |

Ingen av flaggene endrer det andre. En artikkel med `draft: false` og ufullstendig metadata feiler i valideringen i stedet for å bli publisert med hull.

## Hva som skjer ved en push

![Stegene i pipelinen fra en pushet commit til et deployet nettsted og utkast til sosiale medier](pipeline.svg "Stegene kjører i én workflow-kjøring; en feil stopper alt som kommer etter.")

Den samme sekvensen, som et diagram rendret fra tekst:

```mermaid
flowchart LR
  A[Push til main] --> B[Behandle innhold]
  B --> C[Commit genererte filer]
  C --> D[Bygg og deploy]
  D --> E[Utkast til SoMe]
```

Genererte filer committes tilbake med en melding som inneholder `[skip ci]`, og den samme kjøringen fortsetter med å bygge og deploye akkurat den commiten. Hvis noen andre har pushet i mellomtiden, stopper kjøringen i stedet for å overskrive arbeidet deres.

## De daglige kommandoene

```bash
./publish.sh new "min-artikkel" no
./publish.sh preview
./publish.sh ship "Publiser artikkelen"
```

En ny artikkel starter som utkast. Å markere den som klar er et bevisst steg:

```bash
./publish.sh ready content/no/posts/2026-11-13-min-artikkel/index.md
```

## Hva som ikke er automatisert

Utkast til LinkedIn og X skrives etter en vellykket deploy og lagres som workflow-artefakter. Ingenting postes til noen av plattformene. En oversatt artikkel opprettes alltid som utkast og publiseres først etter gjennomgang.
