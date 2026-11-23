# Published v0.15.0 post-command rerun

Outcome of the original November 20 rerun: PASS. The published, freshly
installed fleetdiff v0.15.0 reproduced all three retained pre-release output
files byte for byte. The post's text and input exports were not changed. No
new provider or model call was made.

This provenance record omits local installation and cache paths.
Source record SHA-256:
`8f5caedd6416efad9446f7103684512d72cc9ea4846b0729b93e9ad1f8e4cf9f`.
The three accompanying text outputs are unmodified copies, not sanitized or
reformatted output. [RUN.md](RUN.md) records the site-layout reproduction.

## Executable And Release

- [Release v0.15.0](https://github.com/llm-measurement/fleetdiff/releases/tag/v0.15.0).
- Published `2026-11-20T07:00:29Z` after workflow `44689788366` completed SUCCESS.
- Signed tag object `b05b037940e34abbe05b0d079f38878e1bb8e097` targets
  `e1ace5424804b49c8fa4f69e3adea5a41f814401`.
- Installed binary SHA-256:
  `842d81feefe9f675609466ef9853f6c3537b3bc63a6d8196b38ba55a29ee408e`.
- `--version`: `fleetdiff v0.15.0 (e1ace5424804b49c8fa4f69e3adea5a41f814401) go1.26.11 darwin/arm64`.

The original release verification recorded a fresh anonymous tagged-README
install with a fresh HOME/cache, no GitHub token, no login and no Go on PATH.
It verified both archive and checksum-manifest attestations. The installed
binary equaled the independently verified asset. All six release checksums
and all seven asset attestations verified under the exact repository, tag,
workflow identity and hosted-runner restriction. Native binary govulncheck
was clean; all packaged-binary tests passed. These are historical release
verification results, not checks repeated by the offline reproduction rerun.

## Inputs

Both request-level exports remain private. The included
`trace_to_litellm.py` generator reproduces them from the public source trace.

| File | SHA-256 |
| --- | --- |
| trace-sonnet.csv | b573b795b54384f350d36f9422c3367a51bdf109f73bd3a12e0a00fced03eeae |
| trace-haiku.csv | 2b897bd33667e5f9be8bb5e24a79d9fc5757c6897c1df1b2ba54bc3783a2ca9e |

## Commands And Output

`FLEETDIFF` denotes the installed release binary; `OUT` denotes the private
directory holding regenerated exports. See [RUN.md](RUN.md) for setup.

```sh
nice -n 10 "$FLEETDIFF" what-if --litellm-spend "$OUT/trace-sonnet.csv" --period 2026-10-07 \
  --from claude-sonnet-5-5 --to claude-haiku-5-5 --fraction 1
nice -n 10 "$FLEETDIFF" investigate --litellm-spend "$OUT/trace-sonnet.csv" --period 2026-10-07
nice -n 10 "$FLEETDIFF" investigate --litellm-spend "$OUT/trace-haiku.csv" --period 2026-10-07
```

Each original command exited 0 with empty stderr. Its output matched the
retained pre-release record byte for byte in two independent comparisons.

| Published output | SHA-256; identical to retained pre-release output |
| --- | --- |
| fleetdiff-v0150-what-if.txt | 3792f63caab39bce9a2356f7613978ee7b5560204866c5e9461723ee02c46650 |
| fleetdiff-v0150-session-sonnet.txt | 9b0b61fbdbc1799b2a63d2b7d9a7e6296148cfa64795ebb8d336f6a951e3ee47 |
| fleetdiff-v0150-session-haiku.txt | f2ea37a0af0a4164e8240d511b4c3c27d23f2d15582b8b3e23b9c40209139462 |

The exact what-if headline remains $3,558.76 to $1,060.99 with 22,592 requests
at or under 100,000 prompt tokens and 38,404 over. Session USD p50/p95/max:
Sonnet $4.20/$65.89/$364.75; Haiku $1.08/$19.35/$116.90. Both retain 233
sessions and calls p50=81, p95=979, max=4095. These are the same observed
work re-priced, not measurements of a real model switch.

The independent offline site-layout rerun also reproduced both generated
exports and all three text outputs byte for byte, using the same installed
release binary. It did not repeat release-network or attestation checks.
