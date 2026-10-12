# Guide Verification

The guides use synthetic inputs and released software. Each command is checked
from a new directory with fresh caches. No real prompts, user records or API
credentials are needed.

The current command manifests were refreshed for fleetdiff v0.8.0 on
October 11, 2026. The historical offline-analysis evidence below retains its
v0.7.0 scope. The v0.8.0 release also passed the
[packaged offline smoke](https://github.com/llm-measurement/fleetdiff/actions/runs/38200307889)
on Linux amd64 and arm64. An anonymous local check verified the released Linux
arm64 archive and reran `scripts/restricted-smoke.sh` from v0.8.0 with all seven
command checks passing.

| Guide | Released program | Input and reference |
| --- | --- | --- |
| Cardinality | fleetdiff v0.8.0 | `examples/diagnose/unsafe.yaml` from the v0.8.0 tag; expected exit 3 |
| Token spike | fleetdiff v0.8.0 | Checked-in `examples/sessions/data` from the v0.8.0 tag; expected exit 0 |
| Tokenmaxxing | PyPI llm-sketchkit 0.3.0 | One synthetic week of reported tokens for 60 people, defined in the page's command; expected exit 0 |
| LiteLLM spend | fleetdiff v0.8.0 | `examples/litellm-spend/synthetic.csv` from the v0.8.0 tag; headline, keyed contributors and completeness; expected exit 0 |
| Session budget | fleetdiff v0.8.0 | `examples/litellm-spend/session-budget.csv` from the v0.8.0 tag; observed session totals, cap review, counter sharing and duration; expected exit 0 |
| Cache check | fleetdiff v0.8.0 | `examples/litellm-spend/cache-drop.csv` from the v0.8.0 tag; cache-read/write shares and keyed uncached-input growth; expected exit 0 |
| Anomalies | fleetdiff v0.8.0 | `examples/scan` generator from the v0.8.0 tag; fixed reference time; expected exit 3 |
| Trace check | fleetdiff v0.8.0 | Shipped `examples/inspect/synthetic-traces.json` from the v0.8.0 tag; synthetic OTLP usage and identity fields, no Go generator; expected exit 0 |
| Distinct users | PyPI llm-sketchkit 0.3.0 | Four synthetic events, three distinct IDs, defined in the page's command |

The fleetdiff v0.8.0 tag resolves to `44967bd743a6fa26588742f67c54df6e323e90e0`.
The installer checks the binary and checksum-file attestations before extraction.
Collector links describe v0.3.2 configuration and chart 0.3.4; these guide commands do not start
a collector or claim a live Prometheus series measurement.

The reproduction command is:

```sh
python3 scripts/outsider.py --output evidence/local
```

The checker extracts commands and output excerpts directly from the page sources,
checks exit codes, and requires each output excerpt to occur in the saved stdout.
Trailing whitespace is ignored; numbers and wording must match. It saves output,
machine details, command digests and results under the ignored output directory.

The recorded local check uses macOS arm64 and Go 1.26.9 for the anomaly fixture generator.
The LiteLLM spend, session-budget, cache-check and trace-check commands use the released binary without Go.
The cache example checks recorded arithmetic and coverage, not provider cache behavior,
cause diagnosis or billing impact.
This is a functional example check, not a throughput or anomaly-accuracy study.
The checked-in `verified.json` records the run without local paths or credentials.

## Own-data commands

Every guide and the homepage put the operator's input path first. Run the exact
published commands with synthetic files placed at those paths:

```sh
python3 scripts/check.py --own-data --output evidence/local/own-data
```

This requires Docker for an isolated Postgres fixture as well as the tools named
on the pages. The SQL command connects through real psql as a SELECT-only role;
the test transports psql through Docker, rather than replacing it with a stub.
Each page gets a fresh directory and caches. Fixture source is anonymously cloned
at the release tag; the visitor's install/analyze blocks never clone a repository.
The scan fixture is shifted to recent complete windows while preserving canonical
summary serialization. Private sentinel identities must stay out of output.
The installer checks run with `GH_TOKEN` and `GITHUB_TOKEN` removed and a fresh
`GH_CONFIG_DIR`: gh must be installed but need not be signed in. The LiteLLM path
exports first, installs next, and investigates that same exported file.
`own-data-verified.json` binds the 17 successful command blocks to their source
hashes and records the released fixture commit. CI reruns these checks.

## Manual release checks

With trusted gh and Cosign installations, execute the security page's exact
manual verification blocks:

```sh
python3 scripts/check.py --release-review --output evidence/local/release-review
```

The recorded check used gh 2.69.0 and Cosign 3.1.3. It downloads and verifies
fleetdiff v0.8.0, the collector v0.3.2 image and chart 0.3.4 with fresh credential
configuration. No container is started or cluster changed by these blocks.
`release-review-verified.json` binds the commands to the successful check. The
default site check rejects stale own-data or manual-verification command records.

## Offline analysis evidence

The production code under `cmd/` and `internal/` is unchanged between fleetdiff
v0.7.0 (`25694f060c01af075a612b2ec1c67482a9c6c695`) and merged guard commit
`d44056043628c421c6bb190b1a23e8665be92169`. In a fleetdiff checkout, this command
prints nothing; the same comparison with `--exit-code` also exits 0:

```sh
git diff --stat v0.7.0 d44056043628c421c6bb190b1a23e8665be92169 -- cmd internal ':(exclude)*_test.go'
```

On October 11, 2026, the offline smoke at that merged commit also passed against
the exact released `fleetdiff_v0.7.0_linux_arm64.tar.gz`, not a rebuilt binary.
Before extraction, GitHub CLI verified the archive and SHA256SUMS attestations
against the release workflow, repository and `refs/tags/v0.7.0`, with self-hosted
runners denied; the archive then passed its SHA-256 check. Verification used
anonymous access and a fresh gh configuration.

To repeat, use the download, attestation and checksum portions of the
[manual verification steps](https://llm-measurement.github.io/security.html#verify-fleetdiff)
with `os=linux` and `arch=arm64`. The harness handles extraction and execution
inside Docker. From a fleetdiff checkout at
`d44056043628c421c6bb190b1a23e8665be92169`, run the following with
`VERIFIED_ARCHIVE` set to the absolute path of that verified archive. The harness
requires Go 1.26.9, Docker, jq and tar; the recorded run used Docker Desktop's
native Linux/arm64 VM on macOS arm64.

```sh
sh scripts/restricted-smoke.sh "${VERIFIED_ARCHIVE:?set the verified archive path}" linux/arm64
```

The route probe confirmed bridge routing was available and `--network none`
returned `ENETUNREACH`. All six cases had identical exit status, stdout and stderr:
compare, investigate (summaries), investigate (LiteLLM spend), inspect, diagnose
and scan. Scan returned the expected 3; the other cases returned 0.
[`offline-verified.json`](offline-verified.json) records the commits, artifact
hashes, verification constraints and results. This released-binary run covers
Linux arm64; the earlier built-binary checks covered Linux arm64 and amd64.
