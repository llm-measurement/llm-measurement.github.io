#!/usr/bin/env python3
"""Follow-up analyses for the cheaper-model post (draft 3), on the same re-priced trace.

1. Dollar breakdown by component (cache read, cache write, output) per model.
2. Haiku 5.5 if every prompt stayed at or under 100,000 tokens (all calls priced on the short row):
   an upper bound on the discount that compaction below the line could reach, before compaction's
   own costs.
3. How the Haiku/Sonnet cost ratio changes with session size; the top ten sessions' share of spend.
4. Tokenizer sensitivity: calls recorded on models before Claude 4.7 (old tokenizer) scaled by 1.3
   when deciding Haiku 5.5's tier and pricing their tokens.
5. Prompt-length distribution: share of calls and of Sonnet spend above the 100,000 line.

Usage: python3 -I -B tier_analysis.py TRACES_JSONL [--json out.json]
"""

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cached_session_cost import LONG_PROMPT, PRICES, flatten, per_call  # noqa: E402

OLD_TOKENIZER = ("claude-haiku-4-5", "claude-opus-4-6", "claude-sonnet-4-6", "claude-sonnet-4-5")


def rates(model, prompt, force_short=False):
    if model == "haiku-5.5" and prompt > LONG_PROMPT and not force_short:
        return PRICES["haiku-5.5-long"]
    return PRICES[model]


def components(calls, model, force_short=False, scale=None):
    read = write = output = 0.0
    for i, (prompt, r, w, o) in enumerate(calls):
        k = scale[i] if scale else 1.0
        _, p_w, p_r, p_out = rates(model, prompt * k, force_short)
        read += r * k * p_r
        write += w * k * p_w
        output += o * p_out
    return {"read": read / 1e6, "write": write / 1e6, "output": output / 1e6}


def total(c):
    return c["read"] + c["write"] + c["output"]


def main(path):
    sessions, scales = [], []
    for line in open(path):
        s = json.loads(line)
        reqs = [q for q in flatten(s) if q.get("hash_ids")]
        if reqs:
            sessions.append(per_call(reqs))
            scales.append([1.3 if q["model"].startswith(OLD_TOKENIZER) else 1.0 for q in reqs])
    out = {"breakdown_usd": {}, "breakdown_share": {}}
    for label, model, short in (("sonnet-5.5", "sonnet-5.5", False), ("fable-5.2", "fable-5.2", False),
                                ("haiku-5.5", "haiku-5.5", False), ("haiku-5.5-all-short", "haiku-5.5", True)):
        agg = {"read": 0.0, "write": 0.0, "output": 0.0}
        for c in sessions:
            for k, v in components(c, model, short).items():
                agg[k] += v
        out["breakdown_usd"][label] = agg
        out["breakdown_share"][label] = {k: v / total(agg) for k, v in agg.items()}
    son = total(out["breakdown_usd"]["sonnet-5.5"])
    out["ratio_to_sonnet"] = {k: total(v) / son for k, v in out["breakdown_usd"].items()}
    out["times_cheaper_than_sonnet"] = {k: 1 / r for k, r in out["ratio_to_sonnet"].items()}

    per = []
    for c in sessions:
        s_cost = total(components(c, "sonnet-5.5"))
        h_cost = total(components(c, "haiku-5.5"))
        per.append((s_cost, h_cost, len(c), sum(1 for p, *_ in c if p > LONG_PROMPT) / len(c)))
    per.sort()
    n = len(per)
    out["by_session_size_quartile"] = []
    for q in range(4):
        part = per[q * n // 4:(q + 1) * n // 4]
        out["by_session_size_quartile"].append({
            "sessions": len(part), "sonnet_usd_min": part[0][0], "sonnet_usd_max": part[-1][0],
            "times_cheaper": sum(p[0] for p in part) / sum(p[1] for p in part),
            "median_share_calls_over_100k": statistics.median(p[3] for p in part)})
    top10 = sum(p[0] for p in per[-10:])
    out["top10_share_of_sonnet_spend"] = top10 / sum(p[0] for p in per)
    out["largest_session_over_median"] = per[-1][0] / statistics.median(p[0] for p in per)

    tok = {"read": 0.0, "write": 0.0, "output": 0.0}
    for c, sc in zip(sessions, scales):
        for k, v in components(c, "haiku-5.5", False, sc).items():
            tok[k] += v
    son_scaled = 0.0
    for c, sc in zip(sessions, scales):
        son_scaled += total(components(c, "sonnet-5.5", False, sc))
    out["tokenizer_sensitivity_times_cheaper"] = son_scaled / total(tok)

    calls = [p for c in sessions for p, *_ in c]
    out["calls"] = len(calls)
    out["calls_over_100k_share"] = sum(1 for p in calls if p > LONG_PROMPT) / len(calls)
    spend_over = sum(total(components([x], "sonnet-5.5")) for c in sessions for x in c if x[0] > LONG_PROMPT)
    out["sonnet_spend_over_100k_share"] = spend_over / son
    out["prompt_tokens_quartiles"] = statistics.quantiles(calls, n=4)
    print(json.dumps(out, indent=2))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1])
