# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check native page contracts; opt in to a real cached PostgreSQL fixture."""
import csv
from datetime import datetime, timedelta, timezone
import hashlib
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
        security = (ROOT / "pages/security.html").read_text()
        for text in ("0600", "symlink", "effective user", "exactly one", "sslmode=verify-full",
                     "sslrootcert", "numeric loopback", "pgpass", "PG*", "shell history",
                     "two adjacent seven-day periods", "ending at today's UTC midnight", "NEWDIR"):
            self.assertIn(text, security)
        self.assertIn('data-sql="litellm-reader-grants"', spend)
        self.assertIn('data-sql="litellm-daily-grants"', spend)
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

    def test_daily_page_documents_additional_grants_and_private_connection(self):
        source = (ROOT / "pages/row-coverage.html").read_text()
        for text in ("SELECT (date, api_requests, successful_requests, failed_requests)",
                     'public."LiteLLM_DailyUserSpend"', 'data-sql="row-coverage-daily-grants"',
                     "litellm-spend.html#access", "litellm-spend.html#run", "security.html"):
            self.assertIn(text, source)
        security = (ROOT / "pages/security.html").read_text()
        for text in ("0600", "0700", "effective user", "symlink", "sslmode=verify-full",
                     "sslrootcert", "numeric loopback", "exactly one", "two adjacent seven-day periods",
                     "FLEETDIFF_LITELLM_DATABASE_URL</code> unset", "--keep-export NEWDIR",
                     "last 14 complete UTC days", "16 days"):
            self.assertIn(text, security)
        grants = own_data.page_native_grants("row-coverage")
        self.assertEqual([b["id"] for b in grants], ["litellm-reader-grants", "row-coverage-daily-grants"])
        self.assertEqual(grants[0], own_data.page_blocks("litellm-spend").sql[0])
        self.assertEqual(grants[1], own_data.page_blocks("row-coverage").sql[0])

    def test_native_file_native_order_preserves_both_fixture_versions(self):
        for slug in ("routing", "row-coverage"):
            with self.subTest(page=slug), tempfile.TemporaryDirectory() as directory:
                fresh = Path(directory)
                day = "01" if slug == "routing" else "07"
                spend = ("request_id,startTime,endTime,spend,attempted_fallbacks\r\n"
                         f"first,2026-10-{day}T12:00:00Z,2026-10-{day}T12:00:01Z,0.001,0\r\n").encode()
                daily = b"date,api_requests,successful_requests,failed_requests\r\n2026-10-07,9,8,1\r\n"
                (fresh / "spend.csv").write_bytes(spend)
                if slug == "row-coverage":
                    (fresh / "daily.csv").write_bytes(daily)
                env = {"HOME": str(fresh), "ROUTE": "SENTINEL_route"}
                original_env = dict(env)
                end, variants = own_data.database_fixture_variants(
                    fresh, env, slug, datetime(2030, 2, 15, 23, 59, tzinfo=timezone.utc))
                self.assertEqual(env, original_env)
                self.assertEqual(end.date().isoformat(), "2030-02-15")
                for mode in ("native", "file", "native", "file"):
                    files, selected_env = variants[mode]
                    for name, data in files.items():
                        (fresh / name).write_bytes(data)
                    self.assertEqual(selected_env["ROUTE"], env["ROUTE"])
                    if mode == "file":
                        self.assertEqual((fresh / "spend.csv").read_bytes(), spend)
                        if slug == "routing":
                            self.assertEqual(selected_env["BEFORE"], "2026-10-01")
                            self.assertEqual(selected_env["AFTER"], "2026-10-02")
                            self.assertEqual(selected_env["EXPORT_AFTER"], "2026-10-03T00:00:00Z")
                        else:
                            self.assertEqual((fresh / "daily.csv").read_bytes(), daily)
                            self.assertEqual(selected_env["EXPORT_BEFORE"], own_data.EXPORT_START)
                            self.assertEqual(selected_env["EXPORT_AFTER"], own_data.EXPORT_END)
                    else:
                        self.assertNotIn(b"2026-10-", (fresh / "spend.csv").read_bytes())
                        self.assertEqual(selected_env["BEFORE"], "2030-02-01")
                        self.assertEqual(selected_env["AFTER"], "2030-02-08")
                        if slug == "row-coverage":
                            self.assertIn(b"2030-02-13,9,8,1", (fresh / "daily.csv").read_bytes())

    def test_daily_dates_move_with_spend_without_changing_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            fresh = Path(directory)
            (fresh / "spend.csv").write_text(
                "request_id,startTime,endTime,spend\n"
                "last,2026-10-08T23:00:00Z,2026-10-08T23:00:01Z,0.002\n"
                "cross,2026-10-07T23:59:59.000Z,2026-10-08T00:00:01.000Z,0.003\n")
            (fresh / "daily.csv").write_text(
                "date,api_requests,successful_requests,failed_requests\n"
                "2026-10-07,9,8,1\n2026-10-08,1,1,0\n")
            env = {}
            end = own_data.refresh_database_dates(fresh, env, "row-coverage",
                                                   datetime(2030, 2, 15, 23, 59, tzinfo=timezone.utc))
            with (fresh / "spend.csv").open() as handle:
                spend = list(csv.DictReader(handle))
            with (fresh / "daily.csv").open() as handle:
                daily = list(csv.DictReader(handle))
            self.assertEqual([row["date"] for row in daily], ["2030-02-13", "2030-02-14"])
            self.assertEqual(spend[0]["startTime"], daily[-1]["date"] + "T23:00:00Z")
            self.assertEqual(spend[0]["endTime"], daily[-1]["date"] + "T23:00:01Z")
            self.assertEqual(spend[0]["spend"], "0.002")
            self.assertEqual(spend[1]["startTime"], "2030-02-13T23:59:59.000Z")
            self.assertEqual(spend[1]["endTime"], "2030-02-14T00:00:01.000Z")
            self.assertEqual(spend[1]["spend"], "0.003")
            self.assertEqual([(r["api_requests"], r["successful_requests"], r["failed_requests"]) for r in daily],
                             [("9", "8", "1"), ("1", "1", "0")])
            self.assertEqual(env["EXPORT_BEFORE"], (end - timedelta(days=16)).isoformat())
            self.assertEqual(env["EXPORT_AFTER"], end.isoformat())

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
            self.assertEqual(env["BEFORE"], "2030-02-01")
            self.assertEqual(env["AFTER"], "2030-02-08")

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
        for slug in ("litellm-spend", "routing", "row-coverage"):
            with self.subTest(page=slug), tempfile.TemporaryDirectory(prefix="site-db-test-") as directory:
                fresh = Path(directory).resolve()
                env = own_data.environment(fresh)
                own_data.prepare(fresh, source, env, slug)
                own_data.refresh_database_dates(fresh, env, slug, datetime.now(timezone.utc))
                with own_data.database(fresh, source, env, coverage=slug == "row-coverage",
                                       routing=slug == "routing", native=True,
                                       sql_blocks=own_data.page_native_grants(slug)) as db_env:
                    credential = Path(db_env["DATABASE_URL_FILE"])
                    self.assertEqual(credential, fresh / ".config/litellm-db-url")
                    self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
                    url = urlsplit(credential.read_text().strip())
                    self.assertEqual(url.path, "/litellm")
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
                self.assertEqual(evidence["database"], "litellm")
                self.assertEqual(evidence["column_select_privileges"]["messages"], "f")
                self.assertEqual(evidence["column_select_privileges"]["response"], "f")
                self.assertEqual(evidence["column_select_privileges"]["proxy_server_request"], "f")
                self.assertEqual(evidence["role_restrictions"], "litellm|" + "|".join(["f"] * 12))
                if slug in {"litellm-spend", "row-coverage"}:
                    self.assertEqual(evidence["daily_readonly_identity"], "t|t|t|t|f|f")
                    self.assertEqual([(b["block"], b["command_sha256"]) for b in evidence["sql_blocks"]],
                        [(b["id"], hashlib.sha256(b["text"].encode()).hexdigest()) for b in own_data.page_native_grants(slug)])
                if slug == "row-coverage":
                    self.assertEqual(evidence["daily_readonly_identity"], "t|t|t|t|f|f")
                    self.assertEqual(evidence["daily_fixture_sha256"],
                                     hashlib.sha256((fresh / "daily.csv").read_bytes()).hexdigest())

    def test_daily_grants_are_opt_in_and_match_released_column_grants(self):
        source = Path(os.environ["SITE_POSTGRES_SOURCE"]).resolve(strict=True)
        spend = own_data.native_grants(source)
        daily = own_data.native_grants(source, daily=True)
        self.assertNotIn("LiteLLM_DailyUserSpend", spend)
        self.assertIn("CONNECT ON DATABASE litellm", spend)
        self.assertNotIn("CONNECT ON DATABASE fixture", spend)
        self.assertTrue(daily.startswith(spend))
        self.assertEqual(daily[len(spend):].strip(),
                         'GRANT SELECT (date, api_requests, successful_requests, failed_requests)\n'
                         '  ON TABLE public."LiteLLM_DailyUserSpend" TO fleetdiff_reader;')


@unittest.skipUnless(os.environ.get("SITE_POSTGRES_SOURCE") and os.environ.get("SITE_FLEETDIFF_BINARY"),
                     "set SITE_POSTGRES_SOURCE and SITE_FLEETDIFF_BINARY for the real native daily command")
class NativeDailyCommandTests(unittest.TestCase):
    def test_exact_page_command_with_released_binary_and_real_daily_database(self):
        source = Path(os.environ["SITE_POSTGRES_SOURCE"]).resolve(strict=True)
        binary = Path(os.environ["SITE_FLEETDIFF_BINARY"]).resolve(strict=True)
        binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
        blocks = Blocks()
        blocks.feed((ROOT / "pages/row-coverage.html").read_text())
        command = next(b["text"] for b in blocks.own if b["id"] == "row-coverage-native")
        with tempfile.TemporaryDirectory(prefix="site-native-daily-") as directory:
            fresh = Path(directory).resolve()
            env = own_data.environment(fresh)
            own_data.prepare(fresh, source, env, "row-coverage")
            end = own_data.refresh_database_dates(fresh, env, "row-coverage", datetime.now(timezone.utc))
            (fresh / "bin").mkdir()
            installed = fresh / "bin/fleetdiff"
            shutil.copyfile(binary, installed)
            installed.chmod(0o700)
            version = own_data.run([str(installed), "--version"], cwd=fresh, env=env)
            self.assertEqual(version.split()[:3], ["fleetdiff", own_data.FIXTURE_VERSION,
                                                  "(" + own_data.FIXTURE_COMMIT + ")"])
            with own_data.database(fresh, source, env, coverage=True, native=True,
                                   sql_blocks=own_data.page_native_grants("row-coverage")) as db_env:
                db_env.pop("FLEETDIFF_LITELLM_DATABASE_URL")
                before_files = set(fresh.iterdir())
                result = subprocess.run(["bash", "-e", "-c", command], cwd=fresh,
                                        env=db_env, text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(set(fresh.iterdir()), before_files, "temporary export was not removed")
                self.assertEqual(datetime.now(timezone.utc).date(), end.date(), "UTC day changed; rerun")
                for excerpt in own_data.EXPECTED["row-coverage-native"]:
                    self.assertIn(excerpt, result.stdout)
                missing_day = (end - timedelta(days=2)).date().isoformat()
                matching_day = (end - timedelta(days=1)).date().isoformat()
                self.assertIn(missing_day + " UTC: 8 exported rows; 9 daily requests", result.stdout)
                self.assertIn(matching_day + " UTC: 1 exported row; 1 daily request", result.stdout)
                with (fresh / "spend.csv").open() as handle:
                    for row in csv.DictReader(handle):
                        if row["api_key"]:
                            self.assertNotIn(row["api_key"], result.stdout + result.stderr)
                self.assertNotIn("postgresql://", result.stdout + result.stderr)
            evidence = json.loads((fresh / "database-evidence.json").read_text())
            self.assertEqual(evidence["daily_readonly_identity"], "t|t|t|t|f|f")
            self.assertGreater(evidence["transport"]["server_bytes"], 0)
            self.assertEqual(hashlib.sha256(installed.read_bytes()).hexdigest(), binary_hash)
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), binary_hash)


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
        investigate = next(b["text"] for b in blocks.own if b["id"] == "litellm-export-file")
        bounds = dict(line.split("=", 1) for line in export.splitlines()
                      if line.startswith(("BEFORE=", "AFTER=")))
        start = datetime.fromisoformat(bounds["BEFORE"].replace("Z", "+00:00"))
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
                for first, rows, status in ((bounds["BEFORE"], 160, 0),
                                             ((start + timedelta(days=2)).isoformat(), 140, 1)):
                    with self.subTest(start=first, expected_rows=rows):
                        exported = subprocess.run(["psql", "service=litellm_readonly", "-Xq", "-v", "ON_ERROR_STOP=1",
                            "-v", "start_utc=" + first, "-v", "end_utc=" + bounds["AFTER"],
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
