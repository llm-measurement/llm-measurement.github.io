#!/usr/bin/env python3
"""Write the public Claude Code trace as a LiteLLM-shaped spend export, priced as one model.

Every session's real call sequence (prompt size, five-minute cache read/write split from the cache
study's replay, output tokens) becomes one row per call. Spend uses the official per-million prices
in cached_session_cost.py. This re-prices real session structure; it does not simulate a different
model's behavior. Usage: python3 -I -B trace_to_litellm.py TRACES_JSONL MODEL_KEY LITELLM_MODEL DATE OUT_CSV
"""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta, timezone
from cached_session_cost import flatten, per_call, price

def main(path, key, litellm_model, date, out_path):
    day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc) + timedelta(hours=3)
    cols = ["request_id", "call_type", "api_key", "team_id", "session_id", "model", "prompt_tokens",
            "completion_tokens", "total_tokens", "spend", "status", "startTime", "endTime",
            "cache_read_input_tokens", "cache_write_input_tokens"]
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for n, line in enumerate(open(path)):
            s = json.loads(line)
            reqs = [q for q in flatten(s) if q.get("hash_ids")]
            for i, ((prompt, read, written, out), q) in enumerate(zip(per_call(reqs), reqs)):
                p_in, p_w, p_r, p_out = price(key, prompt)
                spend = (read * p_r + written * p_w + out * p_out) / 1e6
                start = day + timedelta(seconds=min(q["t"], 64800))
                w.writerow([f"{key}-s{n:03d}-{i:05d}", "acompletion", "trace-key", "trace-team", f"{key}-session-{n:03d}",
                            litellm_model, prompt, out, prompt + out, f"{spend:.9f}", "success",
                            start.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), (start + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                            read, written])

if __name__ == "__main__":
    main(*sys.argv[1:6])
