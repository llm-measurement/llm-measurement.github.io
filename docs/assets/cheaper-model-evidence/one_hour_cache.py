#!/usr/bin/env python3
"""The Sonnet 5.5 / Haiku 5.5 ratio on the trace with five-minute and with one-hour prompt caching.

Same replay and prices as cached_session_cost.py. The one-hour case replays every prompt with a
3,600-second lifetime and prices writes at Anthropic's one-hour rate, 2x the input price (Sonnet 5.5
$4, Haiku 5.5 $0.20, Haiku 5.5 over 100,000 prompt tokens $1; pricing page read Nov 19, 2026).
Usage: python3 -I -B one_hour_cache.py TRACES_JSONL
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cached_session_cost as csc

WRITE_1H = {"sonnet-5.5": 4.00, "haiku-5.5": 0.20, "haiku-5.5-long": 1.00}

def bill(calls, model, one_hour):
    parts = {"writes": 0.0, "reads": 0.0, "output": 0.0}
    for p, r, w, o in calls:
        _, pw, pr, po = csc.price(model, p)
        if one_hour:
            key = "haiku-5.5-long" if model == "haiku-5.5" and p > csc.LONG_PROMPT else model
            pw = WRITE_1H[key]
        parts["writes"] += w * pw / 1e6
        parts["reads"] += r * pr / 1e6
        parts["output"] += o * po / 1e6
    parts["total"] = sum(parts.values())
    return parts

def main(path):
    sessions = [[q for q in csc.flatten(json.loads(line)) if q.get("hash_ids")] for line in open(path)]
    out = {}
    for name, ttl, one_hour in (("5min", 300.0, False), ("1h", 3600.0, True)):
        csc.TTL = ttl
        calls = [c for reqs in sessions for c in csc.per_call(reqs)]
        s, h = bill(calls, "sonnet-5.5", one_hour), bill(calls, "haiku-5.5", one_hour)
        out[name] = {"sonnet": {k: round(v, 2) for k, v in s.items()},
                     "haiku": {k: round(v, 2) for k, v in h.items()},
                     "times_cheaper": round(s["total"] / h["total"], 4),
                     "written_tokens": sum(c[2] for c in calls), "read_tokens": sum(c[1] for c in calls)}
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main(sys.argv[1])
