# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Synthetic citation/live responses only; the shared fetcher is never invoked."""
import shutil
from unittest.mock import patch
from urllib.parse import urldefrag, urljoin
import unittest

import cheaper_study_checks as study
import cheaper_study_outsider as outsider
from study_checks import Document
from test_cheaper_study_checks import CheaperFixture


class CheaperStudyOutsider(CheaperFixture):
    def test_uses_the_existing_fetch_reference_and_local_bytes_without_wrappers(self):
        import study_outsider
        self.assertIs(outsider.fetch, study_outsider.fetch)
        self.assertIs(outsider.fetch_reference, study_outsider.fetch_reference)
        self.assertIs(outsider.local_bytes, study_outsider.local_bytes)

    def test_citation_preflight_is_source_only_and_independent_of_build_manifest_and_git(self):
        shutil.rmtree(self.root / "docs")
        shutil.rmtree(self.root / "assets")
        (self.root / study.MANIFEST).unlink()
        calls = []
        with patch.object(outsider, "check", side_effect=AssertionError("offline gate not needed")), \
             patch.object(outsider, "staged_articles", side_effect=AssertionError("Git not needed")):
            result = outsider.check_citations(self.root, lambda url: calls.append(url) or b"source")
        self.assertEqual(set(calls), {
            "https://platform.claude.com/docs/en/about-claude/pricing",
            "https://huggingface.co/datasets/semianalysisai/cc-traces-weka-061526",
            "https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence",
            "https://www.anthropic.com/claude-haiku-5-5",
            "https://github.com/llm-measurement/fleetdiff/blob/main/docs/WHAT_IF_CALIBRATION.md",
            "https://github.com/llm-measurement/fleetdiff",
        })
        self.assertEqual(len(calls), len(set(calls)))
        self.assertTrue(result["pass"])
        self.assertEqual(result["mode"], "citations")

    def test_unavailable_citation_and_changed_source_do_not_pass(self):
        with self.assertRaises(TimeoutError):
            outsider.check_citations(self.root, lambda url: (_ for _ in ()).throw(TimeoutError()))
        self.change(self.body_path, "69%", "68%")
        calls = []
        with self.assertRaisesRegex(AssertionError, "pinned v6 conversion"):
            outsider.check_citations(self.root, lambda url: calls.append(url))
        self.assertEqual(calls, [])

    def live_fixture(self):
        docs = self.root / "docs"
        (docs / "prompt-cache-bills.html").write_bytes(b'<h1 id="cache">Preview cache study</h1>')
        self.asset("pixel.png", b"fixture local CSS image")
        self.asset("site.css", b'body { background: url("pixel.png"); }')
        # Preview dates differ from first-parent publication dates by design.
        staged = self.built_path.read_bytes().replace(study.DATE.encode(), b"2026-11-21T05:06:07Z")
        publication = {f"docs/{study.SLUG}.html": staged,
                       "docs/prompt-cache-bills.html": b'<h1 id="cache">Published cache study</h1>'}
        replies = {study.BASE + path.relative_to(docs).as_posix(): path.read_bytes()
                   for path in docs.rglob("*") if path.is_file()}
        for name, data in publication.items():
            replies[study.BASE + name.removeprefix("docs/")] = data
        replies[study.BASE + study.EVIDENCE_DIR + "/"] = (docs / study.EVIDENCE_DIR / "index.html").read_bytes()
        article, = Document(staged.decode()).root.walk("article")
        for link in outsider.article_links(article):
            url = urldefrag(urljoin(study.URL, link))[0]
            if not url.startswith(study.BASE):
                replies[url] = b"primary citation"
        calls = []

        def fetch(url):
            calls.append(url)
            return replies[url]
        return publication, replies, calls, fetch

    def test_live_checks_exact_staged_articles_all_evidence_and_css_dependencies(self):
        publication, replies, calls, fetch = self.live_fixture()
        with patch.object(outsider, "staged_articles", return_value=publication):
            result = outsider.check_live(self.root, fetch)
        self.assertTrue(result["pass"])
        self.assertTrue(result["staged_publication_bytes_match"])
        self.assertEqual(result["evidence_files"], 21)
        self.assertEqual(result["inline_charts"], 2)
        self.assertEqual(set(calls), set(replies))
        self.assertEqual(len(calls), len(set(calls)))
        self.assertIn(study.BASE + "assets/pixel.png", calls)
        self.assertIn(study.BASE + study.CHART, calls)
        self.assertIn(study.BASE + study.CHART_NARROW, calls)

    def test_unstaged_preview_or_wrong_live_article_stops_before_link_fetches(self):
        publication, replies, calls, fetch = self.live_fixture()
        for content in (b"changed", self.built_path.read_bytes()):
            calls.clear()
            replies[study.URL] = content
            with patch.object(outsider, "staged_articles", return_value=publication), \
                 self.assertRaisesRegex(ValueError, "staged publication artifact"):
                outsider.check_live(self.root, fetch)
            self.assertEqual(calls, [study.URL])

    def test_changed_live_chart_output_evidence_or_css_dependency_is_rejected(self):
        publication, replies, _, fetch = self.live_fixture()
        for name in (study.CHART, study.CHART_NARROW, study.EVIDENCE_DIR + "/fleetdiff-v0150-what-if.txt",
                     study.EVIDENCE_DIR + "/RUN.md", "assets/pixel.png", "prompt-cache-bills.html"):
            url = study.BASE + name
            original = replies[url]
            replies[url] = original + b"\n"
            with self.subTest(name=name), patch.object(outsider, "staged_articles", return_value=publication), \
                 self.assertRaisesRegex(ValueError, "checked publication bytes"):
                outsider.check_live(self.root, fetch)
            replies[url] = original

    def test_live_local_fragments_are_checked_after_staged_byte_comparison(self):
        publication, replies, _, fetch = self.live_fixture()
        # The approved article has no local fragments; exercise that small branch
        # without changing the article acceptance pins or its frozen fixture.
        original = outsider.article_links
        with patch.object(outsider, "article_links", side_effect=lambda article:
                          original(article) + ["prompt-cache-bills.html#missing"]), \
             patch.object(outsider, "staged_articles", return_value=publication), \
             self.assertRaisesRegex(ValueError, "matching fragment"):
            outsider.check_live(self.root, fetch)

    def test_offline_gate_failure_prevents_all_live_fetches(self):
        path = self.root / study.EVIDENCE_DIR / "RUN.md"
        path.write_bytes(path.read_bytes() + b"\n")
        calls = []
        with patch.object(outsider, "staged_articles", side_effect=AssertionError("not reached")), \
             self.assertRaisesRegex(AssertionError, "evidence hash mismatch"):
            outsider.check_live(self.root, lambda url: calls.append(url))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
