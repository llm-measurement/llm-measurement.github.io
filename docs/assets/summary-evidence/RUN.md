# Reproduce The Summary Measurements

Run from a fresh copy outside a synced folder. The connector creates summaries;
exact reference tables validate their totals and bounds. Keep downloaded records
and generated identity tables local. Recorded versions and machine details are
in [recorded/run.json](recorded/run.json).

## Setup And Input Pins

Use Go 1.26.9 and Python 3.11 on macOS arm64, the recorded environment. The
Python lock covers those wheels. The experiment uses a public test key.

```sh
mkdir -p data evidence
python3.11 -m venv venv
venv/bin/python -m pip install --require-hashes -r requirements.lock
git clone https://github.com/llm-measurement/otelcol-genai-sketches.git collector
git -C collector checkout --detach 32bd078e61fefa7294d6d4748a3db4e1aa562994
cp -R go/summary-replay go/summary-scale collector/connector/genaisketchconnector/cmd/
export GOWORK=off
export GOCACHE="$PWD/go-build"
export GOMODCACHE="$PWD/go-mod"
export GENAI_SKETCH_SECRET=llm-measurement-summary-evidence-test-key-20261010
go -C collector/connector/genaisketchconnector build -tags tracelab_replay -o "$PWD/replay" ./cmd/summary-replay
go -C collector/connector/genaisketchconnector build -o "$PWD/scale" ./cmd/summary-scale
curl -fL https://github.com/uw-syfi/TraceLab/releases/download/v0.0.2/syfi_coding_trace.jsonl.gz -o data/syfi_coding_trace.jsonl.gz
curl -fL https://github.com/HPMLL/BurstGPT/releases/download/v2.0/BurstGPT_1.csv -o data/BurstGPT_1.csv
curl -fL https://github.com/HPMLL/BurstGPT/releases/download/v2.0/BurstGPT_2.csv -o data/BurstGPT_2.csv
curl -fL https://raw.githubusercontent.com/uw-syfi/TraceLab/61fea8f97277d0aa247cc2e4c7e31f90ed2bea1c/LICENSE-DATASET.md -o data/TraceLab-LICENSE-DATASET.md
curl -fL https://raw.githubusercontent.com/HPMLL/BurstGPT/7eb2c4f8350f8a6985272386f5c14af1f678b299/LICENSE -o data/BurstGPT-LICENSE.txt
venv/bin/python scripts/data_audit.py --fetch-sources
venv/bin/python scripts/data_audit.py
```

Both audit and replay verify these hashes before processing:

| Asset | SHA-256 |
| --- | --- |
| syfi_coding_trace.jsonl.gz | `11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65` |
| BurstGPT_1.csv | `4bb3783693d0a435686fbfc885615d2349bd067239079fa4b749f2e679e12122` |
| BurstGPT_2.csv | `44bf5942b03fca42c01a226a545ad3a750ec62688faecd67b6831c56a8928bf7` |

[ATTRIBUTION.md](ATTRIBUTION.md) records licenses and modifications.

## Combined Users, History And Contributors

```sh
./replay --dataset tracelab --data data --out data/tracelab-summaries
./replay --dataset burstgpt --data data --out data/burstgpt-summaries
venv/bin/python scripts/features.py
venv/bin/python scripts/sketch_experiments.py
```

Use new replay output directories. `features.py` checks every counter and
complete-attempt weight against the source reference. `sketch_experiments.py`
records union errors, storage, timings and contributor bounds. Each query timing
divides the median of five whole-batch measurements by that batch's query count.
Contributor flags ask whether the two largest positive key changes together
account for more than half a positive daily increase, using lower bounds for the
summary result. Every exact key is checked, including keys outside the candidates.

## Synthetic Scale

Each identity occurs once, followed by Zipf(1.2) events. Weights come from a seeded
reservoir of successful requests in the hosted-model records.

```sh
venv/bin/python -c 'import json; from pathlib import Path; source=json.loads(Path("data/oracle.json").read_text()); Path("data/weights.json").write_text(json.dumps(source["burstgpt"]["success_weight_sample"]))'
for seed in 20261010 20261011 20261012; do
  ./scale data/weights.json "evidence/scale-isolated-1000000-$seed" 1000000 "$seed"
done
```

## Summary-Only Analyst And Identifier Checks

```sh
mkdir -p analyst-inputs/tracelab analyst-inputs/burstgpt
cp -R data/analyst/tracelab/platform-claude data/analyst/tracelab/platform-codex analyst-inputs/tracelab/
cp -R data/analyst/burstgpt/model-ChatGPT data/analyst/burstgpt/model-GPT-4 analyst-inputs/burstgpt/
SUMMARY_EVIDENCE_SENTINEL_DIR="$PWD/data/sentinel" go -C collector/connector/genaisketchconnector test -tags tracelab_replay ./cmd/summary-replay -run TestSentinelSummaryOnly -v
venv/bin/python scripts/isolated_analyst.py
venv/bin/python scripts/privacy_audit.py
venv/bin/python scripts/record_results.py
```

The isolation runner requires raw-file and network access to fail under the
macOS policy, then reads summaries under that policy. The separate validator
scans visible and decoded values and verifies itself with injected leaks.
`record_results.py` collects aggregate evidence into `recorded/`.

## What The Numbers Mean

Exact counts and wire sizes can be compared across reruns; timings and heap
deltas describe one machine. Query times are batch averages. Summary bytes cover
selected measurements; raw records contain additional fields. The exact scale
comparison is compact keyed-table JSON, and wire bytes exclude process RAM.
The constant prompt key groups complete-attempt weight. MinHash overlap is a
separate library measurement. The public key and identifier scans establish
known-pattern exclusion, not anonymity; keyed identities remain linkable.
Keep raw references, downloaded rows and generated windows local; share the
aggregate records in [recorded/](recorded/).
