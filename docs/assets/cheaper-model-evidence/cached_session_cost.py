#!/usr/bin/env python3
"""Re-price every call of a public Claude Code trace under official Anthropic prices, with caching.

Input: traces.jsonl from semianalysisai/cc-traces-weka-061526 (Apache-2.0), revision 42610fc7, the
same file the cache study used. Each request's cache read and write split comes from replaying its
64-token prefix blocks with a five-minute lifetime (the cache study's model, imported from
../cache-evidence/trace_replay.py). Prices: platform.claude.com/docs/en/about-claude/pricing, read
Nov 19, 2026, USD per million tokens. Haiku 5.5 is priced per request by prompt size (over 100,000
input tokens uses its long-prompt row).

For each session we price the actual call sequence on the expensive and the cheaper model and take
r = cheaper / expensive. If the cheaper model needed k times the steps and each extra step cost the
session's average step, it would cost more once k > 1/r. Extra steps late in a growing context cost
more than average, so 1/r is the generous end for the cheaper model.

Usage: python3 -I -B cached_session_cost.py TRACES_JSONL [--json out.json]
"""

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache-evidence"))
from trace_replay import BLOCK, flatten  # noqa: E402  (the cache study's reviewed helpers)

# input, 5-minute cache write, cache read, output (USD per million tokens)
PRICES = {
    "fable-5.2": (8.00, 10.00, 0.20, 40.00),
    "opus-5.5": (4.00, 5.00, 0.20, 20.00),
    "sonnet-5.5": (2.00, 2.50, 0.10, 10.00),
    "haiku-5.5": (0.10, 0.125, 0.01, 0.50),
    "haiku-5.5-long": (0.50, 0.625, 0.05, 2.50),
}
LONG_PROMPT = 100_000
TTL = 300.0
PAIRS = [("opus-5.5", "sonnet-5.5"), ("fable-5.2", "sonnet-5.5"), ("sonnet-5.5", "haiku-5.5")]


def price(model, prompt_tokens):
    if model == "haiku-5.5" and prompt_tokens > LONG_PROMPT:
        return PRICES["haiku-5.5-long"]
    return PRICES[model]


def per_call(reqs):
    """Per-request (prompt, read, written, output) under the cache study's replay rules."""
    cache, out = {}, []
    for q in reqs:
        t, model, blocks = q["t"], q["model"], q["hash_ids"]
        avail = t + (q["ttft"] if q.get("ttft") is not None else q.get("api_time") or 0.0)
        k = 0
        for b in blocks:
            e = cache.get((model, b))
            if e is None or e[1] <= t or e[0] > t:
                break
            k += 1
        for i, b in enumerate(blocks):
            key = (model, b)
            if i < k:
                cache[key][1] = t + TTL
            else:
                e = cache.get(key)
                cache[key] = [e[0] if (e is not None and e[1] > t) else avail, t + TTL]
        out.append((len(blocks) * BLOCK, k * BLOCK, (len(blocks) - k) * BLOCK, q.get("out", 0)))
    return out


def cost(calls, model, cached=True, output_factor=1.0):
    total = 0.0
    for prompt, read, written, output in calls:
        p_in, p_w, p_r, p_out = price(model, prompt)
        inp = (read * p_r + written * p_w) if cached else prompt * p_in
        total += inp + output * output_factor * p_out
    return total / 1e6


def summarize(values):
    q = statistics.quantiles(values, n=4)
    return {"median": statistics.median(values), "q1": q[0], "q3": q[2]}


def main(path):
    sessions = []
    for line in open(path):
        s = json.loads(line)
        reqs = [q for q in flatten(s) if q.get("hash_ids")]
        if reqs:
            sessions.append(per_call(reqs))
    out = {"sessions": len(sessions), "calls": sum(len(c) for c in sessions),
           "calls_over_100k": sum(1 for c in sessions for p, *_ in c if p > LONG_PROMPT),
           "prices_usd_per_million": PRICES, "pairs": {}}
    for model in ("sonnet-5.5", "haiku-5.5"):
        for cached in (True, False):
            total = sum(cost(c, model, cached) for c in sessions)
            output = sum(sum(o for *_, o in c) for c in sessions) * PRICES[model][3] / 1e6
            if model == "haiku-5.5":
                output = sum(o * price(model, p)[3] for c in sessions for p, _, _, o in c) / 1e6
            out.setdefault("output_share", {})[f"{model}-{'cached' if cached else 'uncached'}"] = output / total
    for exp, cheap in PAIRS:
        row = {}
        for label, cached, factor in (("cached", True, 1.0), ("uncached", False, 1.0),
                                      ("cached_output_2.51x", True, 2.51)):
            ratios = [cost(c, cheap, cached, factor) / cost(c, exp, cached) for c in sessions]
            agg = sum(cost(c, cheap, cached, factor) for c in sessions) / sum(cost(c, exp, cached) for c in sessions)
            row[label] = {"aggregate_cost_ratio": agg, "aggregate_breakeven_steps": 1 / agg,
                          "session_cost_ratio": summarize(ratios),
                          "session_breakeven_steps": summarize([1 / r for r in ratios])}
        sticker = PRICES[cheap][0] / PRICES[exp][0]
        row["sticker_input_ratio"] = sticker
        out["pairs"][f"{exp}->{cheap}"] = row
    print(json.dumps(out, indent=2))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1])
