# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Small source-audit checks; no dataset downloads or third-party dependencies."""
from decimal import Decimal
import unittest

from data_audit import CopiedBlock, daily_gap_report, observe_day_gap


def row(timestamp, **changes):
    value = {"Timestamp": str(timestamp), "Model": "ChatGPT", "Request tokens": "7",
             "Response tokens": "3", "Total tokens": "10", "Log Type": "API log"}
    value.update(changes)
    return value


class DataAuditTests(unittest.TestCase):
    def test_only_later_copies_removed_with_multiplicity(self):
        block = CopiedBlock(2, 3, 604800)
        self.assertFalse(block.observe(2, row("0.5")))
        self.assertFalse(block.observe(3, row("0.5")))
        self.assertFalse(block.observe(4, row("604800.5", Model="GPT-4")))
        self.assertTrue(block.observe(5, row("604800.50")))
        self.assertTrue(block.observe(6, row("604800.5")))
        self.assertFalse(block.observe(7, row("604800.5")))
        result = block.result()
        self.assertEqual(result["removed_rows"], 2)
        self.assertEqual([result["first_copy_line"], result["last_copy_line"]], [5, 6])

    def test_every_field_must_match(self):
        for field, value in (("Timestamp", "604802"), ("Model", "GPT-4"),
                             ("Request tokens", "8"), ("Response tokens", "4"),
                             ("Total tokens", "11"), ("Log Type", "Conversation log")):
            with self.subTest(field=field):
                block = CopiedBlock(2, 2, 604800)
                block.observe(2, row(1))
                self.assertFalse(block.observe(3, row(604801, **{field: value})))
                with self.assertRaisesRegex(AssertionError, "match incomplete"):
                    block.result()

    def test_truncated_source_refuses_sampling(self):
        block = CopiedBlock(2, 3, 518400)
        block.observe(2, row(1))
        with self.assertRaisesRegex(AssertionError, "source incomplete"):
            block.result()

    def test_daily_gaps_include_edges_and_empty_days(self):
        days = {}
        for value in (100, 200, 86400, 86410, 3 * 86400 + 1):
            observe_day_gap(days, Decimal(value))
        result = daily_gap_report(days, Decimal(100), Decimal(3 * 86400 + 1))
        self.assertEqual([d["rows"] for d in result], [2, 2, 0, 1])
        self.assertEqual([d["maximum_gap_with_day_edges_seconds"] for d in result],
                         [86200, 86390, 86400, 86399])

    def test_daily_gaps_reject_unordered_rows(self):
        days = {}
        observe_day_gap(days, Decimal(200))
        with self.assertRaisesRegex(AssertionError, "timestamp order"):
            observe_day_gap(days, Decimal(100))


if __name__ == "__main__":
    unittest.main()
