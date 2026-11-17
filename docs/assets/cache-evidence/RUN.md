# Evidence: "Same prompt, same cache, opposite bills"

Every number in the post comes from the files in this folder.

## What was run

| Step | Command | Output |
|---|---|---|
| Break-evens, closed forms and the four-service simulation | `python3 cache_puzzle.py --json results.json` | `cache_puzzle-output.txt`, `results.json` |
| Sample LiteLLM spend export for the report job | `python3 make_fixture.py scheduled-job.csv` | `scheduled-job.csv` |
| fleetdiff on the sample | `fleetdiff investigate --litellm-spend scheduled-job.csv --before-period 2026-11-02 --after-period 2026-11-03 --group-by key` | `fleetdiff-output.txt` |
| Cache replay over 233 real Claude Code sessions | `python3 trace_replay.py traces.jsonl --json trace_replay-results.json` | `trace_replay-output.txt`, `trace_replay-results.json` |
| Live check of refresh and fan-out (Anthropic API, Claude Haiku 5.5, about $0.08) | `python3 live_check.py --key-file KEY_FILE --out OUT_DIR` | `live_check-summary.json`, `live_check-output.txt` |

- **Machine:** Apple M4 Max, macOS 27.0.1, Python 3.14.2, standard library only. Deterministic seeds.
- **fleetdiff:** v0.14.0, built from the `v0.14.0` tag (`78c6448`) with `go build -trimpath ./cmd/fleetdiff`, fleetdiff v0.14.0 (unknown) go1.26.1 darwin/arm64.
- **Date:** 2026-11-05. The live check ran from 08:53 to 10:33 UTC on the same machine, API version 2023-06-01, standard library only.

## Method

The simulation models one cached prefix per service under Anthropic's documented rules, checked on the prompt-caching
page on Nov 5, 2026: a 5-minute write costs 1.25x the base input price, a 1-hour write 2x, a read 0.1x; the lifetime runs
from the start of the request that writes or reads and each use refreshes it; an entry becomes readable only after the
writing request's response starts (2 seconds after its start here). The docs state the refresh for the 5-minute cache; the
script applies it to both lifetimes and also reports the no-refresh case: the closed-form break-even for random arrivals and a
1-hour simulation of every service (added Nov 5; the refreshed results are unchanged). Costs cover the shared prefix only,
relative to sending it with caching off, over 30 days at 24 calls a day.

**The real-session replay** reads `traces.jsonl` from the public dataset
[`semianalysisai/cc-traces-weka-061526`](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-061526) by
SemiAnalysis, Apache-2.0, revision `42610fc7e9449cde53d41a7aaf43660ae7856214`, SHA-256
`a9f3345b964f7d9f8b1445f83995fc4b5994f183131b0a108cd21b15cc78f627` (1,077,676,163 bytes). It is not republished
here; download it from that revision. The dataset is SemiAnalysis's "top" sample of Claude Code sessions with at least
20 requests, and its input sizes are counts of 64-token prefix blocks. The replay applies the same documented rules
as the simulation, block by block:
- **Reads and writes:** each request offers its whole prompt for caching, reads the longest live, available leading
  run of its blocks, and writes the rest. Entries are per model, and reads refresh.
- **Availability:** a written block becomes readable at the writer's start plus its time to first token, or plus
  `api_time` for non-streamed calls, which have no recorded time to first token.
- **Prices:** writes cost 1.25x or 2x and reads 0.1x, with 0.05x and 0.025x as sensitivities.
- **Write classes:** written tokens are split into first writes, rewrites after expiry, and concurrent rewrites.
- **Fan-out:** a parallel subagent launch means siblings starting within 1 second of the first.
- **Not a billing record:** this models the cache, and isn't what those sessions were billed. The per-session results
  carry no session IDs. Runtime is about 70 seconds.

The live check tests the two rules the post depends on. Each arm uses its own 19,955-token prefix (222 policy
sections, counted with the token-counting endpoint) that starts with a random nonce, thinking off, replies capped at
8 tokens, and no retries:

- **Refresh, 1-hour cache:** a write at 0, reads at 50 and 100 minutes; a control written at 0 and read only at 100.
  Result: both reads hit, and the control missed, so reads refresh the 1-hour entry.
- **Refresh, 5-minute cache (method check on the documented case):** a write at 0, reads at 4, 8 and 12 minutes; a
  control read only at 12. Result: all three reads hit, and the control missed.
- **Fan-out, three repetitions of five calls on fresh prefixes:** five calls sent within half a millisecond all wrote
  (15 of 15). One streamed call first and the other four sent at its first text token: the leader wrote and all 12
  followers read, after a wait of 1.4 to 2.0 seconds. Sending the four at the stream's first event (message_start)
  gave the same 12 of 12, because the response headers, message_start and the first token arrived within a
  millisecond of each other.
- Every write landed in the intended tier (`ephemeral_1h_input_tokens` or `ephemeral_5m_input_tokens`). One run, one
  model, one account, one day. The private event log with request IDs stays outside this folder.

The sample's spend uses illustrative prices of $3 and $15 per million input and output tokens with the same multipliers.
It is synthetic. It demonstrates fleetdiff's arithmetic, not provider behavior.

## Hashes
```
208cb3e1be2d310e8ff1cb0b6c8b26610d3a985f23456e0f3d864d6672c029a7  cache_puzzle.py
31131d8dfde571820e9b929568a64c3ab35703657f8443b3eb4b7dcb6609f70d  make_fixture.py
66956c74b547ab24d7695500c4afd5ee7a5430c0d30c37e7b79bfda2b200a0ec  scheduled-job.csv
6491730a71be9733f6d421452e1d7f64d2de59dcb88bb3f6486f8ee46a7a58ee  cache_puzzle-output.txt
ee5040bdf0e3ad1fb5523867af43e59e08d35cbb1ad8517151308d206ea1b02d  results.json
0e539d6ad7eae025669cf532bda9ee87ce00a1b41e34d9e369b33cf906f27015  fleetdiff-output.txt
294ae3c37ac31e4ef80223317c4bf92de26dbaab20335586e05d1a24d89bab03  live_check.py
1fa3f57b04ab2617ee257b3226afc5002e384c714d321e6eb6610569b3df5205  live_check-summary.json
1b78dc9dbd9cdf1ad996b392754344fd8f3a3766006489e4dc9e8659585aae91  live_check-output.txt
a2562fb6534f1255e45bd6e46b1a80a618383ea49d288e29d35662d1e0b2f395  trace_replay.py
3bf93651e8b0404a7497180b8ba9a115ca23d21d87b632188e8a0cf258cb275a  trace_replay-output.txt
69cd657a0831bf8ac863b89622b696933c3a56c0d97e5e5cf70fa22a94f9a9cf  trace_replay-results.json
```
