# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Isolated mutation tests; never build the shared tree or access the network."""
import copy
import html
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import cheaper_study_checks as study
from study_checks import Document, PLAUSIBLE_INIT, PLAUSIBLE_SRC, sha256


class CheaperFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.enterContext(patch("socket.socket", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("network forbidden")))
        self.body_path = self.root / f"pages/{study.SLUG}.html"
        self.built_path = self.root / f"docs/{study.SLUG}.html"
        self.body_path.parent.mkdir()
        (self.root / "evidence").mkdir()
        self.body_path.write_bytes((study.ROOT / f"pages/{study.SLUG}.html").read_bytes())
        self.record = json.loads((study.ROOT / study.MANIFEST).read_bytes())
        for prefix in (self.root, self.root / "docs"):
            for name in study.EVIDENCE_NAMES:
                target = prefix / study.EVIDENCE_DIR / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(study.ROOT / study.EVIDENCE_DIR / name, target)
            for name in study.DEPENDENCIES:
                target = prefix / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(study.ROOT / name, target)
        self.page = {"slug": study.SLUG, "title": study.TITLE, "document_title": study.DOCUMENT_TITLE,
                     "description": study.DESCRIPTION, "kind": "study", "article": True,
                     "published": study.DATE, "modified": study.DATE, "navigation": False}
        self.save_config()
        self.save_record()
        self.asset("site.css", b"body { color: black; }\n")
        self.asset("site.js", b"'use strict';\n")
        self.render()

    def save_record(self):
        (self.root / study.MANIFEST).write_text(json.dumps(self.record), encoding="utf-8")

    def save_config(self):
        (self.root / "pages.json").write_text(json.dumps([self.page]), encoding="utf-8")

    def asset(self, name, content):
        for prefix in (self.root, self.root / "docs"):
            (prefix / "assets" / name).write_bytes(content)

    def render(self):
        # Independent frame: do not depend on the parent's concurrently edited builder.
        meta = [("name", "description", study.DESCRIPTION),
                ("property", "og:title", study.DOCUMENT_TITLE),
                ("property", "og:description", study.DESCRIPTION),
                ("property", "og:type", "article"), ("property", "og:url", study.URL),
                ("property", "og:site_name", "LLM Measurement"),
                ("property", "article:published_time", study.DATE),
                ("property", "article:modified_time", study.DATE),
                ("name", "twitter:card", "summary"),
                ("name", "twitter:title", study.DOCUMENT_TITLE),
                ("name", "twitter:description", study.DESCRIPTION),
                ("name", "twitter:url", study.URL)]
        ld = {"@context": "https://schema.org", "@type": "BlogPosting", "headline": study.TITLE,
              "description": study.DESCRIPTION, "datePublished": study.DATE, "dateModified": study.DATE,
              "author": {"@type": "Person", "name": "Vijay"},
              "publisher": {"@type": "Organization", "name": "LLM Measurement"},
              "mainEntityOfPage": {"@type": "WebPage", "@id": study.URL}}
        head = ''.join(f'<meta {attr}="{key}" content="{html.escape(value, quote=True)}">'
                       for attr, key, value in meta)
        self.built_path.write_text(
            '<!doctype html><html><head><title>' + html.escape(study.DOCUMENT_TITLE) + '</title>'
            + head + f'<link rel="canonical" href="{study.URL}">'
            '<link rel="stylesheet" href="assets/site.css">'
            '<script type="application/ld+json">' + json.dumps(ld) + '</script>'
            '<!-- Privacy-friendly analytics by Plausible -->'
            f'<script async src="{PLAUSIBLE_SRC}"></script><script>{PLAUSIBLE_INIT}</script>'
            '<script defer src="assets/site.js"></script></head><body><main><h1>'
            + html.escape(study.TITLE) + '</h1>' + self.body_path.read_text(encoding="utf-8")
            + '</main><footer>Privacy-friendly analytics by '
            '<a href="https://plausible.io/data-policy">Plausible</a>: no cookies, no personal data'
            '</footer></body></html>', encoding="utf-8")

    def change(self, path, old, new):
        data = path.read_text(encoding="utf-8")
        self.assertIn(old, data)
        path.write_text(data.replace(old, new, 1), encoding="utf-8")

    def change_built(self, old, new):
        self.change(self.built_path, old, new)


class CheaperStudyChecks(CheaperFixture):
    def test_pinned_article_and_all_twenty_evidence_files_pass_offline(self):
        summary = study.check(self.root)
        self.assertEqual(summary["evidence_files"], 20)
        self.assertEqual((summary["code_blocks"], summary["tables"], summary["headings"]), (2, 2, 5))
        self.assertTrue(summary["offline"])

    def test_source_words_and_output_cannot_be_reapproved_by_refreshing_manifest(self):
        original = self.body_path.read_bytes()
        for old, new in (("69%", "68%"), ("$3,558.76", "$3,558.77")):
            with self.subTest(old=old):
                self.body_path.write_bytes(original)
                self.change(self.body_path, old, new)
                with self.assertRaisesRegex(AssertionError, "pinned v6 conversion"):
                    study.check(self.root)
                self.record["conversion"]["article_body_sha256"] = sha256(self.body_path.read_bytes())
                self.save_record()
                with self.assertRaisesRegex(AssertionError, "conversion pins"):
                    study.check(self.root)
                self.record["conversion"] = copy.deepcopy(study.APPROVED_CONVERSION)
                self.save_record()

    def test_built_article_output_chart_and_line_endings_are_exact(self):
        for old, new in (("$3,558.76", "$3,558.77"), ("h34.8", "h34.9"),
                         (study.CHART_ALT, "Different chart alt")):
            with self.subTest(old=old):
                self.render()
                self.change_built(old, new)
                with self.assertRaisesRegex(AssertionError, "built article"):
                    study.check(self.root)
        self.render()
        self.built_path.write_bytes(self.built_path.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(AssertionError, "built article"):
            study.check(self.root)

    def test_evidence_and_chart_hashes_check_both_source_and_built_even_when_equal(self):
        for name in ("cached-session-cost-output.json", "cheaper-ratio-chart.svg",
                     "fleetdiff-v0150-what-if.txt", "RUN.md"):
            paths = [prefix / study.EVIDENCE_DIR / name for prefix in (self.root, self.root / "docs")]
            original = paths[0].read_bytes()
            for indexes in ((0,), (1,), (0, 1)):
                with self.subTest(name=name, indexes=indexes):
                    for index in indexes:
                        paths[index].write_bytes(original + b"\n")
                    with self.assertRaisesRegex(AssertionError, "evidence hash mismatch"):
                        study.check(self.root)
                    for path in paths:
                        path.write_bytes(original)

    def test_evidence_inventory_missing_extra_directory_and_symlink_fail(self):
        for prefix in (self.root, self.root / "docs"):
            folder = prefix / study.EVIDENCE_DIR
            path = folder / "private-extra.txt"
            path.write_bytes(b"private")
            with self.assertRaisesRegex(AssertionError, "inventory"):
                study.check(self.root)
            path.unlink()
            path.mkdir()
            with self.assertRaisesRegex(AssertionError, "regular files"):
                study.check(self.root)
            path.rmdir()
            target = folder / "RUN.md"
            original = target.read_bytes()
            target.unlink()
            with self.assertRaisesRegex(AssertionError, "inventory"):
                study.check(self.root)
            target.symlink_to(folder / "ATTRIBUTION.md")
            with self.assertRaisesRegex(AssertionError, "regular files"):
                study.check(self.root)
            target.unlink()
            target.write_bytes(original)

    def test_manifest_inventory_and_shared_dependency_pins_fail_closed(self):
        original = copy.deepcopy(self.record)
        for change in (lambda: self.record["evidence"].pop("RUN.md"),
                       lambda: self.record["evidence"].update({"draft.md": "a" * 64}),
                       lambda: self.record["dependencies"].clear(),
                       lambda: self.record.update(schema=True),
                       lambda: self.record.update(site_layout_evidence_reproduced=False),
                       lambda: self.record.update(converter_report_sha256="not-a-hash")):
            change()
            self.save_record()
            with self.assertRaises(AssertionError):
                study.check(self.root)
            self.record = copy.deepcopy(original)
        self.save_record()
        for prefix in (self.root, self.root / "docs"):
            path = prefix / sorted(study.DEPENDENCIES)[0]
            content = path.read_bytes()
            path.write_bytes(content + b"\n")
            with self.assertRaisesRegex(AssertionError, "evidence hash mismatch"):
                study.check(self.root)
            path.write_bytes(content)

    def test_tracker_missing_duplicate_wrong_or_nonexecuting_fails(self):
        script = f'<script async src="{PLAUSIBLE_SRC}"></script>'
        for replacement in ("", script + script, script.replace(PLAUSIBLE_SRC, "https://plausible.io/wrong.js"),
                            script.replace("async", 'async type="text/plain"')):
            with self.subTest(replacement=replacement):
                self.render()
                self.change_built(script, replacement)
                with self.assertRaises(AssertionError):
                    study.check(self.root)

    def test_unexpected_third_party_resources_and_active_surfaces_fail(self):
        for injected in ('<img src="https://tracker.example/pixel">',
                         '<script src="https://tracker.example/a.js"></script>',
                         '<link rel="preconnect" href="https://tracker.example">',
                         '<svg><image href="https://tracker.example/pixel"/></svg>',
                         '<iframe src="assets/frame.html"></iframe>'):
            with self.subTest(injected=injected):
                self.render()
                self.change_built("</main>", injected + "</main>")
                with self.assertRaises(AssertionError):
                    study.check(self.root)
        for css in (b'@import "https://tracker.example/a.css";',
                    b'body { background: url(https://tracker.example/pixel); }'):
            self.asset("site.css", css)
            with self.assertRaises(AssertionError):
                study.check(self.root)

    def test_privacy_footer_and_initializer_fail_when_changed(self):
        for old, new in (("no cookies, no personal data", "cookies"),
                         ("https://plausible.io/data-policy", "https://example.org/privacy"),
                         (PLAUSIBLE_INIT, "plausible.init({extra:true})")):
            with self.subTest(old=old):
                self.render()
                self.change_built(old, new)
                with self.assertRaises(AssertionError):
                    study.check(self.root)

    def test_wrong_head_author_dates_canonical_and_titles_fail(self):
        for old, new in (("<title>" + study.DOCUMENT_TITLE, "<title>Wrong"),
                         ("<h1>" + study.TITLE, "<h1>Wrong"),
                         ('"name": "Vijay"', '"name": "Another Author"'),
                         ('"datePublished": "' + study.DATE, '"datePublished": "2026-11-19T00:00:00Z'),
                         ('property="article:modified_time" content="' + study.DATE,
                          'property="article:modified_time" content="2026-11-19T00:00:00Z'),
                         ('rel="canonical" href="' + study.URL, 'rel="canonical" href="https://example.org/'),
                         ('name="twitter:card" content="summary"', 'name="twitter:card" content="other"'),
                         ('property="og:url" content="' + study.URL,
                          'property="og:url" content="https://example.org/')):
            with self.subTest(old=old):
                self.render()
                self.change_built(old, new)
                with self.assertRaises(AssertionError):
                    study.check(self.root)

    def test_duplicate_missing_or_unreviewed_metadata_fails(self):
        for injection in ('<meta property="og:type" content="article">',
                          '<meta property="og:image" content="https://example.org/not-real.png">',
                          '<link rel="canonical" href="' + study.URL + '">',
                          '<script type="application/ld+json">{}</script>'):
            self.render()
            self.change_built("</head>", injection + "</head>")
            with self.assertRaises(AssertionError):
                study.check(self.root)
        self.render()
        self.change_built('<meta name="twitter:card" content="summary">', "")
        with self.assertRaisesRegex(AssertionError, "head metadata"):
            study.check(self.root)

    def test_page_configuration_is_independently_pinned(self):
        for key, value in (("title", "Wrong"), ("published", "2026-11-19T00:00:00Z"),
                           ("modified", "2026-11-21T00:00:00Z"), ("article", 1)):
            old = self.page[key]
            self.page[key] = value
            self.save_config()
            with self.assertRaisesRegex(AssertionError, "page configuration"):
                study.check(self.root)
            self.page[key] = old

    def test_structure_retains_h3_divider_two_tables_two_blocks_and_exact_inline_svg(self):
        source = self.body_path.read_text(encoding="utf-8")
        chart = (self.root / study.CHART).read_bytes()
        for old, new in (("<hr>", ""), ('<h3 id="what-the-numbers-mean">',
                                          '<h2 id="what-the-numbers-mean">'),
                         ('class="study-table"', 'class="other"'),
                         ('class="output"', 'class="other"'),
                         (study.CHART_ALT, "Wrong alt"), ("h34.8", "h34.9")):
            changed = source.replace(old, new, 1)
            if new.startswith("<h2"):
                changed = changed.replace("</h3>", "</h2>", 1)
            document = Document(changed)
            article, = document.root.walk("article")
            with self.subTest(old=old), self.assertRaises(AssertionError):
                study.check_article_structure(article, changed, chart)

    def test_private_paths_draft_markers_and_comments_fail(self):
        for injection in ("<p>file://private-example</p>", "<p>POST_DRAFT_v6</p>", "<!-- internal draft -->"):
            self.render()
            self.change_built("</main>", injection + "</main>")
            with self.assertRaisesRegex(AssertionError, "private"):
                study.check(self.root)
        name = "ATTRIBUTION.md"
        content = b"Private machine path: /home/example/project\n"
        for prefix in (self.root, self.root / "docs"):
            (prefix / study.EVIDENCE_DIR / name).write_bytes(content)
        self.record["evidence"][name] = sha256(content)
        self.save_record()
        with self.assertRaisesRegex(AssertionError, "private text"):
            study.check(self.root)

    def test_local_css_dependency_bytes_use_existing_resource_checker(self):
        self.asset("pixel.png", b"fixture image")
        self.asset("site.css", b'body { background: url("pixel.png"); }')
        self.assertIn("assets/pixel.png", study.check(self.root)["resources"])
        (self.root / "docs/assets/pixel.png").write_bytes(b"different")
        with self.assertRaisesRegex(AssertionError, "built resource differs"):
            study.check(self.root)


if __name__ == "__main__":
    unittest.main()
