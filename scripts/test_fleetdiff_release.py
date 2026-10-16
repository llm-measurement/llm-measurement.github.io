# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Keep current installation commands and new guide registration in sync."""
import json
import subprocess
import unittest

from outsider import Blocks, ROOT


class FleetdiffReleaseTests(unittest.TestCase):
    def test_fleetdiff_commands_use_published_v0100(self):
        for path in (ROOT / "pages").glob("*.html"):
            if path.stem == "summaries":
                continue
            source = path.read_text()
            with self.subTest(page=path.stem):
                self.assertNotIn("fleetdiff/v0.8.0", source)
                self.assertNotIn("fleetdiff v0.8.0", source)
                blocks = Blocks()
                blocks.feed(source)
                for block in blocks.commands + blocks.own:
                    if "install.sh" in block["text"] or "install-fleetdiff.sh" in block["text"]:
                        self.assertIn("v0.10.0", block["text"])
                    self.assertNotIn("git clone", block["text"])

    def test_home_library_installs_use_v040(self):
        source = (ROOT / "pages/index.html").read_text()
        self.assertIn("llm-sketchkit==0.4.0", source)
        self.assertIn("sketchkit/...@v0.4.0", source)

    def test_new_guides_are_registered_and_runnable(self):
        pages = json.loads((ROOT / "pages.json").read_text())
        slugs = [page["slug"] for page in pages]
        self.assertLess(slugs.index("litellm-spend"), slugs.index("row-coverage"))
        self.assertLess(slugs.index("row-coverage"), slugs.index("what-if"))
        for slug in ("row-coverage", "what-if"):
            source = (ROOT / "pages" / (slug + ".html")).read_text()
            blocks = Blocks()
            blocks.feed(source)
            with self.subTest(page=slug):
                self.assertEqual(len(blocks.commands), 1)
                self.assertTrue(blocks.expected)
                self.assertTrue(blocks.own)
                self.assertEqual(source.count("<h2>Limits</h2>"), 1)
                for block in blocks.commands + blocks.own:
                    result = subprocess.run(["bash", "-n"], input=block["text"],
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
