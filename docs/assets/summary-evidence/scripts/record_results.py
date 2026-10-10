# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Collect aggregate evidence after a complete rerun; keep raw inputs local."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "recorded")
    out = parser.parse_args().output
    audit = read("evidence/data-audit.json")
    checks = read("evidence/features-validation.json")
    sketches = read("evidence/sketch-results.json")
    privacy = read("evidence/privacy-audit.json")
    isolation = read("evidence/analyst-denial.log")
    assert not checks["mismatches"] and privacy["passed"]
    assert isolation == {"raw_read_denied": True, "network_denied": True}
    assert not sketches["identifier_exclusion"]["raw_identity_hits"]
    scales = []
    for seed in (20261010, 20261011, 20261012):
        values = read(f"evidence/scale-isolated-1000000-{seed}/results.json")
        assert len(values) == 1 and values[0]["seed"] == seed
        assert values[0]["weights_sha256_json"] == audit["burstgpt"]["sample"]["sha256_json"]
        scales.extend(values)
    records = {
        "sketch-results": sketches,
        "overlap": audit["tracelab"]["overlap"],
        "scale": scales,
        "sampling": {key: audit["burstgpt"][key] for key in
                     ("deduplication", "daily_gaps", "sample")},
        "privacy": {
            "known_identifier_scan": sketches["identifier_exclusion"],
            "analyst_artifact_scan": {
                "passed": privacy["passed"], "checks": privacy["checks"],
                "raw_identity_count": privacy["patterns"]["raw_identity_count"],
                "planted_sentinel_count": privacy["patterns"]["planted_sentinel_count"],
            },
            "isolation": isolation,
        },
        "run": {
            "machine": subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip(),
            "os": f"{platform.system()} {platform.release()} {platform.machine()}",
            "go": subprocess.check_output(["go", "version"], text=True).strip(),
            "python": platform.python_version(),
            "sketchkit": importlib.metadata.version("llm-sketchkit"),
            "protobuf": importlib.metadata.version("protobuf"),
            "collector_source": subprocess.check_output(["git", "-C", str(ROOT / "collector"), "rev-parse", "HEAD"], text=True).strip(),
            "test_key": audit["reproducibility"]["public_experiment_key"],
            "inputs": audit["inputs"],
            "sources": audit["sources"]["documents"],
            "accounting_checks": checks["counters_checked"],
            "accounting_mismatches": len(checks["mismatches"]),
            "source_sha256": {
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for directory in ("scripts", "go")
                for p in sorted((ROOT / directory).rglob("*"))
                if p.is_file() and p.suffix in {".py", ".go"}
            },
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, value in records.items():
        (out / f"{name}.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print("Recorded aggregate evidence: " + ", ".join(records))


if __name__ == "__main__":
    main()
