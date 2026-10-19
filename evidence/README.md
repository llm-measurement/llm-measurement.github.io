# Guide Verification

The guides use synthetic inputs and released software. Each command is checked
from a new directory with fresh caches. No real prompts, user records or
model-provider credentials are needed. The manual collector provenance check
uses GitHub authentication as described below.

The current manifests record fresh full runs of all 12 samples and all 41
own-data command blocks on October 19, 2026 (UTC), using published fleetdiff
v0.12.0, plus three executable configuration checks described below. Earlier
targeted checks are historical, not substituted for the final full run. The homepage installs
sketchkit v0.4.0 in Python and Go; the existing Python guides retain their checked
v0.3.0 examples. These site command checks ran on macOS arm64 against the released
binary, not a local rebuild. The historical offline-analysis evidence below
retains its v0.7.0 scope; it is not relabeled as a check of later production code.

The later prose pass rechecked all twelve samples, 41 own-data commands and three
configuration blocks. The prose checker rejects the removed phrases throughout
all twelve guides, including folded/sample text, and enforces the reviewed
installer wording and the manual-verification link's footer location.
Each guide stays within 250 visible words before the sample for LiteLLM spend,
routing and row coverage, or 200 for the other nine. Counts include H1s, path
links and visible commands; closed details contribute only their summaries.
The source counts match the browser's rendered text across all 72 guide views.

The final publication pass uses plain `BEFORE`, `AFTER`, `ROUTE` and `PERIOD`
variables with setup text beside each command. All 41 own-data commands and
105 tests passed, including real PostgreSQL regressions, with no skips.

| Guide | Released program | Input and reference |
| --- | --- | --- |
| Cardinality | fleetdiff v0.12.0 | `examples/diagnose/unsafe.yaml` from the v0.12.0 tag; expected exit 3 |
| Token spike | fleetdiff v0.12.0 | Checked-in `examples/sessions/data` from the v0.12.0 tag; expected exit 0 |
| Tokenmaxxing | PyPI llm-sketchkit 0.3.0 | One synthetic week of reported tokens for 60 people, defined in the page's command; expected exit 0 |
| LiteLLM spend | fleetdiff v0.12.0 | `examples/litellm-spend/synthetic.csv` from the v0.12.0 tag; headline, keyed contributors and completeness; expected exit 0 |
| Row coverage | fleetdiff v0.12.0 | Released paired runtime CSVs: 8 spend rows versus 9 daily requests on October 7, then 1 versus 1; expected exit 0 |
| Routing audit | fleetdiff v0.12.0 | `examples/routing/synthetic.csv`; model shares, classifier overhead and missing Responses agents; expected exit 0 |
| Model what-if | fleetdiff v0.12.0 | `examples/what-if/spend.csv`; complete text matches `expected.text`, with the displayed whole-period range and excluded missing split; expected exit 0 |
| Session budget | fleetdiff v0.12.0 | `examples/litellm-spend/session-budget.csv` from the v0.12.0 tag; observed session totals, cap review, counter sharing and duration; expected exit 0 |
| Cache check | fleetdiff v0.12.0 | `examples/litellm-spend/cache-drop.csv` from the v0.12.0 tag; cache-read/write shares and keyed uncached-input growth; expected exit 0 |
| Anomalies | fleetdiff v0.12.0 | `examples/scan` generator from the v0.12.0 tag; fixed reference time; expected exit 3 |
| Trace check | fleetdiff v0.12.0 | Shipped `examples/inspect/synthetic-traces.json` from the v0.12.0 tag; synthetic OTLP usage and identity fields, no Go generator; expected exit 0 |
| Distinct users | PyPI llm-sketchkit 0.3.0 | Four synthetic events, three distinct IDs, defined in the page's command |

The fleetdiff v0.12.0 tag resolves to `6089061c931fa19fac876e40b3809fdea4792ab8`.
The installer checks the binary and checksum-file attestations before extraction.
Installer URLs pin `6089061c931fa19fac876e40b3809fdea4792ab8` and explicitly
request v0.12.0. Own-data checks require the installed version and source commit
to match the released fixture commit exactly.
`python3 scripts/check.py --release-pins` also resolves the tag anonymously and
checks every active fleetdiff commit URL in source and generated pages. The
build job runs this check; unavailable or mismatched tag resolution fails it.
It also reads the collector's public stable releases and advisories anonymously:
active pins must match the latest stable runtime and must not fall in an affected
range. Unavailable lookups and unsupported range syntax fail the check. The
offline check uses `collector-release-policy.json`, regenerated from the public
API by `python3 scripts/collector_pins.py --record evidence/collector-release-policy.json`.
Collector links pin v0.6.1 configuration and chart 0.6.1. The added configuration
checks execute the pinned collectors' validation subcommand; they do not start
receiver traffic or claim a live Prometheus series measurement.
Install-guide, configuration and source links use the same runtime tag.

The reproduction command is:

```sh
python3 scripts/outsider.py --output evidence/local
```

The checker extracts commands and output excerpts directly from the page sources,
checks exit codes, and requires each output excerpt to occur in the saved stdout.
Trailing whitespace is ignored; numbers and wording must match. It saves output,
machine details, command digests and results under the ignored output directory.

The recorded local check uses macOS arm64 and Go 1.26.9 for the anomaly fixture generator.
The LiteLLM spend, row-coverage, routing, what-if, session-budget, cache-check and trace-check commands use the released binary without Go.
The cache example checks recorded arithmetic and coverage, not provider cache behavior,
cause diagnosis or billing impact.
This is a functional example check, not a throughput or anomaly-accuracy study.
The checked-in `verified.json` records the run without local paths or credentials.

## Own-data commands

Every guide and the homepage put the operator's data first. LiteLLM spend,
routing and row coverage lead with native database investigation; routing adds
`--routing-audit` and row coverage adds `--daily`.
Run the exact published commands with synthetic inputs:

```sh
python3 scripts/check.py --own-data --output evidence/local/own-data
```

This requires Docker for a cached digest-pinned Postgres fixture as well as the
tools named on the pages. Containers use `--pull=never --network=none`; a missing
image fails the check. Fresh machines must first cache the exact image listed
in the [released fixture manifest](https://raw.githubusercontent.com/llm-measurement/fleetdiff/6089061c931fa19fac876e40b3809fdea4792ab8/examples/litellm-spend/images.json);
the own-data CI job explicitly pulls that digest before the runtime check.
This local verification reused the existing image and did not pull a new one.
Native commands run the unchanged installed host binary
through a loopback byte transport to real PostgreSQL, not a database mock.
The fixture applies the documented native role grants and verifies read-only
defaults, access to projected columns, and no message-column or INSERT access.
The manual SQL command connects through real psql as a SELECT-only role;
the test transports psql through Docker, rather than replacing it with a stub.
Each page gets a fresh HOME, directory and caches. Fixture source is downloaded
anonymously as an archive at the immutable release commit; the installer and
analysis commands need no Git checkout. The paired coverage helper runs unmodified
inside the network-isolated container so its two inherited output descriptors
remain separate. The test checks both complete CSV exports against the seeded
fixtures and verifies the SELECT-only role on both tables. This is a projection
and command check, not another LiteLLM writer or load experiment.
The scan fixture is shifted to recent complete windows while preserving canonical
summary serialization. Private sentinel identities must stay out of output.
The installer checks run with `GH_TOKEN` and `GITHUB_TOKEN` removed and a fresh
`GH_CONFIG_DIR`: gh must be installed but need not be signed in. The LiteLLM path
installs first, then checks both an owned mode-0600 credential file and the
dedicated environment variable against the real database. Both produce identical
aliased reports. Clock-relative native fixtures follow the last 14 complete UTC days; an
intervening UTC midnight fails the run rather than changing its reference window.
The what-if native block instead retains its explicitly selected historical period.
All nine native blocks require actual database traffic and temporary-export cleanup.
The daily mode also verifies column-only read access to the daily table and
reports the planted 8-row versus 9-request discrepancy. Native fixture dates
shift start and end timestamps together, preserving cross-midnight durations.
The routing path checks native audit, route-agent JSON and route scope, plus the
manual opt-in SQL projection against all eight seeded rows and the file audit.
Missing agent and cache fields stay missing, and private sentinel labels stay
out of reports.

The manual spend alternative explicitly exports September 23 through October 9,
2026 (exclusive), a 16-day interval. Its subsequent file investigation excludes
potentially partial edge days. The harness executes those visible bounds, not a
larger hidden fixture interval. A real-PostgreSQL regression using the verified
released binary separately confirms 160 exported rows succeed, while a shortened
14-day, 140-row export fails the same file-default investigation. This does not
change native mode's clock-based 14-complete-day default.

`own-data-verified.json` binds all 41 successful command blocks to their source
hashes and records the released fixture commit, native transport counts, role
checks and installed binary versions. CI reruns these checks.

### Earlier LiteLLM page rewrite check

The targeted rewrite check reran the five LiteLLM own-data blocks, the environment
credential block moved to security, and the LiteLLM sample with every displayed
excerpt matched. Security executes the linked installer as a recorded dependency
and compares the file and environment credential commands against the same
synthetic database. The file path is exactly `~/.config/litellm-db-url`; no command
text is rewritten. The existing-file command reads `./spend.csv`, while the
separate export-file command reads the actual psql-produced CSV. Both explanatory
comments in the manual export block were included in its executed hash.

Both displayed administrator SQL blocks were decoded from the page, checked
against the released statements, and executed unchanged in a real database named
`litellm`. Checks verify all 21 permitted spend columns, denial of the three
content columns, the four optional daily columns, and absence of table-wide
SELECT, writes, privileged role flags, memberships and schema/database CREATE
privileges. Their exact command hashes and results are nested under
`litellm-native`'s `database.sql_blocks`. PostgreSQL reused the cached pinned image
with `--pull=never --network=none`; no new image or Git checkout was used.

That earlier targeted refresh retained 27 other own-data records and 11 other
sample records. The current manifests supersede it with fresh full runs.
The 13 native/database regression tests also passed, including the shortened
14-day export failure. The anonymous fleetdiff manual release block was rechecked;
the unchanged collector OCI verification retains its earlier authenticated result.

### Final guide command checks

The routing and row-coverage commands separately exercise existing stand-in
files and the actual SQL-produced exports. Each exported dataset is compared
with its seeded rows; the reports from both paths must be identical. Historical
file fixtures and clock-relative native fixtures are selected per block, so a
later native command cannot accidentally reuse the file example's periods.
The row page's exact daily SQL is executed after the shared LiteLLM reader grant;
both hashes are recorded under `row-coverage-native.database.sql_blocks`.

The session-budget, cache-check and what-if native commands use the exact
`~/.config/litellm-db-url` path. Their synthetic database rows preserve session
and agent IDs, cache and reasoning fields, and missing-versus-zero distinctions.
The planted session-budget failure matches every discriminator in the released
SQL projection and remains one recorded rejection. This is a reader/command
check using synthetic metadata, not a new LiteLLM failure-writer experiment.

The token-only what-if fixture has no recorded-spend field. Its database fixture
deliberately assigns a synthetic USD 1 per row to satisfy the required database
column; the complete report still must equal the released reference based on
token prices. This checks that repricing does not use recorded spend. The file
fixture's tokens and missing splits remain unchanged.

The final Python suite passed all 101 tests with no skips, including the gated
real-PostgreSQL checks and the retained shortened-export rejection. The static
site check also passed with all command, SQL, configuration and visual bindings.

### Published configuration checks

The three `data-config` blocks have separate `config_records` in the own-data
manifest. Each record binds the exact decoded page text with `config_sha256`.
The workload-map JSON is written byte-for-byte to `workload-map.json`, with mode
0600. Only the synthetic CSV identities are adapted to match the published
placeholder IDs. The released CLI consumes that file; checked covered/excluded
counts, prices and zero unmapped moved observations must still match.

The two YAML fragments are inserted unchanged into minimal complete collector
configurations. The cardinality fragment connects a local OTLP receiver through
genaisketch to Prometheus. The file exporter is added alongside a retained debug
exporter. Actual pinned collectors run `validate` with `--pull=never`,
`--network none`, a read-only root filesystem, no capabilities, and synthetic
test-only hashing material. Both configurations must pass; an invalid connector
weight and an unknown file-exporter setting must be rejected by the respective
collector. Logs and hashes bind both cases. No receiver traffic is sent and no
trace capture or ranking output is claimed.

CI explicitly caches these two collector images in addition to the existing
PostgreSQL digest before executing the full own-data suite:

```sh
docker pull ghcr.io/llm-measurement/otelcol-genai-sketches@sha256:b17b3489b65c27a622402982e8e61ee44c7ada247ff3168efacc63a3867c7818
docker pull otel/opentelemetry-collector-contrib@sha256:fd328de2552466ad78385e1b1289c3f2402b1c45f265b252aab1955b42845ac1
```

The local run reused cached images without downloading new ones. The published
v0.6.1 OCI index is retained as public test data in
`scripts/collector-v061-index.json`; its bytes, excluding the file's final newline,
must hash to the pinned index digest before a cached platform child can be used.
The manifest distinguishes the declared `image` from the actual
`runtime_image` and records its architecture and removal after validation.

## v0.12.0 network boundary

File-based analysis stays offline, including when database credentials are
present in the environment. Only explicit `--litellm-db` and `export litellm`
modes connect to the chosen PostgreSQL server, with DNS resolution if needed;
installation separately downloads release artifacts. Native export uses a
read-only repeatable snapshot, private raw exports and aliased reports.
See the released [network guard](https://github.com/llm-measurement/fleetdiff/blob/v0.12.0/internal/cli/network_test.go),
[real-database checks](https://github.com/llm-measurement/fleetdiff/blob/v0.12.0/examples/litellm-spend/test_native_export.py)
and [TLS transport tests](https://github.com/llm-measurement/fleetdiff/blob/v0.12.0/internal/postgres/tls_test.go).
The site's synthetic database fixture uses explicit numeric-loopback plaintext;
it does not claim to test remote TLS. Remote native connections require
`sslmode=verify-full`, with no plaintext fallback. This v0.12.0 boundary is
separate from the historical v0.7.0 offline evidence below.

## Manual release checks

With trusted gh and Cosign installations, and gh signed in for the collector's
OCI provenance API checks, execute the security page's exact manual verification blocks:

```sh
python3 scripts/check.py --release-review --output evidence/local/release-review
```

The fleetdiff v0.12.0 and collector v0.6.1 / chart 0.6.1 manual checks both passed
on October 19, 2026 (UTC), using gh 2.69.0 and Cosign 3.1.3.
Downloads, fleetdiff
bundle verification and Cosign checks use anonymous access; collector OCI
provenance verification uses existing GitHub CLI credentials. Working directories,
caches and Docker credential configuration are fresh. No container is started or
cluster changed by these blocks.
`release-review-verified.json` binds the commands to the successful check. The
default site check rejects stale own-data or manual-verification command records.

The earlier full-suite check passed all twelve sample guides and 32 own-data
blocks. The current full run covers all 41 command blocks after the guide rewrites;
it does not relabel the earlier manual collector provenance check as a new run.

## Visual checks

The first rewrite passed 24 views across LiteLLM spend, routing, row coverage
and security. The final guide rewrite extends this to 78 views: all twelve
sample guides and security at 1366, 390 and 320 pixels, each in light and dark
mode. The path indexes are visible without scrolling at laptop width.
Each path link reached a visible
section on mobile, with security folded initially and no page-wide overflow.
The generated pages were checked in installed Chromium with external requests
blocked. `rewrite-visual-verified.json` binds these results to the page and CSS
hashes. Titles, descriptions and H1s are unchanged, and the twelve sample
commands and their checked output bytes are preserved.

The earlier collector 0.6.1 and native row-coverage update had 22 checked combinations:
homepage, LiteLLM spend, row coverage, cardinality and security at 1440- and
390-pixel widths, plus row coverage at 320 pixels, each in light and dark mode.
An exact generated-HTML snapshot ran in cached Chromium via Playwright with
external requests blocked. Images decoded, mobile navigation worked, and checks
found no page errors, content overlap or page-level horizontal overflow.
Intentional code-block scrolling remained reachable. The 110 screenshots and
source hashes are recorded in `visual-verified.json`. In that earlier batch,
the other pages changed version pins only.

Separately, the historical v0.11.0 visual check covered all 15 pages at 1280- and
390-pixel widths in light and dark modes, plus the homepage, routing, what-if and
security pages at 320 pixels: 68 views. That earlier result is retained as
historical evidence, not relabeled as 68 new v0.12.0 views. These checks cover
the guide site, not a Kubernetes rollout.

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
