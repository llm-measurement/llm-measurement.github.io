#!/usr/bin/env python3
"""Write scheduled-job.csv: a synthetic LiteLLM spend export for the post's scheduled job.

Nov 2: 24 calls, every 30 minutes from 08:00 UTC, with the 5-minute cache, so every call writes
the 20,000-token prefix. Nov 3: the same calls with the 1-hour cache, so the first call writes
and the other 23 read. Each call also sends a 500-token question and gets a 300-token answer.
Spend uses an illustrative $3 per million input tokens and $15 per million output tokens,
with Anthropic's multipliers: 1.25x for a 5-minute write, 2x for a 1-hour write, 0.1x for a read.
"""
import csv, sys
PREFIX, QUESTION, ANSWER = 20_000, 500, 300
P_IN, P_OUT = 3e-6, 15e-6
cols = ["request_id","call_type","api_key","team_id","session_id","model","prompt_tokens","completion_tokens",
        "total_tokens","spend","status","startTime","endTime","cache_read_input_tokens","cache_write_input_tokens",
        "reasoning_output_tokens"]
w = csv.writer(open(sys.argv[1] if len(sys.argv) > 1 else "scheduled-job.csv", "w", newline=""))
w.writerow(cols)
for day, write_mult, label in (("2026-11-02", 1.25, "five-minute"), ("2026-11-03", 2.0, "one-hour")):
    for i in range(24):
        hh, mm = 8 + i // 2, 30 * (i % 2)
        reads = 0 if (label == "five-minute" or i == 0) else PREFIX
        writes = PREFIX - reads
        spend = P_IN * (QUESTION + write_mult * writes + 0.1 * reads) + P_OUT * ANSWER
        w.writerow([f"{label}-{i:02d}", "completion", "scheduled-job-key", "reports-team", f"run-{day}-{i:02d}",
                    "example-model", PREFIX + QUESTION, ANSWER, PREFIX + QUESTION + ANSWER, f"{spend:.6f}", "success",
                    f"{day}T{hh:02d}:{mm:02d}:00Z", f"{day}T{hh:02d}:{mm:02d}:04Z", reads, writes, 0])
