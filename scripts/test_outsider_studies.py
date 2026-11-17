# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Studies have a separate evidence checker, not annotated guide commands."""
import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

import outsider


class OutsiderPageKindsTests(unittest.TestCase):
    def run_fixture(self, directory, pages):
        root = Path(directory)
        (root / 'pages').mkdir()
        (root / 'pages.json').write_text(json.dumps(pages))
        cache = root / 'cache'
        cache.mkdir()
        (cache / 'cache-identity.json').write_text('{}')
        output = root / 'output'
        for page in pages:
            if not page.get('kind') and page['slug'] != 'index':
                (root / 'pages' / (page['slug'] + '.html')).write_text(
                    '<pre data-run="sample" data-exit="0">sample-command</pre>'
                    '<pre data-output="sample">sample-output</pre>')
        with patch.object(outsider, 'ROOT', root), \
             patch('sys.argv', ['outsider.py', '--output', str(output)]), \
             patch('release_cache.cache_root', return_value=cache), \
             patch('release_cache.consumer_pin', return_value={}), \
             patch('own_data.environment', return_value={}), \
             patch.object(outsider.subprocess, 'run', return_value=CompletedProcess(
                 ['sample-command'], 0, 'sample-output', '')) as runner:
            outsider.main()
        return json.loads((output / 'manifest.json').read_text()), runner

    def test_study_is_never_parsed_or_executed_as_a_guide(self):
        pages = [{'slug': 'index'}, {'slug': 'studies', 'kind': 'reference'},
                 {'slug': 'summaries', 'kind': 'evidence'},
                 {'slug': 'prompt-cache-bills', 'kind': 'study'}]
        with tempfile.TemporaryDirectory() as directory:
            manifest, runner = self.run_fixture(directory, pages)
        self.assertEqual(manifest['results'], [])
        runner.assert_not_called()

    def test_existing_guide_still_executes_with_a_study_registered(self):
        pages = [{'slug': 'cache-check'}, {'slug': 'prompt-cache-bills', 'kind': 'study'}]
        with tempfile.TemporaryDirectory() as directory:
            manifest, runner = self.run_fixture(directory, pages)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], ['bash', '-e', '-c', 'sample-command'])
        self.assertEqual([(row['page'], row['pass']) for row in manifest['results']],
                         [('cache-check', True)])


if __name__ == '__main__':
    unittest.main()
