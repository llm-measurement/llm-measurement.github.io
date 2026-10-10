#!/usr/bin/env python3
"""Validate pinned source records against exact reference totals and identities."""

from __future__ import annotations

import argparse
import ast
import collections
import csv
import datetime as dt
from decimal import Decimal
import functools
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import re
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EVIDENCE = ROOT / "evidence"
SOURCES = EVIDENCE / "data-audit-sources"
KEY = "llm-measurement-summary-evidence-test-key-20261010"
SEED = 20261010
TRACE_REV = "61fea8f97277d0aa247cc2e4c7e31f90ed2bea1c"
BURST_REV = "7eb2c4f8350f8a6985272386f5c14af1f678b299"
HASHES = {
    "syfi_coding_trace.jsonl.gz": "11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65",
    "BurstGPT_1.csv": "4bb3783693d0a435686fbfc885615d2349bd067239079fa4b749f2e679e12122",
    "BurstGPT_2.csv": "44bf5942b03fca42c01a226a545ad3a750ec62688faecd67b6831c56a8928bf7",
}
METRICS = ("requests", "input_tokens", "output_tokens", "missing_token_usage", "complete_tokens")
IDENTITY_KEYS = {"user", "user_name", "username", "session_id", "round_id", "turn_id",
                 "trace_key", "project", "tool_call_id", "continuation_of_tool_call_id",
                 "_assistant_uuid"}
TRACE_START = dt.date(2025, 9, 23)
TRACE_END = dt.date(2026, 7, 25)
BURST_EPOCH = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
BURST_COPIED_BLOCKS = ((2, 710854, 604800), (2296677, 2965272, 518400))


class CopiedBlock:
    """Match later copies of a pinned CSV block, preserving row multiplicity."""

    def __init__(self, first, last, shift):
        self.first, self.last, self.shift = first, last, shift
        self.pending = collections.Counter()
        self.source_rows = self.removed = 0
        self.first_copy = self.last_copy = None
        self.digest = hashlib.sha256()

    def observe(self, line, row):
        key = (burst_offset(row["Timestamp"]), row["Model"], int(row["Request tokens"]),
               int(row["Response tokens"]), int(row["Total tokens"]), row["Log Type"])
        if self.first <= line <= self.last:
            shifted = (key[0] + self.shift, *key[1:])
            self.pending[shifted] += 1
            self.source_rows += 1
            self.digest.update((json.dumps([str(shifted[0]), *shifted[1:]],
                                          separators=(",", ":")) + "\n").encode())
        elif line > self.last and self.pending.get(key, 0):
            self.pending[key] -= 1
            if not self.pending[key]:
                del self.pending[key]
            self.removed += 1
            if self.first_copy is None:
                self.first_copy = line
            self.last_copy = line
            return True
        return False

    def result(self):
        require(self.source_rows == self.last - self.first + 1, "copied-block source incomplete")
        require(not self.pending and self.removed == self.source_rows,
                "copied-block match incomplete; refuse to sample weights")
        return {"source_lines_inclusive": [self.first, self.last],
                "shift_seconds": self.shift, "removed_rows": self.removed,
                "first_copy_line": self.first_copy, "last_copy_line": self.last_copy,
                "shifted_source_sha256": self.digest.hexdigest(), "all_rows_matched": True}


def observe_day_gap(days, offset):
    index = int(offset // 86400)
    if index not in days:
        days[index] = {"rows": 0, "first": offset, "last": offset, "gap": Decimal(0)}
    day = days[index]
    require(offset >= day["last"], "daily gap check requires timestamp order")
    day["gap"] = max(day["gap"], offset - day["last"])
    day["last"] = offset
    day["rows"] += 1


def daily_gap_report(days, first, last):
    report = []
    for index in range(int(first // 86400), int(last // 86400) + 1):
        start, end = Decimal(index * 86400), Decimal((index + 1) * 86400)
        day = days.get(index)
        report.append({"offset_day": index, "rows": day["rows"] if day else 0,
            "maximum_gap_with_day_edges_seconds": float(max(
                day["gap"], day["first"] - start, end - day["last"])) if day else 86400.0})
    return report


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        stream.write(value)
    temporary.replace(path)


def write_json(path, value, *, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, sort_keys=True, ensure_ascii=True,
                  indent=None if compact else 2,
                  separators=(",", ":") if compact else None)
        stream.write("\n")
    temporary.replace(path)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "llm-measurement-summary-evidence"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_sources():
    """Read public pinned source only; never import or execute upstream code."""
    documents = [
        ("tracelab-sanitizer.py", "uw-syfi/TraceLab", TRACE_REV, "scripts/sanitize_round_trace.py", None),
        ("tracelab-privacy.py", "uw-syfi/TraceLab", TRACE_REV, "scripts/trace_privacy.py", None),
        ("tracelab-license.md", "uw-syfi/TraceLab", TRACE_REV, "LICENSE-DATASET.md", "TraceLab-LICENSE-DATASET.md"),
        ("burstgpt-license.txt", "HPMLL/BurstGPT", BURST_REV, "LICENSE", "BurstGPT-LICENSE.txt"),
        ("burstgpt-readme.md", "HPMLL/BurstGPT", BURST_REV, "README.md", None),
    ]
    pins = {"documents": {}, "releases": {}}
    for name, repo, rev, source_path, local in documents:
        url = f"https://raw.githubusercontent.com/{repo}/{rev}/{source_path}"
        body = fetch(url)
        if local:
            require(body == (DATA / local).read_bytes(), f"pinned license mismatch: {local}")
        write_text(SOURCES / name, body.decode("utf-8"))
        pins["documents"][name] = {
            "source_url": f"https://github.com/{repo}/blob/{rev}/{source_path}",
            "download_url": url, "revision": rev,
            "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
            "local_license_matches": True if local else None,
        }
    for name, repo, tag, revision, filenames in (
        ("tracelab", "uw-syfi/TraceLab", "v0.0.2", TRACE_REV, ["syfi_coding_trace.jsonl.gz"]),
        ("burstgpt", "HPMLL/BurstGPT", "v2.0", BURST_REV, ["BurstGPT_1.csv", "BurstGPT_2.csv"]),
    ):
        ref_url = f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}"
        ref = json.loads(fetch(ref_url))
        require(ref["object"]["type"] == "commit" and ref["object"]["sha"] == revision,
                f"release revision mismatch: {name}")
        release = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/tags/{tag}"))
        assets = {}
        for asset in release["assets"]:
            if asset["name"] in filenames:
                digest = asset.get("digest")
                if digest:
                    require(digest == "sha256:" + HASHES[asset["name"]], "release asset digest mismatch")
                assets[asset["name"]] = {k: asset.get(k) for k in (
                    "browser_download_url", "size", "digest", "created_at", "updated_at")}
        require(set(assets) == set(filenames), f"release asset missing: {name}")
        pins["releases"][name] = {"source_url": release["html_url"], "tag": tag,
            "revision": revision, "tag_ref_url": ref_url, "tag_ref_verified": True,
            "assets": assets, "published_at": release["published_at"]}
    write_json(EVIDENCE / "data-audit-source-pins.json", pins)
    print("Pinned source, licenses, release tags, and asset metadata verified.", flush=True)


def source_checks():
    pins = json.loads((EVIDENCE / "data-audit-source-pins.json").read_text())
    for name, info in pins["documents"].items():
        require(sha256(SOURCES / name) == info["sha256"], f"cached source changed: {name}")
    for saved, original in (("tracelab-license.md", "TraceLab-LICENSE-DATASET.md"),
                            ("burstgpt-license.txt", "BurstGPT-LICENSE.txt")):
        require(sha256(SOURCES / saved) == sha256(DATA / original), "saved license changed")
    tree = ast.parse((SOURCES / "tracelab-sanitizer.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "StableIdSanitizer")
    user = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "user")
    require([x.arg for x in user.args.args] == ["self", "original"], "user namespace signature changed")
    call = user.body[0].value
    require(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "map_value" and ast.literal_eval(call.args[0]) == "user"
            and isinstance(call.args[1], ast.Name) and call.args[1].id == "original",
            "user map is not provider-independent")
    mapper = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "map_value")
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    constructors = [n for n in ast.walk(main) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "StableIdSanitizer"]
    require(len(constructors) == 1, "sanitizer instance count changed")
    first_loop = min(n.lineno for n in ast.walk(main) if isinstance(n, ast.For))
    require(constructors[0].lineno < first_loop, "sanitizer is not shared across input rows")
    privacy_tree = ast.parse((SOURCES / "tracelab-privacy.py").read_text())
    user_keys = next(ast.literal_eval(n.value) for n in privacy_tree.body
                     if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                     and t.id == "USER_KEYS" for t in n.targets))
    require("user" in user_keys, "user key not pseudonymized")
    pins["namespace_verification"] = {
        "provider_independent_user_map": True, "one_sanitizer_instance_before_row_loop": True,
        "user_function_lines": [user.lineno, user.end_lineno],
        "map_value_function_lines": [mapper.lineno, mapper.end_lineno],
        "shared_instance_line": constructors[0].lineno, "user_keys": sorted(user_keys),
        "interpretation": "Released pseudonym equality is comparable across providers within this release; not verified human identity or cross-release identity.",
    }
    return pins


def dates_between(start, end):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days)]


def empty_counts():
    return dict.fromkeys(METRICS, 0)


def row_counts(inp, out):
    for value in (inp, out):
        require(value is None or (type(value) is int and value >= 0), "invalid token count")
    missing = inp is None or out is None
    return {"requests": 1, "input_tokens": inp or 0, "output_tokens": out or 0,
            "missing_token_usage": int(missing),
            "complete_tokens": 0 if missing else inp + out}


def add_counts(target, addition):
    for name in METRICS:
        target[name] += addition[name]


def collect_identities(value, target):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in IDENTITY_KEYS and isinstance(child, str) and child:
                target.add(child)
            elif isinstance(child, (dict, list)):
                collect_identities(child, target)
    elif isinstance(value, list):
        for child in value:
            collect_identities(child, target)


def reconcile_days(days, groups):
    checks = 0
    for daily in days.values():
        counts = daily["counts"]
        for prefix in groups:
            for name in METRICS:
                require(sum(v[name] for k, v in counts.items() if k.startswith(prefix))
                        == counts["total"][name], f"daily {prefix} reconciliation failed")
                checks += 1
    return checks


def aggregate_days(days):
    totals = collections.defaultdict(empty_counts)
    for day in days.values():
        for group, counts in day["counts"].items():
            add_counts(totals[group], counts)
    return dict(sorted(totals.items()))


def audit_tracelab():
    from llm_sketchkit import canon
    from llm_sketchkit import hash as keyed_hash

    reference_dir = ROOT / "collector/examples/tracelab"
    sys.path.insert(0, str(reference_dir))
    import audit as reference_audit
    import run as reference_run

    path = DATA / "syfi_coding_trace.jsonl.gz"
    print("TraceLab: running existing source audit.", flush=True)
    source_audit = reference_audit.audit(path)
    require(reference_audit.SHA256 == HASHES[path.name], "reference data pin mismatch")
    print("TraceLab: running unmodified source_oracle reference.", flush=True)
    reference = reference_run.source_oracle(path, KEY)
    secret = keyed_hash.Secret(KEY.encode())

    @functools.lru_cache(maxsize=None)
    def identity_hash(domain, value):
        digest = keyed_hash.digest64_hex(secret, domain, canon.canonicalize_text_v1(value))
        require(digest == reference_run.identity_hash(KEY, domain, value), "identity hash parity failure")
        require(re.fullmatch("[0-9a-f]{16}", digest), "invalid keyed hash encoding")
        return digest

    dates = dates_between(TRACE_START, TRACE_END)
    days = {day: {"users": {"claude": set(), "codex": set()},
                  "counts": collections.defaultdict(empty_counts),
                  "top_users": collections.Counter(), "top_sessions": collections.Counter()}
            for day in dates}
    identities = set()
    provider_users = {"claude": set(), "codex": set()}
    models, cells, model_times = set(), set(), {}
    raw_bytes = 0
    first = last = None
    print("TraceLab: building local daily sets, cells, and keyed weights.", flush=True)
    with gzip.open(path, "rb") as stream:
        for line in stream:
            raw_bytes += len(line)
            row = json.loads(line)
            at = reference_audit.timestamp(row)
            require(at is not None and at.tzinfo is not None, "missing or naive TraceLab timestamp")
            at = at.astimezone(dt.timezone.utc)
            first = at if first is None else min(first, at)
            last = at if last is None else max(last, at)
            day = at.date().isoformat()
            require(day in days, "TraceLab row outside preregistered window")
            provider, model = row["provider"], row["model"]
            require(provider in provider_users and bool(model), "invalid TraceLab provider/model")
            counts = row_counts(row["input_tokens_total"], row["output_tokens"])
            target = days[day]
            cell = f"cell:{provider}:{model}"
            for group in ("total", f"platform:{provider}", f"model:{model}", cell):
                add_counts(target["counts"][group], counts)
            target["users"][provider].add(row["user"])
            provider_users[provider].add(row["user"])
            models.add(model)
            cells.add(cell)
            if model not in model_times:
                model_times[model] = [at, at]
            model_times[model] = [min(model_times[model][0], at), max(model_times[model][1], at)]
            weight = counts["input_tokens"] + counts["output_tokens"]
            target["top_users"][identity_hash(keyed_hash.USER_V1, row["user"])] += weight
            session = json.dumps([row["user"], row["session_id"]], separators=(",", ":"), ensure_ascii=False)
            target["top_sessions"][identity_hash(keyed_hash.SESSION_V1, session)] += weight
            collect_identities(row, identities)
    all_groups = ["total", "platform:claude", "platform:codex"] + ["model:" + m for m in sorted(models)] + sorted(cells)
    reference_checks = 0
    for day, target in days.items():
        for group in all_groups:
            target["counts"].setdefault(group, empty_counts())
        target["users"] = {p: sorted(v) for p, v in target["users"].items()}
        expected = reference.get(day, {"counters": {}, "top_users": {}, "top_sessions": {}})
        for metric in METRICS[:-1]:
            require(target["counts"]["total"][metric] == expected["counters"].get(metric, 0),
                    "existing source_oracle daily total mismatch")
            reference_checks += 1
        for ranking in ("top_users", "top_sessions"):
            require(dict(target[ranking]) == dict(expected[ranking]), "existing source_oracle weight mismatch")
            reference_checks += 1
    checks = reconcile_days(days, ("platform:", "model:", "cell:"))
    aggregates = aggregate_days(days)
    require(aggregates["total"]["requests"] == source_audit["totals"]["steps"], "TraceLab audit row mismatch")
    for field, metric in (("input_tokens_total", "input_tokens"), ("output_tokens", "output_tokens")):
        require(aggregates["total"][metric] == source_audit["totals"][field], "TraceLab audit tokens mismatch")
    claude, codex = provider_users["claude"], provider_users["codex"]
    overlap = {"claude_labels": len(claude), "codex_labels": len(codex),
               "union_labels": len(claude | codex), "intersection_labels": len(claude & codex),
               "naive_sum_labels": len(claude) + len(codex),
               "naive_overcount_labels": len(claude & codex),
               "naive_overcount_fraction_of_union": len(claude & codex) / len(claude | codex),
               "both_provider_days": sum(bool(x["users"]["claude"]) and bool(x["users"]["codex"]) for x in days.values()),
               "days_with_shared_labels": sum(bool(set(x["users"]["claude"]) & set(x["users"]["codex"])) for x in days.values()),
               "interpretation": "Observed pseudonymous label overlap, not inferred humans."}
    zeros = [d for d, x in days.items() if not x["counts"]["total"]["requests"]]
    public = {"counts": aggregates, "overlap": overlap, "models": sorted(models),
        "cells": sorted(cells), "first_timestamp_utc": first.isoformat(), "last_timestamp_utc": last.isoformat(),
        "window_start": dates[0], "window_end_exclusive": TRACE_END.isoformat(),
        "calendar_days": len(dates), "active_days": len(dates) - len(zeros), "zero_activity_dates": zeros,
        "compressed_bytes": path.stat().st_size, "uncompressed_bytes": raw_bytes,
        "source_audit_totals": source_audit["totals"], "source_audit_issues": source_audit["issues"],
        "event_types": source_audit["event_types"],
        "model_timestamp_ranges": {m: [a.isoformat(), b.isoformat()] for m, (a, b) in sorted(model_times.items())},
        "existing_oracle_checks": reference_checks, "hierarchy_checks": checks,
        "hash_parity_unique_inputs": identity_hash.cache_info().currsize,
        "raw_identity_values_count": len(identities),
        "raw_identity_utf8_bytes": sum(len(v.encode()) for v in identities),
        "raw_user_session_json_bytes_by_day_total": sum(len(json.dumps(x["users"], separators=(",", ":")).encode()) for x in days.values()),
        "top_weight_semantics": "Exact existing source_oracle input+output recorded weight; all current TraceLab attempts must be complete to equal connector complete-attempt weights.",
        "timestamp_rule": "Existing audit.timestamp: latest text/reasoning/tool_call/usage_report event, converted to UTC.",
        "normalization": "Use released input_tokens_total, including Claude uncached + cache creation + cache read; never add those subsets again.",
        "boundary_interpretation": "Fixed preregistered 305-day release window; zero-event dates retained. Event endpoints alone do not certify continuous source observation."}
    return {"dates": dates, "days": days, "raw_identity_values": sorted(identities)}, public


def burst_offset(value):
    offset = Decimal(value)
    require(offset.is_finite() and offset >= 0, "invalid BurstGPT offset")
    return offset


def audit_burstgpt():
    days = collections.defaultdict(lambda: {"counts": collections.defaultdict(empty_counts)})
    files, sample = [], []
    random_source = random.Random(SEED)
    successful = sample_population = 0
    blocks = [CopiedBlock(*spec) for spec in BURST_COPIED_BLOCKS]
    raw_gaps, retained_gaps = {}, {}
    retained_counts = empty_counts()
    first = last = None
    expected_headers = ["Timestamp", "Model", "Request tokens", "Response tokens", "Total tokens", "Log Type"]
    for name in ("BurstGPT_1.csv", "BurstGPT_2.csv"):
        print(f"BurstGPT: auditing {name}.", flush=True)
        file_counts = empty_counts()
        info = {"name": name, "counts": file_counts, "log_types": collections.Counter(),
                "models": collections.Counter(), "out_of_order_rows": 0,
                "consecutive_identical_rows": 0, "total_token_column_mismatches": 0,
                "fractional_timestamp_rows": 0, "maximum_adjacent_gap_seconds": 0}
        file_first = file_last = previous_offset = None
        previous_row = None
        dates_seen = set()
        first_in_file = last_in_file = None
        with (DATA / name).open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            require(reader.fieldnames == expected_headers, "unexpected BurstGPT CSV schema")
            for line, row in enumerate(reader, 2):
                offset = burst_offset(row["Timestamp"])
                observe_day_gap(raw_gaps, offset)
                copied = sum(block.observe(line, row) for block in blocks) if name == "BurstGPT_2.csv" else 0
                require(copied <= 1, "overlapping copied blocks")
                if first_in_file is None:
                    first_in_file = offset
                last_in_file = offset
                day_index = int(offset // 86400)
                day = (BURST_EPOCH.date() + dt.timedelta(days=day_index)).isoformat()
                dates_seen.add(day)
                model = row["Model"]
                require(model in ("ChatGPT", "GPT-4"), "unexpected BurstGPT model")
                inp, out, total = (int(row[k]) for k in ("Request tokens", "Response tokens", "Total tokens"))
                require(inp >= 0 and out >= 0 and total >= 0, "negative BurstGPT token value")
                counts = row_counts(inp, None if out == 0 else out)
                if not copied:
                    observe_day_gap(retained_gaps, offset)
                    add_counts(retained_counts, counts)
                for group in ("total", "model:" + model):
                    add_counts(days[day]["counts"][group], counts)
                add_counts(file_counts, counts)
                info["total_token_column_mismatches"] += total != inp + out
                info["fractional_timestamp_rows"] += offset != offset.to_integral_value()
                info["models"][model] += 1
                info["log_types"][row["Log Type"]] += 1
                info["consecutive_identical_rows"] += row == previous_row
                if previous_offset is not None:
                    info["out_of_order_rows"] += offset < previous_offset
                    info["maximum_adjacent_gap_seconds"] = max(info["maximum_adjacent_gap_seconds"], float(offset - previous_offset))
                previous_offset, previous_row = offset, row
                file_first = offset if file_first is None else min(file_first, offset)
                file_last = offset if file_last is None else max(file_last, offset)
                if out > 0:
                    successful += 1
                if out > 0 and not copied:
                    sample_population += 1
                    if len(sample) < 100000:
                        sample.append(inp + out)
                    else:
                        index = random_source.randrange(sample_population)
                        if index < len(sample):
                            sample[index] = inp + out
        require(file_first is not None, "empty BurstGPT file")
        first = file_first if first is None else min(first, file_first)
        last = file_last if last is None else max(last, file_last)
        info.update({"minimum_offset_seconds": str(file_first), "maximum_offset_seconds": str(file_last),
                     "first_row_offset_seconds": str(first_in_file), "last_row_offset_seconds": str(last_in_file),
                     "first_synthetic_timestamp": (BURST_EPOCH + dt.timedelta(seconds=float(file_first))).isoformat(),
                     "last_synthetic_timestamp": (BURST_EPOCH + dt.timedelta(seconds=float(file_last))).isoformat(),
                     "active_days": len(dates_seen), "first_day": min(dates_seen), "last_day": max(dates_seen),
                     "bytes": (DATA / name).stat().st_size})
        files.append(info)
    start_day = BURST_EPOCH.date() + dt.timedelta(days=int(first // 86400))
    end_day = BURST_EPOCH.date() + dt.timedelta(days=int(last // 86400) + 1)
    dates = dates_between(start_day, end_day)
    for day in dates:
        for group in ("total", "model:ChatGPT", "model:GPT-4"):
            days[day]["counts"].setdefault(group, empty_counts())
    days = {d: days[d] for d in dates}
    checks = reconcile_days(days, ("model:",))
    totals = aggregate_days(days)
    require(successful == totals["total"]["requests"] - totals["total"]["missing_token_usage"], "success count mismatch")
    block_results = [block.result() for block in blocks]
    removed_rows = sum(block["removed_rows"] for block in block_results)
    require(removed_rows == 1379449, "pinned duplicate count changed")
    require(retained_counts["requests"] + removed_rows == totals["total"]["requests"], "dedup count mismatch")
    require(sample_population == retained_counts["requests"] - retained_counts["missing_token_usage"], "dedup success count mismatch")
    deduplication = {
        "file": "BurstGPT_2.csv", "blocks": block_results, "removed_rows": removed_rows,
        "fraction_of_both_files": removed_rows / totals["total"]["requests"],
        "retained_counts": retained_counts, "successful_sampling_population": sample_population,
        "method": "Match all six fields with exact Decimal timestamp shifts and row multiplicity; retain source occurrences, remove only later matching copies before reservoir sampling.",
        "replay_scope": "Original rows remain in the accounting replay and exact counter reconciliation; synthetic scale weights use only deduplicated successful rows."}
    daily_gaps = {"source": daily_gap_report(raw_gaps, first, last),
                  "deduplicated": daily_gap_report(retained_gaps, first, last),
                  "interpretation": "Largest gap between recorded events or a calendar-day edge. A day without retained events is an observation gap, not measured zero demand."}
    continuity = {
        "second_min_minus_first_max_seconds": float(Decimal(files[1]["minimum_offset_seconds"]) - Decimal(files[0]["maximum_offset_seconds"])),
        "overlapping_offset_ranges": Decimal(files[1]["minimum_offset_seconds"]) <= Decimal(files[0]["maximum_offset_seconds"]),
        "zero_activity_dates": [d for d, x in days.items() if x["counts"]["total"]["requests"] == 0],
        "interpretation": "One unchanged offset axis; positive inter-file gap is time between observed requests, not proof of lost requests."}
    require(not continuity["overlapping_offset_ranges"], "BurstGPT file ranges overlap: do not concatenate by inventing dates")
    boundary = {"first_event_seconds_after_day_start": float(first % 86400),
        "seconds_from_last_event_to_end_exclusive": float(Decimal((end_day - BURST_EPOCH.date()).days * 86400) - last),
        "first_synthetic_timestamp": (BURST_EPOCH + dt.timedelta(seconds=float(first))).isoformat(),
        "last_synthetic_timestamp": (BURST_EPOCH + dt.timedelta(seconds=float(last))).isoformat(),
        "replay_start": dt.datetime.combine(start_day, dt.time(), dt.timezone.utc).isoformat(),
        "replay_end_exclusive": dt.datetime.combine(end_day, dt.time(), dt.timezone.utc).isoformat(),
        "excluded_quality_dates": [dates[0], dates[-1]],
        "quality_days": len(dates[1:-1]),
        "decision": "Conservatively exclude first and last event-containing days from quality evaluation. Five-second edge gaps alone do not establish partial collection; complete edge observation is unverified, not proven absent. Replay retains all 121 days."}
    info = {"counts": totals, "files": files, "calendar_days": len(dates),
        "active_days": sum(bool(d["counts"]["total"]["requests"]) for d in days.values()),
        "calendar_is_synthetic": True, "calendar_zero": BURST_EPOCH.isoformat(),
        "minimum_offset_seconds": str(first), "maximum_offset_seconds": str(last),
        "continuity": continuity, "boundaries": boundary, "hierarchy_checks": checks,
        "deduplication": deduplication, "daily_gaps": daily_gaps,
        "successful_requests": successful,
        "known_input_on_failed_attempts": totals["total"]["input_tokens"] + totals["total"]["output_tokens"] - totals["total"]["complete_tokens"],
        "sample": {"method": "Algorithm R uniform reservoir over deduplicated successful rows, file1 then file2 source order",
                   "population": sample_population,
                   "seed": SEED, "size": len(sample), "minimum": min(sample), "maximum": max(sample),
                   "sha256_json": hashlib.sha256(json.dumps(sample, separators=(",", ":")).encode()).hexdigest()},
        "identity_columns_present": False,
        "failure_semantics": "Response tokens=0 is source failure: input retained, output absent, missing_token_usage=1, complete_tokens=0.",
        "source_documentation_anomalies": ["Pinned v2.0 README links v1.2 in Data section; exact v2.0 release assets are pinned by filename and SHA256.",
            "Pinned README describes new Session ID and Elapsed time columns, but the pinned files contain only the six audited columns; no user/session inference is possible."]}
    return {"dates": dates, "days": days, "success_weight_sample": sample,
            "quality_dates": dates[1:-1], "excluded_quality_dates": boundary["excluded_quality_dates"],
            "calendar_is_synthetic": True, "calendar_zero": BURST_EPOCH.isoformat(),
            "boundary_policy": boundary}, info


def contract_tests():
    require(row_counts(7, None) == dict(requests=1, input_tokens=7, output_tokens=0, missing_token_usage=1, complete_tokens=0), "missing output fixture")
    require(row_counts(None, 4)["complete_tokens"] == 0, "missing input fixture")
    require(row_counts(7, 0)["complete_tokens"] == 7, "known zero fixture")
    require(row_counts(7, 4)["complete_tokens"] == 11, "complete fixture")
    require(int(burst_offset("86399.999") // 86400) == 0, "fractional boundary fixture")
    require(int(burst_offset("86400.0") // 86400) == 1, "midnight fixture")
    require(len(dates_between(TRACE_START, TRACE_END)) == 305, "TraceLab calendar fixture")
    for invalid in ("NaN", "Infinity", "-1"):
        try:
            burst_offset(invalid)
        except AssertionError:
            pass
        else:
            raise AssertionError("invalid offset accepted")
    return 10


def render_report(evidence):
    t, b = evidence["tracelab"], evidence["burstgpt"]
    lines = ["# Summary Evidence Data Audit", "", "Exact source validation for the summary measurements.", "",
        "## Inputs And Attribution", "",
        f"- TraceLab v0.0.2, SyFI Lab, University of Washington; revision `{TRACE_REV}`.",
        f"- BurstGPT v2.0, Wang et al.; revision `{BURST_REV}`. [Paper](https://doi.org/10.1145/3711896.3737413).",
        "- Both saved licenses match their pinned sources byte-for-byte and identify CC BY 4.0. TraceLab explicitly separates released data from Apache-2.0 source code.",
        "- This is provenance verification, not a legal opinion or a guarantee of underlying contributor rights. Retain attribution, source/license links, and a modification notice in any approved derived release; imply no endorsement.",
        "- Changes here: UTC model-event daily grouping, keyed pseudonyms, exact aggregate validation, and a synthetic BurstGPT replay calendar. Raw-reference outputs stay local.", ""]
    for name, info in evidence["inputs"].items():
        lines.append(f"- `{name}`: SHA256 `{info['sha256']}`; {info['bytes']:,} bytes; verified.")
    lines.extend(["", "Pinned sources and license hashes:", ""])
    for name, info in evidence["sources"]["documents"].items():
        lines.append(f"- [{name}]({info['source_url']}): SHA256 `{info['sha256']}`.")
    for name, info in evidence["sources"]["releases"].items():
        lines.append(f"- [{name} release]({info['source_url']}): pinned tag reference verified; asset links and server digests retained in data-audit-source-pins.json.")
    o = t["overlap"]
    lines.extend(["", "## TraceLab", "",
        f"- {t['counts']['total']['requests']:,} model attempts across {t['calendar_days']} calendar days; {t['active_days']} active days.",
        f"- UTC model-event endpoints: `{t['first_timestamp_utc']}` to `{t['last_timestamp_utc']}`. Fixed replay window: 2025-09-23 through 2026-07-25 exclusive.",
        f"- Released labels: Claude {o['claude_labels']}, Codex {o['codex_labels']}, union {o['union_labels']}, intersection {o['intersection_labels']}; naive summation overcounts by {o['naive_overcount_labels']} labels ({100 * o['naive_overcount_fraction_of_union']:.2f}% of union).",
        "- Static inspection verifies provider-independent StableIdSanitizer.user mapping and one shared instance before the row loop. The observed release-label overlap is usable directly; it is not a count or verification of distinct humans, nor evidence of cross-release consistency.",
        f"- Existing audit.timestamp and unmodified run.source_oracle used. {t['existing_oracle_checks']:,} daily reference assertions and {t['hierarchy_checks']:,} hierarchy assertions passed; {t['hash_parity_unique_inputs']:,} unique hash inputs match sketchkit canonical/HMAC helpers exactly.",
        "- Released Claude input is already inclusive of uncached, cache creation and cache read; these are not summed twice.",
        f"- All source issues, including expected nullable provider-specific subsets, are retained in evidence. Nonzero issues: `{json.dumps({k:v for k,v in t['source_audit_issues'].items() if v}, sort_keys=True)}`.",
        "", "## BurstGPT", "",
        f"- {b['counts']['total']['requests']:,} attempts, {b['successful_requests']:,} successful and {b['counts']['total']['missing_token_usage']:,} failed; no user identifiers in these pinned files.",
        f"- Offset range `{b['minimum_offset_seconds']}` to `{b['maximum_offset_seconds']}` seconds; mapped only for replay to `{b['boundaries']['first_synthetic_timestamp']}` through `{b['boundaries']['last_synthetic_timestamp']}`.",
        f"- One unchanged offset axis across files, {b['calendar_days']} calendar days; no overlapping ranges. Inter-file last-to-first gap: {b['continuity']['second_min_minus_first_max_seconds']:g} seconds. This is an event gap, not evidence of lost traffic.",
        f"- Replay window: `{b['boundaries']['replay_start']}` to `{b['boundaries']['replay_end_exclusive']}` exclusive. These dates are synthetic, not observed UTC dates.",
        f"- Quality-only boundary exclusion: {', '.join(b['boundaries']['excluded_quality_dates'])}; retain {b['boundaries']['quality_days']} interior days. Edge gaps are {b['boundaries']['first_event_seconds_after_day_start']:g}s and {b['boundaries']['seconds_from_last_event_to_end_exclusive']:g}s. Exclusion is conservative because observation completeness is unverified; these event gaps do not prove partial collection.",
        f"- Source failures retain {b['known_input_on_failed_attempts']:,} known input tokens and absent output. Complete-token target excludes the whole failed attempt, not just its zero-coded output.",
        f"- Successful-request weight reservoir: {b['sample']['size']:,} values, Algorithm R, seed {SEED}; independent raw validation only.",
        f"- Removed {b['deduplication']['removed_rows']:,} later copied rows before sampling; {b['sample']['population']:,} successful rows remain in the sampling population. All six fields and row multiplicity match the pinned shifted blocks. Original rows remain only in accounting replay and reconciliation.",
        "- Daily-gap checks cover source and deduplicated rows separately, including calendar-day edges and empty retained days. Observation gaps are not measured zero demand; the numeric audit retains every day.",
        "- Pinned-source documentation anomalies: " + " ".join(b["source_documentation_anomalies"]), "",
        "## Exact Aggregate Reconciliation", "",
        "| Dataset / group | Requests | Input | Output | Missing usage | Complete tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for dataset, info in (("TraceLab", t), ("BurstGPT", b)):
        for group, counts in info["counts"].items():
            lines.append("| " + dataset + " / " + group + " | " + " | ".join(f"{counts[k]:,}" for k in METRICS) + " |")
    lines.extend(["", "## Reproduction And Privacy", "",
        "- Local reference: data/oracle.json (mode 0600), containing exact daily user sets, keyed user/session weights, raw identity scan values, all daily cells, and the BurstGPT reservoir. Keep it local and use it only for validation.",
        "- Small evidence: evidence/data-audit.json and evidence/data-audit-source-pins.json. Source snapshots: evidence/data-audit-sources/. No raw data rows or identity values are copied into the report.",
        "- The public experiment key is llm-measurement-summary-evidence-test-key-20261010; it is not a credential or a privacy secret. Keyed values remain linkable.",
        "- Replay uses a constant synthetic accounting-group prompt to expose connector complete-attempt total weight. The connector produces summaries; the reference tables validate them.",
        f"- Reproduce from `{ROOT}`: `venv/bin/python -B scripts/data_audit.py --fetch-sources`, then `venv/bin/python -B scripts/data_audit.py`. Offline reruns use verified cached source snapshots.",
        f"- Contract checks: {evidence['checks']['contract_tests']}; own script/evidence raw-identity scan hits: {evidence['checks']['raw_identity_leaks_in_shareable_audit_artifacts']}. Run privacy_audit.py separately on the analyst artifacts.",
        "", "## Judgment And Next Steps", "",
        "Positive for source validation: file pins, source/license provenance, daily exact counters and namespace evidence are verified. Sketch accuracy is measured in the subsequent experiments.",
        "Next: reconcile replay totals against oracle.json, read measurements from connector summaries, and keep failed-attempt input separate from complete tokens. Keep raw-reference artifacts local; report released pseudonym overlap.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-sources", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    if args.fetch_sources:
        fetch_sources()
        return
    started = time.perf_counter()
    sources = source_checks()
    inputs = {}
    for name, expected in HASHES.items():
        actual = sha256(DATA / name)
        require(actual == expected, f"dataset SHA256 mismatch: {name}")
        inputs[name] = {"sha256": actual, "bytes": (DATA / name).stat().st_size, "verified": True}
    checks = {"contract_tests": contract_tests(), "raw_identity_leaks_in_shareable_audit_artifacts": 0}
    tracelab_oracle, tracelab = audit_tracelab()
    burst_oracle, burstgpt = audit_burstgpt()
    require(tracelab["counts"]["total"]["missing_token_usage"] == 0,
            "TraceLab incomplete rows: existing oracle weights differ from connector complete-only weights")
    oracle = {"tracelab": tracelab_oracle, "burstgpt": burst_oracle}
    write_json(DATA / "oracle.json", oracle, compact=True)
    reference_files = [ROOT / "collector/examples/tracelab/audit.py", ROOT / "collector/examples/tracelab/run.py",
                       ROOT / "collector/connector/genaisketchconnector/internal/tracelab/rows.go"]
    evidence = {"schema_version": 1, "purpose": "Exact source validation for the summary measurements",
        "inputs": inputs, "sources": sources, "tracelab": tracelab, "burstgpt": burstgpt,
        "checks": checks, "reproducibility": {"python": sys.version, "platform": platform.platform(),
            "machine": platform.machine(), "llm_sketchkit": importlib.metadata.version("llm-sketchkit"),
            "script_sha256": sha256(Path(__file__)),
            "reference_source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in reference_files},
            "seed": SEED, "public_experiment_key": KEY,
            "elapsed_seconds": time.perf_counter() - started},
        "oracle": {"path": "data/oracle.json", "bytes": (DATA / "oracle.json").stat().st_size,
                   "sha256": sha256(DATA / "oracle.json"), "mode": oct((DATA / "oracle.json").stat().st_mode & 0o777),
                   "contains_raw_identifiers": True, "shareable": False}}
    rendered = render_report(evidence)
    shareable = [json.dumps(evidence, sort_keys=True), rendered, Path(__file__).read_text()]
    for value in tracelab_oracle["raw_identity_values"]:
        require(not any(value in text for text in shareable), "raw identity detected in audit evidence")
    write_json(EVIDENCE / "data-audit.json", evidence)
    write_text(ROOT / "DATA_AUDIT.md", rendered)
    print(json.dumps({"result": "audit complete", "trace_counts": tracelab["counts"]["total"],
                      "trace_overlap": tracelab["overlap"], "burst_counts": burstgpt["counts"]["total"],
                      "burst_boundaries": burstgpt["boundaries"], "oracle_bytes": evidence["oracle"]["bytes"]}, indent=2))


if __name__ == "__main__":
    main()
