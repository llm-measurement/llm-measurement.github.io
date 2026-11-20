# Haiku And Sonnet Study: Draft QA

PASS for the v6 preview build. This is not the final-text or merge approval.
The source words, currency, headings, links, alt text and both code blocks
match the source through the converter's independent text comparison.
See [converter-PASS-v6.txt](converter-PASS-v6.txt) for the source,
converter, fragment and chart hashes.

## Evidence And Prices

All 11 sequential nice-10 reproduction runs passed with empty stderr:
five JSON outputs, the SVG, two generated exports and three published
fleetdiff v0.15.0 outputs match their retained records byte for byte.
The original trace, replay helper, scripts and outputs were re-hashed
unchanged. The only script adjustment is the replay-helper directory in
`cached_session_cost.py`. The 20-file package and both shared dependencies
are pinned in [the manifest](../cheaper-study-manifest.json).

The [public reproduction guide](../../assets/cheaper-model-evidence/RUN.md)
has the exact commands and figure-to-field map, including the cache-write
split and one-hour-cache result. Full v0.15.0 stdout is preserved there.
The quoted repricing is $3,558.76 to $1,060.99, with 22,592 short-tier and
38,404 long-tier requests.

The November 20 re-read of Anthropic's official pricing page matches the
November 19 rates for Sonnet 5.5, Haiku 5.5 (both tiers), Opus 5.5 and
Fable 5.2. Prompt length includes cache reads and writes, each request is
priced independently, and the whole over-threshold request uses its higher
tier, including output. [Citation checks](citations.json) record seven
anonymous HTTP-200 fetches with the existing 2-MiB local / 8-MiB external
bounds. No trace download or provider call was made by those checks.

## Browser QA

Machine: Apple M4 Max, macOS 27.0.1. The existing site remains light-only,
as requested. Light and dark user preferences are both tested; no theme
toggle was added.

Chrome uses the installed Google Chrome binary, version 155.0.8059.80,
through the site's Playwright harness. All 20 pages at 1366, 390 and
320 pixels pass: 60 page/viewports, 225 exact keyboard copies and
531 path-only events, with every external request intercepted and zero
external requests completed. Existing pages retain their input-first
structure, palette, typography and published command blocks. The second
study's chart, tables and code scroll locally; its chart remains light
under both preferences. Full-page captures:

| Width | Chrome Light | Chrome Dark Preference | Safari Light | Safari Dark Preference |
| --- | --- | --- | --- | --- |
| 1366 | [View](chrome/haiku-sonnet-100k-cliff-1366-light.png) | [View](chrome/haiku-sonnet-100k-cliff-1366-dark-system.png) | [View](safari/1366-light-preference.png) | [View](safari/1366-dark-preference.png) |
| 390 | [View](chrome/haiku-sonnet-100k-cliff-390-light.png) | [View](chrome/haiku-sonnet-100k-cliff-390-dark-system.png) | [View](safari/390-light-preference.png) | [View](safari/390-dark-preference.png) |
| 320 | [View](chrome/haiku-sonnet-100k-cliff-320-light.png) | [View](chrome/haiku-sonnet-100k-cliff-320-dark-system.png) | [View](safari/320-light-preference.png) | [View](safari/320-dark-preference.png) |

Safari is the installed Safari 27.0.1, not Playwright WebKit. Native
Responsive Design Mode sets each exact width at height 768. Its detached
Web Inspector emulates light and dark user preferences; `matchMedia`
readbacks confirm each preference. [Measurements](safari/measurements.json)
confirm page scroll width equals viewport width at all six combinations,
local overflow boundaries, and the light chart fill. A separate
[scroll readback](safari/local-scroll-readback.json) moves all five local
scrollers to the right while page scrollX stays zero. Safari screenshots
capture the native responsive preview; Chrome captures the full article.

Safari originally rendered an external SVG dark on the light page. The
inline fallback is byte-identical to the downloadable SVG; scoped palette
rules keep it light in both browsers. Its source alt is retained as the
focusable figure's accessible label. The standalone evidence SVG still
has both of its original palettes. Safari preference emulation was reset
to System (Dark), the Inspector and owned preview window were closed,
and remote automation was left at its unchanged original enabled state.
No macOS appearance preference was changed.

## Checks And Publication Gate

- 277 site Python tests pass, with seven environment-dependent skips;
  the dependency-free interaction tests pass 14/14.
- The private converter tests pass 20/20.
- Site, summaries and new study checkers pass; summary-evidence tests
  pass 5/5. Existing article, sitemap, IndexNow and bounded/DOI citation
  regression tests remain enabled.
- Public-text scan of new page, evidence, QA records and source changes:
  no internal product name, surname, employer or machine paths.
- [Built head](HEAD.html): one H1, canonical/OG/article/Twitter fields,
  one BlogPosting with author Vijay, exactly one supplied Plausible
  snippet plus the normal privacy footer, and no other third-party
  resource. Dates here are preview placeholders; existing publication
  staging derives the actual mainline introduction and modification
  timestamps for head, JSON-LD and sitemap.

The brief mentions a text-view table below the chart, but v6 contains no
such table. The source is preserved; its chart has accessible title and
description, and the two supplied tables are unchanged.

Next: exact-head PR review, Vijay's final rewrite and preview approval.
Only after his merge go and deployment may the fresh-cache live checker
pass and IndexNow run. No merge, live deployment, release or IndexNow
submission is part of this draft build.
