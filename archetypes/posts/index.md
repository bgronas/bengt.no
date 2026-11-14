---
title: "{{ site.Params.new.title | default (replaceRE `^\d{4}-\d{2}-\d{2}-` "" .File.ContentBaseName | replaceRE "-" " " | strings.FirstUpper) }}"
date: "{{ site.Params.new.date | default (.Date | time.Format "2006-01-02T15:04:05-07:00") }}"
lastmod: "{{ site.Params.new.date | default (.Date | time.Format "2006-01-02T15:04:05-07:00") }}"
draft: true
slug: "{{ site.Params.new.slug | default (replaceRE `^\d{4}-\d{2}-\d{2}-` "" .File.ContentBaseName) }}"
translationKey: "{{ site.Params.new.key | default (replaceRE `^\d{4}-\d{2}-\d{2}-` "" .File.ContentBaseName) }}"
auto_enrich: true
auto_translate: false
summary: ""
math: false
mermaid: false
featured: false
description: ""
keywords: []
categories: []
tags: []
series: []
series_order: null
social:
  enabled: true
  language: "inherit"
  regenerate: false
---

