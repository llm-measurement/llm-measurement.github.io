# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import sitemap
import build


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


class ArticlePublicationDatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'docs').mkdir()
        self.article = {'slug': 'prompt-cache-bills', 'title': 'Measured bills',
                        'document_title': 'Prompt cache bills', 'description': 'A study.',
                        'article': True, 'published': '2026-11-17T00:00:00Z',
                        'modified': '2026-11-17T00:00:00Z'}
        self.url = build.canonical(self.article)
        self.path = 'docs/prompt-cache-bills.html'
        self.preview = ('<!doctype html><head>' + build.article_head(self.article) +
                        '</head><body><h1>Measured bills</h1><math><mi>x</mi></math></body>').encode()
        self.run_git('init', '-b', 'main')
        (self.root / 'docs/index.html').write_bytes(b'home')
        (self.root / 'docs/sitemap.xml').write_text('<urlset xmlns="' + sitemap.NS + '">' +
            '<url><loc>' + sitemap.BASE + '</loc></url></urlset>')
        (self.root / 'pages.json').write_text('[]')
        self.commit('2026-11-16T01:00:00Z')
        self.run_git('checkout', '-b', 'article')
        (self.root / 'pages.json').write_text(json.dumps([self.article]))
        (self.root / self.path).write_bytes(self.preview)
        index = self.root / 'docs/sitemap.xml'
        index.write_text(index.read_text().replace('</urlset>', '<url><loc>' + self.url + '</loc></url></urlset>'))
        self.commit('2026-11-17T02:00:00Z')
        self.run_git('checkout', 'main')
        (self.root / 'unrelated.txt').write_text('unrelated mainline work')
        self.commit('2026-11-18T01:00:00Z')
        self.run_git('merge', '--no-ff', 'article', '-m', 'Publish article', date='2026-11-19T05:30:00+05:30')

    def run_git(self, *args, date='2026-11-17T00:00:00Z'):
        if args and args[0] in {'commit', 'merge'}:
            self.assertEqual(self.run_git('config', 'user.name').strip(), b'Vijay')
        env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        return subprocess.check_output(['git', '-c', 'user.name=Vijay', '-c', 'user.email=test@example.invalid',
                                        '-C', str(self.root), *args], env=env, stderr=subprocess.PIPE)

    def commit(self, date):
        self.run_git('add', '.')
        self.run_git('commit', '-m', 'Fixture content', date=date)

    def test_main_merge_not_branch_authoring_sets_publication_dates(self):
        dates = sitemap.content_dates(self.root)
        self.assertEqual(dates[self.url], '2026-11-19T00:00:00Z')
        staged = sitemap.staged_articles(self.root)[self.path]
        expected = self.preview.replace(build.article_head(self.article).encode(), build.article_head(
            self.article, published='2026-11-19T00:00:00Z', modified='2026-11-19T00:00:00Z').encode())
        self.assertEqual(staged, expected)
        self.assertEqual((self.root / self.path).read_bytes(), self.preview)

    def test_later_content_merge_advances_modified_not_published(self):
        self.run_git('checkout', '-b', 'edit')
        edited = self.preview.replace(b'<mi>x</mi>', b'<mi>y</mi>')
        (self.root / self.path).write_bytes(edited)
        self.commit('2026-11-20T02:00:00Z')
        self.run_git('checkout', 'main')
        self.run_git('merge', '--no-ff', 'edit', '-m', 'Update article', date='2026-11-22T03:04:05Z')
        self.assertEqual(sitemap.content_dates(self.root)[self.url], '2026-11-22T03:04:05Z')
        before = {path: (self.root / path).read_bytes() for path in
                  (self.path, 'docs/index.html', 'pages.json', 'docs/sitemap.xml')}
        for name in ('publication-one', 'publication-two'):
            destination = self.root / name
            sitemap.prepare(self.root, destination)
            staged = (destination / 'prompt-cache-bills.html').read_bytes()
            self.assertIn(build.article_head(self.article, published='2026-11-19T00:00:00Z',
                                            modified='2026-11-22T03:04:05Z').encode(), staged)
            self.assertIn(b'<math><mi>y</mi></math>', staged)
            self.assertEqual((destination / 'index.html').read_bytes(), b'home')
            sitemap.check(self.root, (destination / 'sitemap.xml').read_bytes())
        self.assertEqual((self.root / 'publication-one/prompt-cache-bills.html').read_bytes(),
                         (self.root / 'publication-two/prompt-cache-bills.html').read_bytes())
        self.assertEqual(before, {path: (self.root / path).read_bytes() for path in before})

    def test_unrelated_main_commit_does_not_advance_article_dates(self):
        expected = sitemap.staged_articles(self.root)
        (self.root / 'unrelated.txt').write_text('later unrelated work')
        self.commit('2026-11-25T00:00:00Z')
        self.assertEqual(sitemap.staged_articles(self.root), expected)

    def test_uncommitted_article_is_refused(self):
        (self.root / self.path).write_bytes(self.preview + b'changed')
        with self.assertRaisesRegex(ValueError, 'differs from Git'):
            sitemap.staged_articles(self.root)

    def test_shallow_article_history_is_refused(self):
        with patch.object(sitemap, 'git', return_value=b'true\n'), self.assertRaisesRegex(ValueError, 'full Git history'):
            sitemap.staged_articles(self.root)

    def test_missing_first_parent_introduction_is_refused(self):
        original = sitemap.git

        def missing(root, *args):
            return b'' if '--reverse' in args else original(root, *args)

        with patch.object(sitemap, 'git', side_effect=missing), self.assertRaisesRegex(ValueError, 'introduction'):
            sitemap.staged_articles(self.root)

    def test_staging_requires_exactly_one_preview_head(self):
        for data in (self.preview.replace(b'og:site_name', b'wrong:site_name'), self.preview + build.article_head(self.article).encode()):
            (self.root / self.path).write_bytes(data)
            self.commit('2026-11-20T00:00:00Z')
            with self.assertRaisesRegex(ValueError, 'configured preview'):
                sitemap.staged_articles(self.root)


if __name__ == '__main__':
    unittest.main()
