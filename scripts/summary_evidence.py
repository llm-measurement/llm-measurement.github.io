# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Render measured page values and the claim ledger from recorded evidence."""
from decimal import Decimal, ROUND_CEILING
import hashlib
import html
import json
from string import Template


def evidence(root):
    folder = root / "assets/summary-evidence/recorded"
    return {p.stem: json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))}


def claims(root):
    data = evidence(root)
    result = data["sketch-results"]
    daily = result["unions"]["1"]
    ranges = result["ranges"]["queries"]
    scale = data["scale"]
    contributions = result["contributors"]
    entries = {
        "storage": ("sketch-results", "ranges.storage.tracelab", result["ranges"]["storage"]["tracelab"],
            "Sum the two platform-summary files per day; measure source JSONL and compressed download separately.",
            "venv/bin/python scripts/sketch_experiments.py"),
        "overlap": ("overlap", "", data["overlap"],
            "Exact released-label sets in the shared pseudonym namespace.", "venv/bin/python scripts/data_audit.py"),
        "daily-union": ("sketch-results", "unions.1.union_abs_error", daily["union_abs_error"],
            "Merge the two daily HLL++ states and compare with the exact union.", "venv/bin/python scripts/sketch_experiments.py"),
        "ranges": ("sketch-results", "ranges.queries", ranges,
            "Every contiguous range; timing is median of five whole batches divided by query count.", "venv/bin/python scripts/sketch_experiments.py"),
        "scale": ("scale", "", scale,
            "Isolated processes, mandatory identity events then Zipf(1.2), exact keyed-table comparison.",
            "for seed in 20261010 20261011 20261012; do ./scale data/weights.json evidence/scale-isolated-1000000-$seed 1000000 $seed; done"),
        "contributors": ("sketch-results", "contributors", contributions,
            "Adjacent-day key deltas; flag when the two largest positive lower bounds exceed half of positive total growth.", "venv/bin/python scripts/sketch_experiments.py"),
        "privacy": ("privacy", "", data["privacy"],
            "Known identifiers in serialized summaries; separate decoded-artifact and injected-leak checks; OS denial probe before analyst execution.",
            "venv/bin/python scripts/isolated_analyst.py && venv/bin/python scripts/privacy_audit.py && venv/bin/python scripts/record_results.py"),
        "small-lists": ("sketch-results", "unions.1", {
            "sketch_mean_bytes": daily["hll_exchange_bytes"]["mean"],
            "raw_list_mean_bytes": daily["raw_list_bytes"]["mean"]},
            "Mean daily size of the pair of HLL++ payloads versus compact JSON for the pair of raw label lists.", "venv/bin/python scripts/sketch_experiments.py"),
    }
    ledger = {"status": "Draft for review; site publication held", "environment_evidence": "recorded/run.json", "claims": {}}
    for name, (source, field, values, method, command) in entries.items():
        path = root / "assets/summary-evidence/recorded" / (source + ".json")
        ledger["claims"][name] = {"evidence": f"recorded/{source}.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                 "field": field, "values": values, "method": method, "command": command}
    return ledger


def upper(value, places):
    return format(Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_CEILING), f".{places}f")


def page_values(root):
    data = evidence(root)
    results = data["sketch-results"]
    store = results["ranges"]["storage"]["tracelab"]
    daily = results["unions"]["1"]
    ranges = results["ranges"]["queries"]
    scale = data["scale"]
    contributor = results["contributors"]
    privacy = data["privacy"]
    scan = privacy["known_identifier_scan"]
    run = data["run"]
    sizes = {row["hll_bytes"] + row["fi_bytes"] for row in scale}
    populations = {row["n"] for row in scale}
    assert len(sizes) == len(populations) == 1
    exact_mb = sorted({f'{row["exact_json_bytes"] / 1e6:.1f}' for row in scale})
    recall = sorted({f'{100 * row["top20_recall"]:g}' for row in scale})
    assert len(recall) == 1
    return {
        "days": str(store["days"]), "summary_mb": f'{store["summary_bytes"] / 1e6:.1f}',
        "source_gb": f'{store["raw_bytes"] / 1e9:.2f}', "summary_bytes": f'{store["summary_bytes"]:,}',
        "source_bytes": f'{store["raw_bytes"]:,}', "source_gzip_bytes": f'{store["raw_compressed_bytes"]:,}',
        "union_error": upper(daily["union_abs_error"]["max"], 4),
        "union_days": str(daily["union_abs_error"]["n"]),
        "claude_users": str(data["overlap"]["claude_labels"]), "codex_users": str(data["overlap"]["codex_labels"]),
        "union_users": str(data["overlap"]["union_labels"]), "sum_users": str(data["overlap"]["naive_sum_labels"]),
        "query_count": str(sum(row["queries"] for row in ranges)),
        "range_days": ", ".join(str(row["days"]) for row in ranges),
        "range_error": upper(max(row["absolute_error"]["max"] for row in ranges), 4),
        "query_ms": upper(max(row["median_ms_per_query"] for row in ranges), 3),
        "scale_users": f'{next(iter(populations)):,}', "scale_bytes": f'{next(iter(sizes)):,}',
        "exact_mb": " to ".join(exact_mb),
        "scale_min_error": f'{100 * min(row["distinct_relative_error"] for row in scale):.1f}',
        "scale_max_error": f'{100 * max(row["distinct_relative_error"] for row in scale):.1f}',
        "scale_seeds": str(len(scale)), "top_recall": recall[0],
        "user_flags": str(contributor["top_users"]["true_positive"]),
        "session_flags": str(contributor["top_sessions"]["true_positive"]),
        "flag_misses": str(sum(row["false_negative"] for row in contributor.values())),
        "extra_flags": str(sum(row["false_positive"] for row in contributor.values())),
        "key_checks": f'{sum(row["keys_checked"] for row in contributor.values()):,}',
        "bound_violations": str(sum(row["bound_violations"] for row in contributor.values())),
        "raw_hits": str(len(scan["raw_identity_hits"])), "raw_ids": f'{scan["raw_identity_values"]:,}',
        "raw_files": f'{scan["files_scanned"]:,}',
        "analyst_files": f'{privacy["analyst_artifact_scan"]["checks"]["files_scanned"]:,}',
        "decoded_hits": str(privacy["analyst_artifact_scan"]["checks"]["leak_findings"]),
        "sketch_daily_bytes": str(round(daily["hll_exchange_bytes"]["mean"])),
        "list_daily_bytes": str(round(daily["raw_list_bytes"]["mean"])),
        "machine": html.escape(run["machine"]), "os": html.escape(run["os"]),
        "go": html.escape(run["go"]), "python": html.escape(run["python"]),
        "sketchkit": html.escape(run["sketchkit"]), "collector_source": run["collector_source"],
    }


def render(root):
    return Template((root / "pages/summaries.html").read_text()).substitute(page_values(root))
