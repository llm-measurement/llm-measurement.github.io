# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check generated pages, local links, question titles and the text indexes."""
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.h1 = 0
        self.commands = 0
        self.has_description = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.h1 += tag == "h1"
        self.commands += tag == "pre" and "data-run" in attrs
        if tag in {"a", "link", "img"}:
            self.links.append(attrs.get("href", attrs.get("src", "")))
        if tag == "meta" and attrs.get("name") == "description":
            self.has_description = bool(attrs.get("content"))


def main():
    pages = json.loads((ROOT / "pages.json").read_text())
    for entry in pages:
        path = ROOT / "docs" / (entry["slug"] + ".html")
        page = Page()
        page.feed(path.read_text())
        assert page.h1 == 1 and page.has_description, path.name
        if entry.get("kind") == "evidence":
            assert page.commands == 0, path.name
            assert 'id="reproduce"' in path.read_text(), path.name
        elif entry["slug"] != "index":
            assert entry["title"].endswith("?") and page.commands == 1, path.name
        for link in page.links:
            target = urlsplit(link)
            if not target.scheme and target.path:
                assert (path.parent / target.path).is_file(), (path.name, link)
    urls = ET.parse(ROOT / "docs/sitemap.xml").findall("{*}url")
    assert len(urls) == len(pages)
    text_index = (ROOT / "docs/llms.txt").read_text()
    assert all(p["slug"] + ".html" in text_index for p in pages[1:])
    assert (ROOT / "docs/.nojekyll").exists()
    guides = sum(p["slug"] != "index" and p.get("kind") != "evidence" for p in pages)
    print(f"PASS: {len(pages)} pages, {guides} runnable guides, local links, sitemap and llms.txt")


if __name__ == "__main__":
    main()
