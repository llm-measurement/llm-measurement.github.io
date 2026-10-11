# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check generated pages, local links, question titles and the text indexes."""
from html.parser import HTMLParser
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


def main():
    pages = json.loads((ROOT / "pages.json").read_text())
    measurement_sections = 0
    for entry in pages:
        path = ROOT / "docs" / (entry["slug"] + ".html")
        page = Page()
        page.feed(path.read_text())
        nav = path.read_text().split('<nav aria-label="Guides">', 1)[1].split('</nav>', 1)[0]
        assert nav.index('href="token-spike.html"') < nav.index('href="tokenmaxxing.html"') < nav.index('href="cardinality.html"'), path.name
        assert '>A token spike</a>' in nav and '>Tokenmaxxing</a>' in nav and '>Per-user metrics</a>' in nav, path.name
        assert '>LiteLLM spend</a>' in nav, path.name
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
        if entry["slug"] == "cardinality":
            assert entry["title"] == "How do I see LLM usage per user without a metric label for every user?"
            assert '<p class="lead">Keep user IDs out of your metric labels.' in path.read_text()
            for source in (
                "https://prometheus.io/docs/concepts/data_model/",
                "https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/metrics/",
                "https://docs.datadoghq.com/account_management/billing/custom_metrics/",
                "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch_concepts.html",
                "https://github.com/llm-measurement/otelcol-genai-sketches/blob/v0.3.1/builder.yaml",
            ):
                assert source in page.links, source
        if entry.get("kind") == "evidence":
            assert page.commands == 0, path.name
            assert 'id="reproduce"' in path.read_text(), path.name
        elif entry["slug"] != "index":
            assert "?" in entry["title"] and page.commands == 1, path.name
            context = html.escape(GUIDE_CONTEXT[entry["slug"]])
            expected = (f'<p class="measurement-context">{context}<br>\n'
                        '<a href="summaries.html#measurement-notes">Measurement notes</a></p>')
            assert expected in path.read_text(), (path.name, "guide context must precede its notes link")
            assert path.read_text().count('class="measurement-context"') == 1, path.name
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
    assert home.index('href="anomalies.html"') < home.index('href="traces-usage.html"') < home.index('href="distinct-users.html"')
    assert '<h2>Guides</h2>' in (ROOT / "docs/index.html").read_text()
    for entry in pages:
        if entry["slug"] in {"token-spike", "tokenmaxxing", "litellm-spend", "cardinality", "traces-usage"}:
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
    litellm_home = (ROOT / "docs/index.html").read_text().split('<h2>Using LiteLLM?</h2>', 1)[1].split('<h2>', 1)[0]
    assert litellm_home.index('fleetdiff/blob/v0.6.0/README.md#using-litellm') < litellm_home.index('otelcol-genai-sketches/tree/v0.3.1')
    urls = ET.parse(ROOT / "docs/sitemap.xml").findall("{*}url")
    assert len(urls) == len(pages)
    text_index = (ROOT / "docs/llms.txt").read_text()
    assert all(p["slug"] + ".html" in text_index for p in pages[1:])
    assert (ROOT / "docs/.nojekyll").exists()
    for name in STATIC_ROOT_FILES:
        assert (ROOT / "docs" / name).read_bytes() == (ROOT / name).read_bytes(), name
    guides = sum(p["slug"] != "index" and p.get("kind") != "evidence" for p in pages)
    verified = json.loads((ROOT / "evidence/verified.json").read_text())["results"]
    guide_slugs = {p["slug"] for p in pages if p["slug"] != "index" and p.get("kind") != "evidence"}
    assert len(verified) == len(guide_slugs) and {r["page"] for r in verified} == guide_slugs
    for record in verified:
        blocks = Blocks()
        blocks.feed((ROOT / "pages" / (record["page"] + ".html")).read_text())
        assert len(blocks.commands) == 1
        command = blocks.commands[0]
        assert record["pass"] and record["exit"] == command["exit"], record["page"]
        assert record["command_sha256"] == hashlib.sha256(command["text"].encode()).hexdigest(), record["page"]
    print(f"PASS: {len(pages)} pages, {guides} runnable guides, local links, sitemap, llms.txt and static root files")


if __name__ == "__main__":
    main()
