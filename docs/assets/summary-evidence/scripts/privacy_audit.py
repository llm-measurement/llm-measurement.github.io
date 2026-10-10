#!/usr/bin/env python3
"""Audit the completed analyst artifact set for exact known identifier leaks."""

from __future__ import annotations

import base64
import collections
import csv
import datetime as dt
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import random
import re
import sys
import time

from google.protobuf.descriptor import FieldDescriptor
from llm_sketchkit import frequentitems, sketches_pb2, summary

from data_audit import ROOT, dates_between, require, sha256, write_json, write_text


SCOPES = ("analyst-inputs", "analyst-output", "data/sentinel")
TEST_SOURCE = ROOT / "collector/connector/genaisketchconnector/cmd/summary-replay/main_test.go"
LOG = ROOT / "evidence/analyst-sandbox.log"
EXPECTED = {
    "tracelab/platform-claude": ("claude", "2025-09-23", "2026-07-25"),
    "tracelab/platform-codex": ("codex", "2025-09-23", "2026-07-25"),
    "burstgpt/model-ChatGPT": ("g000", "2024-01-01", "2024-05-01"),
    "burstgpt/model-GPT-4": ("g001", "2024-01-01", "2024-05-01"),
}
OUTPUTS = {"features.json", "input-files.json"}


def planted_sentinels():
    # This bounded Go literal uses JSON-compatible quoted strings; reject other syntax.
    text = TEST_SOURCE.read_text()
    match = re.search(r'\bsentinels\s*:=\s*\[\]string\s*\{([^\n]+)\}', text)
    require(match is not None, "five-sentinel Go declaration not found")
    values = json.loads("[" + match.group(1) + "]")
    require(len(values) == len(set(values)) == 5 and all(isinstance(v, str) for v in values),
            "unexpected planted-sentinel declaration")
    return [v.encode("utf-8") for v in values]


def prefix_index(patterns):
    index = collections.defaultdict(lambda: collections.defaultdict(set))
    short = collections.defaultdict(set)
    for pattern in patterns:
        require(bool(pattern), "empty privacy pattern")
        if len(pattern) < 8:
            short[len(pattern)].add(pattern)
        else:
            index[pattern[:8]][len(pattern)].add(pattern)
    return dict(index), dict(short)


def matches(data, index):
    """Exact substring matching at every byte offset, including prefix collisions."""
    prefixes, short = index
    found = set()
    for offset in range(max(0, len(data) - 7)):
        candidates = prefixes.get(data[offset:offset + 8])
        if candidates:
            for length, patterns in candidates.items():
                value = data[offset:offset + length]
                if value in patterns:
                    found.add(value)
    for length, patterns in short.items():
        for offset in range(max(0, len(data) - length + 1)):
            value = data[offset:offset + length]
            if value in patterns:
                found.add(value)
    return found


def stamp(path):
    s = path.stat()
    return s.st_size, s.st_mtime_ns, s.st_ino


def inventory():
    result = []
    for scope in SCOPES:
        folder = ROOT / scope
        require(folder.is_dir() and not folder.is_symlink(), "missing or symlinked audit root")
        for path in sorted(folder.rglob("*")):
            require(not path.is_symlink(), "symlinks are excluded from this local audit")
            if path.is_file():
                result.append((scope, path, stamp(path)))
    require(all(any(s == scope for s, _, _ in result) for scope in SCOPES), "empty audit scope")
    return result


def completion_check(files):
    require(LOG.is_file(), "analyst sandbox completion log missing; wait for analyst run")
    results = []
    for line in LOG.read_text().splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "summary_files_read" in value and "series" in value:
            results.append(value)
    require(len(results) == 1, "expected one unambiguous completed analyst result")
    result = results[0]
    require(result.get("raw_reference_fields_present") is False, "unexpected analyst completion marker")
    input_root = ROOT / "analyst-inputs"
    directories = {str(p.relative_to(input_root)) for p in input_root.glob("*/*") if p.is_dir()}
    require(directories == set(EXPECTED), "analyst input producer directory roster differs")
    expected_inputs = []
    for directory, (producer, first, end) in EXPECTED.items():
        dates = dates_between(dt.date.fromisoformat(first), dt.date.fromisoformat(end))
        paths = sorted((input_root / directory).glob("*.json"))
        require([p.stem for p in paths] == dates, "analyst input day roster differs")
        expected_inputs.extend(str(p.relative_to(input_root)) for p in paths)
    actual_inputs = [str(p.relative_to(input_root)) for scope, p, _ in files if scope == "analyst-inputs"]
    require(sorted(actual_inputs) == sorted(expected_inputs), "unexpected analyst input file")
    require(result["summary_files_read"] == len(expected_inputs), "analyst input count differs")
    output = ROOT / "analyst-output"
    require(OUTPUTS <= {p.name for p in output.iterdir() if p.is_file()}, "analyst outputs incomplete")
    reported_inputs = json.loads((output / "input-files.json").read_text())
    require(sorted(reported_inputs) == sorted(expected_inputs), "analyst input manifest differs")
    features = json.loads((output / "features.json").read_text())
    require(len(features["series"]) == result["series"], "analyst series count differs")
    forbidden = {"users_exact", "exact_values", "raw_identity_values", "naive_values"}
    require(not any(forbidden & set(item) for item in features["series"]), "raw-reference feature field present")
    return {"log_path": str(LOG.relative_to(ROOT)), "log_sha256": sha256(LOG),
            "result": result, "fixed_directory_roster_verified": True,
            "fixed_daily_file_rosters_verified": True, "input_manifest_verified": True,
            "raw_reference_feature_fields_absent": True,
            "isolation_evidence_limit": "Completion marker and artifacts verified here. The OS deny-read/network policy and its initial probe were not re-executed by this audit; this audit deliberately reads the local reference as validation input."}


def protobuf_scalars(message):
    for field, value in message.ListFields():
        values = value if field.is_repeated else [value]
        for item in values:
            if field.type == FieldDescriptor.TYPE_MESSAGE:
                yield from protobuf_scalars(item)
            elif field.type == FieldDescriptor.TYPE_STRING:
                yield item.encode("utf-8")
            elif field.type == FieldDescriptor.TYPE_BYTES:
                yield bytes(item)


def inspect_file(data, suffix, index, *, expect_envelope=False):
    hits = collections.defaultdict(set)
    decoded = collections.Counter()
    wire = collections.Counter()
    fi = collections.defaultdict(lambda: {"entry_occurrences": 0, "protobuf_wire_bytes": 0, "keys": set()})
    errors = []

    def scan(value, representation):
        hits[representation].update(matches(value, index))

    def payloads(sketches):
        if not isinstance(sketches, dict):
            return
        for payload in sketches.values():
            if not isinstance(payload, dict) or "data" not in payload:
                continue
            try:
                binary = base64.b64decode(payload["data"], validate=True)
            except (ValueError, TypeError):
                errors.append("invalid_base64_sketch")
                continue
            scan(binary, "decoded_protobuf_wire")
            decoded["protobuf_payloads"] += 1
            wire["all_sketch_protobuf_wire_bytes"] += len(binary)
            wire["sketch_base64_character_bytes"] += len(payload["data"].encode("ascii"))
            message = sketches_pb2.Sketch()
            try:
                message.ParseFromString(binary)
            except Exception as exc:
                errors.append("protobuf_" + type(exc).__name__)
                continue
            for value in protobuf_scalars(message):
                scan(value, "decoded_protobuf_scalar")
                decoded["protobuf_scalar_values"] += 1
            if payload.get("kind") == "frequent_items":
                try:
                    state = frequentitems.parse(binary)
                except ValueError:
                    errors.append("invalid_frequent_items_payload")
                    continue
                domain = message.metadata.hash_domain
                items = state.items()
                wire["frequent_items_protobuf_wire_bytes"] += len(binary)
                wire["fi_entry_occurrences"] += len(items)
                wire["fi_item_hash_value_bytes"] += 8 * len(items)
                group = fi[domain]
                group["entry_occurrences"] += len(items)
                group["protobuf_wire_bytes"] += len(binary)
                group["keys"].update(item.hash for item in items)

    def walk(value):
        if isinstance(value, dict):
            if "sketches" in value:
                payloads(value["sketches"])
            for key, child in value.items():
                scan(key.encode("utf-8"), "decoded_json_scalar")
                decoded["json_scalar_values"] += 1
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            scan(value.encode("utf-8"), "decoded_json_scalar")
            decoded["json_scalar_values"] += 1

    scan(data, "file_bytes")
    try:
        if suffix == ".json":
            walk(json.loads(data))
        elif suffix == ".jsonl":
            for line in data.splitlines():
                if line.strip():
                    walk(json.loads(line))
        elif suffix == ".csv":
            for row in csv.reader(io.StringIO(data.decode("utf-8"), newline="")):
                for value in row:
                    scan(value.encode("utf-8"), "decoded_csv_scalar")
                    decoded["csv_scalar_values"] += 1
    except (ValueError, TypeError, UnicodeError):
        errors.append("invalid_structured_artifact")
    if expect_envelope:
        try:
            envelope = summary.Envelope.parse(data)
            wire["summary_envelope_json_bytes"] += len(data)
            wire["summary_envelopes"] += 1
        except ValueError:
            errors.append("invalid_summary_envelope")
            envelope = None
    else:
        envelope = None
    return {"hits": {k: v for k, v in hits.items() if v}, "decoded": decoded,
            "wire": wire, "fi": fi, "errors": errors, "envelope": envelope}


def scanner_tests(index, sentinels, raw_examples):
    tests = []
    cases = {b"a", b"ab", b"1234567", b"12345678", b"12345678x", b"12345678xy",
             b"overlap-overlap", b'escaped"line\nend', "unicode-\u2603-value".encode()}
    tiny = prefix_index(cases)
    random_source = random.Random(20261010)
    for number in range(100):
        blob = bytes(random_source.randrange(256) for _ in range(number))
        for pattern in sorted(cases):
            at = random_source.randrange(len(blob) + 1)
            blob = blob[:at] + pattern + blob[at:]
        require(matches(blob, tiny) == {p for p in cases if p in blob}, "prefix scanner differs from exact substring oracle")
    tests.append({"name": "prefix_scan_vs_naive_short_overlap_collision_unicode", "cases": 100, "passed": True})
    patterns = sentinels + raw_examples
    for pattern in patterns:
        for blob in (pattern, b"\x00" + pattern + b"\xff", b"end:" + pattern):
            require(pattern in matches(blob, index), "known injected plaintext leak missed")
    tests.append({"name": "full_index_injected_plaintext", "cases": 3 * len(patterns), "passed": True})
    for pattern in patterns:
        message = sketches_pb2.Sketch()
        message.metadata.hash_domain = pattern.decode("utf-8")
        binary = message.SerializeToString(deterministic=True)
        document = {"sketches": {"injected": {"kind": "test-only", "data": base64.b64encode(binary).decode()}}}
        data = json.dumps(document).encode()
        require(pattern not in data, "injected encoded-only fixture is not encoded-only")
        result = inspect_file(data, ".json", index)
        require(pattern in result["hits"].get("decoded_protobuf_wire", set()), "known encoded protobuf leak missed")
        require(pattern in result["hits"].get("decoded_protobuf_scalar", set()), "known decoded protobuf scalar leak missed")
    tests.append({"name": "full_index_base64_protobuf_only_leaks", "cases": len(patterns), "passed": True})
    escaped = next(p for p in cases if b'"' in p)
    result = inspect_file(json.dumps({"value": escaped.decode()}).encode(), ".json", tiny)
    require(escaped in result["hits"].get("decoded_json_scalar", set()), "escaped JSON leak missed")
    output = io.StringIO(newline="")
    csv.writer(output).writerow([escaped.decode()])
    result = inspect_file(output.getvalue().encode(), ".csv", tiny)
    require(escaped in result["hits"].get("decoded_csv_scalar", set()), "escaped CSV leak missed")
    tests.append({"name": "decoded_json_and_csv_escaped_leaks", "cases": 2, "passed": True})
    require(not matches(b"negative-control-without-known-markers", index), "negative control matched")
    tests.append({"name": "negative_control", "cases": 1, "passed": True})
    return tests


def public_fi(groups):
    return {domain: {"entry_occurrences": v["entry_occurrences"],
                     "item_hash_value_bytes": 8 * v["entry_occurrences"],
                     "unique_item_hash_values": len(v["keys"]),
                     "unique_item_hash_value_bytes": 8 * len(v["keys"]),
                     "protobuf_wire_bytes": v["protobuf_wire_bytes"]}
            for domain, v in sorted(groups.items())}


def report_markdown(result):
    checks = result["checks"]
    lines = ["# Analyst Privacy Audit", "", "## Result", "",
             f"- Files scanned: {checks['files_scanned']}; decoded protobuf payloads: {checks['protobuf_payloads']:,}.",
             f"- Exact raw-identifier patterns: {result['patterns']['raw_identity_count']:,}; planted sentinels: {result['patterns']['planted_sentinel_count']}.",
             f"- Known-pattern leak findings: {checks['leak_findings']}; decode/validation errors: {checks['decode_or_validation_errors']}.",
             "- Scanned original file bytes, relative paths, decoded JSON keys/string values, decoded CSV fields, base64-decoded protobuf bytes, and parsed protobuf string/bytes fields.",
             "- Prefix matching visits every byte offset and verifies the entire candidate. Short patterns are handled separately. In-memory injected plaintext and encoded-only protobuf leaks were detected before the artifact scan.",
             "- Analyst completion log, input manifest, expected producer directories, full daily input rosters, envelope timestamps/producer IDs, output counts, and file stability were independently checked.",
             "", "## Linkable Hash Bytes", "",
             "| Scope | Files | Artifact bytes | Sketch protobuf bytes | FI protobuf bytes | FI item ID bytes |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for scope, row in result["scopes"].items():
        lines.append("| " + scope + " | " + " | ".join(f"{row.get(k, 0):,}" for k in (
            "files", "artifact_bytes", "all_sketch_protobuf_wire_bytes", "frequent_items_protobuf_wire_bytes", "fi_item_hash_value_bytes")) + " |")
    lines.extend(["", "FI item ID bytes count eight bytes per stored 64-bit frequent-items hash occurrence, including repetitions across files. They exclude protobuf tags, estimates, errors, metadata, and base64 overhead. Unique domain/hash counts are separate in the JSON evidence. Other sketches can also expose linkable information; this is not an estimate of all identifying information.",
        "The analyst-input prompt:v1 hash represents the constant synthetic accounting group, not a real prompt count. The separate sentinel fixture deliberately hashes a planted prompt marker.",
        "", "## Evidence And Limits", "",
        "- Evidence: evidence/privacy-audit.json (checks and counts); evidence/privacy-audit-files.json (file hashes and scoped findings). Test leaks were in memory only and were never written into analyst artifacts.",
        "- Marker sources are the local reference and the five literals in the pinned local main_test.go. Those inputs contain identifiers by design and are excluded from the scanned sharing surface. Evidence findings retain marker hashes, never raw values.",
        "- The audit reads the local reference for validation; it is not itself the isolated analyst run. The prior OS raw-read/network denial test was not re-executed here. The completion marker verifies the runner reached its post-output completion statement, not the policy configuration.",
        "- Zero detected exact known patterns is a scoped non-disclosure check, not anonymity, non-linkability, resistance to reidentification, or absence of arbitrary encodings/transformed/unknown identifiers. The public experiment key is not a privacy secret.",
        "- Reproduce after analyst completion: `venv/bin/python -B scripts/privacy_audit.py` from this experiment directory.",
        "", "## Judgment And Next Steps", "",
        ("Positive for this fixed artifact snapshot: all known-pattern checks and validation checks passed. "
         if result["passed"] else "Negative for this artifact snapshot: leaks or validation failures require investigation. ")
        + "The result establishes known-pattern exclusion for this artifact set.",
        "Next: retain the file hashes and local evidence, re-audit after any artifact change, and keep release approval separate. Use a fixed analyst input manifest and explicit day alignment checks in the runner before claiming missing-directory refusal.", ""])
    return "\n".join(lines)


def main():
    started = time.perf_counter()
    files = inventory()
    completion = completion_check(files)
    oracle_path = ROOT / "data/oracle.json"
    marker_source_stamps = {p: stamp(p) for p in (oracle_path, TEST_SOURCE)}
    oracle = json.loads(oracle_path.read_bytes())
    values = oracle["tracelab"]["raw_identity_values"]
    raw_examples = [values[i].encode() for i in (0, len(values) // 2, len(values) - 1)]
    sentinels = planted_sentinels()
    raw_count = len(values)
    raw_bytes = sum(len(v.encode()) for v in values)
    minimum = min(len(v.encode()) for v in values)
    index = prefix_index(v.encode() for v in values)
    extra, short = prefix_index(sentinels)
    for prefix, lengths in extra.items():
        target = index[0].setdefault(prefix, collections.defaultdict(set))
        for length, patterns in lengths.items():
            target[length].update(patterns)
    for length, patterns in short.items():
        index[1].setdefault(length, set()).update(patterns)
    indexed_count = sum(len(p) for lengths in index[0].values() for p in lengths.values())
    indexed_count += sum(len(p) for p in index[1].values())
    require(indexed_count == raw_count + len(sentinels), "marker index omitted or duplicated a source pattern")
    del values, oracle
    tests = scanner_tests(index, sentinels, raw_examples)
    print("Injected-leak scanner tests passed; scanning completed analyst artifacts.", flush=True)
    scopes = {scope: collections.Counter() for scope in SCOPES}
    by_domain = {scope: collections.defaultdict(lambda: {"entry_occurrences": 0, "protobuf_wire_bytes": 0, "keys": set()}) for scope in SCOPES}
    records, findings, errors = [], [], []
    for position, (scope, path, initial_stamp) in enumerate(files, 1):
        relative = str(path.relative_to(ROOT))
        data = path.read_bytes()
        require(stamp(path) == initial_stamp, "artifact changed during privacy scan")
        result = inspect_file(data, path.suffix, index, expect_envelope=scope != "analyst-output")
        path_matches = matches(relative.encode(), index)
        if path_matches:
            result["hits"]["relative_path"] = path_matches
            relative = "redacted-path-" + hashlib.sha256(relative.encode()).hexdigest()
        env = result["envelope"]
        if scope == "analyst-inputs" and env is not None:
            directory = str(path.parent.relative_to(ROOT / scope))
            producer = EXPECTED[directory][0]
            day = dt.datetime.fromisoformat(path.stem).replace(tzinfo=dt.timezone.utc)
            start = int(day.timestamp()) * 1_000_000_000
            if env.producer_id != producer or env.window_start_unix_nano != start:
                result["errors"].append("producer_or_filename_timestamp_mismatch")
            if (env.window_duration_unix_nano != 86400_000_000_000
                    or env.observed_start_unix_nano != start
                    or env.observed_end_unix_nano != start + 86400_000_000_000):
                result["errors"].append("incomplete_daily_input_coverage")
        for representation, patterns in result["hits"].items():
            for pattern in sorted(patterns):
                findings.append({"file": relative, "representation": representation,
                                 "pattern_type": "planted_sentinel" if pattern in sentinels else "raw_identity",
                                 "pattern_sha256": hashlib.sha256(pattern).hexdigest(), "pattern_bytes": len(pattern)})
        errors.extend({"file": relative, "error": error} for error in result["errors"])
        group = scopes[scope]
        group.update(result["decoded"])
        group.update(result["wire"])
        group["files"] += 1
        group["artifact_bytes"] += len(data)
        for domain, part in result["fi"].items():
            target = by_domain[scope][domain]
            target["entry_occurrences"] += part["entry_occurrences"]
            target["protobuf_wire_bytes"] += part["protobuf_wire_bytes"]
            target["keys"].update(part["keys"])
        records.append({"path": relative, "scope": scope, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "decoded": dict(result["decoded"]), "wire": dict(result["wire"])})
        if position % 200 == 0:
            print(f"Scanned {position}/{len(files)} files.", flush=True)
    require(inventory() == files and sha256(LOG) == completion["log_sha256"],
            "artifact inventory or analyst completion log changed during audit")
    require(all(stamp(p) == before for p, before in marker_source_stamps.items()),
            "local marker source changed during audit")
    result = {"schema_version": 1, "passed": not findings and not errors,
        "scope": list(SCOPES), "scopes": scopes, "fi_by_hash_domain": {s: public_fi(g) for s, g in by_domain.items()},
        "patterns": {"raw_identity_count": raw_count, "raw_identity_utf8_bytes": raw_bytes,
                     "raw_identity_minimum_bytes": minimum, "planted_sentinel_count": len(sentinels),
                     "indexed_pattern_count": indexed_count,
                     "sentinel_sha256": [hashlib.sha256(v).hexdigest() for v in sentinels],
                     "prefix_bytes": 8, "prefix_count": len(index[0]),
                     "short_pattern_count": sum(len(p) for p in index[1].values()),
                     "oracle_sha256": sha256(oracle_path), "go_test_source_sha256": sha256(TEST_SOURCE)},
        "checks": {"files_scanned": len(records), "protobuf_payloads": sum(s["protobuf_payloads"] for s in scopes.values()),
                   "leak_findings": len(findings), "decode_or_validation_errors": len(errors),
                   "stable_inventory": True, "stable_marker_sources": True,
                   "all_marker_patterns_indexed": True, "injected_leak_tests": tests},
        "analyst_completion": completion,
        "reproducibility": {"python": sys.version, "llm_sketchkit": importlib.metadata.version("llm-sketchkit"),
                            "protobuf": importlib.metadata.version("protobuf"), "script_sha256": sha256(Path(__file__)),
                            "analyst_runner_sha256": sha256(ROOT / "scripts/analyst_run.py"),
                            "elapsed_seconds": time.perf_counter() - started},
        "limits": ["Exact known-pattern scan only; no anonymity or non-linkability claim.",
                   "FI hash bytes are 8-byte values per occurrence, not total identifying information or total wire bytes.",
                   "Raw oracle and test source are validator-only marker sources, not analyst inputs.",
                   "OS sandbox policy enforcement was not re-executed in this audit."]}
    evidence = ROOT / "evidence"
    write_json(evidence / "privacy-audit-files.json", {"files": records, "findings": findings, "errors": errors})
    result["inventory_sha256"] = sha256(evidence / "privacy-audit-files.json")
    write_json(evidence / "privacy-audit.json", result)
    write_text(evidence / "privacy-audit.md", report_markdown(result))
    print(json.dumps({"passed": result["passed"], "checks": result["checks"], "scopes": scopes,
                      "fi_by_hash_domain": result["fi_by_hash_domain"]}, indent=2))
    require(result["passed"], "privacy audit found leaks or validation errors; inspect local hashed findings")


if __name__ == "__main__":
    main()
