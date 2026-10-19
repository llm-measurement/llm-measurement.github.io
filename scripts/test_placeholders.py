# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check simple published placeholders without changing executed shell text."""
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from guide_flow import GuideFlow
import own_data


class Paragraphs(GuideFlow):
    def handle_data(self, data):
        for node in self.stack:
            if node["tag"] == "p":
                node["text"] = node.get("text", "") + data


class PlaceholderTests(unittest.TestCase):
    def assert_plain_block(self, source, block_id, variables, explanation):
        parsed = Paragraphs()
        parsed.feed(source)
        node = next(n for n in parsed.nodes if n["attrs"].get("data-own") == block_id)
        siblings = [n for n in parsed.nodes if n["parents"] == node["parents"]]
        position = siblings.index(node)
        self.assertGreater(position, 0)
        previous = siblings[position - 1]
        self.assertEqual(previous["tag"], "p", block_id)
        paragraph = " ".join(previous.get("text", "").split())
        self.assertTrue(paragraph.startswith("Set "), (block_id, paragraph))
        self.assertIn(explanation, paragraph)
        from outsider import Blocks
        blocks = Blocks()
        blocks.feed(source)
        command = next(b["text"] for b in blocks.own if b["id"] == block_id)
        self.assertNotIn("$" + "{", command, block_id)
        self.assertEqual(set(re.findall(r"\$([A-Z][A-Z_0-9]*)", command)), set(variables))
        for variable in variables:
            self.assertIn('"$' + variable + '"', command, block_id)
            self.assertRegex(paragraph, r"\b" + variable + r"\b")
        self.assertNotRegex(command, r"\b(?:BEFORE_PERIOD_UTC|AFTER_PERIOD_UTC|ORIGINAL_ROUTE|PERIOD_UTC|START_UTC|END_UTC)\b")

    def test_all_changed_blocks_use_plain_names_and_adjacent_explanations(self):
        cases = {
            "litellm-spend": {"spend-export": (("BEFORE", "AFTER"), "16 days of RFC3339 UTC")},
            "routing": {
                "routing-scope": (("BEFORE", "AFTER", "ROUTE"), "comparison dates"),
                "routing-agents": (("BEFORE", "AFTER"), "comparison dates"),
                "routing-audit": (("BEFORE", "AFTER"), "comparison dates"),
                "routing-export": (("BEFORE", "AFTER"), "RFC3339 UTC bounds"),
                "routing-export-file": (("BEFORE", "AFTER"), "comparison dates"),
            },
            "row-coverage": {"row-coverage-export": (("BEFORE", "AFTER"), "16 days of RFC3339 UTC midnight")},
        }
        # PR1 intentionally retains the old what-if page until PR2.
        if "what-if-native" in own_data.NATIVE_BLOCKS:
            cases["what-if"] = {name: (("PERIOD",), "completed")
                               for name in ("what-if-native", "what-if-reprice", "what-if-workload-map")}
        for page, blocks in cases.items():
            source = (own_data.ROOT / "pages" / (page + ".html")).read_text()
            for block_id, (variables, explanation) in blocks.items():
                with self.subTest(page=page, block=block_id):
                    self.assert_plain_block(source, block_id, variables, explanation)

    def test_guarded_values_and_missing_adjacent_explanations_are_rejected(self):
        source = '<p>Set <code>BEFORE</code> and <code>AFTER</code> to comparison dates.</p>' \
                 '<pre data-own="probe" data-exit="0"><code>printf "%s" "$BEFORE" "$AFTER"</code></pre>'
        self.assert_plain_block(source, "probe", ("BEFORE", "AFTER"), "comparison dates")
        for changed in (
            source.replace("$BEFORE", "$" + "{BEFORE:?set a date}"),
            source.replace('<pre ', '<p>Unrelated paragraph.</p><pre '),
            source.replace('<code>BEFORE</code>', '<code>START</code>'),
        ):
            with self.subTest(source=changed), self.assertRaises(AssertionError):
                self.assert_plain_block(changed, "probe", ("BEFORE", "AFTER"), "comparison dates")


@unittest.skipUnless(os.environ.get("SITE_POSTGRES_SOURCE"),
                     "set SITE_POSTGRES_SOURCE for real cached PostgreSQL environment checks")
class ExportEnvironmentTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("SITE_FLEETDIFF_BINARY"),
                         "set SITE_FLEETDIFF_BINARY for released native/file routing checks")
    def test_native_scope_dates_and_file_audit_survive_manual_export(self):
        source = Path(os.environ["SITE_POSTGRES_SOURCE"]).resolve(strict=True)
        binary = Path(os.environ["SITE_FLEETDIFF_BINARY"]).resolve(strict=True)
        commands = {b["id"]: b["text"] for b in own_data.page_blocks("routing").own}
        with tempfile.TemporaryDirectory(prefix="site-routing-sequence-") as directory:
            fresh = Path(directory).resolve()
            env = own_data.environment(fresh)
            own_data.prepare(fresh, source, env, "routing")
            day, variants = own_data.database_fixture_variants(fresh, env, "routing", datetime.now(timezone.utc))
            (fresh / "bin").mkdir()
            shutil.copyfile(binary, fresh / "bin/fleetdiff")
            (fresh / "bin/fleetdiff").chmod(0o700)
            version = own_data.run([str(fresh / "bin/fleetdiff"), "--version"], cwd=fresh, env=env)
            self.assertEqual(version.split()[:3],
                             ["fleetdiff", own_data.FIXTURE_VERSION, "(" + own_data.FIXTURE_COMMIT + ")"])
            native_env = variants["native"][1]

            def execute(block, selected):
                result = subprocess.run(["bash", "-e", "-c", commands[block]],
                                        cwd=fresh, env=selected, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                for excerpt in own_data.EXPECTED[block]:
                    self.assertIn(excerpt, result.stdout)
                self.assertNotIn("SENTINEL_", result.stdout + result.stderr)
                return result.stdout

            with own_data.database(fresh, source, native_env, routing=True, native=True) as selected:
                selected.pop("FLEETDIFF_LITELLM_DATABASE_URL")
                self.assertEqual((selected["BEFORE"], selected["AFTER"]),
                                 (native_env["BEFORE"], native_env["AFTER"]))
                self.assertNotIn("T", selected["BEFORE"])
                self.assertNotIn("T", selected["AFTER"])
                before_files = set(fresh.iterdir())
                execute("routing-scope", selected)
                execute("routing-agents", selected)
                self.assertEqual(set(fresh.iterdir()), before_files)
                self.assertEqual(datetime.now(timezone.utc).date(), day.date())

            files, file_env = variants["file"]
            for name, data in files.items():
                (fresh / name).write_bytes(data)
            original = dict(file_env)
            reference = execute("routing-audit", file_env)
            shutil.copyfile(source / "examples/litellm-spend/export.sql", fresh / "export.sql")
            (fresh / "routing-export").mkdir(mode=0o700)
            with own_data.database(fresh, source, file_env, routing=True) as exported:
                self.assertEqual((exported["BEFORE"], exported["AFTER"]),
                                 ("2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z"))
                own_data.run(["psql", "service=litellm_readonly", "-Xq", "-v", "ON_ERROR_STOP=1",
                              "-v", "start_utc=" + exported["BEFORE"], "-v", "end_utc=" + exported["AFTER"],
                              "-v", "routing_details=true", "-v", "csv_file=./routing-export/spend.csv",
                              "-f", "export.sql"], cwd=fresh, env=exported)
                with (fresh / "routing-export/spend.csv").open() as handle:
                    self.assertEqual(len(list(csv.DictReader(handle))), 8)
            self.assertEqual(file_env, original)
            self.assertEqual((file_env["BEFORE"], file_env["AFTER"]), ("2026-10-01", "2026-10-02"))
            self.assertEqual(execute("routing-export-file", file_env), reference)

    def test_export_bounds_do_not_overwrite_investigation_dates(self):
        source = Path(os.environ["SITE_POSTGRES_SOURCE"]).resolve(strict=True)
        for slug in ("routing", "row-coverage"):
            with self.subTest(page=slug), tempfile.TemporaryDirectory(prefix="site-bound-env-") as directory:
                fresh = Path(directory).resolve()
                env = own_data.environment(fresh)
                own_data.prepare(fresh, source, env, slug)
                _, variants = own_data.database_fixture_variants(
                    fresh, env, slug, datetime(2030, 2, 15, tzinfo=timezone.utc))
                files, file_env = variants["file"]
                for name, data in files.items():
                    (fresh / name).write_bytes(data)
                original = dict(file_env)
                native_env = dict(variants["native"][1])
                with own_data.database(fresh, source, file_env,
                                       routing=slug == "routing", coverage=slug == "row-coverage") as exported:
                    self.assertEqual(exported["BEFORE"], file_env["EXPORT_BEFORE"])
                    self.assertEqual(exported["AFTER"], file_env["EXPORT_AFTER"])
                    for name in ("BEFORE", "AFTER"):
                        bound = datetime.fromisoformat(exported[name].replace("Z", "+00:00"))
                        self.assertIsNotNone(bound.tzinfo)
                        self.assertEqual((bound.hour, bound.minute, bound.second), (0, 0, 0))
                    if slug == "routing":
                        self.assertEqual((exported["BEFORE"], exported["AFTER"]),
                                         ("2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z"))
                        self.assertEqual((file_env["BEFORE"], file_env["AFTER"]),
                                         ("2026-10-01", "2026-10-02"))
                        self.assertEqual(exported["ROUTE"], file_env["ROUTE"])
                    else:
                        self.assertEqual((exported["BEFORE"], exported["AFTER"]),
                                         (own_data.EXPORT_START, own_data.EXPORT_END))
                    count = own_data.run(
                        ["psql", "service=litellm_readonly", "-At", "-c",
                         'SELECT count(*) FROM public."LiteLLM_SpendLogs";'],
                        cwd=fresh, env=exported)
                    with (fresh / "spend.csv").open() as handle:
                        self.assertEqual(int(count.strip()), len(list(csv.DictReader(handle))))
                self.assertEqual(file_env, original)
                self.assertEqual(variants["native"][1], native_env)
                self.assertEqual((native_env["BEFORE"], native_env["AFTER"]),
                                 ("2030-02-01", "2030-02-08"))


if __name__ == "__main__":
    unittest.main()
