import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import collect_oxyfi as c

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic.jsonl"
DOC_SAMPLE = "$GPRMC,142937,A,5948.7028,N,01307.9771,E,49.53,349.7,101212,1.8,E* 3A,,1421.trains.se,,8955.public.trains.se@2012-12-10;8957.public.trains.se@2012-12-10,oxyfi"


def sentence(**changes):
    f = ["GPRMC", "120000.250", "A", "5948.7028", "N", "01307.9771", "E", "49.53", "349.7", "010120", "1.8", "E"]
    indexes = {"clock": 1, "status": 2, "lat": 3, "ns": 4, "lon": 5, "ew": 6, "speed": 7, "heading": 8, "date": 9}
    for name, value in changes.items():
        f[indexes[name]] = value
    payload = ",".join(f)
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    return f"${payload}*{checksum:02X},,990001.trains.se,,123.public.trains.se@2020-01-01;999.internal.trains.se@2020-01-01,oxyfi"


def stats():
    return {"mode": "replay", "connection_attempts": 0, "successful_connections": 0, "connection_errors": 0}


class ParserTests(unittest.TestCase):
    def test_provider_documentation_example(self):
        row = c.parse_message(DOC_SAMPLE)
        self.assertEqual(row["vehicle_id"], "1421")
        self.assertEqual(row["public_train_numbers"], "8955;8957")
        self.assertAlmostEqual(row["latitude"], 59.811713333, places=7)
        self.assertAlmostEqual(row["longitude"], 13.132951667, places=7)
        self.assertEqual(row["gps_time_utc"], "2012-12-10T14:29:37.000000Z")

    def test_valid_fix_time_speed_latency_and_services(self):
        row = c.parse_message(sentence(), "2020-01-01T12:00:00.350Z")
        self.assertTrue(row["valid_position"])
        self.assertTrue(row["checksum_valid"])
        self.assertAlmostEqual(row["speed_kmh"], 49.53 * 1.852)
        self.assertEqual(row["internal_train_numbers"], "999")
        self.assertEqual(row["latency_seconds"], 0.1)

    def test_southern_western_hemispheres(self):
        row = c.parse_message(sentence(ns="S", ew="W"))
        self.assertLess(row["latitude"], 0)
        self.assertLess(row["longitude"], 0)

    def test_invalid_minutes(self):
        with self.assertRaises(ValueError):
            c.parse_message(sentence(lat="5960.0000"))

    def test_invalid_coordinate_boundary(self):
        with self.assertRaises(ValueError):
            c.parse_message(sentence(lon="18000.0001"))

    def test_void_fix_without_coordinates(self):
        row = c.parse_message(sentence(status="V", lat="", ns="", lon="", ew=""))
        self.assertFalse(row["valid_position"])
        self.assertIsNone(row["latitude"])

    def test_void_fix_with_coordinates_is_still_invalid(self):
        self.assertFalse(c.parse_message(sentence(status="V"))["valid_position"])

    def test_bad_checksum_is_flagged_not_silently_discarded(self):
        raw = sentence().replace("49.53", "48.53")
        row = c.parse_message(raw)
        self.assertFalse(row["checksum_valid"])
        self.assertFalse(row["valid_position"])

    def test_no_checksum_is_rejected(self):
        with self.assertRaises(ValueError):
            c.parse_message(sentence().split("*")[0])

    def test_invalid_numeric_values(self):
        for field, value in [("speed", "nan"), ("speed", "-1"), ("heading", "361"), ("heading", "inf")]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                c.parse_message(sentence(**{field: value}))

    def test_no_service_is_allowed(self):
        raw = sentence().replace("123.public.trains.se@2020-01-01;999.internal.trains.se@2020-01-01", "")
        row = c.parse_message(raw)
        self.assertTrue(row["valid_position"])
        self.assertEqual(row["public_train_numbers"], "")

    def test_missing_vehicle_is_rejected(self):
        with self.assertRaises(ValueError):
            c.parse_message(sentence().replace("990001.trains.se", ""))

    def test_invalid_and_missing_time(self):
        for clock in ("240000", "126000", "120060", "bad"):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                c.parse_message(sentence(clock=clock))
        self.assertFalse(c.parse_message(sentence(clock=""))["valid_position"])

    def test_leap_second(self):
        self.assertEqual(c.gps_timestamp("235960", "311216"), "2017-01-01T00:00:00.000000Z")

    def test_key_redaction(self):
        self.assertNotIn("EXAMPLE_SECRET", c.redact("oops EXAMPLE_SECRET /?key=EXAMPLE_SECRET", "EXAMPLE_SECRET"))

    def test_naive_receipt_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            c.parse_message(sentence(), "2020-01-01T12:00:00")


class CollectionTests(unittest.TestCase):
    def test_synthetic_batch_multi_vehicle_csv_and_cadence(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "sample.csv"
            s = stats()
            self.assertEqual(c.collect(c.replay_messages(FIXTURE), output, s), 0)
            with output.open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 30)
            self.assertEqual({r["capture_mode"] for r in rows}, {"synthetic"})
            self.assertEqual(s["unique_vehicles"], 3)
            self.assertEqual(s["valid_positions"], 30)
            self.assertTrue(all(v["mean_interval_seconds"] == 1 for v in s["vehicles"].values()))
            self.assertEqual(len(output.with_suffix(".raw.jsonl").read_text().splitlines()), 30)

    def test_overwrite_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "sample.csv"
            c.collect(iter([]), output, stats())
            with self.assertRaises(FileExistsError):
                c.collect(iter([]), output, stats())
            self.assertEqual(c.collect(iter([]), output, stats(), overwrite=True), 3)

    def test_companion_file_is_also_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "sample.csv"
            output.with_suffix(".raw.jsonl").write_text("keep")
            with self.assertRaises(FileExistsError):
                c.collect(iter([]), output, stats())

    def test_malformed_message_does_not_stop_batch_and_key_not_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "sample.csv"
            s = stats()
            records = iter([{"message": "bad EXAMPLE_SECRET"}, {"message": sentence()}])
            self.assertEqual(c.collect(records, output, s, key="EXAMPLE_SECRET"), 0)
            self.assertEqual(s["parse_errors"], 1)
            for p in Path(folder).iterdir():
                self.assertNotIn("EXAMPLE_SECRET", p.read_text())

    def test_duplicates_and_out_of_order_not_used_for_cadence(self):
        vehicles = {}
        for clock in ("120001", "120002", "120002", "120000", "120004"):
            c.update_vehicle(vehicles, c.parse_message(sentence(clock=clock)))
        v = vehicles["990001"]
        self.assertEqual(v["duplicate_timestamps"], 1)
        self.assertEqual(v["out_of_order_timestamps"], 1)
        self.assertEqual(v["interval_sum_seconds"], 3)
        self.assertEqual(v["positive_interval_count"], 2)

    def test_spreadsheet_formula_injection_is_escaped(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "sample.csv"
            message = sentence().removesuffix("oxyfi") + "=1+1"
            c.collect(iter([{"message": message}]), output, stats())
            with output.open() as f:
                self.assertEqual(next(csv.DictReader(f))["source"], "'=1+1")

    def test_replayed_live_capture_cannot_claim_to_be_live(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "raw.jsonl"
            p.write_text(json.dumps({"message": sentence(), "capture_mode": "live"}) + "\n")
            self.assertEqual(next(c.replay_messages(p))["capture_mode"], "replay")

    def test_no_valid_rows_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(c.collect(iter([{"message": sentence(status="V")}]), Path(folder)/"void.csv", stats()), 3)

    def test_dns_failure_is_reported_without_secret_leak(self):
        s = stats()
        with patch("websocket.create_connection", side_effect=socket.gaierror("EXAMPLE_SECRET")), patch("sys.stderr", new_callable=io.StringIO) as log:
            self.assertEqual(list(c.live_messages("EXAMPLE_SECRET", 1, 0, s)), [])
            self.assertNotIn("EXAMPLE_SECRET", log.getvalue())
        self.assertEqual(s["connection_attempts"], 1)
        self.assertEqual(s["successful_connections"], 0)
        self.assertNotIn("EXAMPLE_SECRET", json.dumps(s))

    def test_websocket_frames_with_multiple_trains(self):
        import websocket
        class FakeSocket:
            def __init__(self):
                self.first = True
            def settimeout(self, value):
                pass
            def recv(self):
                if not self.first:
                    raise websocket.WebSocketConnectionClosedException("closed")
                self.first = False
                return sentence() + "\n" + sentence().replace("990001.trains.se", "990002.trains.se")
            def close(self, **kwargs):
                pass
        s = stats()
        with patch("websocket.create_connection", return_value=FakeSocket()):
            records = list(c.live_messages("EXAMPLE_SECRET", 1, 0, s))
        self.assertEqual(len(records), 2)
        self.assertEqual(s["successful_connections"], 1)
        self.assertEqual({c.parse_message(r["message"])["vehicle_id"] for r in records}, {"990001", "990002"})


if __name__ == "__main__":
    unittest.main()
