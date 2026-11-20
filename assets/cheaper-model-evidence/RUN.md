# Reproducing The Haiku And Sonnet Study

November 20, 2026 reproduction result: PASS. All 11 sequential runs exited 0 with
empty stderr. The five JSON records, both SVG layouts, both regenerated CSVs and all
three published-binary text outputs matched their retained originals byte
for byte. All original inputs and outputs were re-hashed unchanged at the
end. No reproduction mismatch was found.

The outputs re-price the same recorded work; they do not measure model quality
or the behavior of a real model switch.

## Environment And Source

- Evidence-layout rerun: November 20, 2026, Apple M4 Max, macOS 27.0.1,
  arm64, Python 3.14.2. Python scripts use only the standard library.
- Scripts and binary commands run sequentially at `nice -n 10`.
- Each new output goes to a fresh private cache directory, never over a
  published or original file. Comparisons use `cmp`, byte for byte, without
  parsing, reformatting, floating-point tolerances or semantic normalization.
  A mismatch stops the run; it is not repaired by changing research behavior.
- The source is SemiAnalysis's Apache-2.0
  [cc-traces-weka-061526 dataset](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-061526).
  Download `traces.jsonl` from revision
  `42610fc7e9449cde53d41a7aaf43660ae7856214` using this
  [revision-pinned file link](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-061526/resolve/42610fc7e9449cde53d41a7aaf43660ae7856214/traces.jsonl).
  Size: 1,077,676,163 bytes. SHA-256:
  `a9f3345b964f7d9f8b1445f83995fc4b5994f183131b0a108cd21b15cc78f627`.
  The trace is not included here.
- Prices were read November 19, 2026, and rechecked unchanged on
  November 20, 2026, for Sonnet 5.5, both Haiku 5.5 tiers,
  Opus 5.5, Fable 5.2 and the long-context rule. See
  [ATTRIBUTION.md](ATTRIBUTION.md) for the pricing source and credit.
- The rerun used existing local inputs and the already-installed published
  binary, with no network access or provider calls.

The replay helper is the existing sibling
[`../cache-evidence/trace_replay.py`](../cache-evidence/trace_replay.py),
SHA-256 `a2562fb6534f1255e45bd6e46b1a80a618383ea49d288e29d35662d1e0b2f395`.
It is hash-identical to the original helper.
The sibling cache-study result has SHA-256
`69cd657a0831bf8ac863b89622b696933c3a56c0d97e5e5cf70fa22a94f9a9cf`.

## Setup

Start in `assets/cheaper-model-evidence/`. Set `TRACE` to the downloaded file
and, for the binary commands, `FLEETDIFF` to the installed v0.15.0 binary.
Use absolute values for these environment placeholders if changing directory.
The output directory must be new and private.

```sh
set -eu
umask 077
EVIDENCE="$(pwd)"
: "${TRACE:?Set TRACE to the downloaded traces.jsonl}"
mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"
OUT="$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/cheaper-model-evidence.XXXXXX")"
printf '%s  %s\n' a9f3345b964f7d9f8b1445f83995fc4b5994f183131b0a108cd21b15cc78f627 "$TRACE" | shasum -a 256 -c -
printf '%s  %s\n' a2562fb6534f1255e45bd6e46b1a80a618383ea49d288e29d35662d1e0b2f395 "$EVIDENCE/../cache-evidence/trace_replay.py" | shasum -a 256 -c -
printf '%s  %s\n' 69cd657a0831bf8ac863b89622b696933c3a56c0d97e5e5cf70fa22a94f9a9cf "$EVIDENCE/../cache-evidence/trace_replay-results.json" | shasum -a 256 -c -
```

## Analysis Commands

Run in this order. The first two scripts' `--json` option writes the retained
one-space, sorted-key format without a final newline. The other three JSON
records are the scripts' stdout, including its final newline. Use those exact
interfaces; do not serialize the results again.

```sh
nice -n 10 python3 -I -B "$EVIDENCE/cached_session_cost.py" "$TRACE" --json "$OUT/cached-session-cost-output.json" >"$OUT/cached-session-cost.stdout" 2>"$OUT/cached-session-cost.stderr"
test ! -s "$OUT/cached-session-cost.stderr"
cmp "$EVIDENCE/cached-session-cost-output.json" "$OUT/cached-session-cost-output.json"

nice -n 10 python3 -I -B "$EVIDENCE/tier_analysis.py" "$TRACE" --json "$OUT/tier-analysis-output.json" >"$OUT/tier-analysis.stdout" 2>"$OUT/tier-analysis.stderr"
test ! -s "$OUT/tier-analysis.stderr"
cmp "$EVIDENCE/tier-analysis-output.json" "$OUT/tier-analysis-output.json"

nice -n 10 python3 -I -B "$EVIDENCE/subagent_split.py" "$TRACE" >"$OUT/subagent-split-output.json" 2>"$OUT/subagent-split.stderr"
test ! -s "$OUT/subagent-split.stderr"
cmp "$EVIDENCE/subagent-split-output.json" "$OUT/subagent-split-output.json"

nice -n 10 python3 -I -B "$EVIDENCE/tail_sensitivity.py" "$TRACE" >"$OUT/tail-sensitivity-output.json" 2>"$OUT/tail-sensitivity.stderr"
test ! -s "$OUT/tail-sensitivity.stderr"
cmp "$EVIDENCE/tail-sensitivity-output.json" "$OUT/tail-sensitivity-output.json"

nice -n 10 python3 -I -B "$EVIDENCE/one_hour_cache.py" "$TRACE" >"$OUT/one-hour-cache-output.json" 2>"$OUT/one-hour-cache.stderr"
test ! -s "$OUT/one-hour-cache.stderr"
cmp "$EVIDENCE/one-hour-cache-output.json" "$OUT/one-hour-cache-output.json"
```

The chart generator writes desktop and narrow SVG layouts using relative
input and output filenames. Run it against the two freshly reproduced JSON
files in `OUT`, not against the published directory as a writable working directory.

```sh
(
  cd "$OUT"
  nice -n 10 python3 -I -B "$EVIDENCE/make_chart.py" >chart.stdout 2>chart.stderr
)
test ! -s "$OUT/chart.stderr"
cmp "$EVIDENCE/cheaper-ratio-chart.svg" "$OUT/cheaper-ratio-chart.svg"
cmp "$EVIDENCE/cheaper-ratio-chart-narrow.svg" "$OUT/cheaper-ratio-chart-narrow.svg"
```

## Regenerate Both Exports

These CSVs are generated privately, not included in the evidence package.
Each has 60,996 data rows. Their full SHA-256 hashes must match the retained
release-rerun inputs before running the binary.

```sh
nice -n 10 python3 -I -B "$EVIDENCE/trace_to_litellm.py" "$TRACE" sonnet-5.5 claude-sonnet-5-5 2026-10-07 "$OUT/trace-sonnet.csv" >"$OUT/trace-sonnet.stdout" 2>"$OUT/trace-sonnet.stderr"
test ! -s "$OUT/trace-sonnet.stderr"
printf '%s  %s\n' b573b795b54384f350d36f9422c3367a51bdf109f73bd3a12e0a00fced03eeae "$OUT/trace-sonnet.csv" | shasum -a 256 -c -

nice -n 10 python3 -I -B "$EVIDENCE/trace_to_litellm.py" "$TRACE" haiku-5.5 claude-haiku-5-5 2026-10-07 "$OUT/trace-haiku.csv" >"$OUT/trace-haiku.stdout" 2>"$OUT/trace-haiku.stderr"
test ! -s "$OUT/trace-haiku.stderr"
printf '%s  %s\n' 2b897bd33667e5f9be8bb5e24a79d9fc5757c6897c1df1b2ba54bc3783a2ca9e "$OUT/trace-haiku.csv" | shasum -a 256 -c -
```

The November 20 evidence-layout rerun also used `cmp` against both existing
private CSVs, not just their hashes. If you have retained copies, compare
those too before continuing.

## Published fleetdiff v0.15.0

The tagged README's pinned installer line is below for readers who need to
install the release. This is a separate, networked setup step, not something
executed by the offline reproduction rerun. Run it from a chosen private
directory; it creates `./fleetdiff-install/` there.

```sh
bash -o pipefail -c 'curl --fail --location --proto "=https" --tlsv1.2 https://raw.githubusercontent.com/llm-measurement/fleetdiff/0d7db95c5bb3013f8c564c91fbb07b6235a2664e/scripts/install.sh | sh -s -- v0.15.0 ./fleetdiff-install'
FLEETDIFF="$(pwd)/fleetdiff-install/fleetdiff"
nice -n 10 "$FLEETDIFF" --version
```

The binary actually used for this offline rerun was the previously fresh
anonymous release installation, not a local build. Version:
`fleetdiff v0.15.0 (e1ace5424804b49c8fa4f69e3adea5a41f814401) go1.26.11 darwin/arm64`.
Its darwin/arm64 SHA-256 is
`842d81feefe9f675609466ef9853f6c3537b3bc63a6d8196b38ba55a29ee408e`;
other release platforms have different binary hashes. Historical release
verification is in the
[provenance record](FLEETDIFF_V0150_RERUN_2026-11-20.md).

```sh
: "${FLEETDIFF:?Set FLEETDIFF to the installed v0.15.0 binary}"
nice -n 10 "$FLEETDIFF" what-if --litellm-spend "$OUT/trace-sonnet.csv" --period 2026-10-07 \
  --from claude-sonnet-5-5 --to claude-haiku-5-5 --fraction 1 >"$OUT/fleetdiff-v0150-what-if.txt" 2>"$OUT/fleetdiff-v0150-what-if.stderr"
test ! -s "$OUT/fleetdiff-v0150-what-if.stderr"
cmp "$EVIDENCE/fleetdiff-v0150-what-if.txt" "$OUT/fleetdiff-v0150-what-if.txt"

nice -n 10 "$FLEETDIFF" investigate --litellm-spend "$OUT/trace-sonnet.csv" --period 2026-10-07 >"$OUT/fleetdiff-v0150-session-sonnet.txt" 2>"$OUT/fleetdiff-v0150-session-sonnet.stderr"
test ! -s "$OUT/fleetdiff-v0150-session-sonnet.stderr"
cmp "$EVIDENCE/fleetdiff-v0150-session-sonnet.txt" "$OUT/fleetdiff-v0150-session-sonnet.txt"

nice -n 10 "$FLEETDIFF" investigate --litellm-spend "$OUT/trace-haiku.csv" --period 2026-10-07 >"$OUT/fleetdiff-v0150-session-haiku.txt" 2>"$OUT/fleetdiff-v0150-session-haiku.stderr"
test ! -s "$OUT/fleetdiff-v0150-session-haiku.stderr"
cmp "$EVIDENCE/fleetdiff-v0150-session-haiku.txt" "$OUT/fleetdiff-v0150-session-haiku.txt"
```

## Field-To-Figure Map

Paths below are JSON field paths; keys containing arrows are literal keys.
Amounts and percentages in the essay are rounded from these fields, never
written back into the retained outputs.

| Figure or claim | File and field, or explicit arithmetic |
| --- | --- |
| 233 sessions; 60,996 calls; 38,404 calls over 100k (63%) | `cached-session-cost-output.json`: `sessions`, `calls`, `calls_over_100k`; share also in `tier-analysis-output.json`: `calls_over_100k_share` |
| 20x price-sheet gap; long tier is 5x short tier | `cached-session-cost-output.json`: `pairs.sonnet-5.5->haiku-5.5.sticker_input_ratio`; `prices_usd_per_million.haiku-5.5` and `haiku-5.5-long` |
| 3.4x cheaper; 29.8% of Sonnet's bill | `cached-session-cost-output.json`: `pairs.sonnet-5.5->haiku-5.5.cached.aggregate_breakeven_steps` and `.aggregate_cost_ratio` |
| Dollars and percentage cost-component table | `tier-analysis-output.json`: `breakdown_usd` and `breakdown_share`, keys `sonnet-5.5`, `haiku-5.5`, `fable-5.2`; total is read + write + output |
| 69% of written tokens are rewrites after expiry | `../cache-evidence/trace_replay-results.json`: `summary.totals.300.written_split.expired / summary.totals.300.written`; command below |
| Roughly a third of Sonnet's bill pays for expired-context rewrites | Previous share times `breakdown_usd.sonnet-5.5.write`, divided by Sonnet's total |
| One-hour cache: Sonnet -16%, Haiku -14%; 3.4x becomes 3.3x | `one-hour-cache-output.json`: `5min.sonnet.total`, `1h.sonnet.total`, corresponding `haiku.total` fields; reduction = 1 - one-hour/five-minute total; `5min.times_cheaper`, `1h.times_cheaper` |
| Output is 17% of Sonnet's bill and 11% of Haiku's | `cached-session-cost-output.json`: `output_share.sonnet-5.5-cached` and `output_share.haiku-5.5-cached`; also `tier-analysis-output.json`: `breakdown_share.*.output` |
| Read multipliers 0.025x, 0.05x and 0.10x; long-tier writes/output 4x cheaper, reads 2x; short reads 10x, other lines 20x | `cached-session-cost-output.json`: `prices_usd_per_million`; tuple order is input, five-minute write, read, output; divide the named rates |
| Over-100k calls carry 85% of Sonnet spend | `tier-analysis-output.json`: `sonnet_spend_over_100k_share` |
| Fable-to-Sonnet 3.3x, Opus-to-Sonnet 2x | `cached-session-cost-output.json`: `pairs.fable-5.2->sonnet-5.5.cached.aggregate_breakeven_steps`, `pairs.opus-5.5->sonnet-5.5.cached.aggregate_breakeven_steps` |
| Chart: price sheet, cached trace, all-short ceiling | `make_chart.py`: the preceding pair fields, inverse `sticker_input_ratio`, and `tier-analysis-output.json`: `times_cheaper_than_sonnet.haiku-5.5-all-short` |
| All-short Haiku ceiling, 15x | `tier-analysis-output.json`: `times_cheaper_than_sonnet.haiku-5.5-all-short`; no compaction calls or quality effects are simulated |
| Median prompt 140,800; upper quartile 275,200 | `tier-analysis-output.json`: `prompt_tokens_quartiles[1]` and `[2]` |
| Four session-size rows: ranges, over-100k shares, discounts | `tier-analysis-output.json`: `by_session_size_quartile[]`: `sonnet_usd_min`, `sonnet_usd_max`, `median_share_calls_over_100k`, `times_cheaper` |
| Top ten hold 41%; largest equals 87 median sessions | `tier-analysis-output.json`: `top10_share_of_sonnet_spend`, `largest_session_over_median` |
| Subagents: 18% of bill, 43% over 100k, 4.0x slice discount, 13% whole-bill saving | `subagent-split-output.json`: `subagent_share_of_sonnet_bill`, `sub_over_100k / sub`, `subagent_times_cheaper_on_haiku`, `1 - bill_with_subagents_on_haiku_vs_all_sonnet` |
| Average-step break-even 3.4x; failed full Haiku attempt then Sonnet about 1.3x | `cached-session-cost-output.json`: reciprocal of aggregate cost ratio; failed-attempt illustration is `1 + aggregate_cost_ratio`, not an observed switch |
| $3,558.76 to $1,060.99; 22,592 short-tier and 38,404 long-tier calls | `fleetdiff-v0150-what-if.txt`: first two lines; also five-minute totals in `one-hour-cache-output.json` |
| Sonnet p50/p95/max $4.20/$65.89/$364.75; Haiku $1.08/$19.35/$116.90 | `fleetdiff-v0150-session-sonnet.txt`, `fleetdiff-v0150-session-haiku.txt`: `Recorded USD` lines |
| Calls p50/p95/max 81/979/4095, 233 sessions | Both session outputs: `Logged model calls` and session coverage lines |
| Tokenizer sensitivity 3.35x to 3.34x | `tier-analysis-output.json`: `times_cheaper_than_sonnet.haiku-5.5`, `tokenizer_sensitivity_times_cheaper`; `tier_analysis.py`: `OLD_TOKENIZER` and scale 1.3 |
| 85% of calls use the newer tokenizer | Raw trace `flatten(session)` requests with `hash_ids`, whose `model` does not start with `tier_analysis.OLD_TOKENIZER`; tally command below |
| Worst-tail shrink 3.42x; dropping over-500k calls 3.56x | `tail-sensitivity-output.json`: `shrink_over_500k_by_260k`, `drop_over_500000.times_cheaper` |
| 90k/150k compaction example and 70% reduction | External [Anthropic cost guide](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), not measured by these scripts |
| Terminal-Bench 4.0: 39.2% and 70.6%; recommended subagent use | External [Haiku 5.5 announcement](https://www.anthropic.com/claude-haiku-5-5), not measured by these scripts |
| 64-token blocks, up-to-260k heavy-tail overcount, at-least-20-request selection | SemiAnalysis dataset card linked above; `trace_replay.py` supplies the reviewed parsing helpers |

The requested `totals.300.written_split` is nested under `summary` in the
published cache-study JSON. This one-line command prints that exact object
and its expired fraction without changing the result file:

```sh
nice -n 10 python3 -I -B -c 'import json,sys; d=json.load(open(sys.argv[1]))["summary"]["totals"]["300"]["written_split"]; print(d); print(d["expired"]/sum(d.values()))' "$EVIDENCE/../cache-evidence/trace_replay-results.json" >"$OUT/cache-write-split.txt"
```

Expected split: concurrent `12607488`, expired `485735360`, first `209180864`;
total `707523712`, expired fraction `0.6865287364390128` (68.7%, rounded to
69% in the essay). The model-share tally uses the same request filter as the
analyses, without a new replay or pricing model:

```sh
nice -n 10 python3 -I -B -c 'import json,sys; sys.path.insert(0,sys.argv[1]); from tier_analysis import OLD_TOKENIZER,flatten; new=[not r["model"].startswith(OLD_TOKENIZER) for line in open(sys.argv[2]) for r in flatten(json.loads(line)) if r.get("hash_ids")]; print(sum(new),len(new),sum(new)/len(new))' "$EVIDENCE" "$TRACE" >"$OUT/new-tokenizer-share.txt"
```

Both lookup commands were executed sequentially at nice 10 with empty
stderr. The tokenizer tally printed `52120 60996 0.8544822611318775`
(85.4%, rounded to 85% in the essay).

## Reproduction Script Changes

`cached_session_cost.py` differs from its original by two literal
replacements of the old helper-directory name with `cache-evidence`, one in
the docstring and one in `sys.path.insert`. No calculations, rates, iteration
order, serialization or CLI behavior changed.

Original script SHA-256:
`22a056641459de1d221757b4c0a1079f1093e6da859ea274aec08d2516e32ca0`.
Site-layout script SHA-256:
`ece4078b62228d83c7893bbc9880e8e8ccfe1e6b436073995d4b06c5c011eff6`.
The remaining analysis and export scripts are byte-identical to their originals.
`make_chart.py` renders desktop and narrow SVG layouts from the same two JSON
inputs, with `cr-`-prefixed SVG class names. Numeric output files are not edited.

## SHA-256 Reference Manifest

```text
ece4078b62228d83c7893bbc9880e8e8ccfe1e6b436073995d4b06c5c011eff6  cached_session_cost.py
ef390d733029e8bf0bf7d986dbd6519f6297933b7519d144cb0dc5885da6e049  cached-session-cost-output.json
226188e884f3e76b59aa43c343788cbc47f0474307f8fbf5ef4af6ea9c49f14f  tier_analysis.py
5c7e182d95b1fa8d6c5fd63549bb29549c22f9e2f9ae7a6a616169a8d3fb310e  tier-analysis-output.json
d9aba91b4ce80f5c009638ac16877bd8f5e4f136815d71d21808caf25c06ccc1  subagent_split.py
28d866919899c17c2d0b08ac5868dade190b9526dea73f271096875f159a7c1c  subagent-split-output.json
ea24bdced9a6a332dc807aaa245cf4c33db2f31042a36c07fe6c8d9f26a4a320  tail_sensitivity.py
2830852353db357f92a808e5fbbb8a58a53fe9ad857f3620f48323ab04ee13c9  tail-sensitivity-output.json
11b066405f3306f1c47e7da98b2ac14461f15ef73b448c827a1042850711ce14  one_hour_cache.py
812da87722547b1b6989de28600e589ffa8204b6d736b6b37f1bf534a8398cbc  one-hour-cache-output.json
c41aded60df0f871bd99da5b703ff426021e7e923897cb6947ec533aa21bfa06  trace_to_litellm.py
181ba2a913ed9189b24923c4836eb96708897270d9063c679d77976aa6ef059f  make_chart.py
1d2efce75cd9c1e745098bba08097162cd1f44efac7c5e9d5ee0278f946282b8  cheaper-ratio-chart.svg
bc0070c31c1cb108e71dc06bfa3334c1404fa350be72fd1a8b731fb560ffad99  cheaper-ratio-chart-narrow.svg
3792f63caab39bce9a2356f7613978ee7b5560204866c5e9461723ee02c46650  fleetdiff-v0150-what-if.txt
9b0b61fbdbc1799b2a63d2b7d9a7e6296148cfa64795ebb8d336f6a951e3ee47  fleetdiff-v0150-session-sonnet.txt
f2ea37a0af0a4164e8240d511b4c3c27d23f2d15582b8b3e23b9c40209139462  fleetdiff-v0150-session-haiku.txt
b573b795b54384f350d36f9422c3367a51bdf109f73bd3a12e0a00fced03eeae  trace-sonnet.csv (generated privately, not included)
2b897bd33667e5f9be8bb5e24a79d9fc5757c6897c1df1b2ba54bc3783a2ca9e  trace-haiku.csv (generated privately, not included)
```
