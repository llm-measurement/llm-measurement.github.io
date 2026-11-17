# Prompt Cache Study Checks

The approved article conversion passed:

```text
PASS: approved text, equations and all three code blocks unchanged
```

The verified fleetdiff v0.14.1 sample produced the complete saved stdout byte
for byte, including all four quoted lines and recorded spend of 1.944 to 0.402.
See [the rerun record](../../assets/cache-evidence/RERUN_v0.14.1.md) and
[the protected evidence inventory](../cache-study-verified.json). All 13 original
evidence files retain their original bytes. No provider calls were made for this
site build.

## Chrome

The installed Google Chrome was checked at 1366, 390 and 320 CSS pixels.
Native MathML, the SQL fold with pointer and Enter/Space, the fold with scripts
disabled, viewport overflow and local table/code scrolling passed. Analytics
and other external requests were blocked during QA without changing the HTML.
The [machine-readable record](chrome.json) binds the checked source bytes,
browser version, measured geometry and screenshots.

| Width | First View | Math | Open SQL Fold | Full Page |
| --- | --- | --- | --- | --- |
| 1366 | [Screenshot](chrome-1366-top.png) | [Screenshot](chrome-1366-math.png) | [Screenshot](chrome-1366-sql.png) | [Screenshot](chrome-1366.png) |
| 390 | [Screenshot](chrome-390-top.png) | [Screenshot](chrome-390-math.png) | [Screenshot](chrome-390-sql.png) | [Screenshot](chrome-390.png) |
| 320 | [Screenshot](chrome-320-top.png) | [Screenshot](chrome-320-math.png) | [Screenshot](chrome-320-sql.png) | [Screenshot](chrome-320.png) |

The existing all-page interaction suite also passes for 57 page/viewports,
225 exact keyboard-copy checks and 522 path-only analytics events with synthetic
private query and fragment markers. No external requests completed.

## Safari And Publication

Safari review is reserved for Vijay before merge. The native responsive-mode
inspection covered the three widths and pointer/Enter/Space disclosure behavior;
it is not claimed as the complete automated Safari matrix.

The [built head](head.html.txt) has provisional preview dates. Publication staging
replaces those dates with the article's actual mainline merge timestamps, in the
article metadata, JSON-LD and sitemap. Tests cover later edits and unchanged
rebuilds. The live article and evidence must pass the anonymous outsider check
before the existing IndexNow submission. Neither deployment nor submission is
performed by preparing this PR.
