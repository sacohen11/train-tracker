#!/usr/bin/env python3
"""Collect all Oxyfi Trainpos vehicles into CSV without persisting API keys."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import csv
from datetime import datetime, timedelta, timezone
import getpass
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterator
from urllib.parse import urlencode

ENDPOINT = "wss://api.oxyfi.com/trainpos/listen"
FIELDS = [
    "capture_mode", "received_at_utc", "gps_time_utc", "vehicle_id", "vehicle_ref",
    "public_train_numbers", "internal_train_numbers", "train_refs", "latitude",
    "longitude", "speed_knots", "speed_kmh", "heading_deg", "fix_status",
    "checksum_valid", "valid_position", "latency_seconds", "source", "raw_nmea",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include its UTC offset")
    return result.astimezone(timezone.utc)


def number(value: str) -> float | None:
    if not value.strip():
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric field")
    return result


def coordinate(value: str, hemisphere: str, latitude: bool) -> float | None:
    if not value and not hemisphere:
        return None
    directions = "NS" if latitude else "EW"
    digits, limit = (4, 90) if latitude else (5, 180)
    if hemisphere not in directions or len(hemisphere) != 1:
        raise ValueError("Invalid coordinate hemisphere")
    if not re.fullmatch(r"\d{" + str(digits) + r"}(?:\.\d+)?", value):
        raise ValueError("Invalid degrees/minutes coordinate")
    n = float(value)
    degrees = int(n // 100)
    minutes = n - degrees * 100
    if minutes >= 60 or degrees > limit or (degrees == limit and minutes != 0):
        raise ValueError("Coordinate outside permitted range")
    result = degrees + minutes / 60
    return round(-result if hemisphere in "SW" else result, 8)


def gps_timestamp(clock: str, date: str) -> str:
    if not clock or not date:
        return ""
    if not re.fullmatch(r"\d{6}(?:\.\d+)?", clock) or not re.fullmatch(r"\d{6}", date):
        raise ValueError("Invalid GPS date/time")
    hour, minute, second = int(clock[:2]), int(clock[2:4]), float(clock[4:])
    if hour > 23 or minute > 59 or not 0 <= second < 61:
        raise ValueError("Invalid GPS clock")
    # A reported leap second (23:59:60) is normalized to the next UTC day.
    if second >= 60 and (hour, minute) != (23, 59):
        raise ValueError("Invalid leap-second placement")
    dt = datetime.strptime(date, "%d%m%y").replace(tzinfo=timezone.utc)
    dt += timedelta(hours=hour, minutes=minute, seconds=second)
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_message(message: str, received_at: str = "", mode: str = "live") -> dict[str, Any]:
    """Parse extended RMC; invalid checksums/fixes are retained and flagged."""
    raw = message.strip()
    if "*" not in raw:
        raise ValueError("Missing NMEA checksum")
    nmea, tail = raw.split("*", 1)
    match = re.fullmatch(r"\s*([0-9a-fA-F]{2})(,.*)?", tail)
    if not match:
        raise ValueError("Malformed checksum or extension")
    fields = nmea.split(",")
    if fields[0] not in ("$GPRMC", "$GNRMC") or len(fields) < 10:
        raise ValueError("Not a supported RMC sentence")
    check = 0
    for char in nmea[1:]:
        check ^= ord(char)
    checksum_valid = check == int(match[1], 16)
    extensions = (match[2] or "").split(",")
    # Match tags, not table indices: checksum is attached to the NMEA field.
    vehicles = [v for v in extensions if re.fullmatch(r"\d+\.trains\.se", v)]
    if len(vehicles) != 1:
        raise ValueError("Missing or ambiguous vehicle identity")
    refs = []
    public, internal = [], []
    for extension in extensions:
        for ref in extension.split(";"):
            service = re.fullmatch(r"(\d+)\.(public|internal)\.trains\.se(?:@\d{4}-\d{2}-\d{2})?", ref)
            if service:
                refs.append(ref)
                (public if service[2] == "public" else internal).append(service[1])
    status = fields[2]
    if status not in ("A", "V"):
        raise ValueError("Invalid fix status")
    lat = coordinate(fields[3], fields[4], True)
    lon = coordinate(fields[5], fields[6], False)
    speed, heading = number(fields[7]), number(fields[8])
    if speed is not None and speed < 0:
        raise ValueError("Negative speed")
    if heading is not None and not 0 <= heading <= 360:
        raise ValueError("Heading outside 0..360 degrees")
    gps = gps_timestamp(fields[1], fields[9])
    valid = status == "A" and checksum_valid and lat is not None and lon is not None and bool(gps)
    lag = round((timestamp(received_at) - timestamp(gps)).total_seconds(), 6) if received_at and gps else None
    return dict(zip(FIELDS, [
        mode, received_at, gps, vehicles[0].split(".")[0], vehicles[0],
        ";".join(public), ";".join(internal), ";".join(refs), lat, lon,
        speed, round(speed * 1.852, 6) if speed is not None else None, heading,
        status, checksum_valid, valid, lag, extensions[-1] or "oxyfi", raw,
    ]))


def redact(text: str, key: str = "") -> str:
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"(?i)([?&]key=)[^\s&\"'<>]+", r"\1[REDACTED]", text)


def live_messages(key: str, seconds: float, max_retries: int, stats: dict) -> Iterator[dict]:
    import websocket

    # Tracing would reveal the authentication URL; never enable it here.
    websocket.enableTrace(False)
    url = ENDPOINT + "?" + urlencode({"v": 1, "key": key})
    deadline = time.monotonic() + seconds if seconds else math.inf
    failures = 0
    while time.monotonic() < deadline:
        ws = None
        try:
            stats["connection_attempts"] += 1
            ws = websocket.create_connection(url, timeout=min(10.0, max(0.1, deadline - time.monotonic())))
            stats["successful_connections"] += 1
            last_data = time.monotonic()
            while time.monotonic() < deadline:
                ws.settimeout(min(1.0, max(0.01, deadline - time.monotonic())))
                try:
                    message = ws.recv()
                except websocket.WebSocketTimeoutException:
                    if time.monotonic() - last_data >= 30:
                        raise TimeoutError("No data for 30 seconds") from None
                    continue
                if message == "" or message == b"":
                    raise ConnectionError("WebSocket closed")
                if isinstance(message, bytes):
                    message = message.decode("ascii", errors="replace")
                failures = 0
                last_data = time.monotonic()
                received = utc_now()
                for line in message.splitlines():
                    if line.strip():
                        yield {"received_at_utc": received, "message": line, "capture_mode": "live"}
        except (OSError, websocket.WebSocketException) as exc:
            failures += 1
            stats["connection_errors"] += 1
            # Exception text / handshake response bodies can contain secrets.
            error = {"at_utc": utc_now(), "type": type(exc).__name__}
            status = getattr(exc, "status_code", None)
            if status is not None:
                error["http_status"] = status
            stats["last_connection_error"] = error
            print(f"Connection failed: {error['type']}" + (f" (HTTP {status})" if status else ""), file=sys.stderr)
            if status in (401, 403) or failures > max_retries:
                break
        finally:
            if ws is not None:
                try:
                    ws.close(timeout=1)
                except (OSError, websocket.WebSocketException):
                    pass
        if time.monotonic() < deadline:
            time.sleep(min(2 ** min(failures, 5), max(0, deadline - time.monotonic())))


def replay_messages(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            if line.lstrip().startswith("{"):
                record = json.loads(line)
                if not isinstance(record.get("message"), str):
                    raise ValueError("Replay records need a string 'message' field")
                record["capture_mode"] = "synthetic" if record.get("capture_mode") == "synthetic" else "replay"
                yield record
            else:
                yield {"message": line.strip(), "received_at_utc": "", "capture_mode": "replay"}


def update_vehicle(vehicles: dict, row: dict) -> None:
    v = vehicles.setdefault(row["vehicle_id"], {
        "rows": 0, "valid_positions": 0, "first_gps_time_utc": "", "last_gps_time_utc": "",
        "positive_interval_count": 0, "interval_sum_seconds": 0.0,
        "min_interval_seconds": None, "max_interval_seconds": None,
        "duplicate_timestamps": 0, "out_of_order_timestamps": 0,
    })
    v["rows"] += 1
    if not row["valid_position"]:
        return
    v["valid_positions"] += 1
    current = row["gps_time_utc"]
    previous = v["last_gps_time_utc"]
    if previous:
        gap = (timestamp(current) - timestamp(previous)).total_seconds()
        if gap > 0:
            v["positive_interval_count"] += 1
            v["interval_sum_seconds"] += gap
            for kind, fn in (("min", min), ("max", max)):
                field = kind + "_interval_seconds"
                v[field] = gap if v[field] is None else fn(v[field], gap)
        elif gap == 0:
            v["duplicate_timestamps"] += 1
        else:
            v["out_of_order_timestamps"] += 1
    v["first_gps_time_utc"] = min(v["first_gps_time_utc"] or current, current)
    v["last_gps_time_utc"] = max(previous or current, current)


def collect(records: Iterator[dict], output: Path, stats: dict, key: str = "", overwrite: bool = False) -> int:
    paths = [output, output.with_suffix(".raw.jsonl"), output.with_suffix(".errors.jsonl"), output.with_suffix(".summary.json")]
    if len(set(paths)) != len(paths):
        raise ValueError("Output must have a .csv filename")
    if not overwrite and any(p.exists() for p in paths):
        raise FileExistsError("Output or a companion file exists; choose another name or use --overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    stats.update({"started_at_utc": utc_now(), "messages_received": 0, "rows_written": 0,
                  "valid_positions": 0, "parse_errors": 0, "vehicles": {}, "interrupted": False})
    with ExitStack() as stack:
        files = [stack.enter_context(p.open("w" if overwrite else "x", encoding="utf-8", newline="")) for p in paths]
        csv_file, raw_file, errors_file, summary_file = files
        writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
        writer.writeheader()
        try:
            for record in records:
                stats["messages_received"] += 1
                record = dict(record)
                record["message"] = redact(record["message"], key)
                raw_file.write(json.dumps(record, ensure_ascii=True) + "\n")
                try:
                    row = parse_message(record["message"], record.get("received_at_utc", ""), record.get("capture_mode", "replay"))
                except (ValueError, IndexError, OverflowError) as exc:
                    stats["parse_errors"] += 1
                    errors_file.write(json.dumps({"message_number": stats["messages_received"],
                                                 "error_type": type(exc).__name__, "error": redact(str(exc), key)}) + "\n")
                else:
                    # Prevent spreadsheet formula interpretation in untrusted text cells.
                    safe = {k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v) for k, v in row.items()}
                    writer.writerow(safe)
                    stats["rows_written"] += 1
                    stats["valid_positions"] += int(row["valid_position"])
                    update_vehicle(stats["vehicles"], row)
                csv_file.flush()
                raw_file.flush()
                errors_file.flush()
        except KeyboardInterrupt:
            stats["interrupted"] = True
        finally:
            close = getattr(records, "close", None)
            if close:
                close()
            stats["finished_at_utc"] = utc_now()
            stats["unique_vehicles"] = len(stats["vehicles"])
            stats["invalid_positions"] = stats["rows_written"] - stats["valid_positions"]
            for v in stats["vehicles"].values():
                n = v["positive_interval_count"]
                v["mean_interval_seconds"] = round(v["interval_sum_seconds"] / n, 6) if n else None
            summary_file.write(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(f"{stats['rows_written']} rows; {stats['valid_positions']} valid positions; {stats['unique_vehicles']} vehicles -> {output}")
    return 130 if stats["interrupted"] else (0 if stats["valid_positions"] else 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data") / ("oxyfi_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".csv"))
    parser.add_argument("--seconds", type=float, default=120, help="Batch duration, including retries; 0 runs until Ctrl+C (default: 120)")
    parser.add_argument("--max-retries", type=int, default=8, help="Consecutive retries after an initial failure")
    parser.add_argument("--replay", type=Path, help="Parse saved raw JSONL/NMEA instead of using the network")
    parser.add_argument("--overwrite", action="store_true", help="Replace output CSV and its three companion files")
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds < 0 or args.max_retries < 0:
        parser.error("seconds must be finite and nonnegative; max-retries must be nonnegative")
    if args.output.suffix.lower() != ".csv":
        parser.error("output filename must end with .csv")
    key = ""
    stats = {"mode": "replay" if args.replay else "live", "endpoint": ENDPOINT,
             "requested_duration_seconds": None if args.replay else args.seconds,
             "connection_attempts": 0, "successful_connections": 0, "connection_errors": 0}
    try:
        if args.replay:
            records = replay_messages(args.replay)
        else:
            key = os.environ.get("OXYFI_API_KEY", "").strip()
            if not key and sys.stdin.isatty():
                key = getpass.getpass("Oxyfi API key (hidden; not saved): ").strip()
            if not key:
                parser.error("Set OXYFI_API_KEY or run interactively to enter the key securely")
            records = live_messages(key, args.seconds, args.max_retries, stats)
        return collect(records, args.output, stats, key, args.overwrite)
    except (OSError, ValueError) as exc:
        print(redact(f"Error: {exc}", key), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
