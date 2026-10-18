# LLM Measurement Guides

Twelve guides to LLM usage, with commands and output from released tools.
An evidence page explains what can be shared and retained with summaries.

Current command examples pin fleetdiff v0.11.0. The home-page library installs
pin llm-sketchkit v0.4.0; the existing Python guides retain v0.3.0. Collector
configuration pins v0.6.0 and Helm chart 0.6.0. Historical evidence
retains the versions and source revisions used for those measurements.

| Question | Page |
| --- | --- |
| Which user is driving my LLM token spike? | [Token spike](docs/token-spike.html) |
| Who is tokenmaxxing? Find your heaviest AI token users | [Tokenmaxxing](docs/tokenmaxxing.html) |
| Why did our LiteLLM usage jump, and are the spend logs complete? | [LiteLLM spend](docs/litellm-spend.html) |
| Are all our requests actually in the spend log? | [Row coverage](docs/row-coverage.html) |
| Which models served each LiteLLM route? | [Routing audit](docs/routing.html) |
| What would switching models have cost? | [Model what-if](docs/what-if.html) |
| LiteLLM session over its budget? Check what the budget counts | [Session budget](docs/session-budget.html) |
| Prompt cache hit rate dropped after an update? Find whose uncached input grew | [Cache check](docs/cache-check.html) |
| How do I see LLM usage per user without a metric label for every user? | [Per-user metrics](docs/cardinality.html) |
| How do I detect anomalies in LLM token consumption? | [Anomalies](docs/anomalies.html) |
| Do my LLM traces record token usage and user IDs? | [Trace check](docs/traces-usage.html) |
| How do I count distinct LLM users without storing user IDs? | [Distinct users](docs/distinct-users.html) |
| Why summaries instead of raw logs | [Summaries](docs/summaries.html) |

## Build And Check

Requires Python 3.11 or later. The static-site builder uses only the standard library.

```sh
python3 scripts/build.py
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/check.py
```

Open `docs/index.html` in a browser. The site uses Plausible for visitor analytics.
The guides are static HTML and require no account or external fonts to read.

The [outsider check](scripts/outsider.py) extracts the exact command blocks from
each guide, runs them in separate new temporary directories with fresh caches,
and checks the displayed output against the captured output. It downloads public
release artifacts and verifies the fleetdiff checksums and attestations.
It needs curl, gh, shasum, tar, Python 3.11+, and Go 1.26.9 or later for the
synthetic history generator. Run it outside a cloud-synced folder:

```sh
python3 scripts/outsider.py --output evidence/local
```

Machine, versions, source tags, methods and commands for the checked examples
are recorded in [evidence/README.md](evidence/README.md).

## Publishing

The generated `docs/` directory is ready for branch-based GitHub Pages hosting.
Enable it only after the page text has been reviewed and merged. Sitemap and
canonical URLs use `https://llm-measurement.github.io/`; they become live on
publication. This scaffold does not enable hosting or change repository settings.

Change the source pages, rebuild, and check the generated diff in the same PR.
The public Google verification file at the repository root is copied unchanged
into `docs/`, outside the generated-assets cleanup, for Search Console verification.
Keep results tied to released versions. Each guide keeps a short interpretation
line linked to the shared Measurement notes section on the summaries page.
Commits must be signed and signed off (`git commit -s -S`).

Licensed under Apache-2.0. The sessions image comes from fleetdiff under the same license.
