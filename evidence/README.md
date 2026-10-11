# Guide Verification

The guides use synthetic inputs and released software. Each command is checked
from a new directory with fresh caches. No real prompts, user records or API
credentials are needed.

| Guide | Released program | Input and reference |
| --- | --- | --- |
| Cardinality | fleetdiff v0.5.0 | `examples/diagnose/unsafe.yaml` from the v0.5.0 tag; expected exit 3 |
| Token spike | fleetdiff v0.5.0 | Checked-in `examples/sessions/data` from the v0.5.0 tag; expected exit 0 |
| Tokenmaxxing | PyPI llm-sketchkit 0.2.2 | One synthetic week of reported tokens for 60 people, defined in the page's command; expected exit 0 |
| LiteLLM spend | fleetdiff v0.6.0 | `examples/litellm-spend/synthetic.csv` from the v0.6.0 tag; headline, keyed contributors and completeness; expected exit 0 |
| Anomalies | fleetdiff v0.5.0 | `examples/scan` generator from the v0.5.0 tag; fixed reference time; expected exit 3 |
| Distinct users | PyPI llm-sketchkit 0.2.2 | Four synthetic events, three distinct IDs, defined in the page's command |

The fleetdiff v0.5.0 tag resolves to `b214e8466291879aa7862f7d26875778ee20ea95`;
v0.6.0 resolves to `d47787238fa657f585d461260581f503eaa01d10`.
The installer checks the binary and checksum-file attestations before extraction.
Collector links describe v0.3.1 configuration; these guide commands do not start
a collector or claim a live Prometheus series measurement.

The reproduction command is:

```sh
python3 scripts/outsider.py --output evidence/local
```

The checker extracts commands and output excerpts directly from the page sources,
checks exit codes, and requires each output excerpt to occur in the saved stdout.
Trailing whitespace is ignored; numbers and wording must match. It saves output,
machine details, command digests and results under the ignored output directory.

The recorded local check uses macOS arm64 and Go 1.26.9 for the fixture generator.
This is a functional example check, not a throughput or anomaly-accuracy study.
The checked-in `verified.json` records the run without local paths or credentials.
