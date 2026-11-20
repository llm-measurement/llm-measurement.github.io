#!/usr/bin/env python3
"""How much the trace's largest prompts drive the Sonnet/Haiku ratio.

SemiAnalysis notes the `in` block count can overcount by up to about 260,000 tokens in the heavy
cache-write tail. Recompute the cached ratio (a) dropping every call over a cutoff, and (b) shrinking
every call over 500,000 tokens by 260,000 (the worst overcount, applied to all of them).
Usage: python3 -I -B tail_sensitivity.py TRACES_JSONL
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cached_session_cost import flatten, per_call, price

def cost(calls, model):
    t = 0.0
    for p, r, w, o in calls:
        _, pw, pr, po = price(model, p)
        t += r * pr + w * pw + o * po
    return t

def main(path):
    calls = []
    for line in open(path):
        reqs = [q for q in flatten(json.loads(line)) if q.get("hash_ids")]
        calls.extend(per_call(reqs))
    out = {"all": cost(calls, "sonnet-5.5") / cost(calls, "haiku-5.5")}
    for cut in (500_000, 300_000):
        kept = [c for c in calls if c[0] <= cut]
        out[f"drop_over_{cut}"] = {"times_cheaper": cost(kept, "sonnet-5.5") / cost(kept, "haiku-5.5"),
                                   "calls_dropped_share": 1 - len(kept) / len(calls)}
    shrunk = []
    for p, r, w, o in calls:
        if p > 500_000:
            d = 260_000
            r2 = max(r - d, 0); w2 = max(w - max(d - r, 0), 0)
            shrunk.append((p - d, r2, w2, o))
        else:
            shrunk.append((p, r, w, o))
    out["shrink_over_500k_by_260k"] = cost(shrunk, "sonnet-5.5") / cost(shrunk, "haiku-5.5")
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main(sys.argv[1])
