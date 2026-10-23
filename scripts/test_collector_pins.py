# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Reject stale collector pins, affected versions and incomplete live lookups."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import collector_pins as pins


def release(tag, **changes):
    return dict(tag_name=tag, draft=False, prerelease=False, published_at="2026-10-18T21:02:19Z",
                html_url="https://github.com/" + pins.REPO + "/releases/tag/" + tag, **changes)


def advisory(expression=">= 0.3.0, <= 0.6.0", package="ghcr.io/" + pins.REPO):
    return {"ghsa_id": "GHSA-w5rp-j3gj-7x54", "state": "published", "withdrawn_at": None,
            "published_at": "2026-10-18T21:29:17Z", "html_url": "https://example.test/advisory",
            "vulnerabilities": [{"package": {"name": package}, "vulnerable_version_range": expression}]}


def response(records, link=""):
    result = io.BytesIO(json.dumps(records).encode())
    result.headers = {"Link": link}
    return result


class CollectorPinTests(unittest.TestCase):
    def setUp(self):
        self.record = pins.policy([release("v0.6.1")], [advisory()])

    def test_latest_numeric_stable_runtime_ignores_prereleases_drafts_and_chart_tags(self):
        records = [release("v0.6.1"), release("v0.9.0"), release("v0.10.0"),
                   release("chart-v0.12.0"), release("v0.11.0-rc.1")]
        candidate = release("v0.12.0")
        candidate["prerelease"] = True
        records.append(candidate)
        candidate = release("v0.13.0")
        candidate["draft"] = True
        records.append(candidate)
        self.assertEqual(pins.policy(records, [])["latest_stable"], "v0.10.0")

    def test_no_published_stable_release_fails(self):
        with self.assertRaisesRegex(ValueError, "no published stable"):
            pins.policy([release("v0.6.2-rc.1")], [])

    def test_urls_prose_and_security_command_all_checked(self):
        sources = [
            "https://github.com/" + pins.REPO + "/blob/v0.6.1/builder.yaml",
            "https://raw.githubusercontent.com/" + pins.REPO + "/v0.6.1/README.md",
            "https://codeload.github.com/" + pins.REPO + "/tar.gz/v0.6.1",
            "https://codeload.github.com/" + pins.REPO + "/tar.gz/refs/tags/v0.6.1",
            "https://github.com/" + pins.REPO + "/archive/refs/tags/v0.6.1.tar.gz",
            "https://github.com/" + pins.REPO + "/releases/download/v0.6.1/SHA256SUMS",
            "Collector configuration guidance: v0.6.1; Helm chart 0.6.1",
            "v0.6.1 collector distribution; v0.6.1 image",
            "Collector <code>v0.6.1</code>",
            "ghcr.io/" + pins.REPO + ":0.6.1",
            '<pre data-review="collector"><code>release=v0.6.1\n</code></pre>',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertGreater(pins.check_source("page", source, self.record), 0)
                with self.assertRaisesRegex(ValueError, "affected by GHSA"):
                    pins.check_source("page", source.replace("0.6.1", "0.6.0"), self.record)

    def test_stale_but_not_vulnerable_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "latest stable"):
            pins.check_source("page", "collector v0.2.9", self.record)

    def test_historical_evidence_keeps_its_actual_measured_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("pages", "docs", "evidence"):
                (root / name).mkdir()
            (root / "README.md").write_text("collector v0.6.1")
            (root / "docs/llms.txt").write_text("chart 0.6.1")
            history = "Historical collector v0.6.0 measurement; not a current upgrade pin."
            before, after = "collector v0.6.1\n", "\nchart 0.6.1"
            source = before + "<!-- historical-verification:start -->" + history + "<!-- historical-verification:end -->" + after
            (root / "evidence/README.md").write_text(source)
            (root / "evidence/collector-release-policy.json").write_text(json.dumps(self.record))
            pins.check(root)
            self.assertEqual((root / "evidence/README.md").read_text(), source)
            self.assertEqual(pins.current_evidence(source), before + after)

    def test_historical_exception_does_not_exempt_any_current_surface(self):
        for name in ("README.md", "docs/llms.txt", "pages/index.html", "docs/index.html"):
            for stale in ("v0.6.0", "v0.2.9"):
                with self.subTest(name=name, stale=stale), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    for folder in ("pages", "docs", "evidence"):
                        (root / folder).mkdir()
                    for path in ("README.md", "docs/llms.txt", "pages/index.html", "docs/index.html"):
                        (root / path).write_text("collector v0.6.1")
                    (root / "evidence/README.md").write_text(
                        "<!-- historical-verification:start -->Historical collector v0.6.0<!-- historical-verification:end -->")
                    (root / "evidence/collector-release-policy.json").write_text(json.dumps(self.record))
                    (root / name).write_text("collector " + stale)
                    with self.assertRaisesRegex(ValueError, "affected by|latest stable"):
                        pins.check(root)

    def test_current_evidence_prefix_and_suffix_reject_stale_and_affected_pins(self):
        for side in ("before", "after"):
            for stale in ("v0.6.0", "v0.2.9"):
                for text in ("collector " + stale,
                             "https://github.com/" + pins.REPO + "/blob/" + stale + "/README.md"):
                    with self.subTest(side=side, text=text), tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        for folder in ("pages", "docs", "evidence"):
                            (root / folder).mkdir()
                        (root / "README.md").write_text("collector v0.6.1")
                        (root / "docs/llms.txt").write_text("chart 0.6.1")
                        history = "<!-- historical-verification:start -->Historical collector v0.6.0<!-- historical-verification:end -->"
                        source = text + "\n" + history if side == "before" else history + "\n" + text
                        (root / "evidence/README.md").write_text(source)
                        (root / "evidence/collector-release-policy.json").write_text(json.dumps(self.record))
                        with self.assertRaisesRegex(ValueError, "affected by|latest stable"):
                            pins.check(root)

    def test_malformed_duplicate_reversed_and_nested_history_markers_fail_closed(self):
        start = "<!-- historical-verification:start -->"
        end = "<!-- historical-verification:end -->"
        for source in ("", "Historical collector v0.6.0", start, end, end + start,
                       start + start + end + end, start + end + start + end,
                       start.replace(":start", ":begin") + end,
                       start.replace(" -->", "-->") + end,
                       start.upper() + end,
                       start + end + "<!-- historical-verification:broken",
                       start + "<!-- historical-verification:other -->" + end):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for folder in ("pages", "docs", "evidence"):
                    (root / folder).mkdir()
                (root / "README.md").write_text("collector v0.6.1")
                (root / "docs/llms.txt").write_text("chart 0.6.1")
                (root / "evidence/README.md").write_text(source)
                (root / "evidence/collector-release-policy.json").write_text(json.dumps(self.record))
                with self.assertRaisesRegex(ValueError, "historical-verification"):
                    pins.check(root)

    def test_latest_release_is_rejected_if_advisory_affects_it(self):
        record = pins.policy([release("v0.6.1")], [advisory("<= 0.6.1")])
        with self.assertRaisesRegex(ValueError, "affected by"):
            pins.check_source("page", "collector v0.6.1", record)

    def test_chart_and_runtime_advisory_scopes_are_distinct(self):
        record = pins.policy([release("v0.6.1")], [advisory("= 0.6.1", "ghcr.io/llm-measurement/charts/otelcol-genai-sketches")])
        self.assertEqual(pins.check_source("page", "collector v0.6.1", record), 1)
        with self.assertRaisesRegex(ValueError, "affected by"):
            pins.check_source("page", "chart 0.6.1", record)

    def test_standalone_connector_advisory_applies_to_runtime(self):
        record = pins.policy([release("v0.6.1")], [advisory("= 0.6.1", "github.com/" + pins.REPO + "/connector/genaisketchconnector")])
        with self.assertRaisesRegex(ValueError, "affected by"):
            pins.check_source("page", "collector v0.6.1", record)

    def test_draft_and_withdrawn_advisories_ignored(self):
        unpublished, withdrawn = advisory("<= 0.6.1"), advisory("<= 0.6.1")
        unpublished["state"] = "draft"
        withdrawn["withdrawn_at"] = "2026-10-18T22:00:00Z"
        self.assertEqual(pins.policy([release("v0.6.1")], [unpublished, withdrawn])["advisories"], [])

    def test_supported_affected_range_boundaries(self):
        for expression, expected in ((">= 0.3.0, <= 0.6.0", False), (">= 0.3.0, < 0.6.1", False),
                                     (">= 0.6.1", True), ("> 0.6.1", False), ("0.6.1", True),
                                     ("= v0.6.1", True), ("< 0.5.0 || >= 0.6.1", True)):
            with self.subTest(expression=expression):
                self.assertEqual(pins.affected("v0.6.1", expression), expected)
        for expression in ("", None, "*", "~0.6.0", ">= 0.3.0 < 0.6.1", ">= 0.3.0,", "< 0.5.0 || *"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                pins.affected("v0.6.1", expression)

    def test_malformed_published_advisory_and_unstable_pins_fail(self):
        bad = advisory()
        bad["vulnerabilities"] = None
        with self.assertRaises(ValueError):
            pins.policy([release("v0.6.1")], [bad])
        with self.assertRaises(ValueError):
            pins.source_pins("https://github.com/" + pins.REPO + "/blob/v0.6.1-rc.1/README.md")
        with self.assertRaises(ValueError):
            pins.source_pins('<pre data-review="collector"><code>release=latest\n</code></pre>')
        for source in ("collector v0.6.2-rc.1", "Collector <code>v0.6.0</code>",
                       "ghcr.io/" + pins.REPO + ":latest"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                pins.check_source("page", "collector v0.6.1\n" + source, self.record)

    def test_malformed_advisory_inputs_and_snapshots_fail(self):
        for records in ({}, [{}], [None], [{"state": "unknown", "withdrawn_at": None}]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                pins.policy([release("v0.6.1")], records)
        for records in ({}, None, [{}], [{"ghsa_id": "GHSA-w5rp-j3gj-7x54", "vulnerabilities": {}}]):
            record = dict(self.record, advisories=records)
            with self.subTest(records=records), self.assertRaises(ValueError):
                pins.check_source("page", "collector v0.6.1", record)

    def test_invalid_withdrawal_metadata_cannot_suppress_an_advisory(self):
        for value in (True, False, {}, {"date": "2026-10-18"}, "not-a-timestamp", "", "2026-10-18"):
            item = advisory("<= 0.6.1")
            item["withdrawn_at"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                pins.policy([release("v0.6.1")], [item])

    def test_fetch_is_anonymous_paginated_and_bounded(self):
        second = pins.API + "/releases?per_page=100&page=2"
        pages = [response([{}] * 100, f'<{second}>; rel="next"'), response([])]
        with patch("collector_pins.urllib.request.build_opener") as build:
            build.return_value.open.side_effect = pages
            self.assertEqual(len(pins.fetch_list("/releases")), 100)
            calls = build.return_value.open.call_args_list
            self.assertEqual(len(calls), 2)
            for expected, call in zip((pins.API + "/releases?per_page=100", second), calls):
                request = call.args[0]
                self.assertEqual(request.full_url, expected)
                self.assertNotIn("Authorization", request.headers)
                self.assertNotIn("Cookie", request.headers)
            self.assertEqual(build.call_args.args[0].proxies, {})

    def test_live_api_failure_never_falls_back_to_snapshot(self):
        for error in (urllib.error.URLError("offline"), ValueError("malformed JSON")):
            with patch("collector_pins.fetch_list", side_effect=error), self.assertRaises(type(error)):
                pins.live_policy()

    def test_pagination_exhaustion_refuses_incomplete_list(self):
        with patch("collector_pins.urllib.request.build_opener") as build:
            count = 0
            def page(request, **kwargs):
                nonlocal count
                count += 1
                url = pins.API + f"/security-advisories?per_page=100&after={count}"
                return response([{}] * 100, f'<{url}>; rel="next"')
            build.return_value.open.side_effect = page
            with self.assertRaisesRegex(ValueError, "pagination"):
                pins.fetch_list("/security-advisories")
            self.assertEqual(count, 20)

    def test_advisory_cursor_is_followed_not_numbered_page(self):
        first = pins.API + "/security-advisories?per_page=100"
        second = first + "&after=NEXT"
        def page(request, **kwargs):
            if request.full_url == first:
                return response([advisory()] * 100, f'<{second}>; rel="next"')
            self.assertEqual(request.full_url, second)
            return response([advisory("<= 0.6.1")], f'<{first}>; rel="prev"')
        with patch("collector_pins.urllib.request.build_opener") as build:
            build.return_value.open.side_effect = page
            records = pins.fetch_list("/security-advisories")
            self.assertEqual(len(records), 101)
            record = pins.policy([release("v0.6.1")], records)
            with self.assertRaisesRegex(ValueError, "affected by"):
                pins.check_source("page", "collector v0.6.1", record)

    def test_offsite_or_repeated_pagination_fails(self):
        for url in ("https://example.test/?per_page=100", pins.API + "/releases?per_page=100",
                    pins.API + "/security-advisories?per_page=100"):
            with self.subTest(url=url), patch("collector_pins.urllib.request.build_opener") as build:
                build.return_value.open.return_value = response([{}], f'<{url}>; rel="next"')
                with self.assertRaisesRegex(ValueError, "pagination"):
                    pins.fetch_list("/releases")


if __name__ == "__main__":
    unittest.main()
