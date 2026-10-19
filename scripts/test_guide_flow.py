# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
import unittest

from guide_flow import check_guide_flow


GOOD = '''<p class="lead">Compare your recorded usage.</p>
<nav class="path-index" aria-label="Starting point"><ul>
<li><a href="#run">Your data</a></li><li><a href="#sample">Sample</a></li></ul></nav>
<aside id="run" class="own-data"><h2>Run it on your data</h2><p>Install first.</p>
<pre data-own="install"><code>install</code></pre></aside>
<details class="security-note"><summary>Security</summary><p>Details.</p></details>
<section id="sample"><h2>Sample</h2><p>Run this.</p>
<pre data-run="example"><code>run</code></pre>
<pre data-output="example"><code>output</code></pre></section>'''


class GuideFlowTests(unittest.TestCase):
    def test_valid(self):
        check_guide_flow(GOOD, ["#run", "#sample"])

    def test_reject_regressions(self):
        changes = [
            ('href="#run"', 'href="#missing"'),
            ('id="run"', 'id="sample"'),
            ('data-own="install"', ''),
            ('data-own="install"', 'data-output="example"'),
            ('<nav class=', '<p>Extra introduction.</p><nav class='),
            ('<details class=', '<details open class='),
            ('class="security-note"', 'class="other-note"'),
            ('</section>', '</section><section><h2>Late section</h2></section>'),
            ('<pre data-run="example"><code>run</code></pre>', ''),
        ]
        for old, new in changes:
            with self.subTest(old=old), self.assertRaises(AssertionError):
                check_guide_flow(GOOD.replace(old, new), ["#run", "#sample"])

    def test_expected_paths(self):
        with self.assertRaisesRegex(AssertionError, "required input paths"):
            check_guide_flow(GOOD, ["#run", "#access", "#file", "#sample"])

    def test_shared_access_path(self):
        source = GOOD.replace('<li><a href="#sample">',
                              '<li><a href="litellm-spend.html#access">Access</a></li><li><a href="#sample">')
        check_guide_flow(source, ["#run", "litellm-spend.html#access", "#sample"])
        with self.assertRaisesRegex(AssertionError, "missing path target"):
            check_guide_flow(source.replace("litellm-spend.html#access", "unknown.html#access"))

    def test_output_before_sample_command_rejected(self):
        source = GOOD.replace('<pre data-run="example"><code>run</code></pre>', '')
        source = source.replace('</section>', '<pre data-run="example"><code>run</code></pre></section>')
        with self.assertRaisesRegex(AssertionError, "run sample before output"):
            check_guide_flow(source)


if __name__ == "__main__":
    unittest.main()
