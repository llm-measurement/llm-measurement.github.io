# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check generated pages, local links, question titles and the text indexes."""
from html.parser import HTMLParser
import argparse
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from build import STATIC_ROOT_FILES
from outsider import Blocks

ROOT = Path(__file__).resolve().parents[1]
GUIDE_CONTEXT = {
    "cardinality": "diagnose reads your collector configuration; your metrics backend reports live series counts.",
    "token-spike": "A flag marks a session worth a look. With real data, the report shows ranges wherever bounds differ.",
    "tokenmaxxing": "Reported tokens measure usage, not productivity or useful work. Rankings from keyed IDs are pseudonymous: whoever holds the key can identify people.",
    "litellm-spend": "This synthetic example compares logged model requests; zero-only records retain unknown origin, and failed records can overlap usage categories.",
    "session-budget": "Recorded session totals are review evidence, not an enforcement verdict or completed-task costs. Missing identities stay unattributed; absent recorded rejections do not prove that no rejection occurred.",
    "cache-check": "Uncached-input growth can reflect input volume or workload mix, not necessarily a per-key cache-share loss. These recorded shares do not diagnose causes or costs; the synthetic example checks arithmetic, not provider cache behavior. Collector summaries support aggregate shares with sufficient coverage, but lack per-model cache counters and cache-weighted key/session rankings.",
    "anomalies": "This example checks planted changes. Review any flag against your own history; sessions that turn over often can look newly prominent.",
    "traces-usage": "Readiness describes fields in the captured model attempts; zeros without declared usage origin remain unknown.",
    "distinct-users": "Distinct counts are statistical estimates. Your application hashes raw IDs before they reach the sketch.",
}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.h1 = 0
        self.commands = 0
        self.has_description = False
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        self.h1 += tag == "h1"
        self.commands += tag == "pre" and "data-run" in attrs
        if tag in {"a", "link", "img"}:
            self.links.append(attrs.get("href", attrs.get("src", "")))
        if tag == "meta" and attrs.get("name") == "description":
            self.has_description = bool(attrs.get("content"))


class ReadingFlow(HTMLParser):
    """Track block order while treating links and emphasis as inline text."""
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.text_block = None

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "ul", "ol"}:
            self.blocks.append([tag, ""])
            self.text_block = self.blocks[-1] if tag == "p" or tag.startswith("h") else None

    def handle_endtag(self, tag):
        if self.text_block is not None and tag == self.text_block[0]:
            self.text_block = None

    def handle_data(self, data):
        if self.text_block is not None:
            self.text_block[1] += data


def check_reading_flow(source):
    flow = ReadingFlow()
    flow.feed(source)
    for index, (tag, text) in enumerate(flow.blocks):
        following = flow.blocks[index + 1][0] if index + 1 < len(flow.blocks) else None
        if tag.startswith("h") and following and following.startswith("h"):
            raise AssertionError(f"heading followed directly by a heading: {text.strip()}")
        if tag == "p" and text.rstrip().endswith(":") and following not in {"pre", "ul", "ol"}:
            raise AssertionError(f"colon introduction needs a code block or list: {text.strip()}")


def main():
    pages = json.loads((ROOT / "pages.json").read_text())
    measurement_sections = 0
    for entry in pages:
        path = ROOT / "docs" / (entry["slug"] + ".html")
        page = Page()
        page.feed(path.read_text())
        footer = path.read_text().split('<footer>', 1)[1].split('</footer>', 1)[0]
        assert footer.count('Privacy-friendly analytics by <a href="https://plausible.io/data-policy">Plausible</a>: no cookies, no personal data') == 1, path.name
        check_reading_flow((ROOT / "pages" / (entry["slug"] + ".html")).read_text())
        nav = path.read_text().split('<nav aria-label="Guides">', 1)[1].split('</nav>', 1)[0]
        assert nav.index('href="token-spike.html"') < nav.index('href="tokenmaxxing.html"') < nav.index('href="cardinality.html"'), path.name
        assert '>A token spike</a>' in nav and '>Tokenmaxxing</a>' in nav and '>Per-user metrics</a>' in nav, path.name
        assert '>LiteLLM spend</a>' in nav, path.name
        assert '>Session budget</a>' in nav, path.name
        assert nav.index('href="litellm-spend.html"') < nav.index('href="session-budget.html"') < nav.index('href="cache-check.html"'), path.name
        assert '>Cache check</a>' in nav, path.name
        assert nav.index('href="litellm-spend.html"') < nav.index('href="cache-check.html"') < nav.index('href="cardinality.html"'), path.name
        assert '>All guides</a>' in nav and '>All questions</a>' not in nav, path.name
        assert '>Trace check</a>' in nav, path.name
        assert nav.index('href="anomalies.html"') < nav.index('href="traces-usage.html"') < nav.index('href="distinct-users.html"'), path.name
        measurement_sections += "measurement-notes" in page.ids
        assert "What the numbers mean" not in path.read_text(), path.name
        assert page.links.count("summaries.html#measurement-notes") == 1, path.name
        assert page.h1 == 1 and page.has_description, path.name
        title = entry.get("document_title", entry["title"] + " | LLM Measurement")
        assert f"<title>{html.escape(title)}</title>" in path.read_text(), path.name
        assert f'<h1>{html.escape(entry["title"])}</h1>' in path.read_text(), path.name
        assert f'<meta name="description" content="{html.escape(entry["description"])}">' in path.read_text(), path.name
        if entry.get("kind") != "evidence":
            source = (ROOT / "pages" / (entry["slug"] + ".html")).read_text()
            assert "v0.5.0" not in source and "v0.3.1" not in source and "0.2.2" not in source
        if entry["slug"] == "anomalies":
            assert '>chart 0.3.5</a>' in path.read_text()
        if entry["slug"] == "cardinality":
            assert entry["title"] == "How do I see LLM usage per user without a metric label for every user?"
            assert '<p class="lead">Keep user IDs out of your metric labels.' in path.read_text()
            for source in (
                "https://prometheus.io/docs/concepts/data_model/",
                "https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/metrics/",
                "https://docs.datadoghq.com/account_management/billing/custom_metrics/",
                "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch_concepts.html",
                "https://github.com/llm-measurement/otelcol-genai-sketches/blob/v0.3.3/builder.yaml",
            ):
                assert source in page.links, source
        if entry["slug"] in {"token-spike", "cardinality", "anomalies", "litellm-spend", "traces-usage", "cache-check"}:
            source = (ROOT / "pages" / (entry["slug"] + ".html")).read_text()
            assert "--branch v0.8.0" in source and "sh scripts/install.sh v0.8.0 ./release" in source
            assert "v0.6.0" not in source
            if entry["slug"] == "traces-usage":
                assert "./release/fleetdiff inspect examples/inspect/synthetic-traces.json" in source
                assert "go run" not in source and "Go 1.26" not in source
            if entry["slug"] == "cache-check":
                assert entry["title"] == "Prompt cache hit rate dropped after an update? Find whose uncached input grew"
                assert entry["document_title"] == entry["title"]
                assert entry["description"].startswith("Prompt cache hit rate dropped after an update?")
                assert len(entry["description"]) <= 155
                assert "--litellm-spend examples/litellm-spend/cache-drop.csv" in source
                assert "--group-by key" in source and "go run" not in source
                assert source.index('data-output="cache-check"') < source.index('data-run="cache-check"')
                assert "key-1: 80 -&gt; 700 uncached input tokens; change +620." in source
        if entry["slug"] == "session-budget":
            source = (ROOT / "pages/session-budget.html").read_text()
            assert "--branch v0.8.0" in source and "sh scripts/install.sh v0.8.0 ./release" in source
            assert "--session-budget-usd 1.00" in source and "Redis" not in source
            for url in ("https://docs.litellm.ai/docs/a2a_iteration_budgets",
                        "https://github.com/BerriAI/litellm/issues/34732",
                        "https://github.com/BerriAI/litellm/issues/43190"):
                assert url in page.links, url
        if entry["slug"] in {"distinct-users", "tokenmaxxing"}:
            source = (ROOT / "pages" / (entry["slug"] + ".html")).read_text()
            assert "llm-sketchkit==0.3.0" in source and "v0.2.2" not in source
        if entry.get("kind") == "evidence":
            assert page.commands == 0, path.name
            assert 'id="reproduce"' in path.read_text(), path.name
        elif entry["slug"] != "index" and entry.get("kind") != "reference":
            assert "?" in entry["title"] and page.commands == 1, path.name
            context = html.escape(GUIDE_CONTEXT[entry["slug"]])
            notes_link = '<a href="summaries.html#measurement-notes">Measurement notes</a>'
            if entry["slug"] == "cache-check":
                notes_link += '. <a href="https://github.com/llm-measurement/fleetdiff/blob/v0.8.0/docs/CACHE.md">Cache measurements and limits</a>.'
            expected = (f'<p class="measurement-context">{context}<br>\n'
                        f'{notes_link}</p>')
            assert expected in path.read_text(), (path.name, "guide context must precede its notes link")
            assert path.read_text().count('class="measurement-context"') == 1, path.name
            source = (ROOT / "pages" / (entry["slug"] + ".html")).read_text()
            ordered = ['class="lead"', 'class="own-data"', "What you'll see", "No data handy? Try the sample", 'class="measurement-context"']
            positions = [source.index(marker) for marker in ordered]
            assert positions == sorted(positions), (path.name, "own-data-first order")
            parsed = Blocks()
            parsed.feed(source)
            assert parsed.own and all("git clone" not in b["text"] for b in parsed.own), path.name
        for link in page.links:
            target = urlsplit(link)
            if not target.scheme and (target.path or target.fragment):
                linked_path = path.parent / target.path if target.path else path
                assert linked_path.is_file(), (path.name, link)
                if target.fragment:
                    linked_page = Page()
                    linked_page.feed(linked_path.read_text())
                    assert target.fragment in linked_page.ids, (path.name, link)
    assert measurement_sections == 1, "measurement notes must have one shared home"
    home = (ROOT / "docs/index.html").read_text().split('<ul class="questions">', 1)[1].split('</ul>', 1)[0]
    assert home.index('href="token-spike.html"') < home.index('href="tokenmaxxing.html"') < home.index('href="cardinality.html"')
    assert 'href="litellm-spend.html"' in home
    assert home.index('href="litellm-spend.html"') < home.index('href="session-budget.html"') < home.index('href="cache-check.html"')
    assert home.index('href="litellm-spend.html"') < home.index('href="cache-check.html"') < home.index('href="cardinality.html"')
    assert home.index('href="anomalies.html"') < home.index('href="traces-usage.html"') < home.index('href="distinct-users.html"')
    assert '<h2>Guides</h2>' in (ROOT / "docs/index.html").read_text()
    for entry in pages:
        if entry["slug"] in {"token-spike", "tokenmaxxing", "litellm-spend", "cache-check", "cardinality", "traces-usage"}:
            assert entry["description"] in html.unescape(home), entry["slug"]
        if entry["slug"] in {"token-spike", "tokenmaxxing"}:
            guide = (ROOT / "docs" / (entry["slug"] + ".html")).read_text()
            assert f'<p class="lead">{entry["description"]}</p>' in html.unescape(guide), entry["slug"]
    assert ('<p class="lead">Compare two periods of LiteLLM spend logs to see which models and keys '
            'drove a change, and which records have incomplete usage.</p>') in (ROOT / "docs/litellm-spend.html").read_text()
    for slug in ("anomalies", "litellm-spend"):
        body = (ROOT / "pages" / (slug + ".html")).read_text()
        assert '<a href="traces-usage.html">Do my LLM traces record token usage and user IDs?</a>' in body, slug
    assert ('To see who uses the most overall, rather than who changed, see '
            '<a href="tokenmaxxing.html">Who is tokenmaxxing?</a>') in (ROOT / "docs/token-spike.html").read_text()
    assert ('To see who caused a jump between two periods, see '
            '<a href="token-spike.html">Which user is driving my token spike?</a>') in (ROOT / "docs/tokenmaxxing.html").read_text()
    homepage = (ROOT / "docs/index.html").read_text()
    assert homepage.index('Run it on your data') < homepage.index('Built for enterprise review') < homepage.index('<h2>Guides</h2>')
    assert 'Each guide runs released versions on synthetic examples.' not in homepage
    assert 'href="security.html"' in homepage
    urls = ET.parse(ROOT / "docs/sitemap.xml").findall("{*}url")
    assert len(urls) == len(pages)
    text_index = (ROOT / "docs/llms.txt").read_text()
    assert all(p["slug"] + ".html" in text_index for p in pages[1:])
    assert (ROOT / "docs/.nojekyll").exists()
    for name in STATIC_ROOT_FILES:
        assert (ROOT / "docs" / name).read_bytes() == (ROOT / name).read_bytes(), name
    guides = sum(p["slug"] != "index" and not p.get("kind") for p in pages)
    verified = json.loads((ROOT / "evidence/verified.json").read_text())["results"]
    guide_slugs = {p["slug"] for p in pages if p["slug"] != "index" and not p.get("kind")}
    assert len(verified) == len(guide_slugs) and {r["page"] for r in verified} == guide_slugs
    for record in verified:
        blocks = Blocks()
        blocks.feed((ROOT / "pages" / (record["page"] + ".html")).read_text())
        assert len(blocks.commands) == 1
        command = blocks.commands[0]
        assert record["pass"] and record["exit"] == command["exit"], record["page"]
        assert record["command_sha256"] == hashlib.sha256(command["text"].encode()).hexdigest(), record["page"]
    own_verified = json.loads((ROOT / "evidence/own-data-verified.json").read_text())["results"]
    actual = {}
    for slug in guide_slugs | {"index"}:
        blocks = Blocks()
        blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
        for block in blocks.own:
            assert block["id"] not in actual
            actual[block["id"]] = (slug, block)
    assert set(actual) == {r["block"] for r in own_verified}
    for record in own_verified:
        slug, block = actual[record["block"]]
        assert record["pass"] and record["page"] == slug and record["exit"] == block["exit"]
        assert record["command_sha256"] == hashlib.sha256(block["text"].encode()).hexdigest(), block["id"]
    reviewer = Blocks()
    reviewer.feed((ROOT / "pages/security.html").read_text())
    release_verified = json.loads((ROOT / "evidence/release-review-verified.json").read_text())["results"]
    assert {r["block"] for r in release_verified} == {b["id"] for b in reviewer.review}
    for record in release_verified:
        block = next(b for b in reviewer.review if b["id"] == record["block"])
        assert record["pass"] and record["exit"] == 0
        assert record["command_sha256"] == hashlib.sha256(block["text"].encode()).hexdigest()
    print(f"PASS: {len(pages)} pages, {guides} runnable guides, local links, sitemap, llms.txt and static root files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--own-data", action="store_true", help="execute published own-data commands against stand-in inputs")
    parser.add_argument("--release-review", action="store_true", help="execute manual verification commands (requires trusted gh and cosign)")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/local/own-data")
    parser.add_argument("--page", help="limit runtime verification to one page")
    args = parser.parse_args()
    if args.release_review:
        import review_releases
        review_releases.check(args.output)
    elif args.own_data:
        import own_data
        own_data.check(args.output, args.page)
    else:
        main()
