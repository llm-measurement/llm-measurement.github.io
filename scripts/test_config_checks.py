# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Keep config evidence executable, byte-exact and bound to cached releases."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import config_checks
import own_data


class ConfigChecksTests(unittest.TestCase):
    def test_fragment_inventory_and_exact_composition(self):
        actual = {page: [b["id"] for b in own_data.page_blocks(page).configs]
                  for page in own_data.PAGES if own_data.page_blocks(page).configs}
        self.assertEqual(actual, {"cardinality": ["cardinality"], "traces-usage": ["traces-usage"],
                                 "what-if": ["what-if-workload-map"]})
        for page in config_checks.CONFIG_IMAGES:
            block = own_data.page_blocks(page).configs[0]
            composed = config_checks.compose(block)
            self.assertEqual(composed.count(block["text"].encode()), 1)
            self.assertTrue(composed.startswith(config_checks.RECEIVER.encode()))
            self.assertIn(b"receivers: [otlp]", composed)
            if page == "traces-usage":
                self.assertIn(b"exporters: [debug/existing, file/inspect]", composed)
                self.assertIn(b"path: /private-capture/traces.jsonl", composed)
            else:
                self.assertIn(b"receivers: [genaisketch]", composed)
        with self.assertRaises(AssertionError):
            config_checks.compose({"id": "unknown", "text": "exporters:\n"})

    def test_child_images_are_bound_to_exact_published_index(self):
        self.assertTrue(config_checks.platform_image("cardinality", "arm64").endswith(
            "@sha256:e26262c16484ca62e1618077facf614940dbe8c11c3d05689b570b33f387c152"))
        self.assertTrue(config_checks.platform_image("cardinality", "amd64").endswith(
            "@sha256:7c53d876885df4f0a141e9e9ec9334364e382853edf0472ba2f7695b396fbbd2"))
        with self.assertRaises(AssertionError):
            config_checks.platform_image("cardinality", "unsupported")
        with patch.object(Path, "read_bytes", return_value=b"{}"), self.assertRaisesRegex(AssertionError, "index bytes"):
            config_checks.platform_image("cardinality", "arm64")

    def fake_docker(self, page, seen, *, positive=0, negative=1, wrong_diagnostic=False, cached_child=False):
        image = config_checks.CONFIG_IMAGES[page]
        def run(command, **kwargs):
            seen.append(command)
            if command[:3] == ["docker", "image", "inspect"]:
                if cached_child and command[-1] == image:
                    return subprocess.CompletedProcess(command, 1, "", "not cached")
                info = [{"RepoDigests": [command[-1]], "Id": "sha256:" + "a" * 64, "Architecture": "arm64"}]
                return subprocess.CompletedProcess(command, 0, json.dumps(info), "")
            if command[:2] == ["docker", "ps"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            self.assertEqual(command[:3], ["docker", "run", "--pull=never"])
            self.assertEqual(command[command.index("--network") + 1], "none")
            self.assertIn("--read-only", command)
            self.assertIn("--cap-drop=ALL", command)
            self.assertEqual(command[-2:], ["validate", "--config=file:/fixture/config.yaml"])
            mount = next(v for v in command if v.startswith("type=bind,src=") and "dst=/fixture/config.yaml" in v)
            path = Path(mount.split("src=", 1)[1].split(",dst=", 1)[0])
            raw = path.read_bytes()
            is_negative = path.name.endswith(".negative.yaml")
            if is_negative:
                self.assertIn(b"unsupported_site_test_", raw)
                diagnostic = "topk_keys weight must be tokens or requests" if page == "cardinality" else "unsupported_site_test_setting"
                return subprocess.CompletedProcess(command, negative, "", "unrelated failure" if wrong_diagnostic else diagnostic)
            self.assertEqual(raw, config_checks.compose(own_data.page_blocks(page).configs[0]))
            return subprocess.CompletedProcess(command, positive, "", "" if positive == 0 else "positive failed")
        return run

    def test_real_validator_commands_and_both_cases_are_required(self):
        for page in config_checks.CONFIG_IMAGES:
            with self.subTest(page=page), tempfile.TemporaryDirectory() as directory:
                fresh = Path(directory)
                seen = []
                with patch.object(config_checks.subprocess, "run", side_effect=self.fake_docker(page, seen)):
                    result = config_checks.validate(own_data.page_blocks(page).configs[0], fresh,
                                                    {"DOCKER_HOST": "unix:///synthetic"}, fresh / "out")
                self.assertEqual(result["kind"], "collector-validate")
                self.assertEqual(result["network"], "none")
                self.assertEqual(result["pull"], "never")
                self.assertTrue(result["containers_removed"])
                self.assertEqual(result["image"], config_checks.CONFIG_IMAGES[page])
                self.assertEqual(result["config_sha256"], hashlib.sha256(
                    own_data.page_blocks(page).configs[0]["text"].encode()).hexdigest())
                self.assertEqual([(r["case"], r["exit"], r["pass"]) for r in result["results"]],
                                 [("published", 0, True), ("negative", 1, True)])
                self.assertNotEqual(result["results"][0]["configuration_sha256"],
                                    result["results"][1]["configuration_sha256"])
                self.assertEqual(result["composed_sha256"], result["results"][0]["configuration_sha256"])
                self.assertTrue(all(command[:2] != ["docker", "pull"] for command in seen))

    def test_cached_child_resolution_never_pulls_or_substitutes_a_different_release(self):
        with tempfile.TemporaryDirectory() as directory:
            fresh = Path(directory)
            seen = []
            with patch.object(config_checks.platform, "machine", return_value="arm64"), \
                    patch.object(config_checks.subprocess, "run", side_effect=self.fake_docker("cardinality", seen, cached_child=True)):
                result = config_checks.validate(own_data.page_blocks("cardinality").configs[0], fresh,
                                                {"DOCKER_HOST": "unix:///synthetic"}, fresh / "out")
            self.assertEqual(result["runtime_image"], config_checks.platform_image("cardinality", "arm64"))
            commands = [c for c in seen if c[:2] == ["docker", "run"]]
            self.assertTrue(all(c[-3] == result["runtime_image"] for c in commands))

    def test_failed_positive_accepted_negative_or_unrelated_failure_cannot_pass(self):
        for options in ({"positive": 1}, {"negative": 0}, {"wrong_diagnostic": True}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                fresh = Path(directory)
                with patch.object(config_checks.subprocess, "run", side_effect=self.fake_docker("cardinality", [], **options)), \
                        self.assertRaises(AssertionError):
                    config_checks.validate(own_data.page_blocks("cardinality").configs[0], fresh,
                                           {"DOCKER_HOST": "unix:///synthetic"}, fresh / "out")

    def test_no_cached_image_fails_before_any_container(self):
        seen = []
        def absent(command, **kwargs):
            seen.append(command)
            if kwargs.get("check"):
                raise subprocess.CalledProcessError(1, command, "", "absent")
            return subprocess.CompletedProcess(command, 1, "", "absent")
        with tempfile.TemporaryDirectory() as directory, patch.object(config_checks.platform, "machine", return_value="arm64"), \
                patch.object(config_checks.subprocess, "run", side_effect=absent), self.assertRaises(subprocess.CalledProcessError):
            config_checks.validate(own_data.page_blocks("cardinality").configs[0], Path(directory),
                                   {"DOCKER_HOST": "unix:///synthetic"}, Path(directory) / "out")
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(command[:3] == ["docker", "image", "inspect"] for command in seen))


if __name__ == "__main__":
    unittest.main()
