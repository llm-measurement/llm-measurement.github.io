# Reproduce The Summary Measurements

Review draft. Run from a fresh copy of this directory outside a synced folder.
The scripts use released sketchkit and the pinned collector's event-time replay.
They create local reference files that include released pseudonyms: keep the
generated `data/`, `evidence/` and analyst directories local. No dataset rows,
generated summary windows, private report or forecast backtests are shipped here.

## Machine And Scope

The original measurements used Apple M4 Max, Darwin 27.0.0 arm64, Go 1.26.9,
Python 3.11.14, and Go/Python sketchkit 0.2.2. Timing and heap values are one
machine's measurements. Exact counters, serialized sizes and seeded synthetic
checks can be compared; timings and retained-heap deltas are not equality gates.

The source files are the experiment's existing measurements, not new accounting
or sketch implementations. The raw oracle validates counters and sets; only the
collector creates accounting summaries. B5's public reproduction stops at the
summary-derived series; forecast backtests and their outputs remain out of this
bundle. It rechecks that sharing boundary and does not claim to reproduce the
original full analyst-output file count.

## Setup And Input Pins

Use Go 1.26.9 and Python 3.11. The Python lock is for the original arm64 macOS
environment. This experiment uses a public test key, not a production secret.

```sh
mkdir -p data evidence
python3.11 -m venv venv
venv/bin/python -m pip install --require-hashes -r requirements.lock
git clone https://github.com/llm-measurement/otelcol-genai-sketches.git collector
git -C collector checkout --detach 32bd078e61fefa7294d6d4748a3db4e1aa562994
cp -R go/phase0-replay go/phase0-scale collector/connector/genaisketchconnector/cmd/
export GOWORK=off
export GOCACHE="$PWD/go-build"
export GOMODCACHE="$PWD/go-mod"
export GENAI_SKETCH_SECRET=forecast-phase0-public-test-key-20261010
go -C collector/connector/genaisketchconnector build -tags tracelab_replay -o "$PWD/replay" ./cmd/phase0-replay
go -C collector/connector/genaisketchconnector build -o "$PWD/scale" ./cmd/phase0-scale
curl -fL https://github.com/uw-syfi/TraceLab/releases/download/v0.0.2/syfi_coding_trace.jsonl.gz -o data/syfi_coding_trace.jsonl.gz
curl -fL https://github.com/HPMLL/BurstGPT/releases/download/v2.0/BurstGPT_1.csv -o data/BurstGPT_1.csv
curl -fL https://github.com/HPMLL/BurstGPT/releases/download/v2.0/BurstGPT_2.csv -o data/BurstGPT_2.csv
curl -fL https://raw.githubusercontent.com/uw-syfi/TraceLab/61fea8f97277d0aa247cc2e4c7e31f90ed2bea1c/LICENSE-DATASET.md -o data/TraceLab-LICENSE-DATASET.md
curl -fL https://raw.githubusercontent.com/HPMLL/BurstGPT/7eb2c4f8350f8a6985272386f5c14af1f678b299/LICENSE -o data/BurstGPT-LICENSE.txt
venv/bin/python scripts/data_audit.py --fetch-sources
venv/bin/python scripts/data_audit.py
```

Both the audit and replay verify these SHA-256 values before processing:

| Asset | SHA-256 |
| --- | --- |
| syfi_coding_trace.jsonl.gz | `11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65` |
| BurstGPT_1.csv | `4bb3783693d0a435686fbfc885615d2349bd067239079fa4b749f2e679e12122` |
| BurstGPT_2.csv | `44bf5942b03fca42c01a226a545ad3a750ec62688faecd67b6831c56a8928bf7` |

See [ATTRIBUTION.md](ATTRIBUTION.md) for the pinned licenses and modifications.
No provider keys, database access or paid calls are involved.

## Combined Users, History And Contributors (B1, B2, B4)

```sh
./replay --dataset tracelab --data data --out data/tracelab-summaries
./replay --dataset burstgpt --data data --out data/burstgpt-summaries
venv/bin/python scripts/features.py
venv/bin/python scripts/sketch_experiments.py
```

Output directories must be new. `features.py` checks all available counter
totals against the raw oracle before continuing. Compare the B1, B2 storage and
B4 fields in `evidence/sketch-results.json` with
[recorded/sketch-results.json](recorded/sketch-results.json); query timings vary.
The report's daily sketch/list byte comparison rounds their means to whole bytes.
The combined user counts are in `evidence/data-audit.json`.

The constant prompt ranking is an accounting-group test key, not a real prompt
count. MinHash is measured as a separate library primitive; the collector does
not export that user-overlap sketch. No user-MinHash product feature is implied.

## Synthetic Scale (B3)

The reservoir samples successful BurstGPT request weights with the fixed seed.
Each synthetic identity occurs once, then additional Zipf(1.2) events are added.
There is no forecasting claim from the synthetic workload.

```sh
venv/bin/python -c 'import json; from pathlib import Path; source=json.loads(Path("data/oracle.json").read_text()); Path("data/weights.json").write_text(json.dumps(source["burstgpt"]["success_weight_sample"]))'
for seed in 20261010 20261011 20261012; do
  ./scale data/weights.json "evidence/scale-isolated-1000000-$seed" 1000000 "$seed"
done
```

Compare the serialized HLL plus frequent-items byte total and top-20 recall
with [recorded/scale.json](recorded/scale.json). Inspect every run, not just the
best one. Full state size excludes the enclosing summary JSON and process RAM.

## Summary-Only Analyst And Field Exclusion (B5)

The following is macOS-specific. `sandbox-exec` adds an OS restriction; a
restricted shell may need permission to install it. Do not silently remove the
restriction. The validator runs separately with access to reference identifiers.

```sh
mkdir -p analyst-inputs/tracelab analyst-inputs/burstgpt
cp -R data/analyst/tracelab/platform-claude data/analyst/tracelab/platform-codex analyst-inputs/tracelab/
cp -R data/analyst/burstgpt/model-ChatGPT data/analyst/burstgpt/model-GPT-4 analyst-inputs/burstgpt/
PHASE0_SENTINEL_DIR="$PWD/data/sentinel" go -C collector/connector/genaisketchconnector test -tags tracelab_replay ./cmd/phase0-replay -run TestSentinelSummaryOnly -v
venv/bin/python scripts/isolated_analyst.py
venv/bin/python scripts/privacy_audit.py
```

The isolation runner first requires raw-file reads and local network access to
fail under the policy, then runs the analyst under the same policy. The analyst
uses a fixed producer/day roster. The scanner checks both serialized and decoded
values and tests itself with known plain and encoded leaks. Zero known-pattern
hits establish field exclusion for this artifact set, not anonymity or resistance
to all forms of inference. Keyed identifiers and aggregate activity remain visible.
