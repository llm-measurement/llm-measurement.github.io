# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import sitemap


class SitemapDatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        docs = self.root / 'docs'
        docs.mkdir()
        (docs / 'index.html').write_bytes(b'home')
        (docs / 'routing.html').write_bytes(b'route')
        (docs / 'sitemap.xml').write_text('<urlset xmlns="' + sitemap.NS + '">' +
            '<url><loc>' + sitemap.BASE + '</loc></url>' +
            '<url><loc>' + sitemap.BASE + 'routing.html</loc></url></urlset>')

    def git(self, root, *args):
        self.assertEqual(root, self.root)
        if args == ('rev-parse', '--is-shallow-repository'):
            return b'false\n'
        if args[0] == 'show':
            return (root / args[1].removeprefix('HEAD:')).read_bytes()
        self.assertEqual(args[:4], ('log','-1','--format=%cI','--'))
        return b'2026-10-19T18:30:15-04:00\n' if args[-1] == 'docs/index.html' else b'2026-10-18T01:02:03+02:00\n'

    def test_utc_content_dates_not_build_time(self):
        with patch.object(sitemap, 'git', side_effect=self.git):
            self.assertEqual(sitemap.content_dates(self.root), {
                sitemap.BASE: '2026-10-19T22:30:15Z',
                sitemap.BASE+'routing.html': '2026-10-17T23:02:03Z'})

    def test_prepare_preserves_html_and_generates_dates(self):
        destination = self.root / 'publication'
        with patch.object(sitemap, 'git', side_effect=self.git):
            sitemap.prepare(self.root, destination)
            output = (destination / 'sitemap.xml').read_bytes()
            sitemap.check(self.root, output)
            self.assertEqual(output, sitemap.render(self.root))
            self.assertEqual((destination / 'routing.html').read_bytes(), b'route')
            self.assertNotIn(b'lastmod', (self.root / 'docs/sitemap.xml').read_bytes())
            with self.assertRaises(FileExistsError):
                sitemap.prepare(self.root, destination)

    def test_shallow_history_is_not_silently_dated(self):
        with patch.object(sitemap, 'git', return_value=b'true\n'), self.assertRaisesRegex(ValueError, 'full Git history'):
            sitemap.render(self.root)

    def test_uncommitted_page_is_refused(self):
        def changed(root, *args):
            return b'different' if args[0] == 'show' else self.git(root, *args)
        with patch.object(sitemap, 'git', side_effect=changed), self.assertRaisesRegex(ValueError, 'differs from Git'):
            sitemap.render(self.root)

    def test_bad_or_missing_dates_are_refused(self):
        with patch.object(sitemap, 'git', side_effect=self.git):
            good = sitemap.render(self.root)
            for bad in (good.replace(b'2026-10-19T22:30:15Z', b'2026-10-20T22:30:15Z'),
                        (self.root / 'docs/sitemap.xml').read_bytes(),
                        good.replace(b'<lastmod>', b'<lastmod/><lastmod>')):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    sitemap.check(self.root, bad)

    def test_duplicate_and_external_pages_are_refused(self):
        path = self.root / 'docs/sitemap.xml'
        original = path.read_text()
        with patch.object(sitemap, 'git', side_effect=self.git):
            for text in (original.replace('routing.html',''),
                         original.replace(sitemap.BASE, 'https://example.com/')):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    sitemap.render(self.root)

    def test_existing_dates_are_replaced_once(self):
        path = self.root / 'docs/sitemap.xml'
        path.write_text(path.read_text().replace('</url>', '<lastmod>old</lastmod></url>'))
        with patch.object(sitemap, 'git', side_effect=self.git):
            data = sitemap.render(self.root)
            self.assertNotIn(b'old', data)
            self.assertEqual(len(ET.fromstring(data).findall('.//{*}lastmod')), 2)
            sitemap.check(self.root, data)


if __name__ == '__main__':
    unittest.main()
