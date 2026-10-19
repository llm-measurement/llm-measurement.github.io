# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check shared analytics and root-file preservation across clean builds."""
from html.parser import HTMLParser
import html
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import build


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.current = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        elif tag == "script":
            self.current = {"attrs": dict(attrs), "text": "", "in_head": self.in_head}
            self.scripts.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False
        elif tag == "script":
            self.current = None


class BuildTests(unittest.TestCase):
    def test_litellm_discovery_metadata_keeps_short_navigation_and_page_bodies(self):
        expected = (
            ("litellm-spend", "LiteLLM spend",
             "Check your LiteLLM cost tracking: what changed and who drove it",
             "One read-only command on your LiteLLM database shows which models, teams and keys drove a spend change, "
             "and which requests never reached the spend logs."),
            ("row-coverage", "Row coverage",
             "LiteLLM spend logs missing requests? Compare with daily counts",
             "Compare LiteLLM spend-log rows with recorded daily counts; review missing-row discrepancies "
             "and the released response-ID collision example."),
            ("routing", "Routing audit",
             "Which model actually served your LiteLLM route?",
             "Audit LiteLLM Auto Routing and fallbacks: compare model shares, missing attribution "
             "and classifier overhead using recorded spend only."),
        )
        pages = {page["slug"]: page for page in build.PAGES}
        index = (build.ROOT / "docs/llms.txt").read_text()
        for slug, label, title, description in expected:
            with self.subTest(page=slug):
                self.assertEqual(pages[slug]["title"], title)
                self.assertEqual(pages[slug]["document_title"], title)
                self.assertEqual(pages[slug]["description"], description)
                rendered = (build.ROOT / "docs" / (slug + ".html")).read_text()
                escaped_title, escaped_description = html.escape(title), html.escape(description)
                for element in (f"<title>{escaped_title}</title>", f"<h1>{escaped_title}</h1>",
                                f'<meta property="og:title" content="{escaped_title}">',
                                f'<meta property="og:description" content="{escaped_description}">',
                                f'<meta name="description" content="{escaped_description}">'):
                    self.assertEqual(rendered.count(element), 1)
                self.assertEqual(rendered.count(f'href="{slug}.html" aria-current="page">{label}</a>'), 2)
                body = (build.ROOT / "pages" / (slug + ".html")).read_text()
                self.assertIn(f"<h1>{escaped_title}</h1>{body}</main>", rendered)
                self.assertIn(f"- [{title}]({build.BASE}{slug}.html): {description}\n", index)

    def test_every_page_has_the_supplied_analytics_once_in_head(self):
        for page in build.PAGES:
            with self.subTest(page=page["slug"]):
                parsed = Scripts()
                parsed.feed((build.ROOT / "docs" / (page["slug"] + ".html")).read_text())
                self.assertEqual(len(parsed.scripts), 2)
                external, bootstrap = parsed.scripts
                self.assertTrue(external["in_head"] and bootstrap["in_head"])
                self.assertEqual(external["attrs"], {
                    "async": None,
                    "src": "https://plausible.io/js/pa-XxJJVAxJMHffrJ0MqBrpF.js",
                })
                self.assertEqual(external["text"], "")
                self.assertEqual(bootstrap["attrs"], {})
                self.assertEqual(bootstrap["text"].strip(), (
                    "window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},"
                    "plausible.init=plausible.init||function(i){plausible.o=i||{}};\n"
                    "  plausible.init()"
                ))

    def test_verification_survives_rebuild_and_stale_asset_cleanup(self):
        source = build.ROOT
        name = "googled831a5845f87080c.html"
        expected = b"google-site-verification: googled831a5845f87080c.html"
        self.assertEqual((source / name).read_bytes(), expected)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("assets", "pages"):
                shutil.copytree(source / folder, root / folder)
            shutil.copyfile(source / name, root / name)
            with patch.object(build, "ROOT", root):
                build.build()
                verification = root / "docs" / name
                self.assertEqual(verification.read_bytes(), expected)
                stale_asset = root / "docs/assets/stale-test.txt"
                stale_asset.write_text("remove this generated test asset")
                build.build()
                self.assertFalse(stale_asset.exists())
                self.assertEqual(verification.read_bytes(), expected)
                shutil.rmtree(root / "docs")
                build.build()
                self.assertEqual(verification.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
