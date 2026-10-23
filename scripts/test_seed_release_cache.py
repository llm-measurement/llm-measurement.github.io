# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Offline seed and restored-cache trust-boundary checks."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import download_log
import release_cache as cache
import seed_release_cache as seed


class SeedTests(unittest.TestCase):
    def origin_environment(self):
        return {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main", "GITHUB_REF_PROTECTED": "true",
                "GITHUB_REPOSITORY": seed.REPOSITORY, "GITHUB_WORKFLOW_REF": seed.WORKFLOW,
                "GITHUB_SHA": "a" * 40, "GITHUB_WORKFLOW_SHA": "a" * 40,
                "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}

    def test_seed_only_on_actual_protected_main_dispatch(self):
        env = self.origin_environment()
        self.assertEqual(seed.seed_origin(env)["run_id"], 123)
        for key, value in (("GITHUB_ACTIONS", "false"), ("GITHUB_EVENT_NAME", "pull_request"),
                           ("GITHUB_REF", "refs/heads/topic"), ("GITHUB_REF_PROTECTED", "false"),
                           ("GITHUB_REPOSITORY", "example/fork"), ("GITHUB_WORKFLOW_REF", seed.WORKFLOW + "bad"),
                           ("GITHUB_WORKFLOW_SHA", "b" * 40), ("GITHUB_SHA", "not-a-sha")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                seed.seed_origin(dict(env, **{key: value}))

    def test_non_main_rejected_before_work_or_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(seed.os.environ, {}, clear=True), \
                patch.object(seed.urllib.request, "build_opener", side_effect=AssertionError("no request")):
            root = Path(directory)
            with self.assertRaises(ValueError):
                seed.seed(root, root / "work", root / "cache")
            self.assertFalse((root / "work").exists())

    def test_redirect_host_protocol_and_credentials_are_restricted(self):
        for target in ("http://release-assets.githubusercontent.com/x", "https://example.org/x",
                       "https://user:secret@release-assets.githubusercontent.com/x"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                seed.ReleaseRedirect().redirect_request(None, None, 302, "Found", {}, target)

    def test_asset_request_is_logged_before_fetch_and_after_digest_check(self):
        data = b"synthetic asset"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "requests.jsonl"
            class Opener:
                def open(self, request, timeout):
                    self.request = request
                    self.status_at_request = json.loads(log.read_text())["status"]
                    return io.BytesIO(data)
            opener = Opener()
            seed.download_asset("SHA256SUMS", cache.digest(data), root, log,
                                {"run_id": 123, "run_attempt": 1}, opener)
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(opener.status_at_request, "started")
            self.assertNotIn("Authorization", opener.request.headers)
            self.assertEqual([row["status"] for row in rows], ["started", "verified"])
            self.assertEqual(rows[-1]["sha256"], cache.digest(data))
            self.assertEqual(rows[-1]["bytes"], len(data))

    def test_bad_asset_is_logged_but_not_written_and_errors_are_sanitized(self):
        for mode in ("digest", "network"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log = root / "requests.jsonl"
                class Opener:
                    def open(self, request, timeout):
                        if mode == "network":
                            raise OSError("https://signed.example/?secret=not-for-log")
                        return io.BytesIO(b"changed bytes")
                with self.assertRaises(RuntimeError) as error:
                    seed.download_asset("SHA256SUMS", "0" * 64, root, log,
                                        {"run_id": 123, "run_attempt": 1}, Opener())
                self.assertNotIn("secret", str(error.exception))
                self.assertNotIn("secret", log.read_text())
                self.assertFalse((root / "SHA256SUMS").exists())
                self.assertEqual(json.loads(log.read_text().splitlines()[-1])["status"], "failed")

    def synthetic_cache(self, root):
        definition = {"version": "v0.12.1", "commit": "a" * 40, "tree": "b" * 40,
                      "artifact": {"id": 1}, "tag_ref": "refs/tags/v0.12.1", "source_files": {},
                      "source_archives": {}, "urls": {}, "assets": {}}
        for name in ("SHA256SUMS", "provenance.jsonl"):
            data = ("synthetic " + name).encode()
            (root / name).write_bytes(data)
            definition["assets"][name] = cache.digest(data)
        identity = {"spec_sha256": cache.digest(cache.SPEC.read_bytes()), "version": "v0.12.1",
                    "source_commit": "a" * 40, "source_tree": "b" * 40, "artifact": {"id": 1},
                    "attested_subjects_verified": ["SHA256SUMS"]}
        (root / "cache-identity.json").write_text(json.dumps(identity))
        (root / "seed-origin.json").write_text('{}\n')
        (root / "deliberate-downloads.jsonl").write_text('')
        inventory = json.dumps(cache.member_hashes(root)).encode()
        (root / "cache-members.json").write_bytes(inventory)
        return definition, cache.digest(inventory)

    def test_every_restoration_requires_real_crypto_not_just_identity_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definition, checksum = self.synthetic_cache(root)
            with patch.object(cache, "spec", return_value=definition), patch.object(cache.subprocess, "run") as verify:
                cache.verify_cache(root, checksum)
                cache.verify_cache(root, checksum)
                self.assertEqual(verify.call_count, 2)
                command = verify.call_args.args[0]
                for constraint in ("--bundle", "--repo", "--signer-workflow", "--source-ref",
                                   "--source-digest", "--deny-self-hosted-runners"):
                    self.assertIn(constraint, command)
                verify.side_effect = subprocess.CalledProcessError(1, ["gh"])
                with self.assertRaises(subprocess.CalledProcessError):
                    cache.verify_cache(root, checksum)

    def test_tampering_wrong_manifest_unexpected_and_linked_members_fail(self):
        for mode in ("asset", "manifest", "extra", "link", "nested-manifest", "identity"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                definition, checksum = self.synthetic_cache(root)
                if mode == "asset":
                    (root / "SHA256SUMS").write_bytes(b"changed")
                elif mode == "manifest":
                    checksum = "0" * 64
                elif mode == "identity":
                    (root / "cache-identity.json").write_text('{}')
                elif mode == "extra":
                    (root / "unexpected").write_text('x')
                elif mode == "nested-manifest":
                    (root / "nested").mkdir()
                    (root / "nested/cache-members.json").write_text('{}')
                else:
                    (root / "linked").symlink_to(root / "SHA256SUMS")
                with patch.object(cache, "spec", return_value=definition), \
                        patch.object(cache, "verify_subjects", side_effect=AssertionError("must reject before crypto")):
                    with self.assertRaises(ValueError):
                        cache.verify_cache(root, checksum)

    def test_daily_log_distinguishes_seed_events_from_metadata_collection(self):
        definition = cache.spec()
        item = {"asset": "SHA256SUMS", "url": "https://github.com/llm-measurement/fleetdiff/releases/download/v0.12.1/SHA256SUMS",
                "purpose": "deliberate protected-main cache seed", "run_id": 123, "run_attempt": 1,
                "started_at": "2026-10-22T23:00:00+00:00", "finished_at": "2026-10-22T23:00:01+00:00",
                "status": "verified", "bytes": 579, "sha256": definition["assets"]["SHA256SUMS"]}
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "requests.jsonl"
            log.write_text(json.dumps(item) + '\n')
            self.assertEqual(download_log.seed_requests(log), [item])
            for key, value in (("url", item["url"] + "?signed=secret"), ("sha256", "0" * 64),
                               ("status", "pretend-success"), ("download_count", 0)):
                log.write_text(json.dumps(dict(item, **{key: value})) + '\n')
                with self.subTest(key=key), self.assertRaises(ValueError):
                    download_log.seed_requests(log)

    def test_bootstrap_does_not_change_existing_command_transport(self):
        root = cache.HERE.parent
        workflow = (root / '.github/workflows/seed-release-cache.yml').read_text()
        docs = (root / '.github/workflows/docs.yml').read_text()
        self.assertNotIn('SITE_RELEASE_CACHE', docs)
        self.assertNotIn('needs: release-cache', docs)
        self.assertEqual(docs.count("go-version: '1.26.10'"), 2)
        self.assertIn('if: success()', docs)
        self.assertIn('retention-days: 7', docs)
        self.assertIn('include-hidden-files: false', docs)
        self.assertNotIn('if: always()', docs)
        self.assertNotIn('site-examples-evidence-', docs)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn("github.ref_protected", workflow)
        self.assertNotIn('github-token:', workflow)
        self.assertNotIn('actions: read', workflow)
        self.assertNotIn('secrets.', workflow)
        self.assertNotIn('continue-on-error', workflow)
        self.assertNotIn('restore-keys:', workflow)
        self.assertIn('fail-on-cache-miss: true', workflow)
        self.assertIn('test "$EXACT_HIT" = true', workflow)
        self.assertIn('artifact-ids: ${{ needs.seed.outputs.artifact_id }}', workflow)


if __name__ == '__main__':
    unittest.main()
