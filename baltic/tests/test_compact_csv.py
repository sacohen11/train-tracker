"""Regression checks for lossless column selection using synthetic records."""

import csv
import gzip
import io
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from baltic.compact_csv import FIELDS, compact_rows, export


def row(second, **changes):
    stamp = (datetime(2026, 10, 26, tzinfo=timezone.utc) + timedelta(seconds=second)).isoformat(timespec="microseconds")
    result = dict(
        country="LV", source="Vivi public map stream", service_date="2026-10-26",
        train_id="123", route_label="0804", received_at_utc=stamp, source_time_utc=stamp,
        latitude="56.123456789012345", longitude="24.567890123456789",
        coordinates_valid="True", is_gps_active="True", capture_mode="synthetic",
    )
    result.update(changes)
    return result


def run(rows):
    stats = Counter()
    return list(compact_rows(rows, stats)), stats


def source_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


class CompactCsvTests(unittest.TestCase):
    def test_all_stationary_fresh_reports_are_retained(self):
        source = [row(i) for i in range(3600)]
        result, stats = run(source)
        self.assertEqual(len(result), 3600)
        self.assertEqual(stats["input_rows"], stats["output_rows"])
        self.assertEqual([r["source_time_utc"] for r in result], [r["source_time_utc"] for r in source])

    def test_interleaved_services_keep_exact_original_global_order(self):
        source = [row(0), row(1, train_id="456"), row(2), row(3, train_id="456"), row(4, latitude="57")]
        result, _ = run(source)
        self.assertEqual([(r["train_id"], r["received_at_utc"]) for r in result],
                         [(r["train_id"], r["received_at_utc"]) for r in source])

    def test_timestamp_spelling_offset_and_six_digit_fraction_are_unchanged(self):
        source = [row(0), row(.001), row(.125), row(.123456)]
        result, _ = run(source)
        self.assertEqual([r["received_at_utc"] for r in result], [
            "2026-10-26T00:00:00.000000+00:00", "2026-10-26T00:00:00.001000+00:00",
            "2026-10-26T00:00:00.125000+00:00", "2026-10-26T00:00:00.123456+00:00",
        ])
        self.assertEqual(result[-1]["source_time_utc"], source[-1]["source_time_utc"])

    def test_coordinates_and_leading_zero_train_labels_are_not_coerced(self):
        result, _ = run([row(0, latitude="56.123456700000000", route_label="0804")])
        self.assertEqual(result[0]["latitude"], "56.123456700000000")
        self.assertEqual(result[0]["longitude"], "24.567890123456789")
        self.assertEqual(result[0]["route_label"], "0804")

    def test_flags_and_unknown_values_are_kept_exactly(self):
        source = [row(0), row(1, is_gps_active="False"), row(2, is_gps_active="", source_time_utc="")]
        result, _ = run(source)
        self.assertEqual([r["is_gps_active"] for r in result], ["True", "False", ""])
        self.assertEqual(result[-1]["source_time_utc"], "")

    def test_real_gaps_and_backward_source_times_are_preserved_without_extra_fields(self):
        source = [row(0), row(1), row(100, source_time_utc=row(0)["source_time_utc"])]
        result, _ = run(source)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1]["received_at_utc"], source[-1]["received_at_utc"])
        self.assertEqual(result[-1]["source_time_utc"], source[-1]["source_time_utc"])
        self.assertNotIn("segment_start", result[-1])

    def test_overnight_service_date_and_internal_id_are_unchanged(self):
        source = [row(90000, service_date="2026-10-26", train_id="00123")]
        result, _ = run(source)
        self.assertEqual(result[0]["service_date"], "2026-10-26")
        self.assertEqual(result[0]["train_id"], "00123")
        self.assertNotIn("service_id", result[0])

    def test_missing_or_invalid_position_values_are_not_silently_deleted(self):
        result, _ = run([row(0, latitude="", longitude="", coordinates_valid="False"),
                         row(1, latitude="nan", coordinates_valid="False")])
        self.assertEqual(len(result), 2)
        self.assertEqual([r["latitude"] for r in result], ["", "nan"])

    def test_duplicate_reports_are_kept(self):
        result, _ = run([row(0), row(0)])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], result[1])

    def test_gzip_input_and_csv_round_trip_preserve_every_cell(self):
        source_rows = [row(0), row(1), row(2, is_gps_active="")]
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/"full.csv.gz", Path(folder)/"slim.csv"
            with gzip.open(source, "wt", newline="") as stream:
                stream.write(source_csv(source_rows))
            stats = export(source, target)
            with target.open(newline="") as stream:
                reader = csv.DictReader(stream)
                result = list(reader)
            self.assertEqual(tuple(reader.fieldnames), FIELDS)
            self.assertEqual(stats["removed_rows"], 0)
            for actual, original in zip(result, source_rows):
                for column in FIELDS:
                    self.assertEqual(actual[column], original[column])

    def test_overwrite_is_refused_and_malformed_input_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/"full.csv", Path(folder)/"slim.csv"
            original_text = source_csv([row(0), row(1)])
            source.write_text(original_text)
            export(source, target)
            self.assertEqual(source.read_bytes(), original_text.encode())
            before = target.read_bytes()
            with self.assertRaises(FileExistsError):
                export(source, target)
            self.assertEqual(target.read_bytes(), before)
            source.write_text(original_text + "LV,Vivi\n")
            partial = Path(folder)/"partial.csv"
            with self.assertRaises(ValueError):
                export(source, partial)
            self.assertFalse(partial.exists())
            self.assertFalse(list(Path(folder).glob("*.part")))


if __name__ == "__main__":
    unittest.main()
