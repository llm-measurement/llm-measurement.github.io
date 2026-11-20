# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Offline checks for the pinned second study; no build, execution or network."""
import argparse
import json
from pathlib import Path
import re

from study_checks import (Document, Element, check_local_resources,
                          check_privacy_footer, digest, require,
                          resource_surfaces, sha256)


ROOT = Path(__file__).resolve().parents[1]
SLUG = "haiku-sonnet-100k-cliff"
BASE = "https://llm-measurement.github.io/"
URL = BASE + SLUG + ".html"
TITLE = "Haiku 5.5 is 20\u00d7 cheaper than Sonnet on paper, 3.4\u00d7 on a Claude Code trace"
DOCUMENT_TITLE = "Haiku 5.5 vs Sonnet 5.5: 20\u00d7 Cheaper, 3.4\u00d7 on an Agent"
DESCRIPTION = ("A 233-session Claude Code trace priced at Haiku 5.5 and Sonnet 5.5 rates: "
               "the 100,000-token tier and cache-read discounts turn 20\u00d7 into 3.4\u00d7.")
DATE = "2026-11-20T00:00:00Z"
MANIFEST = "evidence/cheaper-study-manifest.json"
EVIDENCE_DIR = "assets/cheaper-model-evidence"
EVIDENCE_NAMES = frozenset({
    "ATTRIBUTION.md", "RUN.md", "index.html", "FLEETDIFF_V0150_RERUN_2026-11-20.md",
    "cached_session_cost.py", "cached-session-cost-output.json",
    "tier_analysis.py", "tier-analysis-output.json",
    "subagent_split.py", "subagent-split-output.json",
    "tail_sensitivity.py", "tail-sensitivity-output.json",
    "one_hour_cache.py", "one-hour-cache-output.json", "trace_to_litellm.py",
    "make_chart.py", "cheaper-ratio-chart.svg", "fleetdiff-v0150-what-if.txt",
    "fleetdiff-v0150-session-sonnet.txt", "fleetdiff-v0150-session-haiku.txt",
})
DEPENDENCIES = frozenset({"assets/cache-evidence/trace_replay.py",
                          "assets/cache-evidence/trace_replay-results.json"})
# These pins come from the v6 converter self-check, not an independent PR review
# or a fresh approval inferred from whatever bytes happen to be in the worktree.
APPROVED_CONVERSION = {
    "source_sha256": "c7c711760e1ae394f85f6af49e2bff4aa10a3bac3443cea6c974814a0dfbdcbb",
    "article_body_sha256": "35819638e5028e12cd99c906e4e15f8b7e72b9e517834c1e2ee9d4d7102f95aa",
    "converter_sha256": "090145c49d8546f014849f1fceaf2c8f0d902b4efbf95ecf4353e2b4c26dc97e",
}
CONVERTER_REPORT_SHA256 = "36f7d723c3a6c36a85e5d63eca7c4e23c56950dd2e9b7b18294df7920d8da173"
CHART = EVIDENCE_DIR + "/cheaper-ratio-chart.svg"
CHART_ALT = "How much cheaper the smaller model is, on the price sheet and on the re-priced trace"
HEADINGS = [
    ("h2", "where-the-20-goes", "Where the 20\u00d7 goes"),
    ("h2", "long-sessions-and-subagents", "Long sessions and subagents"),
    ("h2", "why-3-4-is-the-best-case", "Why 3.4\u00d7 is the best case"),
    ("h2", "measure-sessions-not-rate-cards", "Measure sessions, not rate cards"),
    ("h3", "what-the-numbers-mean", "What the numbers mean"),
]
PRIVATE_TEXT = re.compile(
    r"\b(?:POST_DRAFT(?:_v\d+)?|NOTES\.md)\b"
    r"|/(?:Users|home|private|tmp)/|file://|[A-Z]:\\", re.I)


def check_public_text(source, label):
    require(PRIVATE_TEXT.search(source) is None, f"{label}: private text or machine path leaked")


def check_manifest(root):
    record = json.loads((root / MANIFEST).read_bytes())
    require(type(record.get("schema")) is int and record["schema"] == 1,
            "second-study manifest schema must be 1")
    require(record.get("slug") == SLUG and record.get("conversion") == APPROVED_CONVERSION,
            "pinned v6 conversion pins differ")
    require(record.get("converter_report_sha256") == CONVERTER_REPORT_SHA256,
            "v6 converter self-check receipt pin differs")
    require(record.get("site_layout_evidence_reproduced") is True,
            "site-layout evidence reproduction not recorded")
    return record


def article_document(root=ROOT):
    body = (Path(root) / f"pages/{SLUG}.html").read_bytes()
    require(sha256(body) == APPROVED_CONVERSION["article_body_sha256"],
            "article body differs from pinned v6 conversion (words, blocks or links)")
    source = body.decode("utf-8")
    document = Document(source)
    articles = list(document.root.walk("article"))
    require(len(articles) == 1 and source.strip() == source[articles[0].start:articles[0].end]
            and articles[0].attrs == {"class": "study"} and not document.comments,
            "expected one uncommented study article fragment")
    check_public_text(source, "article")
    return body, document, articles[0]


def check_article_structure(article, source, chart_bytes):
    headings = [(node.tag, node.attrs.get("id"), node.text())
                for node in article.walk() if re.fullmatch(r"h[1-6]", node.tag)]
    require(headings == HEADINGS, "article headings differ")
    children = [node for node in article.children if isinstance(node, Element)]
    require([node.tag for node in children[-3:]] == ["hr", "h3", "ul"]
            and len(list(article.walk("hr"))) == 1
            and len(list(article.walk("li"))) == 4, "limits H3/divider/list differ")
    blocks = list(article.walk("pre"))
    require(len(blocks) == 2 and all(node.attrs == {"class": "output"} for node in blocks),
            "expected two locally scrolling output blocks")
    for block in blocks:
        codes = list(block.walk("code"))
        require(len(codes) == 1 and codes[0].parent is block
                and codes[0].attrs == {"class": "language-text"}, "output block language differs")
    tables = list(article.walk("table"))
    require(len(tables) == 2 and all(node.parent.tag == "div"
            and node.parent.attrs == {"class": "study-table"} for node in tables),
            "expected two locally scrolling tables")
    charts = list(article.walk("svg"))
    require(not list(article.walk("img")) and len(charts) == 1
            and charts[0].parent.tag == "figure"
            and charts[0].parent.attrs == {"class": "study-chart", "aria-label": CHART_ALT,
                                          "tabindex": "0", "role": "region"},
            "inline chart/accessible source alt differs")
    figure = charts[0].parent
    start = source.index(">", figure.start) + 1
    end = source.rfind("</figure", start, figure.end)
    require(source[start:end].encode("utf-8") == chart_bytes,
            "inline chart differs from frozen SVG asset bytes")


def check_head(root, document):
    pages = [page for page in json.loads((root / "pages.json").read_bytes()) if page.get("slug") == SLUG]
    expected_page = {"slug": SLUG, "title": TITLE, "document_title": DOCUMENT_TITLE,
                     "description": DESCRIPTION, "kind": "study", "article": True,
                     "published": DATE, "modified": DATE, "navigation": False}
    require(len(pages) == 1 and all(type(pages[0].get(key)) is type(value)
            and pages[0][key] == value for key, value in expected_page.items()),
            "study page configuration differs from pinned metadata")
    heads = list(document.root.walk("head"))
    require(len(heads) == 1, "expected one article head")
    head = heads[0]
    titles = list(head.walk("title"))
    require(len(titles) == 1 and titles[0].parent is head
            and titles[0].text() == DOCUMENT_TITLE, "document title differs")
    h1s = list(document.root.walk("h1"))
    require(len(h1s) == 1 and h1s[0].text() == TITLE, "H1 differs from v6 title")
    canonicals = [node for node in document.root.walk("link")
                  if "canonical" in node.attrs.get("rel", "").lower().split()]
    require(len(canonicals) == 1 and canonicals[0].parent is head
            and canonicals[0].attrs == {"rel": "canonical", "href": URL}, "canonical differs")
    expected_meta = {
        ("name", "description"): DESCRIPTION,
        ("property", "og:title"): DOCUMENT_TITLE,
        ("property", "og:description"): DESCRIPTION,
        ("property", "og:type"): "article", ("property", "og:url"): URL,
        ("property", "og:site_name"): "LLM Measurement",
        ("property", "article:published_time"): DATE,
        ("property", "article:modified_time"): DATE,
        ("name", "twitter:card"): "summary", ("name", "twitter:title"): DOCUMENT_TITLE,
        ("name", "twitter:description"): DESCRIPTION, ("name", "twitter:url"): URL,
    }
    actual = []
    for node in document.root.walk("meta"):
        for attr in ("name", "property"):
            key = node.attrs.get(attr, "")
            if key == "description" or key.startswith(("og:", "article:", "twitter:")):
                require(node.parent is head, "article metadata outside head")
                actual.append(((attr, key), node.attrs.get("content")))
    require(len(actual) == len(expected_meta) and dict(actual) == expected_meta,
            "article head metadata differs (including dates)")
    structured = [node for node in document.root.walk("script")
                  if node.attrs.get("type", "").lower() == "application/ld+json"]
    expected_ld = {
        "@context": "https://schema.org", "@type": "BlogPosting", "headline": TITLE,
        "description": DESCRIPTION, "datePublished": DATE, "dateModified": DATE,
        "author": {"@type": "Person", "name": "Vijay"},
        "publisher": {"@type": "Organization", "name": "LLM Measurement"},
        "mainEntityOfPage": {"@type": "WebPage", "@id": URL},
    }
    require(len(structured) == 1 and structured[0].parent is head
            and json.loads(structured[0].text()) == expected_ld, "BlogPosting/author/dates differ")


def check_evidence(root, record):
    evidence = record.get("evidence")
    dependencies = record.get("dependencies")
    require(isinstance(evidence, dict) and set(evidence) == EVIDENCE_NAMES,
            "manifest must protect exactly the approved evidence inventory")
    require(isinstance(dependencies, dict) and set(dependencies) == DEPENDENCIES,
            "manifest must pin both shared replay dependencies")
    for prefix in (root, root / "docs"):
        folder = prefix / EVIDENCE_DIR
        require(folder.is_dir() and not folder.is_symlink(), "missing evidence directory")
        entries = list(folder.iterdir())
        require(all(path.is_file() and not path.is_symlink() for path in entries),
                "evidence entries must be regular files")
        require({path.name for path in entries} == EVIDENCE_NAMES, "evidence inventory differs")
        paths = {f"{EVIDENCE_DIR}/{name}": value for name, value in evidence.items()}
        for name, value in {**paths, **dependencies}.items():
            path = prefix / name
            require(path.is_file() and not path.is_symlink(), f"missing evidence/dependency: {name}")
            data = path.read_bytes()
            require(sha256(data) == digest(value, name), f"evidence hash mismatch: {name}")
            check_public_text(data.decode("utf-8"), name)


def check(root=ROOT):
    root = Path(root)
    record = check_manifest(root)
    body, source_document, source_article = article_document(root)
    check_evidence(root, record)
    check_article_structure(source_article, source_document.source, (root / CHART).read_bytes())
    built = (root / f"docs/{SLUG}.html").read_bytes()
    document = Document(built.decode("utf-8"))
    articles = list(document.root.walk("article"))
    require(len(articles) == 1 and built.count(body) == 1
            and document.source[articles[0].start:articles[0].end]
            == source_document.source[source_article.start:source_article.end],
            "built article differs from approved body")
    require(all(comment == "Privacy-friendly analytics by Plausible" for comment in document.comments),
            "private HTML comment leaked")
    check_public_text(document.source, "built article")
    check_head(root, document)
    check_privacy_footer(document)
    resources = check_local_resources(root, *resource_surfaces(document))
    return {"slug": SLUG, "article_body_sha256": sha256(body), "evidence_files": len(EVIDENCE_NAMES),
            "code_blocks": 2, "tables": 2, "headings": len(HEADINGS), "chart": CHART,
            "resources": sorted(resources), "offline": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(check(args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
