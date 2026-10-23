# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Offline exact-pin, fail-closed consumer and truthful download-log checks."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import download_log
import release_cache as cache


class ConsumerTests(unittest.TestCase):
    def pin(self):
        return json.loads(cache.PIN.read_text())

    def now(self):
        return datetime(2026, 10, 22, tzinfo=timezone.utc)

    def metadata(self, pin):
        return dict(pin['artifact'], expired=False, workflow_run={
            'id': pin['seed_run_id'], 'head_sha': pin['seed_source_sha'], 'head_branch': 'main',
            'repository_id': pin['repository_id'], 'head_repository_id': pin['repository_id']})

    def test_pin_uses_actual_site_seed_and_public_metadata_only(self):
        pin = self.pin()
        self.assertEqual(pin['artifact']['id'], 12471731808)
        self.assertEqual(pin['seed_run_id'], 39883709543)
        self.assertEqual(pin['seed_source_sha'], 'dd5a49ed5efc883dd6b40c82d530c2c59762e709')
        self.assertEqual(pin['member_manifest_sha256'], 'ec4cba42a4fe66cb23e7da861c0ca9a6b49455fa2657aeb3068feedb95dbd35e')
        with patch.object(download_log, 'fetch_json', return_value=self.metadata(pin)) as fetch:
            self.assertEqual(cache.consumer_pin(check_metadata=True, now=self.now()), pin)
            fetch.assert_called_once_with('https://api.github.com/repos/llm-measurement/llm-measurement.github.io/actions/artifacts/12471731808')

    def test_bad_unknown_or_expired_pin_never_requests_or_falls_back(self):
        for change in ('repository', 'source', 'release', 'hash', 'key', 'id', 'expired'):
            pin = self.pin()
            if change == 'repository': pin['repository'] = 'example/other'
            elif change == 'source': pin['seed_source_sha'] = 'not-a-commit'
            elif change == 'release': pin['release_version'] = 'v0.12.0'
            elif change == 'hash': pin['member_manifest_sha256'] = 'unknown'
            elif change == 'key': pin['cache_key'] += '\nfallback=unsafe'
            elif change == 'id': pin['artifact']['id'] = 0
            else: pin['artifact']['expires_at'] = '2026-10-21T00:00:00Z'
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'pin.json'
                path.write_text(json.dumps(pin))
                with patch.object(cache, 'PIN', path), patch.object(download_log, 'fetch_json', side_effect=AssertionError('no request')):
                    with self.assertRaises(ValueError):
                        cache.consumer_pin(check_metadata=True, now=self.now())

    def test_expired_deleted_or_wrong_metadata_is_fatal(self):
        pin = self.pin()
        for field in ('expired', 'missing-expired', 'id', 'digest', 'head_sha', 'head_branch', 'repository_id', 'expires_at'):
            metadata = self.metadata(pin)
            if field == 'expired': metadata['expired'] = True
            elif field == 'missing-expired': del metadata['expired']
            elif field == 'id': metadata['id'] = 1
            elif field == 'digest': metadata['digest'] = 'sha256:' + '0' * 64
            elif field == 'expires_at': metadata['expires_at'] = '2027-01-22T00:00:00Z'
            else: metadata['workflow_run'][field] = 'wrong'
            with self.subTest(field=field), patch.object(download_log, 'fetch_json', return_value=metadata):
                with self.assertRaises(ValueError):
                    cache.consumer_pin(check_metadata=True, now=self.now())
        with patch.object(download_log, 'fetch_json', side_effect=OSError('metadata unavailable')):
            with self.assertRaises(OSError):
                cache.consumer_pin(check_metadata=True, now=self.now())

    def test_missing_cache_unknown_url_and_unknown_curl_option_fail(self):
        with patch.dict(cache.os.environ, {}, clear=True), self.assertRaises(ValueError):
            cache.cache_root()
        with self.assertRaises(ValueError):
            cache.read_url('https://example.org/fallback')
        with self.assertRaises(ValueError):
            cache.curl_arguments(['--header', 'Authorization: unavailable', 'https://example.org'])

    def events(self):
        records = []
        for name, checksum in cache.spec()['assets'].items():
            item = {'asset': name, 'url': 'https://github.com/llm-measurement/fleetdiff/releases/download/v0.12.1/' + name,
                'purpose': 'deliberate protected-main cache seed', 'run_id': 39883709543, 'run_attempt': 1,
                'started_at': '2026-10-23T01:23:30+00:00', 'status': 'started'}
            records.append(item)
            records.append(dict(item, status='verified', bytes=1, sha256=checksum, finished_at='2026-10-23T01:23:31+00:00'))
        return records

    def test_sixteen_seed_states_are_eight_requests_not_sixteen_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            path.write_text(''.join(json.dumps(row) + '\n' for row in self.events()))
            self.assertEqual(len(download_log.seed_requests(path)), 16)
            requests = download_log.seed_requests(path, collapse=True)
            self.assertEqual(len(requests), 8)
            self.assertTrue(all(row['status'] == 'verified' for row in requests))
            metadata = download_log.snapshot('llm-measurement/fleetdiff', lambda _: [])
            self.assertEqual(metadata['deliberate_download_requests_by_this_run'], [])
            self.assertIn('request purpose cannot be inferred', metadata['count_semantics'])

    def test_partial_log_is_truthful_but_duplicate_or_unpaired_finish_is_rejected(self):
        events = self.events()
        cases = ([events[0], events[0]], [events[1]], [events[0], events[1], events[1]])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            path.write_text(json.dumps(events[0]) + '\n')
            self.assertEqual(download_log.seed_requests(path, collapse=True)[0]['status'], 'started')
            for rows in cases:
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                with self.assertRaises(ValueError):
                    download_log.seed_requests(path, collapse=True)

    def test_all_three_jobs_restore_exact_and_reverify_before_use(self):
        root = cache.HERE.parent
        docs = (root / '.github/workflows/docs.yml').read_text()
        daily = (root / '.github/workflows/download-log.yml').read_text()
        for workflow, count in ((docs, 2), (daily, 1)):
            self.assertEqual(workflow.count('actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9'), count)
            self.assertEqual(workflow.count('fail-on-cache-miss: true'), count)
            self.assertEqual(workflow.count('test "$EXACT_HIT" = true'), count)
            self.assertEqual(workflow.count('--verify .site-release-cache --manifest-sha256 "$MANIFEST_SHA256"'), count)
            for forbidden in ('restore-keys:', 'actions/cache/save@', 'seed_release_cache.py', 'actions: read', 'github-token:', 'continue-on-error'):
                self.assertNotIn(forbidden, workflow)
        for name, command in (('examples', 'python3 scripts/outsider.py --output evidence/local'),
                              ('own-data', 'python3 scripts/check.py --own-data --output evidence/local/own-data')):
            job = docs.split('  ' + name + ':\n', 1)[1].split('\n  deploy:', 1)[0]
            self.assertLess(job.index('--verify .site-release-cache'), job.index(command))
        self.assertIn('--seed-log .site-release-cache/deliberate-downloads.jsonl', daily)


if __name__ == '__main__':
    unittest.main()
