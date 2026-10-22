# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Keep current installation commands and new guide registration in sync."""
import json
import subprocess
import unittest

from outsider import Blocks, ROOT
from own_data import FIXTURE_COMMIT, FIXTURE_VERSION


class FleetdiffReleaseTests(unittest.TestCase):
    def test_fleetdiff_commands_pin_v0120(self):
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
                        self.assertIn("v0.12.1", block["text"])
                    if "curl" in block["text"] and "install-fleetdiff.sh" in block["text"]:
                        self.assertIn("fleetdiff/" + FIXTURE_COMMIT + "/scripts/install.sh", block["text"])
                    if "/archive/refs/tags/" in block["text"]:
                        self.assertIn("cd fleetdiff-" + FIXTURE_VERSION.removeprefix("v") + "\n", block["text"])
                    self.assertNotIn("git clone", block["text"])
                self.assertNotIn("v0.11.0", source)

    def test_home_library_installs_use_v040(self):
        source = (ROOT / "pages/index.html").read_text()
        self.assertIn("llm-sketchkit==0.4.0", source)
        self.assertIn("sketchkit/...@v0.4.0", source)

    def test_whatif_approved_limits_and_unchanged_example_arithmetic(self):
        source = (ROOT / "pages/what-if.html").read_text()
        self.assertIn('<li>The factors are geometric-mean paired ratios measured on public benchmark tasks; '
                      'your prompts, workload and model behavior may differ.</li>', source)
        self.assertIn('<li>Level 2 endpoints show the uncertainty of the measured <em>average</em> output-verbosity factor, '
                      'not a range for your traffic. In a fresh calibration on 20 batches of 30 tasks, '
                      'they contained the measured cost of the moved traffic in 19 of 20 batches for Sol to Luna QA '
                      'and 17 of 20 for Sol to Luna extraction, but in only 2 to 14 of 20 for the other six completed cases. '
                      'Coding factors fit on HumanEval did not transfer to MBPP, and an earlier per-request test also failed. '
                      '<a href="https://github.com/llm-measurement/fleetdiff/blob/main/docs/WHAT_IF_CALIBRATION.md">'
                      'See the calibration.</a></li>', source)
        limits = source.split('<summary>What the numbers mean</summary>\n<ul>')[1].split('</ul>')[0]
        self.assertEqual(limits.count('<li>'), 4)
        self.assertIn('<li>This re-prices recorded usage under explicit model, cache and workload assumptions. '
                      'It is not a forecast or an invoice.</li>', limits)
        self.assertIn('<li>No quality equivalence is claimed.</li>', limits)
        blocks = Blocks()
        blocks.feed(source)
        self.assertIn("$0.154400 -> $0.109398 to $0.147974", blocks.expected[0]["text"])
        self.assertIn("Level 1, same work and output verbosity: $0.148703", blocks.expected[0]["text"])
        self.assertIn("Level 2, coding: $0.140323 (propagated mean-interval endpoints $0.133659 to $0.147974)", blocks.expected[0]["text"])
        self.assertEqual(source.count("<summary>What the numbers mean</summary>"), 1)

    def test_new_guides_are_registered_and_runnable(self):
        pages = json.loads((ROOT / "pages.json").read_text())
        slugs = [page["slug"] for page in pages]
        self.assertLess(slugs.index("litellm-spend"), slugs.index("row-coverage"))
        self.assertLess(slugs.index("row-coverage"), slugs.index("what-if"))
        self.assertLess(slugs.index("row-coverage"), slugs.index("routing"))
        self.assertLess(slugs.index("routing"), slugs.index("what-if"))
        for slug in ("row-coverage", "routing", "what-if"):
            source = (ROOT / "pages" / (slug + ".html")).read_text()
            blocks = Blocks()
            blocks.feed(source)
            with self.subTest(page=slug):
                self.assertEqual(len(blocks.commands), 1)
                self.assertTrue(blocks.expected)
                self.assertTrue(blocks.own)
                self.assertEqual(source.count("<summary>What the numbers mean</summary>"), 1)
                for block in blocks.commands + blocks.own:
                    result = subprocess.run(["bash", "-n"], input=block["text"],
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
