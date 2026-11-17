# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Source-only study mutations: isolated minimal frames, no build or network."""
import html
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from study_checks import (CONVERTER_PASS, Document, EVIDENCE_DIR, EVIDENCE_NAMES,
                          MANIFEST, PLAUSIBLE_INIT, PLAUSIBLE_SRC,
                          QUOTED_LINES, RERUN_NAME, ROOT, SLUG, SUPPORT_NAMES,
                          TITLE, check, sha256)


class StudyChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch("socket.socket", side_effect=AssertionError("network forbidden in study tests")).start()
        patch("socket.create_connection", side_effect=AssertionError("network forbidden in study tests")).start()
        for folder in ("pages", "evidence", EVIDENCE_DIR, f"docs/{EVIDENCE_DIR}"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.body_path = self.root / f"pages/{SLUG}.html"
        self.built_path = self.root / f"docs/{SLUG}.html"
        self.body_path.write_bytes((ROOT / f"pages/{SLUG}.html").read_bytes())
        for name in EVIDENCE_NAMES:
            shutil.copyfile(ROOT / EVIDENCE_DIR / name, self.root / EVIDENCE_DIR / name)
        stdout = (self.root / EVIDENCE_DIR / "fleetdiff-output.txt").read_bytes()
        (self.root / EVIDENCE_DIR / RERUN_NAME).write_bytes(stdout)
        self.record = {
            "schema": 1, "source_sha256": sha256(b"approved source provenance"),
            "article_body_sha256": sha256(self.body_path.read_bytes()),
            "converter_pass": CONVERTER_PASS,
            "deterministic_evidence_reproduced": True,
            "evidence": {name: sha256((self.root / EVIDENCE_DIR / name).read_bytes())
                         for name in EVIDENCE_NAMES},
            "rerun": {
                "version": "fleetdiff v0.14.1 (45f8d7aef43a88e1c24033a9f80c4a667f8dbad7) go1.26.11 darwin/arm64",
                "archive_sha256": "a" * 64, "binary_sha256": "b" * 64,
                "stdout_sha256": sha256(stdout), "quoted_lines": list(QUOTED_LINES),
                "full_stdout_byte_equal": True, "spend_before": "1.944", "spend_after": "0.402",
                "sample_csv_sha256": sha256((self.root / EVIDENCE_DIR / "scheduled-job.csv").read_bytes()),
            },
        }
        self.save_record()
        (self.root / "pages.json").write_text(json.dumps([{"slug": SLUG, "title": TITLE}]), encoding="utf-8")
        self.asset("site.css", b"body { color: black; }\n")
        self.asset("site.js", b"/* fixture local site behavior */\n")
        self.copy_evidence()
        self.render()

    def save_record(self):
        (self.root / MANIFEST).write_text(json.dumps(self.record), encoding="utf-8")

    def asset(self, name, data):
        for prefix in (self.root, self.root / "docs"):
            (prefix / "assets" / name).write_bytes(data)

    def copy_evidence(self):
        for path in (self.root / EVIDENCE_DIR).iterdir():
            shutil.copyfile(path, self.root / "docs" / EVIDENCE_DIR / path.name)

    def render(self):
        # Deliberately do not import build: another agent owns its moving API.
        frame = (
            '<!doctype html><html><head><title>Fixture</title>'
            '<link rel="stylesheet" href="assets/site.css">'
            '<script type="application/ld+json">{"@type":"BlogPosting"}</script>'
            '<!-- Privacy-friendly analytics by Plausible -->'
            f'<script async src="{PLAUSIBLE_SRC}"></script>'
            f'<script>\n  {PLAUSIBLE_INIT}\n</script>'
            '<script defer src="assets/site.js"></script></head><body>'
            f'<main><h1>{html.escape(TITLE)}</h1>{self.body_path.read_text(encoding="utf-8")}</main>'
            '<footer>Privacy-friendly analytics by '
            '<a href="https://plausible.io/data-policy">Plausible</a>: no cookies, no personal data'
            '</footer></body></html>'
        )
        self.built_path.write_text(frame, encoding="utf-8")

    def change_built(self, old, new):
        source = self.built_path.read_text(encoding="utf-8")
        self.assertIn(old, source)
        self.built_path.write_text(source.replace(old, new, 1), encoding="utf-8")

    def change_body(self, old, new, *, approve=False):
        source = self.body_path.read_text(encoding="utf-8")
        self.assertIn(old, source)
        self.body_path.write_text(source.replace(old, new, 1), encoding="utf-8")
        if approve:
            self.record["article_body_sha256"] = sha256(self.body_path.read_bytes())
            self.save_record()
            self.render()

    def test_current_article_and_protected_evidence_pass_without_guide_rules(self):
        self.assertEqual(EVIDENCE_NAMES, {
            "RUN.md", "cache_puzzle-output.txt", "cache_puzzle.py", "fleetdiff-output.txt",
            "live_check-output.txt", "live_check-summary.json", "live_check.py",
            "make_fixture.py", "results.json", "scheduled-job.csv",
            "trace_replay-output.txt", "trace_replay-results.json", "trace_replay.py",
        })
        self.assertEqual(SUPPORT_NAMES, {"index.html", "RERUN_v0.14.1.md", "ATTRIBUTION.md"})
        self.assertEqual(RERUN_NAME, "fleetdiff-v0141-output.txt")
        summary = check(self.root)
        self.assertEqual(summary["evidence_files"], 13)
        self.assertEqual(summary["code_blocks"], 3)
        self.assertEqual(summary["quoted_lines"], 4)
        self.assertGreater(summary["mathml"], 1)
        self.assertEqual(summary["spend_before"], "1.944")
        self.assertEqual(summary["spend_after"], "0.402")
        self.assertTrue(summary["offline"])

    def test_parent_manifest_passes_against_real_body_and_original_evidence(self):
        self.record = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        self.save_record()
        check(self.root)

    def test_source_number_change_fails_even_if_built_page_unchanged(self):
        self.change_body("85%", "84%")
        with self.assertRaisesRegex(AssertionError, "body hash"):
            check(self.root)

    def test_built_number_change_fails(self):
        self.change_built("85%", "84%")
        with self.assertRaisesRegex(AssertionError, "built article"):
            check(self.root)

    def test_built_newlines_are_not_silently_normalized(self):
        self.built_path.write_bytes(self.built_path.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(AssertionError, "built article"):
            check(self.root)

    def test_original_evidence_bytes_are_protected(self):
        for prefix in (self.root, self.root / "docs"):
            path = prefix / EVIDENCE_DIR / "results.json"
            original = path.read_bytes()
            path.write_bytes(original + b"\n")
            with self.assertRaisesRegex(AssertionError, "evidence hash mismatch: results.json"):
                check(self.root)
            path.write_bytes(original)

    def test_private_extra_file_is_rejected_in_source_and_docs(self):
        for prefix in (self.root, self.root / "docs"):
            path = prefix / EVIDENCE_DIR / "POST_v2-private.md"
            path.write_text("draft", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "inventory"):
                check(self.root)
            path.unlink()

    def test_missing_evidence_and_directory_are_rejected(self):
        path = self.root / EVIDENCE_DIR / "results.json"
        path.unlink()
        with self.assertRaisesRegex(AssertionError, "inventory"):
            check(self.root)
        path.mkdir()
        with self.assertRaisesRegex(AssertionError, "regular files"):
            check(self.root)

    def test_manifest_cannot_expand_or_shrink_protected_inventory(self):
        self.record["evidence"]["draft.md"] = "a" * 64
        self.save_record()
        with self.assertRaisesRegex(AssertionError, "exactly the 13"):
            check(self.root)
        del self.record["evidence"]["draft.md"]
        del self.record["evidence"]["RUN.md"]
        self.save_record()
        with self.assertRaisesRegex(AssertionError, "exactly the 13"):
            check(self.root)

    def test_explicit_support_files_are_allowed_but_must_match_published_bytes(self):
        for name in SUPPORT_NAMES:
            (self.root / EVIDENCE_DIR / name).write_text("approved support", encoding="utf-8")
        self.copy_evidence()
        check(self.root)
        (self.root / "docs" / EVIDENCE_DIR / "ATTRIBUTION.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, "support file differs"):
            check(self.root)

    def test_repository_relative_manifest_keys_are_accepted(self):
        self.record["evidence"] = {f"{EVIDENCE_DIR}/{name}": value
                                   for name, value in self.record["evidence"].items()}
        self.save_record()
        check(self.root)

    def test_changed_rerun_even_with_updated_hash_is_not_byte_equal(self):
        altered = (self.root / EVIDENCE_DIR / RERUN_NAME).read_bytes() + b"\n"
        for prefix in (self.root, self.root / "docs"):
            (prefix / EVIDENCE_DIR / RERUN_NAME).write_bytes(altered)
        self.record["rerun"]["stdout_sha256"] = sha256(altered)
        self.save_record()
        with self.assertRaisesRegex(AssertionError, "not byte equal"):
            check(self.root)

    def test_rerun_hash_and_published_copy_are_checked(self):
        path = self.root / EVIDENCE_DIR / RERUN_NAME
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(AssertionError, "rerun stdout hash"):
            check(self.root)
        path.write_bytes(original)
        (self.root / "docs" / EVIDENCE_DIR / RERUN_NAME).write_bytes(original + b"\n")
        with self.assertRaisesRegex(AssertionError, "built rerun stdout"):
            check(self.root)

    def test_manifest_quote_spacing_is_literal(self):
        self.record["rerun"]["quoted_lines"][1] = QUOTED_LINES[1].lstrip()
        self.save_record()
        with self.assertRaisesRegex(AssertionError, "quoted lines differ"):
            check(self.root)

    def test_article_quote_spacing_is_literal_even_with_refreshed_hash(self):
        old = "      Cache reads: 0 of 492,000"
        self.change_body(old, old[1:], approve=True)
        with self.assertRaisesRegex(AssertionError, "quote differs"):
            check(self.root)

    def test_spend_and_sample_hash_must_match(self):
        for key, value in (("spend_before", "1.943"), ("spend_after", "0.403"),
                           ("sample_csv_sha256", "c" * 64), ("version", "v0.14.10"),
                           ("full_stdout_byte_equal", False)):
            with self.subTest(key=key):
                original = self.record["rerun"][key]
                self.record["rerun"][key] = value
                self.save_record()
                with self.assertRaises(AssertionError):
                    check(self.root)
                self.record["rerun"][key] = original

    def test_manifest_attestations_and_digest_formats_are_required(self):
        for key, value in (("schema", True), ("source_sha256", "unknown"),
                           ("article_body_sha256", "a" * 64), ("converter_pass", "PASS"),
                           ("deterministic_evidence_reproduced", False)):
            with self.subTest(key=key):
                original = self.record[key]
                self.record[key] = value
                self.save_record()
                with self.assertRaises(AssertionError):
                    check(self.root)
                self.record[key] = original

    def test_missing_duplicate_and_wrong_plausible_are_rejected(self):
        script = f'<script async src="{PLAUSIBLE_SRC}"></script>'
        for replacement in ("", script + script, script.replace(PLAUSIBLE_SRC, "https://plausible.io/js/wrong.js")):
            with self.subTest(replacement=replacement):
                self.render()
                self.change_built(script, replacement)
                with self.assertRaises(AssertionError):
                    check(self.root)

    def test_unexpected_resource_surfaces_are_rejected(self):
        for injected in (
            '<script src="https://tracker.example/a.js"></script>',
            '<script src="assets/extra.js"></script>',
            '<script>fetch("https://tracker.example")</script>',
            '<img src="https://tracker.example/pixel.png">',
            '<img src="//tracker.example/pixel.png">',
            '<img src="assets/a.png" srcset="https://tracker.example/a.png 2x">',
            '<link rel="stylesheet" href="https://tracker.example/a.css">',
            '<link rel="preconnect" href="https://tracker.example">',
            '<iframe src="assets/frame.html"></iframe>',
            '<svg><image href="https://tracker.example/a.svg"/></svg>',
            '<p onclick="alert(1)">event</p>',
            '<meta http-equiv="refresh" content="0;url=https://tracker.example">',
        ):
            with self.subTest(injected=injected):
                self.render()
                self.change_built("</head>", injected + "</head>")
                with self.assertRaises(AssertionError):
                    check(self.root)

    def test_external_citations_do_not_count_as_loaded_resources(self):
        self.change_built("</main>", '<a href="https://example.org/paper">Citation</a></main>')
        check(self.root)

    def test_local_images_and_css_dependencies_are_checked(self):
        self.asset("pixel.png", b"fixture image bytes")
        self.asset("site.css", b'body { background: url("pixel.png"); }')
        self.change_built("</main>", '<img src="assets/pixel.png"></main>')
        self.assertIn("assets/pixel.png", check(self.root)["resources"])
        (self.root / "docs/assets/pixel.png").write_bytes(b"changed")
        with self.assertRaisesRegex(AssertionError, "built resource differs"):
            check(self.root)

    def test_css_imports_and_remote_urls_are_rejected(self):
        for css in (b'@import "https://tracker.example/a.css";',
                    b'body { background: url(https://tracker.example/pixel); }',
                    b'@im\\port "https://tracker.example/a.css";',
                    b'body { background: image-set("https://tracker.example/pixel" 1x); }'):
            with self.subTest(css=css):
                self.asset("site.css", css)
                with self.assertRaises(AssertionError):
                    check(self.root)

    def test_stylesheet_extension_does_not_bypass_import_check(self):
        self.asset("style.txt", b'@import "https://tracker.example/a.css";')
        self.change_built('href="assets/site.css"', 'href="assets/style.txt"')
        with self.assertRaisesRegex(AssertionError, "CSS imports"):
            check(self.root)

    def test_h1_must_be_unique_and_approved(self):
        for replacement in ("", "<h1>Wrong title</h1>", f"<h1>{TITLE}</h1><h1>{TITLE}</h1>"):
            with self.subTest(replacement=replacement):
                self.render()
                self.change_built(f"<h1>{TITLE}</h1>", replacement)
                with self.assertRaisesRegex(AssertionError, "H1/title"):
                    check(self.root)

    def test_privacy_footer_and_initializer_are_required(self):
        for old, new in (("no cookies, no personal data", "cookies"),
                         ("https://plausible.io/data-policy", "https://example.org/privacy"),
                         (PLAUSIBLE_INIT, "plausible.init({extra: true})")):
            with self.subTest(old=old):
                self.render()
                self.change_built(old, new)
                with self.assertRaises(AssertionError):
                    check(self.root)

    def test_mathml_namespace_and_annotation_are_required_even_with_new_hash(self):
        original = self.body_path.read_bytes()
        for old, new in (('xmlns="http://www.w3.org/1998/Math/MathML"', ""),
                         ('encoding="application/x-tex"', 'encoding="text/plain"')):
            with self.subTest(old=old):
                self.body_path.write_bytes(original)
                self.change_body(old, new, approve=True)
                with self.assertRaisesRegex(AssertionError, "MathML"):
                    check(self.root)

    def test_sql_requires_native_collapsed_details_and_summary(self):
        original = self.body_path.read_bytes()
        for old, new in (("<details>", "<details open>"),
                         ("<summary>SQL:", "<summary>Query:")):
            with self.subTest(old=old):
                self.body_path.write_bytes(original)
                self.change_body(old, new, approve=True)
                with self.assertRaisesRegex(AssertionError, "SQL"):
                    check(self.root)

    def test_internal_comments_and_revision_markers_are_rejected(self):
        for injected in ("<!-- internal private draft -->", "<p>FIXES</p>", "<p>POST_v2</p>"):
            with self.subTest(injected=injected):
                self.render()
                self.change_built("</head>", injected + "</head>")
                with self.assertRaisesRegex(AssertionError, "internal"):
                    check(self.root)

    def test_html_structure_and_duplicate_attributes_are_checked(self):
        for source in ("<p><em>text</p></em>", '<img src="assets/a" src="https://example.org/a">',
                       "<p>", '<script src="assets/site.js"/>'):
            with self.subTest(source=source):
                with self.assertRaises(AssertionError):
                    Document(source)


if __name__ == "__main__":
    unittest.main()
