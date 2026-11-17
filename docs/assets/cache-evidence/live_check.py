#!/usr/bin/env python3
"""Live check of the two prompt-caching rules the post depends on (Anthropic API, Claude Haiku 5.5).

1. Refresh. Does a cache read extend a 1-hour entry's lifetime? A 5-minute arm checks the method on the
   documented case. Each refresh arm has a control prefix that is written at the same time and read only once, late:
     1-hour: write at 0, read at 50 min, read at 100 min.  Control: write at 0, read at 100 min.
     5-min:  write at 0, read at 4, 8 and 12 min.          Control: write at 0, read at 12 min.
   A hit at the last read with a miss on the control means reads refresh the entry. If the control also hits,
   entries outlived their lifetime and the arm is inconclusive.
2. Concurrency, three repetitions of three fan-outs of five calls, each on a fresh prefix:
     together:      all five start at the same moment;
     first token:   one streamed call, the other four sent when its first text token arrives;
     message start: one streamed call, the other four sent when its message_start event arrives.

Every prefix is about 20,000 tokens (the post's size) and starts with its own random nonce, so no earlier cache
entry can be hit. Thinking is off, the reply is capped at 8 tokens, and nothing is retried.

Standard library only. Run:
  python3 live_check.py --key-file KEY_FILE --out OUT_DIR [--preflight]
KEY_FILE must be a regular file you own with mode 0600 holding one Anthropic API key; it is read once and never
printed or written. OUT_DIR gets events.jsonl (private: includes request IDs) and summary.json (no IDs).
--preflight sends two tiny calls (one with a 1-hour marker on a prompt too short to cache) and calibrates the prefix
length with the free token-counting endpoint, then exits.
"""

import argparse
import http.client
import json
import os
import platform
import re
import secrets
import ssl
import stat
import sys
import threading
import time

HOST = "api.anthropic.com"
MODEL = "claude-haiku-5-5"
API_VERSION = "2023-06-01"
PRICE_IN = 0.10 / 1e6   # USD per input token, Claude Haiku 5.5, prompts of 100K tokens or fewer
PRICE_OUT = 0.50 / 1e6
WRITE_MULT = {"5m": 1.25, "1h": 2.0}
READ_MULT = 0.10
SPEND_STOP_USD = 0.60   # hard backstop on estimated spend; the planned run is about $0.11
TARGET_PREFIX_TOKENS = 20000
MAX_TOKENS = 8
USER_TEXT = "Reply with the single word OK."
FANOUT = 5

_lock = threading.Lock()


def read_key(path):
    st = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        sys.exit("key file must be a regular file you own with mode 0600")
    with open(path, "r", encoding="ascii") as f:
        key = f.read().strip()
    if not re.fullmatch(r"sk-ant-[A-Za-z0-9_\-]{20,200}", key):
        sys.exit("key file does not hold one Anthropic API key")
    return key


def make_prefix(nonce, sections):
    topics = ["travel", "expenses", "equipment", "security reviews", "data retention", "vendor contracts",
              "hiring", "leave", "incident response", "customer data", "software licences", "office access"]
    roles = ["the team lead", "the finance partner", "the security office", "the department head", "legal"]
    registers = ["approvals", "assets", "contracts", "incidents", "access", "records"]
    lines = [f"Policy manual, edition {nonce}. Answer questions using only the sections below.", ""]
    for i in range(1, sections + 1):
        t = topics[i % len(topics)]
        lines.append(
            f"Section {i}. {t.capitalize()}: a request about {t} above {(i * 137) % 9000 + 250} dollars needs "
            f"written approval from {roles[i % len(roles)]} within {i % 9 + 2} business days. The approval is filed "
            f"in the {registers[i % len(registers)]} register under reference {nonce[:6]}-{i:04d} and kept for "
            f"{i % 7 + 3} years. Exceptions are reviewed every {i % 11 + 1} weeks.")
    return "\n".join(lines)


def request_body(prefix, ttl, stream=False):
    cc = {"type": "ephemeral"} if ttl == "5m" else {"type": "ephemeral", "ttl": "1h"}
    body = {"model": MODEL, "max_tokens": MAX_TOKENS, "thinking": {"type": "disabled"},
            "system": [{"type": "text", "text": prefix, "cache_control": cc}],
            "messages": [{"role": "user", "content": USER_TEXT}]}
    if stream:
        body["stream"] = True
    return body


class Call:
    """One HTTPS request on its own connection, so calls can be pre-connected and fired together."""

    def __init__(self, key, body, path="/v1/messages"):
        self.conn = http.client.HTTPSConnection(HOST, timeout=180, context=ssl.create_default_context())
        self.raw = json.dumps(body).encode()
        self.stream = bool(body.get("stream"))
        self.path = path
        self.headers = {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"}

    def connect(self):
        self.conn.connect()

    def send(self, on_event=None):
        rec = {"t_send": time.time()}
        m0 = time.monotonic()
        ms = lambda: round((time.monotonic() - m0) * 1000.0, 1)  # noqa: E731
        try:
            self.conn.request("POST", self.path, body=self.raw, headers=self.headers)
            resp = self.conn.getresponse()
            rec["status"] = resp.status
            rec["ms_headers"] = ms()
            rec["request_id"] = resp.getheader("request-id")
            rec["ratelimit"] = {k.lower(): v for k, v in resp.getheaders() if k.lower().startswith("anthropic-ratelimit")}
            if resp.status != 200:
                raw = resp.read(65536)
                try:
                    err = json.loads(raw).get("error", {})
                    rec["error"] = {"type": err.get("type"), "message": str(err.get("message"))[:300]}
                except ValueError:
                    rec["error"] = {"type": "unparsed", "message": raw[:300].decode("utf-8", "replace")}
                return rec
            if not self.stream:
                data = json.loads(resp.read(1 << 20))
                rec["usage"] = data.get("usage")
                rec["model"] = data.get("model")
                rec["stop_reason"] = data.get("stop_reason")
                if "input_tokens" in data and "usage" not in data:  # token counting endpoint
                    rec["input_tokens"] = data["input_tokens"]
            else:
                event = None
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    line = line.decode("utf-8").rstrip("\r\n")
                    if line.startswith("event:"):
                        event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:])
                    if event == "message_start":
                        rec["ms_message_start"] = ms()
                        rec["usage"] = data["message"].get("usage")
                        rec["model"] = data["message"].get("model")
                    elif event == "content_block_delta" and "ms_first_delta" not in rec:
                        rec["ms_first_delta"] = ms()
                    elif event == "message_delta":
                        rec["usage_final"] = data.get("usage")
                        rec["stop_reason"] = data.get("delta", {}).get("stop_reason")
                    elif event == "error":
                        rec["error"] = data.get("error")
                    if on_event:
                        on_event(event, rec, ms())
                    if event == "message_stop":
                        break
        except (OSError, http.client.HTTPException, ValueError) as e:
            rec["error"] = {"type": "transport", "message": f"{type(e).__name__}: {e}"[:300]}
        finally:
            rec["ms_done"] = ms()
            self.conn.close()
        return rec


def usage_of(rec):
    u = dict(rec.get("usage") or {})
    for k, v in (rec.get("usage_final") or {}).items():
        if v is not None and k.startswith(("cache_", "input_", "output_")):
            u[k] = v
    return u


def kind_of(rec):
    if rec.get("error") or rec.get("status") != 200:
        return "error"
    u = usage_of(rec)
    w, r = u.get("cache_creation_input_tokens") or 0, u.get("cache_read_input_tokens") or 0
    return "write" if w and not r else "read" if r and not w else "both" if w and r else "none"


def cost_of(rec, ttl):
    u = usage_of(rec)
    cc = u.get("cache_creation") or {}
    c5, c1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    w = u.get("cache_creation_input_tokens") or 0
    if c5 is None and c1 is None:
        c5, c1 = (w, 0) if ttl == "5m" else (0, w)
    units = ((u.get("input_tokens") or 0) + 1.25 * (c5 or 0) + 2.0 * (c1 or 0)
             + READ_MULT * (u.get("cache_read_input_tokens") or 0))
    return units * PRICE_IN + (u.get("output_tokens") or 0) * PRICE_OUT


class Run:
    def __init__(self, key, out, sections, prefix_tokens):
        self.key, self.out, self.sections, self.prefix_tokens = key, out, sections, prefix_tokens
        self.spent = 0.0
        self.records = []
        self.events_fd = os.open(os.path.join(out, "events.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)

    def worst_case(self, n):
        return n * ((self.prefix_tokens * WRITE_MULT["1h"] + 100) * PRICE_IN + MAX_TOKENS * PRICE_OUT)

    def guard(self, n):
        if self.spent + self.worst_case(n) > SPEND_STOP_USD:
            raise SystemExit(f"spend backstop: ${self.spent:.4f} spent, next {n} calls could pass ${SPEND_STOP_USD}")

    def log(self, arm, rep, idx, role, ttl, rec, extra=None):
        rec = dict(rec, arm=arm, rep=rep, idx=idx, role=role, ttl=ttl, kind=kind_of(rec))
        rec["cost_usd"] = cost_of(rec, ttl)
        if extra:
            rec.update(extra)
        with _lock:
            self.spent += rec["cost_usd"]
            self.records.append(rec)
            os.write(self.events_fd, (json.dumps(rec, sort_keys=True) + "\n").encode())
            os.fsync(self.events_fd)
        u = usage_of(rec)
        print(f"{time.strftime('%H:%M:%S')} {arm:14s} rep {rep} call {idx} {role:8s} {rec['kind']:5s} "
              f"write {u.get('cache_creation_input_tokens')} read {u.get('cache_read_input_tokens')} "
              f"input {u.get('input_tokens')} status {rec.get('status')} {rec.get('error') or ''}", flush=True)
        return rec

    def prefix(self):
        return make_prefix(secrets.token_hex(8), self.sections)

    def sequential(self, arm, prefix, ttl, idx, planned, arm_t0=None):
        self.guard(1)
        rec = Call(self.key, request_body(prefix, ttl)).send()
        offset = 0.0 if arm_t0 is None else round(rec["t_send"] - arm_t0, 1)
        return self.log(arm, 1, idx, "single", ttl, rec, {"planned_offset_s": planned, "offset_s": offset})

    def together(self, rep):
        self.guard(FANOUT)
        body = request_body(self.prefix(), "5m")
        calls = [Call(self.key, body) for _ in range(FANOUT)]
        for c in calls:
            c.connect()
        barrier, out = threading.Barrier(FANOUT), [None] * FANOUT

        def go(i):
            barrier.wait()
            out[i] = calls[i].send()
        threads = [threading.Thread(target=go, args=(i,)) for i in range(FANOUT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        out = [r if r is not None else {"t_send": time.time(), "error": {"type": "thread", "message": "no result"}}
               for r in out]
        t0 = min(r["t_send"] for r in out)
        for i, r in enumerate(out):
            self.log("together", rep, i + 1, "peer", "5m", r, {"ms_after_first_send": round((r["t_send"] - t0) * 1000, 1)})

    def leader_followers(self, arm, rep, trigger):
        self.guard(FANOUT)
        prefix = self.prefix()
        followers = [Call(self.key, request_body(prefix, "5m")) for _ in range(FANOUT - 1)]
        for c in followers:
            c.connect()
        leader = Call(self.key, request_body(prefix, "5m", stream=True))
        leader.connect()
        fire, abort, out = threading.Event(), threading.Event(), [None] * (FANOUT - 1)

        def follow(i):
            fire.wait(timeout=180)
            out[i] = None if abort.is_set() or not fire.is_set() else followers[i].send()
        threads = [threading.Thread(target=follow, args=(i,)) for i in range(FANOUT - 1)]
        for t in threads:
            t.start()
        trig = {}

        def on_event(event, rec, at_ms):
            if event == trigger and not fire.is_set():
                trig["ms_trigger"] = at_ms
                fire.set()
        lrec = leader.send(on_event)
        if not fire.is_set():
            abort.set()
            fire.set()
        for t in threads:
            t.join()
        self.log(arm, rep, 1, "leader", "5m", lrec, {"trigger": trigger, **trig})
        for i, r in enumerate(out):
            if r is None:
                print(f"{arm} rep {rep}: follower {i + 2} not sent (leader failed)", flush=True)
                continue
            self.log(arm, rep, i + 2, "follower", "5m", r,
                     {"ms_after_leader_send": round((r["t_send"] - lrec["t_send"]) * 1000, 1)})


def wait_until(t):
    while True:
        d = t - time.time()
        if d <= 0:
            return
        time.sleep(min(d, 10.0))


def calibrate(key):
    probe = 100
    body = request_body(make_prefix("0" * 16, probe), "5m")
    rec = Call(key, {k: body[k] for k in ("model", "system", "messages")}, path="/v1/messages/count_tokens").send()
    if rec.get("status") != 200:
        sys.exit(f"token counting failed: {rec.get('status')} {rec.get('error')}")
    per = rec["input_tokens"] / probe
    sections = max(10, round(TARGET_PREFIX_TOKENS / per))
    body = request_body(make_prefix("0" * 16, sections), "5m")
    rec = Call(key, {k: body[k] for k in ("model", "system", "messages")}, path="/v1/messages/count_tokens").send()
    return sections, rec["input_tokens"]


def preflight(key):
    tiny = {"model": MODEL, "max_tokens": MAX_TOKENS, "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": USER_TEXT}]}
    for label, body in (("plain", tiny), ("1h marker on a short prompt", dict(tiny, system=[
            {"type": "text", "text": "You are terse.", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]))):
        rec = Call(key, body).send()
        print(f"{label}: status {rec.get('status')} model {rec.get('model')} usage {rec.get('usage')} "
              f"error {rec.get('error')}")
        if label == "plain":
            for k, v in sorted(rec.get("ratelimit", {}).items()):
                if k.endswith(("-limit", "-remaining")):
                    print(f"  {k}: {v}")
    sections, tokens = calibrate(key)
    print(f"calibration: {sections} sections give {tokens} input tokens (prefix plus the short user turn)")


def summarize(run, meta):
    recs = run.records

    def seq(arm):
        return sorted((r for r in recs if r["arm"] == arm), key=lambda r: r["idx"])

    def refresh_verdict(main, control):
        m, c = seq(main), seq(control)
        if len(m) < 2 or len(c) < 2 or any(r["kind"] == "error" for r in m + c):
            return "incomplete"
        if c[-1]["kind"] == "read":
            return "inconclusive: the control entry outlived its lifetime"
        if any(r["kind"] != "read" for r in m[1:-1]):
            return "unexpected: an intermediate read missed"
        return {"read": "reads refresh the entry", "write": "reads do not refresh the entry"}.get(m[-1]["kind"], "unexpected")

    def slim(r):
        u = usage_of(r)
        keep = {k: r.get(k) for k in ("arm", "rep", "idx", "role", "ttl", "kind", "status", "offset_s", "planned_offset_s",
                                       "ms_after_first_send", "ms_after_leader_send", "ms_trigger", "ms_message_start",
                                       "ms_first_delta", "ms_headers", "ms_done", "trigger", "model", "stop_reason", "error")
                if r.get(k) is not None}
        keep["usage"] = {k: u.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                               "cache_creation", "output_tokens") if k in u}
        keep["cost_usd"] = round(r["cost_usd"], 6)
        return keep

    fan = {}
    for arm in ("together", "first token", "message start"):
        rows = [r for r in recs if r["arm"] == arm]
        fan[arm] = {"calls": len(rows), "writes": sum(r["kind"] == "write" for r in rows),
                    "reads": sum(r["kind"] == "read" for r in rows),
                    "other": sum(r["kind"] not in ("write", "read") for r in rows)}
    summary = dict(meta, spent_usd_estimate=round(run.spent, 6),
                   verdicts={"1h refresh": refresh_verdict("1h refresh", "1h control"),
                             "5m refresh": refresh_verdict("5m refresh", "5m control")},
                   fanout=fan, calls=[slim(r) for r in sorted(recs, key=lambda r: r["t_send"])])
    path = os.path.join(run.out, "summary.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    print("\nVerdicts:")
    for k, v in summary["verdicts"].items():
        print(f"  {k}: {v}")
    for arm, s in fan.items():
        print(f"  fan-out, {arm}: {s['writes']} writes, {s['reads']} reads, {s['other']} other, of {s['calls']} calls")
    print(f"Estimated spend: ${run.spent:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--preflight", action="store_true")
    a = ap.parse_args()
    key = read_key(a.key_file)
    if a.preflight:
        preflight(key)
        return
    os.makedirs(a.out, mode=0o700, exist_ok=True)
    sections, tokens = calibrate(key)
    meta = {"model": MODEL, "api_version": API_VERSION, "prefix_sections": sections,
            "counted_input_tokens": tokens, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "machine": f"{platform.machine()} {platform.system()} {platform.release()}",
            "python": sys.version.split()[0], "fanout": FANOUT, "max_tokens": MAX_TOKENS}
    print(f"prefix: {sections} sections, {tokens} counted input tokens; spend backstop ${SPEND_STOP_USD}", flush=True)
    run = Run(key, a.out, sections, tokens)

    # Timed arms. Offsets are measured from the start of each arm's first call.
    plan = {"1h refresh": ("1h", [3000, 6000]), "1h control": ("1h", [6000]),
            "5m refresh": ("5m", [240, 480, 720]), "5m control": ("5m", [720])}
    queue = []
    for arm, (ttl, offsets) in plan.items():
        p = run.prefix()
        first = run.sequential(arm, p, ttl, 1, 0)
        for j, off in enumerate(offsets, start=2):
            queue.append((first["t_send"] + off, arm, p, ttl, j, off, first["t_send"]))
    # Fan-outs, two minutes apart so the writes stay well inside input-token rate limits.
    t_start = time.time()
    for rep in (1, 2, 3):
        queue.append((t_start + 120 * rep - 60, "fanout", None, None, rep, None, None))
    queue.sort(key=lambda q: q[0])
    for due, arm, p, ttl, j, off, arm_t0 in queue:
        wait_until(due)
        if arm == "fanout":
            run.together(j)
            run.leader_followers("first token", j, "content_block_delta")
            run.leader_followers("message start", j, "message_start")
        else:
            run.sequential(arm, p, ttl, j, off, arm_t0)
    summarize(run, meta)


if __name__ == "__main__":
    main()
