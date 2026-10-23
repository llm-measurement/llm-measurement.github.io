# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Download-count snapshots do not stand in for deliberate request evidence."""
import copy
import unittest

from download_log import NoRedirect, snapshot


class DownloadLogTests(unittest.TestCase):
    def release(self, identifier=1):
        return {'id': identifier, 'draft': False, 'tag_name': 'v0.12.1',
            'published_at': '2026-10-22T23:13:58Z', 'body': 'not copied',
            'assets': [{'id': identifier, 'name': 'SHA256SUMS', 'size': 579,
                'download_count': 42, 'digest': 'sha256:' + 'a' * 64,
                'url': 'not copied', 'uploader': {'not': 'copied'}}]}

    def test_metadata_only_and_truthful_attribution(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return [self.release()]
        record = snapshot('llm-measurement/fleetdiff', fetch)
        self.assertEqual(calls, ['https://api.github.com/repos/llm-measurement/fleetdiff/releases?per_page=100&page=1'])
        self.assertEqual(record['assets'][0]['download_count'], 42)
        self.assertEqual(record['deliberate_download_requests_by_this_run'], [])
        self.assertIn('Not unique users', record['count_semantics'])
        self.assertNotIn('body', record)
        self.assertNotIn('uploader', record['assets'][0])
        self.assertNotIn('url', record['assets'][0])

    def test_unknown_repository_is_rejected_before_request(self):
        with self.assertRaises(ValueError):
            snapshot('example/private', lambda _: self.fail('must not request'))

    def test_missing_counts_do_not_become_zero(self):
        release = self.release()
        del release['assets'][0]['download_count']
        with self.assertRaises(KeyError):
            snapshot('llm-measurement/fleetdiff', lambda _: [release])

    def test_invalid_counts_and_drafts_fail(self):
        for value in [-1, True, '42', None]:
            release = self.release()
            release['assets'][0]['download_count'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                snapshot('llm-measurement/fleetdiff', lambda _: [release])
        release = self.release()
        release['draft'] = True
        with self.assertRaises(ValueError):
            snapshot('llm-measurement/fleetdiff', lambda _: [release])

    def test_pagination_and_duplicate_asset_fail_closed(self):
        first = [self.release(n) for n in range(100)]
        calls = []
        def fetch(url):
            calls.append(url)
            return first if len(calls) == 1 else [self.release(100)]
        self.assertEqual(len(snapshot('llm-measurement/fleetdiff', fetch)['assets']), 101)
        self.assertEqual(len(calls), 2)
        duplicate = copy.deepcopy(first)
        duplicate[1]['assets'][0]['id'] = 0
        with self.assertRaises(ValueError):
            snapshot('llm-measurement/fleetdiff', lambda _: duplicate)

    def test_api_errors_do_not_produce_partial_success(self):
        def failed(_):
            raise OSError('metadata unavailable')
        with self.assertRaises(OSError):
            snapshot('llm-measurement/fleetdiff', failed)
        with self.assertRaises(ValueError):
            snapshot('llm-measurement/fleetdiff', lambda _: {'message': 'error'})

    def test_metadata_redirect_cannot_become_an_asset_request(self):
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://example.org/archive.zip')


if __name__ == '__main__':
    unittest.main()
