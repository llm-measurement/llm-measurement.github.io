# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Live-study gate tests use synthetic responses and never make network calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import study_outsider as outsider
from study_checks import PLAUSIBLE_INIT, PLAUSIBLE_SRC


class StudyOutsiderTests(unittest.TestCase):
    def test_gets_are_anonymous_bounded_and_uncached(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, count):
                self.count = count
                return b"public bytes"
        response = Response()
        with patch.object(outsider, "urlopen", return_value=response) as opened:
            self.assertEqual(outsider.fetch(outsider.BASE), b"public bytes")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Cache-control"), "no-cache")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(response.count, outsider.MAX_RESPONSE + 1)
        self.assertEqual(opened.call_args.kwargs["timeout"], 30)

    def test_credentials_and_non_https_are_refused_before_network(self):
        with patch.object(outsider, "urlopen", side_effect=AssertionError("network forbidden")):
            for url in ("http://example.com", "https://user:secret@example.com"):
                with self.subTest(url=url), self.assertRaisesRegex(ValueError, "anonymous HTTPS"):
                    outsider.fetch(url)

    def test_live_page_mismatch_stops_before_link_checks(self):
        with patch.object(outsider, "check", return_value={}), \
             patch.object(outsider, "staged_articles", return_value={"docs/prompt-cache-bills.html": b"expected"}):
            with self.assertRaisesRegex(ValueError, "differs"):
                outsider.check_live(fetcher=lambda url: b"different")

    def test_local_paths_cannot_escape_public_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "private.txt").write_text("not public")
            with self.assertRaisesRegex(ValueError, "published local file"):
                outsider.local_bytes(root, outsider.BASE + "../private.txt")

    def test_live_article_links_resources_and_evidence_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            evidence = docs / outsider.EVIDENCE_DIR
            evidence.mkdir(parents=True)
            (evidence / "index.html").write_bytes(b"<h1>Evidence</h1>")
            (evidence / "sample.txt").write_bytes(b"sample")
            (docs / "assets/site.css").write_bytes(b"body{}")
            (docs / "assets/site.js").write_bytes(b"'use strict';")
            html = ('<!doctype html><head><link rel="stylesheet" href="assets/site.css">'
                    '<script async src="' + PLAUSIBLE_SRC + '"></script><script>' +
                    PLAUSIBLE_INIT + '</script><script defer src="assets/site.js"></script></head>'
                    '<body><article><h2 id="method">Method</h2><a href="#method">Method</a>'
                    '<a href="assets/cache-evidence/">Evidence</a>'
                    '<a href="https://example.org/source">Source</a></article></body>').encode()
            article_url = outsider.BASE + outsider.SLUG + ".html"
            replies = {article_url: html, "https://example.org/source": b"primary source"}
            replies.update({outsider.BASE + name: (docs / name).read_bytes() for name in
                            ("assets/site.css", "assets/site.js", "assets/cache-evidence/index.html",
                             "assets/cache-evidence/sample.txt")})
            replies[outsider.BASE + outsider.EVIDENCE_DIR + "/"] = (evidence / "index.html").read_bytes()
            calls = []

            def fetch(url):
                calls.append(url)
                return replies[url]

            with patch.object(outsider, "check", return_value={"evidence_files": 2, "mathml": 1}), \
                 patch.object(outsider, "staged_articles", return_value={"docs/" + outsider.SLUG + ".html": html}):
                result = outsider.check_live(root, fetch)
                self.assertTrue(result["pass"])
                self.assertEqual(set(calls), set(replies))
                self.assertEqual(len(calls), len(set(calls)))
                replies[outsider.BASE + "assets/cache-evidence/sample.txt"] = b"changed"
                with self.assertRaisesRegex(ValueError, "local study link differs"):
                    outsider.check_live(root, fetch)
                replies[article_url] = html.replace(b'id="method"', b'id="different"')
                with patch.object(outsider, "staged_articles", return_value={
                        "docs/" + outsider.SLUG + ".html": replies[article_url]}):
                    with self.assertRaisesRegex(ValueError, "matching fragment"):
                        outsider.check_live(root, fetch)

    def test_live_study_gate_precedes_indexnow(self):
        source = (outsider.ROOT / ".github/workflows/docs.yml").read_text()
        job = source.split("  indexnow:", 1)[1]
        self.assertIn("fetch-depth: 0", job)
        self.assertIn("needs: [deploy]", job)
        self.assertLess(job.index("scripts/study_outsider.py --live"), job.index("scripts/indexnow.py --submit"))
        self.assertNotIn("continue-on-error", job)


if __name__ == "__main__":
    unittest.main()
