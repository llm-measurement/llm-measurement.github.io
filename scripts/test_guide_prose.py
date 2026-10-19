# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
import unittest

from guide_prose import INSTALL_PREAMBLE, check, inspect


class GuideProseTests(unittest.TestCase):
    def test_visible_count_includes_commands_and_summary_but_not_folded_body_or_sample(self):
        source = '<p>Use your data.</p><pre><code>tool --input file</code></pre>' \
                 '<details><summary>More help</summary><p>hidden words</p>' \
                 '<details><summary>nested summary</summary>nested body</details></details>' \
                 '<section id="sample"><p>sample words</p></section>'
        result = check(source, "A title", 10)
        self.assertEqual(result["visible_words"], 10)
        self.assertEqual(result["prose_words"], 7)
        with self.assertRaisesRegex(AssertionError, "word budget"):
            check(source, "A title", 9)

    def test_open_details_count_and_inline_words_are_not_split(self):
        result = inspect('<p>Read <code>--daily</code> now.</p>'
                         '<details open><summary>Help</summary><p>Read this.</p></details>', "Title")
        self.assertEqual(result["visible_words"], 7)

    def test_removed_phrases_are_rejected_in_folded_and_sample_text_too(self):
        phrases = ["sparse logs", "do not establish", "equal-length", "equal duration",
                   "nonoverlapping", "non-overlapping", "approved", "--keep-export NEWDIR",
                   "symlink", "leave <code>DATABASE_URL</code> unset", "private snapshot",
                   "not a substitute", "remains an alternative", "need not be signed in",
                   "start without an existing <code>bin</code> folder"]
        for phrase in phrases:
            for wrapper in ('<details><summary>Help</summary><p>{}</p></details>',
                            '<section id="sample"><p>{}</p></section>'):
                with self.subTest(phrase=phrase, wrapper=wrapper), self.assertRaisesRegex(AssertionError, "removed guide wording"):
                    check(wrapper.format(phrase), "Title", 250)

    def test_installer_preamble_is_the_reviewed_line(self):
        check('<p>' + INSTALL_PREAMBLE + '</p><pre>scripts/install.sh</pre>', "Title", 250)
        with self.assertRaisesRegex(AssertionError, "reviewed install preamble"):
            check('<p>Requires curl, gh, shasum and tar.</p>', "Title", 250)
        with self.assertRaisesRegex(AssertionError, "missing install preamble"):
            check('<pre>scripts/install.sh</pre>', "Title", 250)
        with self.assertRaisesRegex(AssertionError, "footer"):
            check('<a href="security.html#verify-fleetdiff">Manual verification</a>', "Title", 250)


if __name__ == "__main__":
    unittest.main()
