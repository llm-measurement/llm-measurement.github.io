# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import indexnow


def sitemap(*urls):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            ''.join(f'<url><loc>{url}</loc></url>' for url in urls) + '</urlset>').encode()


class IndexNowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'docs').mkdir()
        (self.root / 'docs/index.html').write_bytes(b'home')
        (self.root / 'docs/routing.html').write_bytes(b'route')
        (self.root / 'docs/sitemap.xml').write_bytes(sitemap(indexnow.BASE, indexnow.BASE + 'routing.html'))
        (self.root / 'docs' / indexnow.KEY_FILE).write_text(indexnow.KEY_FILE[:-4] + '\n')
        self.patcher = patch.object(indexnow, 'ROOT', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_first_deployment_registers_current_pages(self):
        with patch.object(indexnow, 'previous_bytes', return_value=None):
            self.assertEqual(indexnow.changes('HEAD^'), {indexnow.BASE: b'home', indexnow.BASE + 'routing.html': b'route'})

    def test_unchanged_pages_are_not_submitted(self):
        def previous(_, path):
            return (self.root / path).read_bytes()
        with patch.object(indexnow, 'previous_bytes', side_effect=previous):
            self.assertEqual(indexnow.changes('HEAD^'), {})

    def test_added_changed_and_deleted_pages(self):
        old = {'docs/' + indexnow.KEY_FILE: b'key',
               'docs/sitemap.xml': sitemap(indexnow.BASE, indexnow.BASE + 'removed.html'),
               'docs/index.html': b'old home'}
        with patch.object(indexnow, 'previous_bytes', side_effect=lambda _, path: old.get(path)):
            self.assertEqual(indexnow.changes('HEAD^'), {indexnow.BASE: b'home',
                indexnow.BASE + 'routing.html': b'route', indexnow.BASE + 'removed.html': None})

    def test_bad_sitemap_refused(self):
        for urls in [[], ['https://elsewhere.example/'], [indexnow.BASE + 'x.html?q=1'],
                     [indexnow.BASE + 'x.html#x'], [indexnow.BASE + 'a/x.html'],
                     [indexnow.BASE, indexnow.BASE]]:
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                indexnow.pages(sitemap(*urls))

    def test_missing_previous_sitemap_refused(self):
        with patch.object(indexnow, 'previous_bytes', side_effect=[b'key', None]):
            with self.assertRaises(ValueError):
                indexnow.changes('HEAD^')

    def test_wait_verifies_exact_key_and_page_bytes(self):
        with patch.object(indexnow, 'fetch', side_effect=lambda url: (self.root / 'docs' /
                (url.removeprefix(indexnow.BASE) or 'index.html')).read_bytes()) as fetch:
            indexnow.wait_live({indexnow.BASE: b'home'}, 0)
            self.assertEqual(fetch.call_count, 2)

    def test_stale_deployment_never_submits(self):
        with patch.object(indexnow, 'fetch', return_value=b'stale'):
            with self.assertRaises(RuntimeError):
                indexnow.wait_live({indexnow.BASE: b'home'}, 0)

    def test_deleted_page_requires_404_or_410(self):
        key = (self.root / 'docs' / indexnow.KEY_FILE).read_bytes()
        for status in (404, 410, 500):
            with self.subTest(status=status), patch.object(indexnow, 'fetch', side_effect=[key,
                    HTTPError(indexnow.BASE + 'removed.html', status, 'error', {}, None)]):
                if status == 500:
                    with self.assertRaises(RuntimeError):
                        indexnow.wait_live({indexnow.BASE + 'removed.html': None}, 0)
                else:
                    indexnow.wait_live({indexnow.BASE + 'removed.html': None}, 0)

    def test_submission_payload_and_success_codes(self):
        for status in (200, 202, 204):
            response = MagicMock()
            response.__enter__.return_value.status = status
            with patch.object(indexnow, 'urlopen', return_value=response) as send:
                with contextlib.redirect_stdout(io.StringIO()):
                    if status == 204:
                        with self.assertRaises(RuntimeError):
                            indexnow.submit({indexnow.BASE: b'home'})
                    else:
                        indexnow.submit({indexnow.BASE: b'home'})
                request = send.call_args.args[0]
                self.assertEqual(request.full_url, 'https://api.indexnow.org/indexnow')
                self.assertEqual(request.method, 'POST')
                self.assertEqual(json.loads(request.data), {'host': 'llm-measurement.github.io',
                    'key': indexnow.KEY_FILE[:-4], 'keyLocation': indexnow.BASE + indexnow.KEY_FILE,
                    'urlList': [indexnow.BASE]})

    def test_key_mismatch_refused_before_network(self):
        (self.root / 'docs' / indexnow.KEY_FILE).write_text('wrong')
        with patch.object(indexnow, 'urlopen') as send, self.assertRaises(ValueError):
            indexnow.submit({indexnow.BASE: b'home'})
        send.assert_not_called()

    def test_dry_run_and_empty_changes_never_send(self):
        for arguments, changed in [(['indexnow.py'], {indexnow.BASE: b'home'}),
                                   (['indexnow.py', '--submit'], {})]:
            with patch('sys.argv', arguments), patch.object(indexnow.subprocess, 'run'), \
                    patch.object(indexnow, 'changes', return_value=changed), \
                    patch.object(indexnow, 'wait_live') as wait, \
                    patch.object(indexnow, 'submit') as send, contextlib.redirect_stdout(io.StringIO()):
                indexnow.main()
                wait.assert_not_called()
                send.assert_not_called()

    def test_workflow_push_only_after_required_site_jobs(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/docs.yml').read_text()
        job = workflow.split('  indexnow:\n', 1)[1]
        self.assertIn("if: github.event_name == 'push' && github.ref == 'refs/heads/main'", job)
        self.assertIn('needs: [deploy]', job)
        deployment = workflow.split('  deploy:\n', 1)[1].split('  indexnow:\n', 1)[0]
        self.assertIn('needs: [build, examples, own-data]', deployment)
        self.assertIn('fetch-depth: 0', deployment)
        self.assertIn('scripts/sitemap.py --check', deployment)
        self.assertIn('fetch-depth: 2', job)
        self.assertIn('persist-credentials: false', job)
        self.assertIn('python3 scripts/indexnow.py --submit', job)


if __name__ == '__main__':
    unittest.main()
