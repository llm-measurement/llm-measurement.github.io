#!/usr/bin/env python3
"""Evidence for the post "Same prompt, same cache, opposite bills".

Computes, from Anthropic's published prompt-caching rules and prices (checked Nov 5, 2026):
  - the exact break-even ratio of cache-read to cache-write tokens,
  - the matching share of short gaps between calls,
  - closed forms for random (Poisson) arrivals,
  - an event-level simulation of four services that make the same 24 calls a day.

Cache rules modeled (Anthropic docs, prompt caching page):
  - A miss on a cacheable prefix writes an entry at w times the base input price
    (w = 1.25 for the 5-minute lifetime, 2.0 for the 1-hour lifetime).
  - A hit reads the prefix at rho times the base price (0.1 by default).
  - The lifetime is measured from the start of the request that writes or reads,
    and each use refreshes it. The docs state the refresh for the 5-minute cache;
    this script applies it to both lifetimes, and also reports the no-refresh case
    (closed form for random arrivals, and a 1-hour simulation of every service).
  - An entry becomes available to other requests only after the writing request's
    response starts (FIRST_TOKEN_S after its start here).

Costs are for the shared prefix only, relative to sending it with no caching.
Standard library only; deterministic seeds. Run: python3 cache_puzzle.py [--json out.json]
"""

import json
import math
import platform
import random
import sys

PRICES = {"write_5m": 1.25, "write_1h": 2.0, "read": 0.1}
READ_EXCEPTIONS = {"0.05x models": 0.05, "0.025x models": 0.025}
TTL_MIN = {"5m": 5.0, "1h": 60.0}
FIRST_TOKEN_S = 2.0
DAYS = 30
CALLS_PER_DAY = 24


def breakeven_reads_per_write(w, rho):
    """Savings = (1 - rho) * R - (w - 1) * W in base-price prefix tokens, so caching pays iff R/W > (w-1)/(1-rho)."""
    return (w - 1.0) / (1.0 - rho)


def breakeven_short_gap_share(k):
    """With sequential calls, R/W = q/(1-q) where q is the share of gaps shorter than the lifetime."""
    return k / (1.0 + k)


def poisson_cost_ratio(w, rho, mean_gap_min, ttl_min, refresh=True):
    """Prefix cost relative to no caching, for Poisson arrivals on one prefix."""
    lt = ttl_min / mean_gap_min
    if refresh:
        q = 1.0 - math.exp(-lt)  # share of calls that arrive before the entry expires
        return (1.0 - q) * w + q * rho
    reads_per_write = lt  # no refresh: arrivals during the fixed lifetime after a write
    return (w + reads_per_write * rho) / (1.0 + reads_per_write)


def solve(f, lo, hi, iters=200):
    """Bisection for a sign change of f on [lo, hi]."""
    flo = f(lo)
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if (f(mid) > 0) == (flo > 0):
            lo, flo = mid, f(mid)
        else:
            hi = mid
    return (lo + hi) / 2.0


def simulate(starts_s, ttl_min, w, rho, refresh=True):
    """Event-level cache for one prefix. Returns writes, reads and the cost ratio.

    With refresh=False a read does not extend the entry, which expires ttl after the write that created it.
    """
    ttl_s = ttl_min * 60.0
    available_at = None  # when the current entry becomes readable
    expires_at = None
    writes = reads = 0
    for s in sorted(starts_s):
        live = expires_at is not None and s < expires_at
        if live and available_at <= s:
            reads += 1
            if refresh:
                expires_at = s + ttl_s
        else:
            writes += 1
            if not live:
                available_at = s + FIRST_TOKEN_S
            expires_at = max(expires_at or 0.0, s + ttl_s)
    n = writes + reads
    return {"calls": n, "writes": writes, "reads": reads,
            "cost_ratio": (w * writes + rho * reads) / n}


def gap_share_below(starts_s, ttl_min):
    s = sorted(starts_s)
    gaps = [b - a for a, b in zip(s, s[1:])]
    return sum(g < ttl_min * 60.0 for g in gaps) / len(gaps)


def services():
    day = 86400.0
    out = {}
    # 1. A scheduled job: every 30 minutes from 08:00 to 19:30.
    out["scheduled job, every 30 min"] = [d * day + 8 * 3600 + i * 1800 for d in range(DAYS) for i in range(CALLS_PER_DAY)]
    # 2. People using an internal tool at random times, 24 calls a day on average.
    rng = random.Random(20261105)
    t, xs = 0.0, []
    while True:
        t += rng.expovariate(CALLS_PER_DAY / day)
        if t >= DAYS * day:
            break
        xs.append(t)
    out["people, random times"] = xs
    # 3. An agent loop: once a day, 24 calls in a row, each starting 10 s after the last.
    rng = random.Random(7)
    out["agent loop, one burst a day"] = _bursts(rng, day, spacing=10.0)
    # 4. A fan-out: once a day, 24 sub-agents launched within half a second.
    rng = random.Random(11)
    out["fan-out, 24 at once"] = _bursts(rng, day, spacing=0.02)
    # 4b. The fix: one call first, the other 23 after its response starts (3 s later).
    rng = random.Random(11)
    fixed = []
    for d in range(DAYS):
        base = d * day + rng.uniform(0, day - 600)
        fixed.append(base)
        fixed.extend(base + 3.0 + i * 0.02 for i in range(CALLS_PER_DAY - 1))
    out["fan-out, one call first"] = fixed
    return out


def _bursts(rng, day, spacing):
    xs = []
    for d in range(DAYS):
        base = d * day + rng.uniform(0, day - 600)
        xs.extend(base + i * spacing for i in range(CALLS_PER_DAY))
    return xs


def main():
    rho = PRICES["read"]
    res = {"machine": f"{platform.machine()} {platform.system()} {platform.release()}",
           "python": sys.version.split()[0], "prices": PRICES, "first_token_s": FIRST_TOKEN_S,
           "days": DAYS, "calls_per_day": CALLS_PER_DAY}

    be = {}
    for name, w, ttl in (("5m", PRICES["write_5m"], 5.0), ("1h", PRICES["write_1h"], 60.0)):
        row = {}
        for label, r in (("default", rho), *READ_EXCEPTIONS.items()):
            k = breakeven_reads_per_write(w, r)
            q = breakeven_short_gap_share(k)
            row[label] = {"reads_per_write": k, "short_gap_share": q,
                          "poisson_mean_gap_min": ttl / math.log(1.0 + k)}
        k = breakeven_reads_per_write(w, rho)
        row["default"]["poisson_mean_gap_min_no_refresh"] = ttl / k
        be[name] = row
    res["breakeven"] = be

    cross = solve(lambda g: poisson_cost_ratio(2.0, rho, g, 60.0) - poisson_cost_ratio(1.25, rho, g, 5.0), 1.0, 1000.0)
    res["poisson_1h_cheaper_than_5m_when_mean_gap_below_min"] = cross

    sims = {}
    for name, starts in services().items():
        r5 = simulate(starts, 5.0, PRICES["write_5m"], rho)
        r60 = simulate(starts, 60.0, PRICES["write_1h"], rho)
        r60_fixed = simulate(starts, 60.0, PRICES["write_1h"], rho, refresh=False)
        sims[name] = {"5m": r5, "1h": r60, "1h_no_refresh": r60_fixed,
                      "share_of_gaps_under_5m": gap_share_below(starts, 5.0),
                      "share_of_gaps_under_1h": gap_share_below(starts, 60.0)}
    res["services"] = sims
    res["poisson_closed_form_mean_gap_60"] = {
        "5m": poisson_cost_ratio(1.25, rho, 60.0, 5.0), "1h": poisson_cost_ratio(2.0, rho, 60.0, 60.0)}

    print(f"Machine: {res['machine']}; Python {res['python']}")
    print("Break-even (default read price 0.1x):")
    for name in ("5m", "1h"):
        d = be[name]["default"]
        print(f"  {name}: reads/writes > {d['reads_per_write']:.3f}; short-gap share > {d['short_gap_share']:.1%}; "
              f"random arrivals: mean gap < {d['poisson_mean_gap_min']:.1f} min "
              f"(no refresh: {d['poisson_mean_gap_min_no_refresh']:.1f} min)")
        for label in READ_EXCEPTIONS:
            print(f"     {label}: reads/writes > {be[name][label]['reads_per_write']:.3f}")
    print(f"Random arrivals: the 1-hour cache is cheaper than the 5-minute cache when the mean gap is below {cross:.1f} min")
    cf = res["poisson_closed_form_mean_gap_60"]
    print(f"Closed form, random arrivals every 60 min on average: 5m {cf['5m'] - 1:+.1%}, 1h {cf['1h'] - 1:+.1%}")
    print(f"Services ({DAYS} days, prefix cost change versus no caching):")
    for name, s in sims.items():
        print(f"  {name:30s} calls {s['5m']['calls']:4d}  5m {s['5m']['cost_ratio'] - 1:+7.1%} "
              f"(W {s['5m']['writes']:3d}, R {s['5m']['reads']:3d}, gaps<5m {s['share_of_gaps_under_5m']:5.1%})  "
              f"1h {s['1h']['cost_ratio'] - 1:+7.1%} (W {s['1h']['writes']:3d}, R {s['1h']['reads']:3d}, "
              f"gaps<1h {s['share_of_gaps_under_1h']:5.1%})")
    print("If reads did not refresh the 1-hour cache (prefix cost change versus no caching):")
    for name, s in sims.items():
        f = s["1h_no_refresh"]
        print(f"  {name:30s} 1h {f['cost_ratio'] - 1:+7.1%} (W {f['writes']:3d}, R {f['reads']:3d})")

    if "--json" in sys.argv:
        path = sys.argv[sys.argv.index("--json") + 1]
        with open(path, "w") as f:
            json.dump(res, f, indent=2, sort_keys=True)
            f.write("\n")


if __name__ == "__main__":
    main()
