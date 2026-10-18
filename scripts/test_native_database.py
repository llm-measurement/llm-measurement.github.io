# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check native page contracts; opt in to a real cached PostgreSQL fixture."""
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import struct
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from outsider import ROOT, Blocks
import own_data


class NativeDatabaseTests(unittest.TestCase):
    def test_ci_preloads_the_recorded_release_source_image(self):
        manifest = json.loads((ROOT / "evidence/own-data-verified.json").read_text())
        self.assertEqual(manifest["fixture_source"], own_data.FIXTURE_COMMIT)
        images = {r["database"]["postgres"] for r in manifest["results"]
                  if r["block"] in own_data.NATIVE_BLOCKS}
        self.assertEqual(len(images), 1)
        image = images.pop()
        self.assertRegex(image, r"^postgres@sha256:[0-9a-f]{64}$")
        workflow = (ROOT / ".github/workflows/docs.yml").read_text().split("\n  own-data:\n", 1)[1]
        pulls = [line.strip().removeprefix("- run: ") for line in workflow.splitlines()
                 if line.strip().startswith("- run: docker pull ")]
        self.assertEqual([shlex.split(command) for command in pulls], [["docker", "pull", image]])
        self.assertIn("fleetdiff/" + own_data.FIXTURE_COMMIT + "/examples/litellm-spend/images.json", workflow)
        self.assertLess(workflow.index(pulls[0]), workflow.index("python3 scripts/check.py --own-data"))
        self.assertIn(pulls[0], (ROOT / "README.md").read_text())

    def test_native_blocks_are_all_checked_as_database_commands(self):
        actual = set()
        for slug in own_data.PAGES:
            blocks = Blocks()
            blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
            for block in blocks.own:
                if "--litellm-db" in block["text"]:
                    actual.add(block["id"])
                    self.assertNotIn("--litellm-spend", block["text"])
                    self.assertNotIn("postgres://", block["text"])
                    self.assertNotIn("postgresql://", block["text"])
        self.assertEqual(actual, own_data.NATIVE_BLOCKS)

    def test_credentials_and_network_boundary_are_explicit(self):
        spend = (ROOT / "pages/litellm-spend.html").read_text()
        for text in ("0600", "symlink", "effective user", "exactly one", "sslmode=verify-full",
                     "sslrootcert", "numeric loopback", "pgpass", "PG*", "shell history",
                     "last 14 complete UTC days", "administrator action", "NEWDIR"):
            self.assertIn(text, spend)
        security = (ROOT / "pages/security.html").read_text()
        self.assertIn("File-based analysis", security)
        self.assertIn("Only explicit", security)
        self.assertNotIn("makes no network connections during analysis", security)
        for path in ("internal/cli/network_test.go", "internal/postgres/tls_test.go",
                     "examples/litellm-spend/test_native_export.py"):
            self.assertIn("fleetdiff/blob/v0.12.0/" + path, security)

    def test_secret_environment_does_not_leak_into_fixture(self):
        with patch.dict(os.environ, {"FLEETDIFF_LITELLM_DATABASE_URL": "not-a-real-secret",
                                     "DATABASE_URL_FILE": "/not-a-real-file"}):
            env = own_data.environment(Path("/fixture"))
        self.assertNotIn("FLEETDIFF_LITELLM_DATABASE_URL", env)
        self.assertNotIn("DATABASE_URL_FILE", env)

    def test_routing_dates_follow_utc_windows_without_changing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            fresh = Path(directory)
            fixture = ("request_id,startTime,endTime,spend,attempted_fallbacks\n"
                       "before,2026-10-01T12:00:00Z,2026-10-01T12:00:01Z,0.001,0\n"
                       "after,2026-10-02T12:00:00Z,2026-10-02T12:00:01Z,0.002,\n")
            (fresh / "spend.csv").write_text(fixture)
            env = {}
            now = datetime(2030, 2, 15, 23, 59, tzinfo=timezone.utc)
            end = own_data.refresh_database_dates(fresh, env, "routing", now)
            self.assertEqual(end.isoformat(), "2030-02-15T00:00:00+00:00")
            with (fresh / "spend.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([r["startTime"] for r in rows],
                             ["2030-02-01T12:00:00Z", "2030-02-08T12:00:00Z"])
            self.assertEqual([r["spend"] for r in rows], ["0.001", "0.002"])
            self.assertEqual([r["attempted_fallbacks"] for r in rows], ["0", ""])
            self.assertEqual(env["BEFORE_PERIOD_UTC"], "2030-02-01")
            self.assertEqual(env["AFTER_PERIOD_UTC"], "2030-02-08")

    def test_missing_cached_image_fails_without_pull_or_stub(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "examples/litellm-spend").mkdir(parents=True)
            image = "postgres@sha256:" + "a" * 64
            (root / "examples/litellm-spend/images.json").write_text(json.dumps({"postgres": image}))
            with patch.object(own_data, "run", side_effect=RuntimeError("image absent")) as run:
                with self.assertRaisesRegex(RuntimeError, "image absent"):
                    with own_data.database(root, root, {"DOCKER_HOST": "unix:///test"}, native=True):
                        self.fail("must never replace the database with a stand-in")
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0], ["docker", "image", "inspect", image])


@unittest.skipUnless(os.environ.get("SITE_POSTGRES_SOURCE"),
                     "set SITE_POSTGRES_SOURCE for real cached network-none PostgreSQL checks")
class RealPostgresFixtureTests(unittest.TestCase):
    def test_ci_image_pin_matches_actual_released_fixture_source(self):
        source = Path(os.environ["SITE_POSTGRES_SOURCE"]).resolve(strict=True)
        image = json.loads((source / "examples/litellm-spend/images.json").read_text())["postgres"]
        workflow = (ROOT / ".github/workflows/docs.yml").read_text().split("\n  own-data:\n", 1)[1]
        self.assertIn("- run: docker pull " + image + "\n", workflow)

    def test_documented_role_credentials_and_real_postgres_transport(self):
        source = Path(os.environ["SITE_POSTGRES_SOURCE"]).resolve(strict=True)
        for slug in ("litellm-spend", "routing"):
            with self.subTest(page=slug), tempfile.TemporaryDirectory(prefix="site-db-test-") as directory:
                fresh = Path(directory).resolve()
                env = own_data.environment(fresh)
                own_data.prepare(fresh, source, env, slug)
                own_data.refresh_database_dates(fresh, env, slug, datetime.now(timezone.utc))
                with own_data.database(fresh, source, env, routing=slug == "routing", native=True) as db_env:
                    credential = Path(db_env["DATABASE_URL_FILE"])
                    self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
                    url = urlsplit(credential.read_text().strip())
                    # A real PostgreSQL SSLRequest. No fake protocol responses.
                    with socket.create_connection((url.hostname, url.port), timeout=10) as client:
                        client.sendall(struct.pack("!II", 8, 80877103))
                        self.assertEqual(client.recv(1), b"N")
                self.assertFalse(credential.exists())
                evidence = json.loads((fresh / "database-evidence.json").read_text())
                self.assertEqual(evidence["network"], "none")
                self.assertEqual(evidence["readonly_identity"], "fleetdiff_reader|on|t|f|f|f")
                self.assertEqual(evidence["transport"]["connections"], 1)
                self.assertFalse(evidence["transport"]["errors"])


@unittest.skipUnless(os.environ.get("SITE_POSTGRES_SOURCE") and os.environ.get("SITE_FLEETDIFF_BINARY"),
                     "set SITE_POSTGRES_SOURCE and SITE_FLEETDIFF_BINARY for the real manual-bounds regression")
class ManualSpendBoundsTests(unittest.TestCase):
    def test_documented_bounds_succeed_and_fourteen_file_days_fail(self):
        """Local SQL/binary probe, not installer or published-release evidence."""
        source = Path(os.environ["SITE_POSTGRES_SOURCE"]).resolve(strict=True)
        binary = Path(os.environ["SITE_FLEETDIFF_BINARY"]).resolve(strict=True)
        blocks = Blocks()
        blocks.feed((ROOT / "pages/litellm-spend.html").read_text())
        export = next(b["text"] for b in blocks.own if b["id"] == "spend-export")
        investigate = next(b["text"] for b in blocks.own if b["id"] == "litellm-spend")
        bounds = dict(line.split("=", 1) for line in export.splitlines()
                      if line.startswith(("START_UTC=", "END_UTC=")))
        start = datetime.fromisoformat(bounds["START_UTC"].replace("Z", "+00:00"))
        with tempfile.TemporaryDirectory(prefix="site-manual-bounds-") as directory:
            fresh = Path(directory).resolve()
            env = own_data.environment(fresh)
            own_data.prepare(fresh, source, env, "litellm-spend")
            (fresh / "bin").mkdir()
            shutil.copyfile(binary, fresh / "bin/fleetdiff")
            (fresh / "bin/fleetdiff").chmod(0o700)
            shutil.copyfile(source / "examples/litellm-spend/export.sql", fresh / "export.sql")
            (fresh / "litellm-export").mkdir(mode=0o700)
            with own_data.database(fresh, source, env) as db_env:
                for first, rows, status in ((bounds["START_UTC"], 160, 0),
                                             ((start + timedelta(days=2)).isoformat(), 140, 1)):
                    with self.subTest(start=first, expected_rows=rows):
                        exported = subprocess.run(["psql", "service=litellm_readonly", "-Xq", "-v", "ON_ERROR_STOP=1",
                            "-v", "start_utc=" + first, "-v", "end_utc=" + bounds["END_UTC"],
                            "-v", "csv_file=./litellm-export/spend.csv", "-f", "export.sql"],
                            cwd=fresh, env=db_env, text=True, capture_output=True, timeout=30)
                        self.assertEqual(exported.returncode, 0, exported.stderr)
                        with (fresh / "litellm-export/spend.csv").open() as handle:
                            self.assertEqual(len(list(csv.DictReader(handle))), rows)
                        result = subprocess.run(["bash", "-e", "-c", investigate], cwd=fresh,
                                                env=env, text=True, capture_output=True, timeout=30)
                        self.assertEqual(result.returncode, status, result.stderr)
                        if status == 0:
                            self.assertIn("Logged model requests: 70 -> 70.", result.stdout)


if __name__ == "__main__":
    unittest.main()
