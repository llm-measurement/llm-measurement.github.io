# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check shared analytics and root-file preservation across clean builds."""
from html.parser import HTMLParser
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
