# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Contact links and published block preservation, without network access."""
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.parse import urlsplit

import build


class PublishedBlocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.raw_blocks = []
        self.current = None
        self.links = []
        self.assets = []

    def feed(self, source):
        self.raw = source
        self.line_starts = [0]
        for line in source.splitlines(keepends=True):
            self.line_starts.append(self.line_starts[-1] + len(line))
        super().feed(source)

    def source_offset(self):
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'pre':
            self.current = {'attrs': attrs, 'text': ''}
            self.raw_start = self.source_offset()
        if tag == 'a':
            self.links.append(attrs)
        if tag == 'script' and attrs.get('src', '').startswith('assets/'):
            self.assets.append(attrs['src'])

    def handle_endtag(self, tag):
        if tag == 'pre' and self.current is not None:
            self.blocks.append(self.current)
            self.raw_blocks.append(self.raw[self.raw_start:self.raw.index('>', self.source_offset()) + 1])
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data


class InteractionPagesTests(unittest.TestCase):
    def test_all_pages_and_guide_endings_have_the_approved_contact_destinations(self):
        expected = {
            'mailto:evijay+fleetdiff@gmail.com',
            'https://github.com/llm-measurement/fleetdiff/discussions/categories/q-a',
            'https://github.com/llm-measurement/fleetdiff/discussions/categories/show-and-tell',
            'https://github.com/llm-measurement/fleetdiff/security/advisories/new',
        }
        for page in build.PAGES:
            with self.subTest(page=page['slug']):
                raw = (build.ROOT / 'docs' / (page['slug'] + '.html')).read_text()
                footer = raw.split('<footer>', 1)[1].split('</footer>', 1)[0]
                parsed = PublishedBlocks()
                parsed.feed(footer)
                self.assertTrue(expected <= {a.get('href') for a in parsed.links})
                for link in expected:
                    self.assertEqual(footer.count('href="' + link + '"'), 1)
                if page['slug'] != 'index' and not page.get('kind'):
                    self.assertIn('<p class="guide-contact">' + build.CONTACT + '</p></main>', raw)
                else:
                    self.assertNotIn('<p class="guide-contact">', raw)
                self.assertIn('Tell us what it found', footer)
                self.assertIn('Security issues (private)', footer)
        self.assertEqual(sum('<p class="guide-contact">' in
                         (build.ROOT / 'docs' / (p['slug'] + '.html')).read_text()
                         for p in build.PAGES), 13)

    def test_all_displayed_blocks_match_the_published_baseline_and_sources(self):
        baseline = json.loads((Path(__file__).parent / 'published_blocks.json').read_text())
        self.assertEqual(set(baseline), {page['slug'] for page in build.PAGES})
        for page in build.PAGES:
            with self.subTest(page=page['slug']):
                generated = PublishedBlocks()
                generated.feed((build.ROOT / 'docs' / (page['slug'] + '.html')).read_bytes().decode())
                source = PublishedBlocks()
                source.feed(build.summary_evidence.render(build.ROOT) if page.get('kind') == 'evidence'
                            else (build.ROOT / 'pages' / (page['slug'] + '.html')).read_bytes().decode())
                self.assertEqual(generated.blocks, source.blocks)
                self.assertEqual(generated.raw_blocks, source.raw_blocks)
                digest = hashlib.sha256(json.dumps(generated.raw_blocks, ensure_ascii=False).encode()).hexdigest()
                self.assertEqual(digest, baseline[page['slug']])

    def test_contact_targets_and_interaction_assets_resolve_without_query_identifiers(self):
        parsed = PublishedBlocks()
        parsed.feed(build.CONTACT)
        for link in parsed.links:
            url = urlsplit(link['href'])
            self.assertEqual(url.query, '')
            self.assertEqual(url.fragment, '')
            if url.scheme == 'https':
                self.assertEqual(url.netloc, 'github.com')
                self.assertTrue(url.path.startswith('/llm-measurement/fleetdiff/'))
            else:
                self.assertEqual(url.scheme, 'mailto')
                self.assertEqual(url.path, 'evijay+fleetdiff@gmail.com')
        for page in build.PAGES:
            parsed = PublishedBlocks()
            parsed.feed((build.ROOT / 'docs' / (page['slug'] + '.html')).read_text())
            self.assertEqual(parsed.assets, ['assets/site.js'])
            for asset in parsed.assets:
                self.assertEqual((build.ROOT / 'docs' / asset).read_bytes(), (build.ROOT / asset).read_bytes())

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for the dependency-free interaction tests')
    def test_clipboard_and_analytics_contract(self):
        subprocess.run(['node', '--test', 'scripts/site_interactions.test.cjs'], cwd=build.ROOT, check=True)


if __name__ == '__main__':
    unittest.main()
