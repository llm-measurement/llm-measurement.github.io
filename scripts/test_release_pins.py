# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Reject a branch-head installer even when it installs the right binary."""
from contextlib import nullcontext
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from own_data import FIXTURE_COMMIT, FIXTURE_VERSION
from outsider import ROOT
from release_pins import check, check_source, resolve_tag


class ReleasePinTests(unittest.TestCase):
    def block(self, commit=FIXTURE_COMMIT, version=FIXTURE_VERSION):
        return ('<pre data-own="install" data-exit="0"><code>'
                'curl -fsSLo install-fleetdiff.sh https://raw.githubusercontent.com/'
                f'llm-measurement/fleetdiff/{commit}/scripts/install.sh\n'
                f'sh install-fleetdiff.sh {version} ./bin</code></pre>')

    def test_matching_installer_and_release(self):
        self.assertEqual(check_source("page", self.block(), FIXTURE_COMMIT), 1)

    def test_branch_head_installer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "pin.*!="):
            check_source("page", self.block("a" * 40), FIXTURE_COMMIT)

    def test_wrong_or_missing_install_version_is_rejected(self):
        for version in ("v0.11.0", ""):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "explicitly install"):
                check_source("page", self.block(version=version), FIXTURE_COMMIT)

    def test_all_source_url_forms_and_short_pins_are_checked(self):
        for prefix in ("raw.githubusercontent.com/llm-measurement/fleetdiff/",
                       "github.com/llm-measurement/fleetdiff/blob/",
                       "github.com/llm-measurement/fleetdiff/tree/",
                       "codeload.github.com/llm-measurement/fleetdiff/tar.gz/"):
            with self.subTest(prefix=prefix):
                self.assertEqual(check_source("page", "https://" + prefix + FIXTURE_COMMIT + "/file", FIXTURE_COMMIT), 1)
                for bad in ("a" * 40, FIXTURE_COMMIT[:7]):
                    with self.assertRaisesRegex(ValueError, "pin.*!="):
                        check_source("page", "https://" + prefix + bad + "/file", FIXTURE_COMMIT)

    def test_installer_in_sample_block_is_checked(self):
        source = self.block("a" * 40).replace('data-own="install"', 'data-run="example"')
        with self.assertRaisesRegex(ValueError, "pin.*!="):
            check_source("page", source, FIXTURE_COMMIT)

    def test_archive_url_at_string_end_and_inside_quotes_is_checked(self):
        url = "https://codeload.github.com/llm-measurement/fleetdiff/tar.gz/" + "a" * 40
        for source in (url, f"curl '{url}'", f'curl "{url}"', f"`{url}`"):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "pin.*!="):
                check_source("page", source, FIXTURE_COMMIT)

    def test_uppercase_commit_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, "pin.*!="):
            check_source("page", self.block("A" * 40), FIXTURE_COMMIT)

    def test_annotated_tag_uses_commit_not_tag_object(self):
        ref = "refs/tags/" + FIXTURE_VERSION
        output = f'{"a" * 40}\t{ref}\n{FIXTURE_COMMIT}\t{ref}^{{}}\n'
        with patch("release_pins.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output)) as run:
            self.assertEqual(resolve_tag(FIXTURE_VERSION), FIXTURE_COMMIT)
        args, kwargs = run.call_args
        self.assertEqual(args[0][-2:], [ref, ref + "^{}"])
        self.assertTrue(kwargs["check"])
        self.assertNotIn("GH_TOKEN", kwargs["env"])
        self.assertEqual(kwargs["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")

    def test_lightweight_tag(self):
        with patch("release_pins.subprocess.run", return_value=subprocess.CompletedProcess(
                [], 0, f"{FIXTURE_COMMIT}\trefs/tags/{FIXTURE_VERSION}\n")):
            self.assertEqual(resolve_tag(FIXTURE_VERSION), FIXTURE_COMMIT)

    def test_tag_lookup_cannot_discover_repository_local_config(self):
        real_run = subprocess.run

        def inspect_lookup(command, **kwargs):
            self.assertEqual(kwargs["env"]["GIT_CEILING_DIRECTORIES"], str(Path(kwargs["cwd"]).parent))
            probe = real_run(["git", "rev-parse", "--git-dir"], cwd=kwargs["cwd"],
                             env=kwargs["env"], text=True, capture_output=True, timeout=10)
            self.assertNotEqual(probe.returncode, 0, probe.stdout)
            return subprocess.CompletedProcess(command, 0, f"{FIXTURE_COMMIT}\trefs/tags/{FIXTURE_VERSION}\n")

        with patch("release_pins.subprocess.run", side_effect=inspect_lookup):
            self.assertEqual(resolve_tag(FIXTURE_VERSION), FIXTURE_COMMIT)
        # Also model TMPDIR being inside a checkout, not only the usual /tmp.
        with patch("release_pins.tempfile.TemporaryDirectory", return_value=nullcontext(str(ROOT / "scripts"))), \
                patch("release_pins.subprocess.run", side_effect=inspect_lookup):
            self.assertEqual(resolve_tag(FIXTURE_VERSION), FIXTURE_COMMIT)

    def test_missing_duplicate_or_malformed_tag_fails(self):
        ref = "refs/tags/" + FIXTURE_VERSION
        line = f"{FIXTURE_COMMIT}\t{ref}\n"
        for output in ("", line + line, "garbage", f"{FIXTURE_COMMIT}\trefs/heads/main\n"):
            with self.subTest(output=output), patch("release_pins.subprocess.run", return_value=
                    subprocess.CompletedProcess([], 0, output)), self.assertRaises(ValueError):
                resolve_tag(FIXTURE_VERSION)

    def test_network_failure_does_not_use_recorded_fallback(self):
        with patch("release_pins.subprocess.run", side_effect=subprocess.CalledProcessError(128, ["git"])):
            with self.assertRaises(subprocess.CalledProcessError):
                check(live=True)

    def test_moved_tag_is_rejected(self):
        with patch("release_pins.resolve_tag", return_value="a" * 40):
            with self.assertRaisesRegex(ValueError, "resolves to"):
                check(live=True)

    def test_site_sources_generated_pages_and_evidence(self):
        check()


if __name__ == "__main__":
    unittest.main()
