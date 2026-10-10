# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check evidence bindings, generated measurements and publication boundaries."""
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

import summary_evidence

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "assets/summary-evidence"


class Article(HTMLParser):
    def __init__(self):
        super().__init__()
        self.claims = set()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-claim" in attrs:
            self.claims.add(attrs["data-claim"])
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))


def mutation_check():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(EVIDENCE / "recorded", root / "assets/summary-evidence/recorded")
        (root / "pages").mkdir()
        shutil.copy2(ROOT / "pages/summaries.html", root / "pages/summaries.html")
        original = summary_evidence.render(root)
        path = root / "assets/summary-evidence/recorded/sketch-results.json"
        data = json.loads(path.read_text())
        data["ranges"]["storage"]["tracelab"]["summary_bytes"] = 3_400_000
        data["unions"]["1"]["union_abs_error"]["max"] = 0.01231
        data["contributors"]["top_users"]["true_positive"] = 123
        path.write_text(json.dumps(data))
        changed = summary_evidence.render(root)
        assert changed != original
        assert "3.4 MB" in changed and "0.0124 users" in changed and "123 matching user flags" in changed
        path = root / "assets/summary-evidence/recorded/scale.json"
        data = json.loads(path.read_text())
        data[0]["fi_bytes"] = 20_000
        path.write_text(json.dumps(data))
        assert "to 36,424 bytes" in summary_evidence.render(root)
        assert summary_evidence.claims(root) != summary_evidence.claims(ROOT)


def main():
    ledger = json.loads((EVIDENCE / "claims.json").read_text())
    assert ledger == summary_evidence.claims(ROOT), "regenerate the evidence ledger"
    recorded = summary_evidence.evidence(ROOT)
    assert recorded["privacy"]["isolation"] == {"raw_read_denied": True, "network_denied": True}
    assert recorded["privacy"]["analyst_artifact_scan"]["passed"]
    assert recorded["run"]["accounting_mismatches"] == 0
    assert recorded["run"]["test_key"] == "llm-measurement-summary-evidence-test-key-20261010"
    for name, digest in recorded["run"]["source_sha256"].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest, name
    for row in recorded["scale"]:
        assert row["bound_violations"] == 0 and row["weight_conserved"]
    source = summary_evidence.render(ROOT)
    assert source in (ROOT / "docs/summaries.html").read_text(), "regenerate page values"
    assert source.count("What the numbers mean") == 1
    assert "A raw-data system computes exact answers," in source
    sampling = recorded["sampling"]
    assert sampling["deduplication"]["removed_rows"] == 1379449
    assert all(block["all_rows_matched"] for block in sampling["deduplication"]["blocks"])
    assert sampling["sample"]["population"] == sampling["deduplication"]["successful_sampling_population"]
    assert all(row["weights_sha256_json"] == sampling["sample"]["sha256_json"] for row in recorded["scale"])
    assert sum(d["rows"] for d in sampling["daily_gaps"]["source"]) - sum(
        d["rows"] for d in sampling["daily_gaps"]["deduplicated"]) == 1379449
    article = Article()
    article.feed(source)
    assert article.claims == set(ledger["claims"])
    for claim in ledger["claims"].values():
        path = Path(claim["evidence"])
        assert path.parent == Path("recorded") and path.suffix == ".json"
        assert hashlib.sha256((EVIDENCE / path).read_bytes()).hexdigest() == claim["sha256"]
        subprocess.run(["bash", "-n"], input=claim["command"], text=True, check=True)
    for link in article.links:
        target = urlsplit(link)
        if not target.path and target.fragment:
            assert target.fragment in article.ids, link
    forbidden = ("phase0", "phase 0", "forecast", "private oracle", "private audit", "report_sha256", "report_section", "\"B6\"", "/Users/", "/private/tmp/", "Erramilli")
    for path in [ROOT / "pages/summaries.html", *EVIDENCE.rglob("*")]:
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text()
        assert not any(term.lower() in text.lower() for term in forbidden), path
    for path in (ROOT / "docs/assets/summary-evidence").rglob("*"):
        assert path.name not in {"oracle.json", "venv", "collector", "data", "analyst-inputs", "analyst-output"}, path
    mutation_check()
    print("PASS: recorded-only claims, source hashes, generated values, mutation checks, links and publication boundary")


if __name__ == "__main__":
    main()
