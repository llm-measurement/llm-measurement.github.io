# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Keep runnable own-data instructions separate from sample output."""
import hashlib
from datetime import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from outsider import Blocks, ROOT
import own_data
from own_data import EXPECTED, PAGES, FIXTURE_COMMIT, FIXTURE_URL, refresh_history


class OwnDataTests(unittest.TestCase):
    def test_session_review_uses_the_released_binary_without_a_required_period(self):
        source = (ROOT / "pages/session-budget.html").read_text()
        blocks = Blocks()
        blocks.feed(source)
        self.assertEqual([block["id"] for block in blocks.own], ["session-budget"])
        self.assertEqual(len(blocks.commands), 1)
        for command in (blocks.own[0]["text"], blocks.commands[0]["text"]):
            self.assertIn("--session-budget-usd 1.00", command)
            self.assertIn("v0.12.0", command)
            self.assertNotIn("--period", command)
            self.assertNotIn("go run", command)
        self.assertGreaterEqual(len(blocks.expected), 5)
        self.assertNotIn("Redis", source)

    def test_litellm_native_path_precedes_manual_export(self):
        blocks = Blocks()
        blocks.feed((ROOT / "pages/litellm-spend.html").read_text())
        self.assertEqual([b["id"] for b in blocks.own],
                         ["litellm-install", "litellm-native", "litellm-native-env", "spend-export", "litellm-spend"])
        self.assertIn("--litellm-db", blocks.own[1]["text"])
        self.assertIn('--database-url-file "${DATABASE_URL_FILE:', blocks.own[1]["text"])
        self.assertNotIn("--database-url-file", blocks.own[2]["text"])
        self.assertIn("./litellm-export/spend.csv", blocks.own[3]["text"])
        self.assertIn("./litellm-export/spend.csv", blocks.own[4]["text"])

    def test_manual_spend_example_uses_its_visible_sixteen_day_bounds(self):
        blocks = Blocks()
        source = (ROOT / "pages/litellm-spend.html").read_text()
        blocks.feed(source)
        command = next(b["text"] for b in blocks.own if b["id"] == "spend-export")
        assignments = dict(line.split("=", 1) for line in command.splitlines()
                           if line.startswith(("START_UTC=", "END_UTC=")))
        self.assertEqual(assignments, {"START_UTC": own_data.EXPORT_START, "END_UTC": own_data.EXPORT_END})
        start, end = (datetime.fromisoformat(assignments[name].replace("Z", "+00:00"))
                      for name in ("START_UTC", "END_UTC"))
        self.assertEqual((end - start).days, 16)
        self.assertIn("excludes potentially partial first and last days", source)
        self.assertIn("last 14 complete UTC days", source)
        native = next(b["text"] for b in blocks.own if b["id"] == "litellm-native")
        self.assertNotIn("--before-period", native)
        self.assertNotIn("--after-period", native)

    def test_slow_install_does_not_expire_the_scan_standin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(30):
                start = index * 60 * 1_000_000_000
                window = {"window_start_unix_nano": start, "observed_start_unix_nano": start,
                    "observed_end_unix_nano": start + 60 * 1_000_000_000,
                    "emitted_at_unix_nano": start + 60 * 1_000_000_000,
                    "counters": {"requests": 100}}
                (root / f"{index:02}.json").write_text(json.dumps(window))
            for now in (2000, 2181, 5600):
                refresh_history(root, now)
                windows = [json.loads(p.read_text()) for p in sorted(root.glob("*.json"))]
                self.assertEqual(windows[-1]["observed_end_unix_nano"], now // 60 * 60 * 1_000_000_000)
                self.assertEqual(windows[0]["observed_end_unix_nano"], windows[-1]["observed_end_unix_nano"] - 29 * 60 * 1_000_000_000)
                for window in windows:
                    self.assertEqual(window["counters"], {"requests": 100})
                self.assertEqual((root / "00.json").read_text(), json.dumps(windows[0], sort_keys=True, separators=(",", ":")))

    def test_extracts_decoded_commands_and_expected_status(self):
        blocks = Blocks()
        blocks.feed('<pre data-own="x" data-exit="3"><code>cmd &gt; out</code></pre>'
                    '<pre data-run="x" data-exit="0">sample</pre>'
                    '<pre data-output="x">answer</pre>'
                    '<pre data-review="r">verify</pre>')
        self.assertEqual(blocks.own, [{"id": "x", "text": "cmd > out", "exit": 3}])
        self.assertEqual(blocks.commands, [{"text": "sample", "exit": 0}])
        self.assertEqual(blocks.expected, [{"text": "answer"}])
        self.assertEqual(blocks.review, [{"id": "r", "text": "verify", "exit": 0}])

    def test_all_real_data_commands_have_runtime_expectations(self):
        ids = []
        for slug in PAGES:
            blocks = Blocks()
            blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
            self.assertTrue(blocks.own, slug)
            for block in blocks.own:
                self.assertNotIn("git clone", block["text"], slug)
                ids.append(block["id"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(EXPECTED))

    def test_environment_is_pure_fresh_and_credential_free(self):
        ambient = {"HOME": "/private-user", "PATH": "/tools:/usr/bin", "DOCKER_HOST": "unix:///test/docker.sock",
                   "GH_TOKEN": "test-only", "GITHUB_TOKEN": "test-only", "OPENAI_API_KEY": "test-only",
                   "DOCKER_AUTH_CONFIG": "test-only", "DOCKER_CONTEXT": "private-context",
                   "PYTHONPATH": "/private-python", "PGPASSWORD": "test-only", "PIP_INDEX_URL": "private-index"}
        with patch.dict(os.environ, ambient, clear=True), patch.object(Path, "mkdir", side_effect=AssertionError("filesystem access")), \
                patch.object(own_data.subprocess, "run", side_effect=AssertionError("subprocess access")):
            env = own_data.environment(Path("/test/fresh"))
        self.assertEqual(env["HOME"], "/test/fresh")
        self.assertEqual(env["XDG_CACHE_HOME"], "/test/fresh/cache")
        self.assertEqual(env["GH_CONFIG_DIR"], "/test/fresh/gh")
        self.assertEqual(env["DOCKER_HOST"], ambient["DOCKER_HOST"])
        self.assertEqual(env["DOCKER_CONFIG"], "/test/fresh/docker")
        self.assertEqual(env["GOPROXY"], "https://proxy.golang.org")
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "DOCKER_AUTH_CONFIG", "DOCKER_CONTEXT", "PYTHONPATH", "PGPASSWORD"):
            self.assertNotIn(name, env)

    @staticmethod
    def source_archive(extra=None):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name in ("go.mod", "examples/litellm-spend/export.sql"):
                member = tarfile.TarInfo("fleetdiff-" + FIXTURE_COMMIT + "/" + name)
                data = b"unit-test fixture\n"
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if extra is not None:
                archive.addfile(extra)
        return buffer.getvalue()

    def test_anonymous_archive_is_commit_bound_and_records_inventory(self):
        data = self.source_archive()
        with tempfile.TemporaryDirectory() as directory, patch.object(own_data.urllib.request, "build_opener") as opener, \
                patch.object(own_data, "run", side_effect=AssertionError("no Git or setup commands")):
            opener.return_value.open.return_value = io.BytesIO(data)
            source, provenance = own_data.fixture_source(Path(directory))
            self.assertEqual(source.name, "fleetdiff-" + FIXTURE_COMMIT)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, FIXTURE_URL)
            self.assertIn(FIXTURE_COMMIT, request.full_url)
            self.assertNotIn("Authorization", request.headers)
            self.assertEqual(provenance["expected_commit"], FIXTURE_COMMIT)
            self.assertEqual(provenance["version"], "v0.12.0")
            self.assertEqual(provenance["archive_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(set(provenance["files"]), {"go.mod", "examples/litellm-spend/export.sql"})
            self.assertFalse(provenance["git_operations"])

    def test_archive_refuses_wrong_commit_paths_links_and_special_files(self):
        prefix = "fleetdiff-" + FIXTURE_COMMIT
        for name, kind in [("fleetdiff-wrong/go.mod", tarfile.REGTYPE),
                           (prefix + "/../../outside", tarfile.REGTYPE),
                           ("/outside", tarfile.REGTYPE), (prefix + "/link", tarfile.SYMTYPE),
                           (prefix + "/hardlink", tarfile.LNKTYPE), (prefix + "/pipe", tarfile.FIFOTYPE),
                           (prefix + "/.git/config", tarfile.REGTYPE)]:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                member = tarfile.TarInfo(name)
                member.type = kind
                archive = root / "source.tar.gz"
                archive.write_bytes(self.source_archive(member))
                with self.assertRaises(AssertionError):
                    own_data.extract_fixture(archive, root)
                self.assertFalse((root / prefix).exists())

    def test_python_311_requires_backported_data_filter_before_download(self):
        with patch.object(own_data.tarfile, "data_filter", None), \
                patch.object(own_data.urllib.request, "build_opener", side_effect=AssertionError("network access")):
            with self.assertRaisesRegex(RuntimeError, "data filter"):
                own_data.fixture_source(Path("/not-created"))

    def test_public_manifest_keeps_full_source_inventory_private(self):
        provenance = {"version": "v0.12.0", "expected_commit": FIXTURE_COMMIT, "url": FIXTURE_URL,
                      "archive_sha256": "a" * 64, "source_sha256": "b" * 64, "files": {"test": "c" * 64}}
        with tempfile.TemporaryDirectory() as directory, patch.object(own_data, "PAGES", ()), \
                patch.object(own_data, "fixture_source", return_value=(Path(directory), provenance)):
            output = Path(directory) / "evidence"
            own_data.check(output)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["fixture_source"], FIXTURE_COMMIT)
            self.assertNotIn("files", manifest["fixture_archive"])
            self.assertEqual(manifest["fixture_archive"]["file_count"], 1)
            self.assertEqual(json.loads((output / "fixture-provenance.json").read_text())["files"], provenance["files"])

    def test_installed_binary_requires_exact_release_and_commit_with_build_metadata(self):
        for version, accepted in (
            ("fleetdiff v0.12.0 (" + FIXTURE_COMMIT + ") go1.26.9 darwin/arm64", True),
            ("fleetdiff v0.12.0 (" + "0" * 40 + ") go1.26.9 darwin/arm64", False),
            ("fleetdiff v0.11.0 (" + FIXTURE_COMMIT + ") go1.26.9 darwin/arm64", False),
            ("fleetdiff dev (unknown) go1.26.9 darwin/arm64", False),
        ):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "pages").mkdir()
                (root / "pages/test.html").write_text(
                    '<pre data-own="test-install" data-exit="0">sh install-fleetdiff.sh v0.12.0 ./bin</pre>')
                provenance = {"files": {}}
                result = subprocess.CompletedProcess([], 0, stdout="Verified", stderr="")
                with patch.object(own_data, "ROOT", root), patch.object(own_data, "PAGES", ("test",)), \
                        patch.object(own_data, "EXPECTED", {"test-install": ("Verified",)}), \
                        patch.object(own_data, "fixture_source", return_value=(root, provenance)), \
                        patch.object(own_data, "prepare"), patch.object(own_data.subprocess, "run", return_value=result), \
                        patch.object(own_data, "run", return_value=version):
                    if accepted:
                        own_data.check(root / "evidence")
                        recorded = json.loads((root / "evidence/manifest.json").read_text())["results"][0]
                        self.assertEqual(recorded["installed_version"], version)
                    else:
                        with self.assertRaises(AssertionError):
                            own_data.check(root / "evidence")

    def test_sql_export_comparison_normalizes_only_numeric_and_time_rendering(self):
        before = {"request_id": "test", "startTime": "2026-10-07T12:00:00Z",
                  "endTime": "2026-10-07T12:00:01Z", "spend": "0.0000036000", "cache_read_input_tokens": ""}
        after = dict(before, startTime="2026-10-07T12:00:00.000Z", endTime="2026-10-07T12:00:01.000Z", spend="3.6e-06")
        self.assertEqual(own_data.comparable_rows([before]), own_data.comparable_rows([after]))
        self.assertNotEqual(own_data.comparable_rows([before]), own_data.comparable_rows([dict(after, cache_read_input_tokens="0")]))

    def test_new_guides_use_paired_export_and_real_workload_mapping(self):
        coverage = Blocks()
        coverage.feed((ROOT / "pages/row-coverage.html").read_text())
        self.assertEqual([b["id"] for b in coverage.own],
                         ["row-coverage-install", "row-coverage-native", "row-coverage-export", "row-coverage"])
        self.assertIn("--litellm-db --daily", coverage.own[1]["text"])
        self.assertIn('--database-url-file "${DATABASE_URL_FILE:', coverage.own[1]["text"])
        self.assertIn('"${START_UTC:', coverage.own[2]["text"])
        self.assertIn('"${END_UTC:', coverage.own[2]["text"])
        self.assertIn("sh ./coverage-helper/export-coverage.sh ./litellm-coverage-export", coverage.own[2]["text"])
        self.assertIn("--litellm-daily-spend ./litellm-coverage-export/daily.csv", coverage.own[3]["text"])
        whatif = Blocks()
        whatif.feed((ROOT / "pages/what-if.html").read_text())
        self.assertEqual([b["id"] for b in whatif.own], ["what-if-install", "what-if-reprice", "what-if-workload-map"])
        self.assertIn("--workload-map ./workload-map.json --format json", whatif.own[2]["text"])

    def test_routing_uses_opt_in_export_and_explicit_scopes(self):
        blocks = Blocks()
        source = (ROOT / "pages/routing.html").read_text()
        blocks.feed(source)
        self.assertEqual([b["id"] for b in blocks.own],
                         ["routing-install", "routing-native", "routing-export", "routing-audit", "routing-agents", "routing-scope"])
        self.assertIn("--litellm-db", blocks.own[1]["text"])
        self.assertIn("--routing-audit", blocks.own[1]["text"])
        self.assertIn("-v routing_details=true", blocks.own[2]["text"])
        self.assertIn("'service=litellm_readonly'", blocks.own[2]["text"])
        self.assertIn("./routing-export/spend.csv", blocks.own[3]["text"])
        for block in blocks.own[3:]:
            self.assertIn('"${BEFORE_PERIOD_UTC:', block["text"])
            self.assertIn('"${AFTER_PERIOD_UTC:', block["text"])
            self.assertNotIn("--show-labels", block["text"])
        self.assertIn("--routing-by route-agent --format json", blocks.own[4]["text"])
        self.assertIn('--scope-route "${ORIGINAL_ROUTE:', blocks.own[5]["text"])
        for block in blocks.own[4:]:
            self.assertIn("--litellm-db", block["text"])
            self.assertIn("--database-url-file", block["text"])
        self.assertEqual(source.count("<h2>Limits</h2>"), 1)
        self.assertEqual(len(blocks.expected), 4)

    def test_routing_export_propagates_failure_without_shell_flags(self):
        blocks = Blocks()
        blocks.feed((ROOT / "pages/routing.html").read_text())
        command = next(b["text"] for b in blocks.own if b["id"] == "routing-export")
        for shell in ("sh", "bash"):
            for curl_status, psql_status in ((0, 0), (22, 0), (0, 42)):
                with self.subTest(shell=shell, curl=curl_status, psql=psql_status), tempfile.TemporaryDirectory() as directory:
                    stubs = f"curl() {{ return {curl_status}; }}\npsql() {{ return {psql_status}; }}\n"
                    result = subprocess.run([shell, "-c", stubs + command], cwd=directory,
                        env={"PATH": os.defpath, "START_UTC": "2026-10-01T00:00:00Z",
                             "END_UTC": "2026-10-03T00:00:00Z"},
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, curl_status or psql_status)
                    self.assertEqual("Exported routing details" in result.stdout,
                                     curl_status == psql_status == 0)

    def test_routing_database_preserves_zero_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "examples/litellm-spend").mkdir(parents=True)
            (root / "examples/litellm-spend/test-schema.sql").write_text("-- schema\n")
            (root / "spend.csv").write_text(
                "request_id,agent_id,original_model_group,attempted_fallbacks,internal_call_origin,cache_read_input_tokens,cache_write_input_tokens\n"
                "test,,SENTINEL_route,0,autorouter_classifier,0,\n")
            sql = own_data.database_sql(root, root, routing=True)
            self.assertIn('""original_model_group"": ""SENTINEL_route""', sql)
            self.assertIn('""attempted_fallbacks"": ""0""', sql)
            self.assertIn('""internal_call_origin"": ""autorouter_classifier""', sql)
            self.assertIn('""cache_read_input_tokens"": 0', sql)
            self.assertNotIn('""cache_creation_input_tokens"": 0', sql)
            self.assertIn("ALTER ROLE fixture_reader SET default_transaction_read_only = on", sql)
            self.assertNotIn("LiteLLM_DailyUserSpend", sql)

    def test_whatif_standin_preserves_cache_columns_and_workload_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, fresh = root / "source", root / "fresh"
            fresh.mkdir()
            for name in ("examples/inspect", "examples/diagnose", "examples/sessions/data/before",
                         "examples/sessions/data/after", "examples/what-if"):
                (source / name).mkdir(parents=True)
            (source / "examples/inspect/synthetic-traces.json").write_text("{}")
            (source / "examples/diagnose/unsafe.yaml").write_text("test: true")
            spend = "request_id,cache_read_input_tokens,cache_write_input_tokens,reasoning_output_tokens\ntest,8000,1000,0\n"
            mapping = '{"version":1,"mappings":[]}'
            (source / "examples/what-if/spend.csv").write_text(spend)
            (source / "examples/what-if/workload-map.json").write_text(mapping)
            env = {}
            with patch.object(own_data, "run"):
                own_data.prepare(fresh, source, env, "what-if")
            self.assertEqual((fresh / "spend.csv").read_text(), spend)
            self.assertEqual((fresh / "workload-map.json").read_text(), mapping)
            self.assertEqual(env["PERIOD_UTC"], "2026-10-07")

    def test_coverage_database_preserves_missing_details_and_recorded_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "examples/litellm-spend").mkdir(parents=True)
            (source / "examples/litellm-spend/test-schema.sql").write_text("-- schema\n")
            (root / "spend.csv").write_text("request_id,startTime,endTime,spend,reasoning_output_tokens,cache_read_input_tokens,cache_write_input_tokens\n"
                "stream,2026-10-07T12:00:00Z,2026-10-07T12:00:01Z,0,0,,\n")
            (root / "daily.csv").write_text("date,api_requests,successful_requests,failed_requests\n2026-10-07,9,8,1\n")
            sql = own_data.database_sql(root, source, coverage=True)
            self.assertIn('"metadata") FROM STDIN WITH CSV HEADER', sql)
            self.assertIn('""reasoning_tokens"": 0', sql)
            self.assertNotIn('""cache_read_input_tokens"": 0', sql)
            self.assertIn("ALTER ROLE fixture_reader SET default_transaction_read_only = on", sql)
            self.assertIn('GRANT SELECT ON public."LiteLLM_DailyUserSpend" TO fixture_reader', sql)
            self.assertIn("2026-10-07,9,8,1", sql)

    def test_sql_copy_payload_uses_lf_without_changing_fixture_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "examples/litellm-spend").mkdir(parents=True)
            (root / "examples/litellm-spend/test-schema.sql").write_text("-- schema\n")
            spend = b"request_id,spend\r\nrequest-1,0\r\n"
            daily = b"date,api_requests,successful_requests,failed_requests\r\n2026-10-07,9,8,1\r\n"
            (root / "spend.csv").write_bytes(spend)
            (root / "daily.csv").write_bytes(daily)
            sql = own_data.database_sql(root, root, coverage=True)
            self.assertNotIn("\r", sql)
            self.assertEqual(sql.count("\n\\.\n"), 2)
            self.assertEqual((root / "spend.csv").read_bytes(), spend)
            self.assertEqual((root / "daily.csv").read_bytes(), daily)

    def test_recorded_own_data_commands_match_page_sources(self):
        recorded = {r["block"]: r for r in json.loads(
            (ROOT / "evidence/own-data-verified.json").read_text())["results"]}
        for slug in PAGES:
            blocks = Blocks()
            blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
            for block in blocks.own:
                result = recorded[block["id"]]
                self.assertTrue(result["pass"])
                self.assertEqual(result["exit"], block["exit"])
                self.assertEqual(result["command_sha256"], hashlib.sha256(block["text"].encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
