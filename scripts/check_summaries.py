# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Keep the page's measured claims tied to the reviewed aggregate evidence."""
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

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


def main():
    ledger = json.loads((EVIDENCE / "claims.json").read_text())
    results = json.loads((EVIDENCE / "recorded/sketch-results.json").read_text())
    overlap = json.loads((EVIDENCE / "recorded/overlap.json").read_text())
    scale = json.loads((EVIDENCE / "recorded/scale.json").read_text())
    claims = ledger["claims"]
    assert claims["overlap"]["values"] == [overlap[k] for k in
        ("claude_labels", "codex_labels", "union_labels", "naive_sum_labels")]
    assert claims["ranges"]["days"] == [q["days"] for q in results["B2"]["queries"]]
    storage = results["B2"]["storage"]["tracelab"]
    for left, right in (("summary_bytes", "summary_bytes"), ("days", "days"),
                        ("raw_uncompressed_bytes", "raw_bytes"),
                        ("raw_compressed_bytes", "raw_compressed_bytes")):
        assert claims["storage"][left] == storage[right]
    daily = results["B1"]["1"]
    assert claims["small-lists"]["rounded_mean_sketch_bytes"] == round(daily["hll_exchange_bytes"]["mean"])
    assert claims["small-lists"]["rounded_mean_raw_list_bytes"] == round(daily["raw_list_bytes"]["mean"])
    assert len(scale) == len(claims["scale"]["seeds"])
    assert {s["seed"] for s in scale} == set(claims["scale"]["seeds"])
    for run in scale:
        assert run["n"] == claims["scale"]["users"]
        assert run["hll_bytes"] + run["fi_bytes"] == claims["scale"]["wire_bytes"]
        assert run["top20_recall"] == claims["scale"]["recall"]
        assert run["bound_violations"] == 0 and run["weight_conserved"]
    assert claims["contributors"]["keys_checked"] == sum(v["keys_checked"] for v in results["B4"].values())
    assert claims["contributors"]["bound_violations"] == sum(v["bound_violations"] for v in results["B4"].values())
    article = Article()
    source = (ROOT / "pages/summaries.html").read_text()
    article.feed(source)
    assert article.claims == set(claims)
    for claim in claims.values():
        assert (EVIDENCE / claim["evidence"]).is_file()
        subprocess.run(["bash", "-n"], input=claim["command"], text=True, check=True)
    for link in article.links:
        target = urlsplit(link)
        if not target.path and target.fragment:
            assert target.fragment in article.ids, link
    assert "A raw-data system can compute exact answers." in source
    for private in ("/Users/", "/private/tmp/", "docs/local/", "Erramilli"):
        assert private not in source
    for path in (ROOT / "docs/assets/summary-evidence").rglob("*"):
        assert path.name not in {"oracle.json", "venv", "collector", "data", "analyst-inputs", "analyst-output"}, path
    print("PASS: summary claim ledger, aggregate evidence, local anchors, command syntax, publication boundary")


if __name__ == "__main__":
    main()
