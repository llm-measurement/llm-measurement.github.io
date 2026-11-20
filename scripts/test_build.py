# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check shared analytics and root-file preservation across clean builds."""
from html.parser import HTMLParser
import hashlib
import html
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import build


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.current = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        elif tag == "script":
            self.current = {"attrs": dict(attrs), "text": "", "in_head": self.in_head}
            self.scripts.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False
        elif tag == "script":
            self.current = None


class BuildTests(unittest.TestCase):
    def assert_analytics(self, rendered, article=False):
        parsed = Scripts()
        parsed.feed(rendered)
        structured = [script for script in parsed.scripts
                      if script['attrs'].get('type') == 'application/ld+json']
        self.assertEqual(len(structured), int(article))
        if article:
            self.assertEqual(structured[0]['attrs'], {'type': 'application/ld+json'})
            self.assertTrue(structured[0]['in_head'])
            self.assertEqual(json.loads(structured[0]['text'])['@type'], 'BlogPosting')
        executable = [script for script in parsed.scripts if script not in structured]
        self.assertEqual(len(parsed.scripts), 3 + int(article))
        self.assertEqual(len(executable), 3)
        external, bootstrap, interactions = executable
        self.assertTrue(interactions['in_head'])
        self.assertEqual(interactions['attrs'], {'defer': None, 'src': 'assets/site.js'})
        self.assertEqual(interactions['text'], '')
        self.assertTrue(external['in_head'] and bootstrap['in_head'])
        self.assertEqual(external['attrs'], {
            'async': None,
            'src': 'https://plausible.io/js/pa-XxJJVAxJMHffrJ0MqBrpF.js',
        })
        self.assertEqual(external['text'], '')
        self.assertEqual(bootstrap['attrs'], {})
        self.assertEqual(bootstrap['text'].strip(), (
            'window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},'
            'plausible.init=plausible.init||function(i){plausible.o=i||{}};\n'
            '  plausible.init()'
        ))

    def fixture(self, pages, bodies=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'assets/summary-evidence').mkdir(parents=True)
        (root / 'assets/header-mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        (root / 'pages').mkdir()
        for page in pages:
            (root / 'pages' / (page['slug'] + '.html')).write_text((bodies or {}).get(page['slug'], '<p>Body</p>'))
        for name in build.STATIC_ROOT_FILES:
            (root / name).write_text('verification')
        with patch.object(build, 'ROOT', root), patch.object(build, 'PAGES', pages), \
                patch.object(build.summary_evidence, 'claims', return_value={}):
            build.build()
        return root

    def article(self, **extra):
        return dict({'slug': 'prompt-cache-bills', 'title': 'Measured cache bills',
                     'document_title': 'Prompt caching and measured bills',
                     'description': 'A measured comparison.', 'article': True, 'kind': 'study',
                     'navigation': False, 'published': '2026-11-17T00:00:00Z',
                     'modified': '2026-11-17T00:00:00Z'}, **extra)

    def test_default_frame_bytes_are_unchanged(self):
        page = {'slug': 'example', 'title': 'Page', 'description': 'Description',
                'document_title': 'Document', 'published': 'ignored', 'modified': 'ignored'}
        rendered = build.FRAME.substitute(
            document_title='Document', title='Page', description='Description',
            canonical=build.canonical(page), metadata=build.metadata(page), header_mark='MARK',
            nav='NAV', body='BODY', contact='CONTACT', guide_contact='GUIDE', measurement_link='NOTES')
        # Fingerprint of the complete pre-article frame, including all whitespace.
        self.assertEqual(hashlib.sha256(rendered.encode()).hexdigest(),
                         'b5e90350871df4065d4c6981b5896173ab9965fc0782b78f25aa39e6b58a5214')
        self.assert_analytics(rendered)
        self.assertNotIn('twitter:', rendered)
        self.assertNotIn('application/ld+json', rendered)

    def test_legacy_labels_and_explicit_navigation(self):
        self.assertEqual(list(build.NAV_LABELS.values()), [
            'All guides', 'A token spike', 'Tokenmaxxing', 'LiteLLM spend', 'Langfuse costs',
            'Agent spend', 'Row coverage', 'Routing audit', 'Model what-if', 'Session budget',
            'Cache check', 'Per-user metrics', 'Unusual windows', 'Trace check', 'Distinct users',
            'Why summaries', 'Security review',
        ])
        pages = [{'slug': slug} for slug in build.NAV_LABELS]
        expected = ''.join(f'<a href="{slug}.html"' + (' aria-current="page"' if slug == 'routing' else '') +
                           f'>{label}</a>' for slug, label in build.NAV_LABELS.items())
        self.assertEqual(build.navigation({'slug': 'routing'}, pages), expected)
        studies = {'slug': 'studies', 'nav_label': 'Studies'}
        article = self.article()
        nav = build.navigation(article, pages + [studies, article])
        studies_link = '<a href="studies.html" aria-current="page">Studies</a>'
        self.assertTrue(nav.startswith('<a href="index.html">All guides</a>' + studies_link))
        self.assertEqual(nav.replace(studies_link, ''), expected.replace(' aria-current="page"', ''))
        self.assertEqual(build.navigation({'slug': 'routing'}, pages + [studies, article]),
                         expected.replace('<a href="index.html">All guides</a>',
                                          '<a href="index.html">All guides</a><a href="studies.html">Studies</a>'))
        self.assertEqual(nav.count('aria-current="page"'), 1)
        self.assertIn('<a href="studies.html" aria-current="page">Studies</a>', nav)
        self.assertNotIn('prompt-cache-bills.html', nav)
        self.assertIn('>A token spike</a>', nav)
        self.assertEqual(build.navigation({'slug': 'x'}, [{'slug': 'x', 'nav_label': 'A & "B"'}]),
                         '<a href="x.html" aria-current="page">A &amp; &quot;B&quot;</a>')
        with self.assertRaisesRegex(ValueError, 'navigation label'):
            build.navigation({'slug': 'unknown'}, [{'slug': 'unknown'}])

    def test_article_metadata_mathml_analytics_and_study_listing(self):
        home = {'slug': 'index', 'title': 'Home', 'description': 'Home description'}
        landing = {'slug': 'studies', 'title': 'Studies', 'description': 'Measured studies',
                   'kind': 'reference', 'nav_label': 'Studies'}
        article = self.article()
        body = '<section><p>Unchanged body.</p><math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math></section>\n'
        root = self.fixture([home, landing, article], {article['slug']: body})
        rendered = (root / 'docs/prompt-cache-bills.html').read_text()
        self.assertIn('<h1>Measured cache bills</h1>' + body + '</main>', rendered)
        self.assertNotIn('class="guide-contact"', rendered)
        self.assertIn('<a href="summaries.html#measurement-notes">Measurement notes</a>', rendered)
        self.assertIn('<a href="studies.html" aria-current="page">Studies</a>', rendered)
        self.assertIn('<title>Prompt caching and measured bills</title>', rendered)
        for attribute, key, value in (
                ('property', 'og:title', article['document_title']),
                ('property', 'og:description', article['description']),
                ('property', 'og:type', 'article'),
                ('property', 'og:url', build.canonical(article)),
                ('property', 'og:site_name', 'LLM Measurement'),
                ('property', 'article:published_time', article['published']),
                ('property', 'article:modified_time', article['modified']),
                ('name', 'twitter:card', 'summary'),
                ('name', 'twitter:title', article['document_title']),
                ('name', 'twitter:description', article['description']),
                ('name', 'twitter:url', build.canonical(article))):
            self.assertEqual(rendered.count(f'<meta {attribute}="{key}" content="{value}">'), 1)
        parsed = Scripts()
        parsed.feed(rendered)
        data = json.loads(parsed.scripts[0]['text'])
        self.assertEqual(data, {
            '@context': 'https://schema.org', '@type': 'BlogPosting',
            'headline': article['title'], 'description': article['description'],
            'datePublished': article['published'], 'dateModified': article['modified'],
            'author': {'@type': 'Person', 'name': 'Vijay'},
            'publisher': {'@type': 'Organization', 'name': 'LLM Measurement'},
            'mainEntityOfPage': {'@type': 'WebPage', '@id': build.canonical(article)},
        })
        for unwanted in ('og:image', 'twitter:image', '"image"'):
            self.assertNotIn(unwanted, rendered)
        self.assertEqual(rendered.count('<h1>'), 1)
        self.assert_analytics(rendered, article=True)
        self.assert_analytics((root / 'docs/studies.html').read_text())
        text_index = (root / 'docs/llms.txt').read_text()
        guides, studies = text_index.split('\n## Studies\n\n')
        self.assertNotIn('prompt-cache-bills', guides)
        self.assertNotIn('studies.html', guides)
        self.assertIn(f'- [{article["title"]}]({build.canonical(article)}): {article["description"]}\n', studies)
        self.assertIn(f'- [Studies]({build.BASE}studies.html): Measured studies\n', studies)

    def test_article_metadata_escaping_and_jsonld_safety(self):
        hostile = '\"<&>\' </script><script>alert(1)</script>\u2028\u2029'
        page = self.article(title=hostile, document_title='SEO ' + hostile, description=hostile)
        rendered = build.article_head(page)
        parsed = Scripts()
        parsed.feed(rendered)
        self.assertEqual(len(parsed.scripts), 1)
        self.assertEqual(json.loads(parsed.scripts[0]['text'])['headline'], hostile)
        self.assertEqual(json.loads(parsed.scripts[0]['text'])['description'], hostile)
        self.assertIn('content="' + html.escape('SEO ' + hostile, quote=True) + '"', rendered)
        self.assertNotIn('</script><script>', rendered)
        self.assertIn('\\u003c/script\\u003e', rendered)
        self.assertIn('\\u0026', rendered)
        self.assertIn('\\u2028\\u2029', rendered)

    def test_article_dates_refuse_missing_malformed_or_reversed_values(self):
        for field in ('published', 'modified'):
            for value in (None, '', 123, True, '2026-11-17', '2026-11-17T00:00:00',
                          '2026-02-30T00:00:00Z', '2026-11-17 00:00:00Z',
                          '2026-11-17T00:00:00Z\" onload=\"bad', '2026-11-17T24:00:00Z'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build.article_head(self.article(**{field: value}))
            page = self.article()
            del page[field]
            with self.assertRaises(ValueError):
                build.article_head(page)
        with self.assertRaisesRegex(ValueError, 'precedes'):
            build.article_head(self.article(modified='2026-11-16T00:00:00Z'))
        rendered = build.article_head(self.article(published='2026-11-17T05:30:00+05:30',
                                                 modified='2026-11-17T00:00:00.250Z'))
        self.assertIn('2026-11-17T05:30:00+05:30', rendered)

    def test_no_studies_keeps_legacy_text_index(self):
        pages = [{'slug': 'index', 'title': 'Home', 'description': 'Home'},
                 {'slug': 'routing', 'title': 'Routing', 'description': 'Route'}]
        root = self.fixture(pages)
        text_index = (root / 'docs/llms.txt').read_text()
        self.assertTrue(text_index.startswith('# LLM Measurement\n\n> Local open-source tools for LLM usage investigations and measurement.\n\n## Guides\n\n'
                                             '- [Routing](https://llm-measurement.github.io/routing.html): Route\n\n## Released tools'))
        self.assertNotIn('## Studies', text_index)

    def test_litellm_discovery_metadata_keeps_short_navigation_and_page_bodies(self):
        expected = (
            ("litellm-spend", "LiteLLM spend",
             "LiteLLM spend tracking: see who drove a spend increase",
             "Spend tracking already on? A read-only command on your LiteLLM spend logs shows what changed, "
             "which model, team or key drove it, and what the logs missed."),
            ("row-coverage", "Row coverage",
             "LiteLLM spend logs missing requests? Compare with daily counts",
             "Compare LiteLLM spend-log rows with daily request counts to find requests that never reached "
             "the spend logs, with a real response-ID collision as the example."),
            ("routing", "Routing audit",
             "Which model actually served your LiteLLM route?",
             "Audit LiteLLM Auto Routing and fallbacks: compare model shares, missing attribution "
             "and classifier overhead using recorded spend only."),
        )
        pages = {page["slug"]: page for page in build.PAGES}
        index = (build.ROOT / "docs/llms.txt").read_text()
        for slug, label, title, description in expected:
            with self.subTest(page=slug):
                self.assertEqual(pages[slug]["title"], title)
                self.assertEqual(pages[slug]["document_title"], title)
                self.assertEqual(pages[slug]["description"], description)
                rendered = (build.ROOT / "docs" / (slug + ".html")).read_text()
                escaped_title, escaped_description = html.escape(title), html.escape(description)
                for element in (f"<title>{escaped_title}</title>", f"<h1>{escaped_title}</h1>",
                                f'<meta property="og:title" content="{escaped_title}">',
                                f'<meta property="og:description" content="{escaped_description}">',
                                f'<meta name="description" content="{escaped_description}">'):
                    self.assertEqual(rendered.count(element), 1)
                self.assertEqual(rendered.count(f'href="{slug}.html" aria-current="page">{label}</a>'), 2)
                body = (build.ROOT / "pages" / (slug + ".html")).read_text()
                self.assertIn(f"<h1>{escaped_title}</h1>{body}<p class=\"guide-contact\">", rendered)
                self.assertIn(f"- [{title}]({build.BASE}{slug}.html): {description}\n", index)

    def test_every_page_has_the_supplied_analytics_once_in_head(self):
        for page in build.PAGES:
            with self.subTest(page=page["slug"]):
                self.assert_analytics((build.ROOT / 'docs' / (page['slug'] + '.html')).read_text(),
                                      article=page.get('article') is True)

    def test_haiku_study_analytics_and_discovery(self):
        slug = 'haiku-sonnet-100k-cliff'
        page, = [page for page in build.PAGES if page['slug'] == slug]
        rendered = (build.ROOT / 'docs' / (slug + '.html')).read_text()
        self.assert_analytics(rendered, article=True)
        self.assertIn('Privacy-friendly analytics by <a href="https://plausible.io/data-policy">Plausible</a>', rendered)
        self.assertEqual(rendered.count('<h1>'), 1)
        self.assertIn('<h1>' + html.escape(page['title']) + '</h1>', rendered)
        self.assertIn('<h3 id="what-the-numbers-mean">What the numbers mean</h3>', rendered)
        self.assertIn(build.canonical(page), (build.ROOT / 'docs/sitemap.xml').read_text())
        self.assertIn(build.canonical(page), (build.ROOT / 'docs/llms.txt').read_text())
        for name in ('index', 'studies'):
            listing = (build.ROOT / 'docs' / (name + '.html')).read_text()
            self.assertLess(listing.index('href="prompt-cache-bills.html"'),
                            listing.index('href="' + slug + '.html"'))

    def test_verification_survives_rebuild_and_stale_asset_cleanup(self):
        source = build.ROOT
        name = "googled831a5845f87080c.html"
        expected = b"google-site-verification: googled831a5845f87080c.html"
        self.assertEqual((source / name).read_bytes(), expected)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("assets", "pages"):
                shutil.copytree(source / folder, root / folder)
            for static_name in build.STATIC_ROOT_FILES:
                shutil.copyfile(source / static_name, root / static_name)
            with patch.object(build, "ROOT", root):
                build.build()
                verification = root / "docs" / name
                self.assertEqual(verification.read_bytes(), expected)
                stale_asset = root / "docs/assets/stale-test.txt"
                stale_asset.write_text("remove this generated test asset")
                build.build()
                self.assertFalse(stale_asset.exists())
                self.assertEqual(verification.read_bytes(), expected)
                shutil.rmtree(root / "docs")
                build.build()
                self.assertEqual(verification.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
