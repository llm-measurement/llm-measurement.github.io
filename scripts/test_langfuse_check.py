import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from langfuse_check import ROOT, environment, saved_verification
from release_pins import check_source


class LangfuseChecks(unittest.TestCase):
    def test_reviewed_plan_privacy_and_accounting_copy(self):
        source = (ROOT / 'pages/langfuse-spend.html').read_text()
        for required in ('Langfuse Cloud Pro with the Teams add-on, Enterprise, or self-hosted; not Hobby/Core',
                         'also exports trace tags. Keep identifiers out of tags.',
                         'conflicting copies stop the comparison with an error',
                         'base input plus cache-read/cache-write, and base output plus reasoning, once',
                         'declared <code>total</code> is checked against that sum, not added to it',
                         'Missing component detail is counted as unreported',
                         'v0.13.0 reports Langfuse request status as unknown; token and cost totals are unaffected'):
            self.assertIn(required, source)
        for removed in ('conflicting copies refuse', 'Do not add', 'not a known zero',
                        'it does not build source', 'Parquet'):
            self.assertNotIn(removed, source)

    def test_actual_saved_command_evidence(self):
        result = saved_verification()
        self.assertEqual(len(result['own']), 3)
        self.assertTrue(result['sample']['pass'])
        self.assertIn('v0.13.0', result['installed_version'])

    def test_credentials_and_cache_shim_setting_not_inherited(self):
        with patch.dict('os.environ', {'GH_TOKEN': 'private', 'OPENAI_API_KEY': 'private',
                                      'HTTP_PROXY': 'private', 'SITE_RELEASE_CACHE': 'private'}):
            env = environment(Path('/tmp/fresh-fixture'))
        for key in ('GH_TOKEN', 'OPENAI_API_KEY', 'HTTP_PROXY', 'SITE_RELEASE_CACHE'):
            self.assertNotIn(key, env)
        self.assertEqual(env['GH_CONFIG_DIR'], '/tmp/fresh-fixture/gh')

    def test_stale_command_or_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('pages', 'evidence'):
                (root / folder).mkdir()
            for name in ('pages/langfuse-spend.html', 'evidence/langfuse-release.json',
                         'evidence/langfuse-verified.json'):
                shutil.copy2(ROOT / name, root / name)
            source = (root / 'pages/langfuse-spend.html').read_text()
            (root / 'pages/langfuse-spend.html').write_text(source.replace('--group-by provided_model_name', '--group-by release', 1))
            with self.assertRaises(AssertionError):
                saved_verification(root)
            (root / 'pages/langfuse-spend.html').write_text(source)
            evidence = json.loads((root / 'evidence/langfuse-verified.json').read_text())
            evidence['sample']['stdout'] += 'altered'
            (root / 'evidence/langfuse-verified.json').write_text(json.dumps(evidence))
            with self.assertRaises(AssertionError):
                saved_verification(root)

    def test_v013_pin_is_scoped_not_global(self):
        release = json.loads((ROOT / 'evidence/langfuse-release.json').read_text())
        source = (ROOT / 'pages/langfuse-spend.html').read_text()
        self.assertGreater(check_source('langfuse', source, release['commit'], release['version']), 0)
        with self.assertRaises(ValueError):
            check_source('legacy', source, '0d7db95c5bb3013f8c564c91fbb07b6235a2664e')


if __name__ == '__main__':
    unittest.main()
