# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Exercise the reviewed DOI registry exception without network access."""
import json
import unittest
from unittest.mock import MagicMock, Mock, patch

import study_outsider as outsider


DOI = '10.1109/JSAC.2002.801752'
DOI_URL = 'https://doi.org/' + DOI
REGISTRY_URL = 'https://doi.org/api/handles/' + DOI
EXPECTED_TARGET = 'ieeexplore.ieee.org/document/1031903'
REGISTRY_TARGET = 'http://' + EXPECTED_TARGET + '/'
EXPECTED_RESULT = {
    'registry_url': REGISTRY_URL,
    'expected_target': EXPECTED_TARGET,
    'publisher_reachability': 'not_asserted',
}


class StudyDoiTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            'responseCode': 1,
            'handle': DOI,
            'values': [
                {'type': 'URL', 'data': {'format': 'string', 'value': REGISTRY_TARGET}},
                {'type': 'HS_ADMIN', 'data': {
                    'format': 'admin', 'value': {'adminId': '0.NA/10.1109', 'adminIdIndex': 200},
                }},
            ],
        }
        self.fetcher = Mock(side_effect=lambda url: json.dumps(self.record).encode('utf-8'))
        network = patch.object(outsider, 'urlopen', side_effect=AssertionError('network forbidden'))
        self.opened = network.start()
        self.addCleanup(network.stop)

    def test_registered_doi_checks_only_registry_and_does_not_assert_publisher(self):
        self.assertEqual(outsider.check_doi(DOI_URL, self.fetcher), EXPECTED_RESULT)
        self.fetcher.assert_called_once_with(REGISTRY_URL)
        self.opened.assert_not_called()

    def test_registry_handle_match_is_case_insensitive(self):
        self.record['handle'] = DOI.lower()
        self.assertEqual(outsider.check_doi(DOI_URL, self.fetcher), EXPECTED_RESULT)
        self.fetcher.assert_called_once_with(REGISTRY_URL)

    def test_registry_not_found_response_code_100_is_refused(self):
        self.record['responseCode'] = 100
        with self.assertRaises(ValueError):
            outsider.check_doi(DOI_URL, self.fetcher)
        self.fetcher.assert_called_once_with(REGISTRY_URL)

    def test_registry_response_code_requires_exact_integer_one(self):
        for code in (True, False, 1.0, '1', None, 0, 2, -1):
            with self.subTest(responseCode=code, kind=type(code).__name__):
                self.record['responseCode'] = code
                self.fetcher.reset_mock()
                with self.assertRaises(ValueError):
                    outsider.check_doi(DOI_URL, self.fetcher)
                self.fetcher.assert_called_once_with(REGISTRY_URL)

    def test_missing_response_code_is_refused(self):
        del self.record['responseCode']
        with self.assertRaises(ValueError):
            outsider.check_doi(DOI_URL, self.fetcher)

    def test_registry_handle_must_be_present_string_and_match(self):
        for handle in (None, True, 1, [], {}, '', '10.1109/JSAC.2002.801753', DOI + '/'):
            with self.subTest(handle=handle):
                self.record['handle'] = handle
                with self.assertRaises(ValueError):
                    outsider.check_doi(DOI_URL, self.fetcher)
        del self.record['handle']
        with self.assertRaises(ValueError):
            outsider.check_doi(DOI_URL, self.fetcher)

    def test_unknown_doi_is_refused_before_any_fetch(self):
        for url in ('https://doi.org/10.1109/JSAC.2002.801753',
                    'https://doi.org/10.9999/unreviewed', DOI_URL + '/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                outsider.check_doi(url, self.fetcher)
        self.fetcher.assert_not_called()
        self.opened.assert_not_called()

    def test_noncanonical_doi_urls_are_refused_before_any_fetch(self):
        urls = (
            'http://doi.org/' + DOI,
            'https://user:secret@doi.org/' + DOI,
            'https://@doi.org/' + DOI,
            'https://doi.org:444/' + DOI,
            'https://doi.org.evil.example/' + DOI,
            'https://example.org/' + DOI,
            DOI_URL + '?redirect=elsewhere',
            DOI_URL + '#fragment',
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                outsider.check_doi(url, self.fetcher)
        self.fetcher.assert_not_called()
        self.opened.assert_not_called()

    def test_malformed_json_is_refused(self):
        for payload in (b'', b'not json', b'{', b'{"responseCode": 1,}'):
            fetcher = Mock(return_value=payload)
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                outsider.check_doi(DOI_URL, fetcher)
            fetcher.assert_called_once_with(REGISTRY_URL)

    def test_registry_root_must_be_an_object(self):
        for record in (None, True, 1, 'registered', [], [self.record]):
            fetcher = Mock(return_value=json.dumps(record).encode('utf-8'))
            with self.subTest(record=record), self.assertRaises(ValueError):
                outsider.check_doi(DOI_URL, fetcher)
            fetcher.assert_called_once_with(REGISTRY_URL)

    def test_registry_values_must_be_a_list_of_objects(self):
        for values in (None, {}, 'URL', [None], [True], [1], ['URL'],
                       [self.record['values'][0], False]):
            with self.subTest(values=values):
                self.record['values'] = values
                with self.assertRaises(ValueError):
                    outsider.check_doi(DOI_URL, self.fetcher)
        del self.record['values']
        with self.assertRaises(ValueError):
            outsider.check_doi(DOI_URL, self.fetcher)

    def test_registry_requires_exactly_one_url_entry(self):
        url_entry, admin_entry = self.record['values']
        different_url = {'type': 'URL', 'data': {
            'format': 'string', 'value': 'https://example.org/document/1031903',
        }}
        for values in ([], [admin_entry], [url_entry, url_entry],
                       [url_entry, admin_entry, different_url]):
            with self.subTest(values=values):
                self.record['values'] = values
                with self.assertRaises(ValueError):
                    outsider.check_doi(DOI_URL, self.fetcher)

    def test_url_data_requires_string_format_and_string_value(self):
        malformed = (
            None, [], 'not an object', {},
            {'value': REGISTRY_TARGET},
            {'format': 'String', 'value': REGISTRY_TARGET},
            {'format': 'url', 'value': REGISTRY_TARGET},
            {'format': 'string'},
            {'format': 'string', 'value': None},
            {'format': 'string', 'value': True},
            {'format': 'string', 'value': 1},
            {'format': 'string', 'value': [REGISTRY_TARGET]},
            {'format': 'string', 'value': {'url': REGISTRY_TARGET}},
        )
        for data in malformed:
            with self.subTest(data=data):
                self.record['values'][0]['data'] = data
                with self.assertRaises(ValueError):
                    outsider.check_doi(DOI_URL, self.fetcher)

    def test_registry_target_mismatch_is_refused(self):
        self.record['values'][0]['data']['value'] = 'https://ieeexplore.ieee.org/document/1031904'
        with self.assertRaises(ValueError):
            outsider.check_doi(DOI_URL, self.fetcher)
        self.fetcher.assert_called_once_with(REGISTRY_URL)

    def test_target_allows_http_https_default_ports_and_one_trailing_slash(self):
        host, path = EXPECTED_TARGET.split('/', 1)
        for scheme, port in (('http', ''), ('http', ':80'), ('https', ''), ('https', ':443')):
            for trailing_slash in ('', '/'):
                value = scheme + '://' + host + port + '/' + path + trailing_slash
                with self.subTest(value=value):
                    self.assertTrue(outsider.matches_doi_target(value, EXPECTED_TARGET))
                    self.record['values'][0]['data']['value'] = value
                    self.assertEqual(outsider.check_doi(DOI_URL, self.fetcher), EXPECTED_RESULT)

    def test_target_rejects_other_hosts_paths_ports_credentials_queries_and_fragments(self):
        values = (
            'ftp://' + EXPECTED_TARGET,
            '//' + EXPECTED_TARGET,
            EXPECTED_TARGET,
            'https://example.org/document/1031903',
            'https://ieeexplore.ieee.org.evil.example/document/1031903',
            'https://ieeexplore.ieee.org@evil.example/document/1031903',
            'https://user:secret@' + EXPECTED_TARGET,
            'https://@' + EXPECTED_TARGET,
            'https://ieeexplore.ieee.org:8443/document/1031903',
            'https://ieeexplore.ieee.org:80/document/1031903',
            'http://ieeexplore.ieee.org:443/document/1031903',
            'https://ieeexplore.ieee.org/Document/1031903',
            'https://ieeexplore.ieee.org/document/1031904',
            'https://' + EXPECTED_TARGET + '//',
            'https://' + EXPECTED_TARGET + '/extra',
            'https://' + EXPECTED_TARGET + '?download=1',
            'https://' + EXPECTED_TARGET + '#abstract',
        )
        for value in values:
            with self.subTest(value=value):
                self.assertFalse(outsider.matches_doi_target(value, EXPECTED_TARGET))
                self.record['values'][0]['data']['value'] = value
                with self.assertRaises(ValueError):
                    outsider.check_doi(DOI_URL, self.fetcher)

    def test_target_rejects_non_string_values(self):
        for value in (None, True, False, 1, [], {}, b'http://' + EXPECTED_TARGET.encode('ascii')):
            with self.subTest(value=value):
                self.assertFalse(outsider.matches_doi_target(value, EXPECTED_TARGET))

    def test_registry_http_200_uses_strict_anonymous_bounded_fetch(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(self.record).encode('utf-8')
        with patch.object(outsider, 'urlopen', return_value=response) as opened:
            self.assertEqual(outsider.check_doi(DOI_URL, outsider.fetch), EXPECTED_RESULT)
        opened.assert_called_once()
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, REGISTRY_URL)
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Cache-control'), 'no-cache')
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(opened.call_args.kwargs['timeout'], 30)
        response.read.assert_called_once_with(outsider.MAX_CITATION_RESPONSE + 1)
        response.__exit__.assert_called_once()

    def test_registry_http_202_is_refused_even_with_valid_registration_body(self):
        response = MagicMock()
        response.status = 202
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(self.record).encode('utf-8')
        with patch.object(outsider, 'urlopen', return_value=response) as opened, \
             self.assertRaisesRegex(ValueError, 'HTTP 200'):
            outsider.check_doi(DOI_URL, outsider.fetch)
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[0].full_url, REGISTRY_URL)
        response.read.assert_not_called()
        response.__exit__.assert_called_once()

    def test_non_doi_http_202_remains_refused(self):
        response = MagicMock()
        response.status = 202
        response.__enter__.return_value = response
        response.read.return_value = b'not a completed publisher response'
        url = 'https://example.org/source'
        with patch.object(outsider, 'urlopen', return_value=response) as opened, \
             self.assertRaisesRegex(ValueError, 'HTTP 200'):
            outsider.fetch(url)
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[0].full_url, url)
        response.read.assert_not_called()
        response.__exit__.assert_called_once()


if __name__ == '__main__':
    unittest.main()
