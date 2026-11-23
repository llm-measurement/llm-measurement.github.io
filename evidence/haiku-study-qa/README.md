# Haiku And Sonnet Study QA

November 20 review delta: responsive chart and table checks pass in Chrome.
The source remains the unchanged v6 text. Refreshed Safari QA is pending;
the earlier Safari captures do not qualify this revision.

## Charts And Tables

The two inline layouts use the same two JSON inputs and identical numeric
rows. The narrow layout places each pair label above its bars, labels every
bar end, and splits the legend across two lines. At 320 and 390 px every
bar, value and chart label is visible without horizontal scrolling. Both
downloadable SVGs remain available and all chart classes use the cr- prefix.
Each layout has its own accessible title and description IDs.

Study tables use fixed tracks, wrapped headers and tighter padding on narrow
screens. All original headings and cell text are retained. Both tables in
this article and the cache study's existing HTML table fit at 320 and 390 px.
The reviewed tree contains one HTML table in the cache study, not two; its
code and SQL output remain locally scrollable.

## Reproduction And Checks

The [converter self-check](converter-PASS-v6.txt) binds the unchanged source,
both exact SVGs and the fragment. The [21-file manifest](../cheaper-study-manifest.json)
pins all evidence and both shared replay dependencies.
[RUN.md](../../assets/cheaper-model-evidence/RUN.md) gives the commands and
hashes for both chart layouts, all five JSON results, both generated exports
and all three published v0.15.0 outputs. The evidence prose records dates,
release identities, commands and hashes, without review or publication tasks.
The [fresh reproduction record](review-delta/reproduction.json) confirms all
11 sequential runs and 19 literal manifest entries, including both SVGs.

Local checks: 279 site tests (seven environment-dependent skips), 24 private
converter tests, 14 dependency-free interaction tests and five summary
evidence tests pass. Site, summaries and the second-study checkers pass.
The built article head and all scientific JSON/text results are unchanged.
The November 20 pricing and bounded citation records remain in
[citations.json](citations.json). No provider calls or local Docker run.

## Chrome Matrix

Machine: Apple M4 Max, macOS 27.0.1, installed Google Chrome 155.0.8059.80.
The site stays light-only under either user preference. All 60 page/viewports,
225 keyboard copies and 531 path-only events pass with no completed external
request. Browser checks now reject chart text outside the SVG, hidden table
columns and overflowing cell text. The baseline is the full commit
2b51843a5862acde3e9b45152ecda98cc426a2dc.

| Width | New Study Light | New Study Dark Preference | Cache Study Light | Cache Study Dark Preference |
| --- | --- | --- | --- | --- |
| 1366 | [View](review-delta/chrome/haiku-sonnet-100k-cliff-1366-light-preference.png) | [View](review-delta/chrome/haiku-sonnet-100k-cliff-1366-dark-preference.png) | [View](review-delta/chrome/prompt-cache-bills-1366-light-preference.png) | [View](review-delta/chrome/prompt-cache-bills-1366-dark-preference.png) |
| 390 | [View](review-delta/chrome/haiku-sonnet-100k-cliff-390-light-preference.png) | [View](review-delta/chrome/haiku-sonnet-100k-cliff-390-dark-preference.png) | [View](review-delta/chrome/prompt-cache-bills-390-light-preference.png) | [View](review-delta/chrome/prompt-cache-bills-390-dark-preference.png) |
| 320 | [View](review-delta/chrome/haiku-sonnet-100k-cliff-320-light-preference.png) | [View](review-delta/chrome/haiku-sonnet-100k-cliff-320-dark-preference.png) | [View](review-delta/chrome/prompt-cache-bills-320-light-preference.png) | [View](review-delta/chrome/prompt-cache-bills-320-dark-preference.png) |

[320 px chart](review-delta/chrome/haiku-sonnet-100k-cliff-320-chart-light.png) ·
[320 px session table](review-delta/chrome/haiku-sonnet-100k-cliff-320-table-1-light.png) ·
[320 px cache table](review-delta/chrome/prompt-cache-bills-320-table-0-light.png)

## Safari And Publication Status

The earlier screenshots and measurements in safari/ are historical evidence
for head 2791dc3, not proof of this responsive revision. The requested fresh
1366/390/320 light/dark Safari matrix has not run. It must be completed
before merge.

[HEAD.html](HEAD.html) is unchanged: canonical, OG/article/Twitter metadata,
one BlogPosting with author Vijay, one supplied Plausible snippet and the
normal privacy footer. Dates are preview placeholders; publication staging
derives the actual mainline introduction/modification timestamps.

Claude re-reviews the exact updated head. Final wording and Vijay's preview
and merge approval remain separate. No merge, deployment or IndexNow
submission occurred. Both live study gates still precede indexing.
