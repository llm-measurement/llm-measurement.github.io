# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check generated pages, local links, question titles and the text indexes."""
from html.parser import HTMLParser
import html
import json
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
GUIDE_CONTEXT = {
    "cardinality": "diagnose reads your collector configuration; your metrics backend reports live series counts.",
    "token-spike": "A flag marks a session worth a look. With real data, the report shows ranges wherever bounds differ.",
    "anomalies": "This example checks planted changes. Review any flag against your own history; sessions that turn over often can look newly prominent.",
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
        measurement_sections += "measurement-notes" in page.ids
        assert "What the numbers mean" not in path.read_text(), path.name
        assert page.links.count("summaries.html#measurement-notes") == 1, path.name
        assert page.h1 == 1 and page.has_description, path.name
        title = entry.get("document_title", entry["title"] + " | LLM Measurement")
        assert f"<title>{html.escape(title)}</title>" in path.read_text(), path.name
        assert f'<h1>{html.escape(entry["title"])}</h1>' in path.read_text(), path.name
        if entry.get("kind") == "evidence":
            assert page.commands == 0, path.name
            assert 'id="reproduce"' in path.read_text(), path.name
        elif entry["slug"] != "index":
            assert entry["title"].endswith("?") and page.commands == 1, path.name
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
    urls = ET.parse(ROOT / "docs/sitemap.xml").findall("{*}url")
    assert len(urls) == len(pages)
    text_index = (ROOT / "docs/llms.txt").read_text()
    assert all(p["slug"] + ".html" in text_index for p in pages[1:])
    assert (ROOT / "docs/.nojekyll").exists()
    guides = sum(p["slug"] != "index" and p.get("kind") != "evidence" for p in pages)
    print(f"PASS: {len(pages)} pages, {guides} runnable guides, local links, sitemap and llms.txt")


if __name__ == "__main__":
    main()
