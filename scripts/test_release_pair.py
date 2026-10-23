# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check release pins and syntax without fetching or installing artifacts."""
import subprocess
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from outsider import Blocks, ROOT
from review_releases import review_environment


class ReleasePairTests(unittest.TestCase):
    def test_current_collector_links_and_pair(self):
        for path in (ROOT / "pages").glob("*.html"):
            if path.stem == "summaries":
                continue
            source = path.read_text()
            with self.subTest(page=path.stem):
                self.assertNotIn("otelcol-genai-sketches/blob/v0.3.2/", source)
                self.assertNotIn("otelcol-genai-sketches/tree/v0.3.2/", source)
                self.assertNotIn("chart 0.3.4", source)
                self.assertNotIn("chart-v0.3.5", source)
        home = (ROOT / "pages/index.html").read_text()
        self.assertIn("Helm chart 0.6.2 and collector v0.6.2", home)

    def test_collector_review_uses_combined_release_metadata(self):
        blocks = Blocks()
        blocks.feed((ROOT / "pages/security.html").read_text())
        command = next(block["text"] for block in blocks.review if block["id"] == "collector")
        self.assertIn("\nrelease=v0.6.2\n", command)
        self.assertIn(".github/workflows/release.yml@refs/tags/$release", command)
        self.assertNotIn("chart-release.yml", command)
        self.assertIn('image="$(cat image-digest.txt)"', command)
        self.assertIn('chart="$(cat chart-digest.txt)"', command)
        self.assertIn("for subject in SHA256SUMS sbom-index.json; do", command)
        self.assertIn("--bundle provenance.jsonl", command)
        self.assertIn('gh attestation verify "oci://$artifact"', command)
        self.assertIn('--source-ref "refs/tags/$release"', command)
        self.assertEqual(command.count("--deny-self-hosted-runners"), 2)
        self.assertLess(command.index('gh attestation verify "$subject"'),
                        command.index("shasum -a 256 --ignore-missing -c SHA256SUMS"))
        self.assertLess(command.index("shasum -a 256 --ignore-missing -c SHA256SUMS"),
                        command.index('image="$(cat image-digest.txt)"'))

    def test_review_authentication_is_scoped_to_collector(self):
        fresh = Path("/test/fresh")
        with patch.dict(os.environ, {"GH_TOKEN": "test-only-token", "GH_CONFIG_DIR": "/test/gh",
                                     "DOCKER_AUTH_CONFIG": "test-only-registry", "COSIGN_PASSWORD": "test-only"}, clear=True):
            for block in ("collector", "fleetdiff"):
                env = review_environment(fresh, block)
                self.assertEqual(env["HOME"], str(fresh))
                self.assertEqual(env["DOCKER_CONFIG"], str(fresh / "docker"))
                self.assertNotIn("DOCKER_AUTH_CONFIG", env)
                self.assertNotIn("COSIGN_PASSWORD", env)
                if block == "collector":
                    self.assertEqual(env["GH_TOKEN"], "test-only-token")
                    self.assertEqual(env["GH_CONFIG_DIR"], "/test/gh")
                else:
                    self.assertNotIn("GH_TOKEN", env)
                    self.assertEqual(env["GH_CONFIG_DIR"], str(fresh / "gh"))

    def test_collector_authentication_prerequisite_is_visible(self):
        self.assertIn("GitHub CLI signed in for the OCI provenance API checks",
                      (ROOT / "pages/security.html").read_text())

    def test_install_guides_pin_the_matching_release_documentation(self):
        revision = "v0.6.2"
        for name in ("anomalies", "token-spike", "index", "security"):
            source = (ROOT / "pages" / (name + ".html")).read_text()
            self.assertIn("otelcol-genai-sketches/blob/" + revision + "/docs/", source)
            self.assertNotIn("blob/v0.3.3/docs/SUMMARY_EXPORT_HELM.md", source)
            self.assertNotIn("blob/v0.3.3/docs/DEPLOYMENT.md", source)

    def test_review_commands_parse_without_execution(self):
        blocks = Blocks()
        blocks.feed((ROOT / "pages/security.html").read_text())
        for block in blocks.review:
            with self.subTest(block=block["id"]):
                result = subprocess.run(["bash", "-n"], input=block["text"],
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
