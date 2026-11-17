#!/usr/bin/env python3
"""Replay Anthropic-style prompt caching over a public Claude Code trace.

Input: traces.jsonl from semianalysisai/cc-traces-weka-061526 (Apache-2.0), revision
42610fc7e9449cde53d41a7aaf43660ae7856214, SHA-256
a9f3345b964f7d9f8b1445f83995fc4b5994f183131b0a108cd21b15cc78f627.

Each session lists requests with a start time t (seconds from session start), model, input size
`in` (64-token prefix blocks x 64), `hash_ids` (one ID per 64-token block; requests with the same
leading content share leading IDs, scoped to one session), api_time, and ttft for streamed calls.
Subagents appear as entries with their own inner requests.

Cache model (Anthropic's documented rules, checked live on Nov 5, 2026):
  - Each request offers its whole prompt for caching. It reads the longest leading run of its blocks
    that is cached, live and already available, and writes the rest.
  - Entries are per model. A read or write sets the block's expiry to request start + lifetime
    (5 or 60 minutes), so reads refresh.
  - A written block becomes readable only after the writing response starts: start + ttft for
    streamed calls, start + api_time for the others (an upper bound, since their ttft isn't recorded).
  - Prices relative to base input: write 1.25x (5 min) or 2x (1 h), read 0.1x. Costs cover the
    cacheable input only. Output costs the same either way.

This is a replay of real arrival times and real prefix structure under a modeled cache. It is not a
record of what these sessions were billed. Standard library only. Run:
  python3 trace_replay.py TRACES_JSONL [--json out.json]
"""

import json
import statistics
import sys

BLOCK = 64
WRITE = {300.0: 1.25, 3600.0: 2.0}
READ = 0.10
FANOUT_WINDOW_S = 1.0   # subagents starting within this window of each other count as one parallel launch


def flatten(session):
    """All model requests in start order, tagged with their agent (main or subagent id)."""
    out = []
    for r in session["requests"]:
        if r.get("type") == "subagent":
            for q in r.get("requests", []):
                out.append(dict(q, agent=r["agent_id"]))
        else:
            out.append(dict(r, agent="main"))
    out.sort(key=lambda q: q["t"])
    return out


def replay(reqs, ttl):
    """Return read and written token totals for one session under one lifetime.

    Written tokens are split three ways: first writes of blocks never cached before (unavoidable at
    any lifetime), rewrites of blocks that had expired, and concurrent rewrites of blocks another
    request had written but whose response hadn't started yet (the fan-out case).
    """
    cache = {}  # (model, block_id) -> [available_at, expires_at]
    seen = set()
    read = written = 0
    split = {"first": 0, "expired": 0, "concurrent": 0}
    for q in reqs:
        t, model, blocks = q["t"], q["model"], q["hash_ids"]
        avail = t + (q["ttft"] if q.get("ttft") is not None else q.get("api_time") or 0.0)
        k = 0
        for b in blocks:
            e = cache.get((model, b))
            if e is None or e[1] <= t or e[0] > t:
                break
            k += 1
        read += k * BLOCK
        written += (len(blocks) - k) * BLOCK
        for i, b in enumerate(blocks):
            key = (model, b)
            if i < k:
                cache[key][1] = t + ttl
                continue
            e = cache.get(key)
            if e is not None and e[1] > t:          # live: written by a request whose response hasn't started
                split["concurrent"] += BLOCK
                e[1] = max(e[1], t + ttl)
            else:
                split["expired" if key in seen else "first"] += BLOCK
                cache[key] = [avail, t + ttl]
            seen.add(key)
    return read, written, split


def cost_ratio(read, written, ttl):
    total = read + written
    return (WRITE[ttl] * written + READ * read) / total if total else None


def gaps(reqs):
    """Start-to-start gaps between consecutive requests of the same agent and model."""
    last, out = {}, []
    for q in reqs:
        key = (q["agent"], q["model"])
        if key in last:
            out.append(q["t"] - last[key])
        last[key] = q["t"]
    return out


def fanout(session):
    """Parallel subagent launches: siblings starting within FANOUT_WINDOW_S of the first."""
    subs = sorted((r for r in session["requests"] if r.get("type") == "subagent"), key=lambda r: r["t"])
    groups, cur = [], []
    for s in subs:
        if cur and s["t"] - cur[0]["t"] > FANOUT_WINDOW_S:
            groups.append(cur)
            cur = []
        cur.append(s)
    if cur:
        groups.append(cur)
    res = []
    for g in groups:
        if len(g) < 2:
            continue
        firsts = [s["requests"][0] for s in g if s.get("requests")]
        if len(firsts) < 2:
            continue
        lead = min(firsts, key=lambda q: q["t"])
        ready = lead["t"] + (lead.get("ttft") or lead.get("api_time") or 0.0)
        shared = []
        for q in firsts:
            if q is lead or q["model"] != lead["model"]:
                continue
            n = 0
            for a, b in zip(lead["hash_ids"], q["hash_ids"]):
                if a != b:
                    break
                n += 1
            shared.append((n, q["t"] < ready, q["t"] - lead["t"]))
        res.append({"size": len(g), "same_model_siblings": len(shared),
                    "shared_blocks": [n for n, _, _ in shared],
                    "started_before_lead_ready": sum(1 for n, early, _ in shared if early and n > 0),
                    "shared_tokens_rewritten": sum(n * BLOCK for n, early, _ in shared if early),
                    "start_offsets_s": [off for _, _, off in shared]})
    return res


def offsets(fan):
    v = sorted(o for f in fan for o in f["start_offsets_s"])
    return {"n": len(v), "median": statistics.median(v), "max": v[-1],
            "share_under_0.2s": sum(o < 0.2 for o in v) / len(v), "share_under_0.5s": sum(o < 0.5 for o in v) / len(v)}


def price_sensitivity(sessions):
    """Read and written tokens don't depend on prices, so other read prices are a re-pricing."""
    out = {}
    for rho in (0.10, 0.05, 0.025):
        c = {ttl: [(WRITE[ttl] * x[str(int(ttl))]["written"] + rho * x[str(int(ttl))]["read"]) /
                   (x[str(int(ttl))]["written"] + x[str(int(ttl))]["read"]) for x in sessions] for ttl in WRITE}
        base = sum(x["300"]["written"] + x["300"]["read"] for x in sessions)
        agg = {ttl: sum(WRITE[ttl] * x[str(int(ttl))]["written"] + rho * x[str(int(ttl))]["read"] for x in sessions) / base
               for ttl in WRITE}
        out[str(rho)] = {"aggregate_saving_5min": 1 - agg[300.0], "aggregate_saving_1h": 1 - agg[3600.0],
                         "sessions_pay_5min": sum(v < 1 for v in c[300.0]), "sessions_pay_1h": sum(v < 1 for v in c[3600.0]),
                         "sessions_1h_cheaper": sum(b < a for a, b in zip(c[300.0], c[3600.0])),
                         "sessions_5min_cheaper": sum(a < b for a, b in zip(c[300.0], c[3600.0]))}
    return out


def main():
    path = sys.argv[1]
    sessions, all_gaps, fan = [], [], []
    with open(path) as f:
        for line in f:
            s = json.loads(line)
            reqs = [q for q in flatten(s) if q.get("hash_ids")]
            row = {"requests": len(reqs), "subagents": sum(1 for r in s["requests"] if r.get("type") == "subagent")}
            for ttl in WRITE:
                r, w, sp = replay(reqs, ttl)
                row[str(int(ttl))] = {"read": r, "written": w, "rw": (r / w) if w else None,
                                      "cost_ratio": cost_ratio(r, w, ttl), "written_split": sp}
            g = gaps(reqs)
            all_gaps.extend(g)
            row["gap_median_s"] = statistics.median(g) if g else None
            fan.extend(fanout(s))
            sessions.append(row)

    n = len(sessions)
    tot = {ttl: {"read": sum(x[str(int(ttl))]["read"] for x in sessions),
                 "written": sum(x[str(int(ttl))]["written"] for x in sessions)} for ttl in WRITE}
    for ttl, d in tot.items():
        d["written_split"] = {k: sum(x[str(int(ttl))]["written_split"][k] for x in sessions)
                              for k in ("first", "expired", "concurrent")}
        d["cost_ratio"] = cost_ratio(d["read"], d["written"], ttl)
        d["rw"] = d["read"] / d["written"]
    pays5 = sum(1 for x in sessions if x["300"]["cost_ratio"] is not None and x["300"]["cost_ratio"] < 1)
    pays60 = sum(1 for x in sessions if x["3600"]["cost_ratio"] is not None and x["3600"]["cost_ratio"] < 1)
    h_better = sum(1 for x in sessions if x["3600"]["cost_ratio"] < x["300"]["cost_ratio"])
    s_better = sum(1 for x in sessions if x["300"]["cost_ratio"] < x["3600"]["cost_ratio"])
    g_sorted = sorted(all_gaps)
    share = lambda c: sum(1 for x in g_sorted if x < c) / len(g_sorted)
    out = {
        "sessions": n, "model_requests": sum(x["requests"] for x in sessions),
        "gaps": {"count": len(g_sorted), "median_s": statistics.median(g_sorted),
                 "p90_s": g_sorted[int(0.9 * len(g_sorted))], "under_5min": share(300), "under_60min": share(3600)},
        "totals": {str(int(k)): v for k, v in tot.items()},
        "sessions_where_5min_pays": pays5, "sessions_where_1h_pays": pays60,
        "sessions_1h_cheaper_than_5min": h_better, "sessions_5min_cheaper_than_1h": s_better,
        "cost_ratio_5min_quartiles": statistics.quantiles([x["300"]["cost_ratio"] for x in sessions], n=4),
        "cost_ratio_1h_quartiles": statistics.quantiles([x["3600"]["cost_ratio"] for x in sessions], n=4),
        "read_price_sensitivity": price_sensitivity(sessions),
        "fanout": {"sibling_start_offset_s": offsets(fan), "parallel_launches": len(fan), "siblings_same_model": sum(f["same_model_siblings"] for f in fan),
                   "siblings_started_before_lead_ready_with_shared_prefix": sum(f["started_before_lead_ready"] for f in fan),
                   "shared_tokens_rewritten": sum(f["shared_tokens_rewritten"] for f in fan),
                   "launch_sizes": sorted(f["size"] for f in fan)},
    }
    print(json.dumps(out, indent=2))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as f:
            json.dump({"summary": out, "sessions": sessions}, f, indent=1, sort_keys=True)
            f.write("\n")


if __name__ == "__main__":
    main()
