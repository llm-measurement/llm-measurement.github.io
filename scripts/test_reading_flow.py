# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Prevent empty guide sections and detached introductions."""
import unittest

from check import check_reading_flow


class ReadingFlowTests(unittest.TestCase):
    def test_consecutive_headings(self):
        with self.assertRaisesRegex(AssertionError, "heading followed"):
            check_reading_flow('<h2>Reading</h2>\n<!-- moved -->\n<section><h3>Next</h3></section>')

    def test_colon_needs_example_or_list(self):
        for tail in ('', '<h2>Next</h2>', '<p>Other text.</p>'):
            with self.subTest(tail=tail), self.assertRaisesRegex(AssertionError, "colon introduction"):
                check_reading_flow('<p>See <em>these</em> results:</p>' + tail)

    def test_colon_before_code_or_list(self):
        for tail in ('<pre><code>result</code></pre>', '<ul><li>result</li></ul>', '<ol><li>result</li></ol>'):
            with self.subTest(tail=tail):
                check_reading_flow('<h2>Results</h2><p>See <a href="#x">this</a>:</p>' + tail)

    def test_inline_tags_and_escaped_code(self):
        check_reading_flow('<h2>Results</h2><p>Run <code>inspect</code>.</p>'
                           '<h3>Output</h3><pre>&lt;h2&gt;not a heading&lt;/h2&gt;</pre>')

    def test_studies_allow_colons_before_tables_or_display_equations_only(self):
        for example in ('<table><tr><td>result</td></tr></table>',
                        '<div class="equation"><math><mn>1</mn></math></div>'):
            with self.subTest(example=example):
                source = '<p>Compare:</p>' + example
                check_reading_flow(source, study=True)
                with self.assertRaisesRegex(AssertionError, "colon introduction"):
                    check_reading_flow(source)
        with self.assertRaisesRegex(AssertionError, "colon introduction"):
            check_reading_flow('<p>Compare:</p><h2>Not an example</h2>', study=True)

    def test_inline_math_does_not_hide_a_study_colon(self):
        with self.assertRaisesRegex(AssertionError, "colon introduction"):
            check_reading_flow('<p>For <math><mi>x</mi></math>:</p><p>No example.</p>', study=True)


if __name__ == "__main__":
    unittest.main()
