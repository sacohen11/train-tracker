"""Synthetic fixtures for map-export timing, identity, and gap preservation."""

import csv
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from baltic.compact_csv import FIELDS, compact_rows, export


def row(second, **changes):
    received = datetime(2026, 10, 26, tzinfo=timezone.utc) + timedelta(seconds=second)
    result = dict(
        country="LV", source="Vivi public map stream", service_date="2026-10-26",
        train_id="123", route_label="804", received_at_utc=received.isoformat(),
        source_time_utc=received.isoformat(), latitude="56.123456789012345",
        longitude="24.567890123456789", coordinates_valid="True",
        is_gps_active="True", source_time_stale="False", capture_mode="synthetic",
    )
    result.update(changes)
    return result


def run(rows):
    stats = Counter()
    output = list(compact_rows(rows, stats))
    return output, stats


class CompactCsvTests(unittest.TestCase):
    def test_stationary_run_preserves_both_endpoints_before_movement(self):
        result, stats = run([row(0), row(1), row(2), row(3, latitude="57"),
                             row(4, latitude="57"), row(5, latitude="57")])
        self.assertEqual([r["received_at_utc"] for r in result], [
            "2026-10-26T00:00:00Z", "2026-10-26T00:00:02Z",
            "2026-10-26T00:00:03Z", "2026-10-26T00:00:05Z",
        ])
        self.assertEqual(stats["removed_repeat_rows"], 2)
        self.assertEqual([r["segment_start"] for r in result], ["1", "0", "0", "0"])

    def test_every_coordinate_change_is_preserved(self):
        result, stats = run([row(i, longitude=str(24 + i / 1000)) for i in range(100)])
        self.assertEqual(len(result), 100)
        self.assertEqual(stats["removed_repeat_rows"], 0)

    def test_fresh_stationary_reports_have_real_first_and_last_source_times(self):
        result, _ = run([row(i) for i in range(3600)])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["source_time_utc"], "2026-10-26T00:00:00Z")
        self.assertEqual(result[1]["source_time_utc"], "2026-10-26T00:59:59Z")
        self.assertEqual(result[1]["segment_start"], "0")

    def test_subsecond_times_and_coordinate_precision_are_preserved(self):
        result, _ = run([row(0.123456), row(1.654321)])
        self.assertEqual(result[0]["received_at_utc"], "2026-10-26T00:00:00.123456Z")
        self.assertEqual(result[1]["source_time_utc"], "2026-10-26T00:00:01.654321Z")
        self.assertEqual(result[0]["latitude"], "56.123456789012345")
        self.assertEqual(result[0]["longitude"], "24.567890123456789")

    def test_gps_false_and_unknown_are_distinct_and_retained(self):
        result, _ = run([row(0), row(1, is_gps_active="False"), row(2, is_gps_active="")])
        self.assertEqual([r["is_gps_active"] for r in result], ["true", "false", ""])
        self.assertEqual([r["segment_start"] for r in result], ["1", "1", "1"])

    def test_stop_is_not_joined_across_feed_gap(self):
        result, stats = run([row(0), row(1), row(100), row(101)])
        self.assertEqual(len(result), 4)
        self.assertEqual([r["segment_start"] for r in result], ["1", "0", "1", "0"])
        self.assertEqual(stats["break_receipt_gap"], 1)

    def test_source_regression_and_source_gap_break_the_path(self):
        result, stats = run([row(0), row(1), row(2, source_time_utc=row(0)["source_time_utc"]),
                             row(3, source_time_utc=row(60)["source_time_utc"])])
        self.assertEqual([r["segment_start"] for r in result], ["1", "0", "1", "1"])
        self.assertEqual(stats["break_source_time_regression"], 1)
        self.assertEqual(stats["break_source_gap"], 1)

    def test_missing_source_time_is_not_replaced_with_receipt_time(self):
        result, _ = run([row(0), row(1, source_time_utc=""), row(2, source_time_utc="")])
        self.assertEqual(result[1]["source_time_utc"], "")
        self.assertEqual(result[1]["segment_start"], "1")

    def test_invalid_coordinates_are_excluded_and_break_the_path(self):
        result, stats = run([row(0), row(1), row(2, latitude="nan"), row(3)])
        self.assertEqual(len(result), 3)
        self.assertEqual([r["segment_start"] for r in result], ["1", "0", "1"])
        self.assertEqual(stats["invalid_coordinate_rows"], 1)

    def test_service_date_and_internal_id_disambiguate_train_numbers(self):
        result, stats = run([row(0), row(1, train_id="456"),
                             row(2, service_date="2026-10-27"), row(3)])
        self.assertEqual(stats["services"], 3)
        self.assertEqual(len({r["service_id"] for r in result}), 3)
        self.assertEqual({r["train_number"] for r in result}, {"804"})
        self.assertTrue(all(r["service_id"].startswith("LV:vivi:") for r in result))

    def test_stale_status_transition_starts_a_new_segment(self):
        result, _ = run([row(0), row(1, source_time_stale="True")])
        self.assertEqual([r["segment_start"] for r in result], ["1", "1"])

    def test_new_file_starts_a_segment_even_for_an_overnight_service(self):
        first, _ = run([row(0), row(1)])
        second, _ = run([row(2), row(3)])
        self.assertEqual(first[0]["service_id"], second[0]["service_id"])
        self.assertEqual(second[0]["segment_start"], "1")

    def test_export_refuses_to_overwrite_and_does_not_publish_partial_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "source.csv", Path(folder) / "map.csv"
            with source.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=row(0).keys())
                writer.writeheader()
                writer.writerows([row(0), row(1)])
            stats = export(source, target)
            self.assertEqual(stats["output_rows"], 2)
            with target.open() as stream:
                self.assertEqual(tuple(csv.DictReader(stream).fieldnames), FIELDS)
            with self.assertRaises(FileExistsError):
                export(source, target)
            bad = Path(folder) / "bad.csv"
            source.write_text(source.read_text().replace("2026-10-26T00:00:01", "INVALID"))
            with self.assertRaises(ValueError):
                export(source, bad)
            self.assertFalse(bad.exists())
            self.assertFalse(list(Path(folder).glob("*.part")))


if __name__ == "__main__":
    unittest.main()
