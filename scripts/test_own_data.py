# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Keep runnable own-data instructions separate from sample output."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from outsider import Blocks, ROOT
from own_data import EXPECTED, PAGES, refresh_history


class OwnDataTests(unittest.TestCase):
    def test_slow_install_does_not_expire_the_scan_standin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(30):
                start = index * 60 * 1_000_000_000
                window = {"window_start_unix_nano": start, "observed_start_unix_nano": start,
                    "observed_end_unix_nano": start + 60 * 1_000_000_000,
                    "emitted_at_unix_nano": start + 60 * 1_000_000_000,
                    "counters": {"requests": 100}}
                (root / f"{index:02}.json").write_text(json.dumps(window))
            for now in (2000, 2181, 5600):
                refresh_history(root, now)
                windows = [json.loads(p.read_text()) for p in sorted(root.glob("*.json"))]
                self.assertEqual(windows[-1]["observed_end_unix_nano"], now // 60 * 60 * 1_000_000_000)
                self.assertEqual(windows[0]["observed_end_unix_nano"], windows[-1]["observed_end_unix_nano"] - 29 * 60 * 1_000_000_000)
                for window in windows:
                    self.assertEqual(window["counters"], {"requests": 100})
                self.assertEqual((root / "00.json").read_text(), json.dumps(windows[0], sort_keys=True, separators=(",", ":")))

    def test_extracts_decoded_commands_and_expected_status(self):
        blocks = Blocks()
        blocks.feed('<pre data-own="x" data-exit="3"><code>cmd &gt; out</code></pre>'
                    '<pre data-run="x" data-exit="0">sample</pre>'
                    '<pre data-output="x">answer</pre>'
                    '<pre data-review="r">verify</pre>')
        self.assertEqual(blocks.own, [{"id": "x", "text": "cmd > out", "exit": 3}])
        self.assertEqual(blocks.commands, [{"text": "sample", "exit": 0}])
        self.assertEqual(blocks.expected, [{"text": "answer"}])
        self.assertEqual(blocks.review, [{"id": "r", "text": "verify", "exit": 0}])

    def test_all_real_data_commands_have_runtime_expectations(self):
        ids = []
        for slug in PAGES:
            blocks = Blocks()
            blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
            self.assertTrue(blocks.own, slug)
            for block in blocks.own:
                self.assertNotIn("git clone", block["text"], slug)
                ids.append(block["id"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(EXPECTED))

    def test_recorded_own_data_commands_match_page_sources(self):
        recorded = {r["block"]: r for r in json.loads(
            (ROOT / "evidence/own-data-verified.json").read_text())["results"]}
        for slug in PAGES:
            blocks = Blocks()
            blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
            for block in blocks.own:
                result = recorded[block["id"]]
                self.assertTrue(result["pass"])
                self.assertEqual(result["exit"], block["exit"])
                self.assertEqual(result["command_sha256"], hashlib.sha256(block["text"].encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
