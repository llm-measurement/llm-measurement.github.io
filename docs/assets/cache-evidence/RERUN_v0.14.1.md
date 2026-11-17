# Sample Rerun With fleetdiff v0.14.1

The complete output matches the historical sample byte for byte. All four
quoted lines are unchanged, including recorded spend from 1.944 to 0.402 USD.

```sh
fleetdiff investigate --litellm-spend scheduled-job.csv \
  --before-period 2026-11-02 --after-period 2026-11-03 --group-by key
```

- Date: November 17, 2026.
- Machine: Apple M4 Max, macOS 27.0.1, darwin/arm64.
- Binary: fleetdiff v0.14.1 (45f8d7aef43a88e1c24033a9f80c4a667f8dbad7), Go 1.26.11.
- Archive SHA-256: 6ee560da587959c41767f87e0c072a7551e6bd5ee5cd51fdc34220672047f19a,
  rechecked against the verified release manifest.
- Sample CSV SHA-256: 66956c74b547ab24d7695500c4afd5ee7a5430c0d30c37e7b79bfda2b200a0ec.
- Output SHA-256: 0e539d6ad7eae025669cf532bda9ee87ce00a1b41e34d9e369b33cf906f27015.
- Exit 0; no stderr. No provider requests.

[Complete output](fleetdiff-v0141-output.txt). The 13 original evidence files,
including RUN.md and its historical version record, are preserved byte for byte.
