# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Keep the light palette readable on both page and code surfaces."""
from pathlib import Path
import re
import unittest


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in channels]
    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(foreground, background):
    bright, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.css = (Path(__file__).resolve().parents[1] / 'assets/site.css').read_text()
        self.tokens = dict(re.findall(r'--([a-z-]+):\s*(#[0-9a-f]{6})\s*;', self.css))

    def test_exact_light_palette(self):
        self.assertEqual(self.tokens, {
            'paper': '#fbfcfa', 'ink': '#17212b', 'muted': '#5b6875', 'line': '#d7dedf',
            'link': '#0e5144', 'link-hover': '#176b5b', 'accent': '#176b5b',
            'surface': '#eef4f0', 'selected': '#eef4f0', 'output': '#eef4f0',
        })
        self.assertIn('color-scheme: light;', self.css)
        self.assertNotIn('prefers-color-scheme', self.css)
        hover = 'a:hover, nav a:hover { color: var(--link-hover); }'
        self.assertIn(hover, self.css)
        self.assertGreater(self.css.index(hover), self.css.index('.path-index a {'))
        self.assertGreater(self.css.index(hover), self.css.index('nav a[aria-current] {'))
        self.assertIn('.own-data pre { background: var(--surface); }', self.css)

    def test_every_text_token_on_every_surface_meets_aa(self):
        for text in ('ink', 'muted', 'link', 'link-hover', 'accent'):
            for surface in ('paper', 'surface', 'selected', 'output'):
                with self.subTest(text=text, background=surface):
                    self.assertGreaterEqual(contrast(self.tokens[text], self.tokens[surface]), 4.5)


if __name__ == '__main__':
    unittest.main()
