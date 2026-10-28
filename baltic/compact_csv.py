#!/usr/bin/env python3
"""Create small Latvia map CSVs without changing the original recordings."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


FIELDS = (
    "service_id", "train_number", "received_at_utc", "source_time_utc",
    "latitude", "longitude", "is_gps_active", "segment_start",
)
REQUIRED = {
    "country", "source", "service_date", "train_id", "route_label",
    "received_at_utc", "source_time_utc", "latitude", "longitude",
    "coordinates_valid", "is_gps_active",
}


def flag(value: str) -> str:
    value = value.strip().lower()
    if value in ("true", "1"):
        return "true"
    if value in ("false", "0"):
        return "false"
    if value == "":
        return ""
    raise ValueError("Unrecognized boolean flag")


def timestamp(value: str, *, optional: bool = False) -> datetime | None:
    if not value and optional:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return result.astimezone(timezone.utc)


def utc_text(value: datetime | None) -> str:
    if value is None:
        return ""
    text = value.isoformat().removesuffix("+00:00")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + "Z"


@dataclass(frozen=True)
class Point:
    index: int
    service: str
    number: str
    received: datetime
    source_time: datetime | None
    latitude: str
    longitude: str
    gps: str
    stale: str
    valid: bool

    @property
    def map_state(self) -> tuple[str, ...]:
        return self.latitude, self.longitude, self.gps, self.number, self.stale

    def output(self, segment_start: bool) -> dict[str, str]:
        return dict(zip(FIELDS, (
            self.service, self.number, utc_text(self.received),
            utc_text(self.source_time), self.latitude, self.longitude,
            self.gps, "1" if segment_start else "0",
        )))


def parse_point(row: dict[str, str], index: int) -> Point:
    if row["country"] != "LV" or row["source"] != "Vivi public map stream":
        raise ValueError("This exporter expects Latvia Vivi recordings")
    service_date = date.fromisoformat(row["service_date"]).isoformat()
    if not row["train_id"]:
        raise ValueError("Service has no train_id")
    service = f"LV:vivi:{service_date}:{row['train_id']}"
    lat, lon = row["latitude"], row["longitude"]
    try:
        latitude, longitude = float(lat), float(lon)
        valid = (math.isfinite(latitude) and math.isfinite(longitude)
                 and -90 <= latitude <= 90 and -180 <= longitude <= 180)
    except ValueError:
        valid = False
    valid = valid and flag(row["coordinates_valid"]) == "true"
    received = timestamp(row["received_at_utc"])
    assert received is not None
    return Point(
        index, service, row["route_label"], received,
        timestamp(row["source_time_utc"], optional=True), lat, lon,
        flag(row["is_gps_active"]), flag(row.get("source_time_stale", "")), valid,
    )


def break_reason(previous: Point, current: Point, max_gap: float) -> str | None:
    gap = (current.received - previous.received).total_seconds()
    if gap < 0:
        return "receipt_time_regression"
    if gap > max_gap:
        return "receipt_gap"
    if (previous.source_time is None) != (current.source_time is None):
        return "source_time_availability"
    if previous.source_time is not None and current.source_time is not None:
        gap = (current.source_time - previous.source_time).total_seconds()
        if gap < 0:
            return "source_time_regression"
        if gap > max_gap:
            return "source_gap"
    if previous.gps != current.gps or previous.stale != current.stale:
        return "quality_change"
    if previous.number != current.number:
        return "train_number_change"
    return None


def compact_rows(
    rows: Iterable[dict[str, str]], stats: Counter, max_gap: float = 15.0,
) -> Iterator[dict[str, str]]:
    """Retain each unchanged run's real first/last rows, with explicit gaps.

    State is bounded by the number of services in this finite input file.
    Rows remain in receipt order within each service; different services may
    be interleaved. No positions, timestamps, or intermediate fixes are made up.
    """
    if not math.isfinite(max_gap) or max_gap <= 0:
        raise ValueError("max_gap must be finite and positive")
    previous: dict[str, Point] = {}
    emitted: dict[str, int] = {}
    services: set[str] = set()
    for index, row in enumerate(rows, start=1):
        stats["input_rows"] += 1
        try:
            if None in row or any(row.get(key) is None for key in REQUIRED):
                raise ValueError("Missing columns or malformed CSV row")
            current = parse_point(row, index)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Input record {index}: {exc}") from exc
        key = current.service
        services.add(key)
        last = previous.get(key)
        if not current.valid:
            stats["invalid_coordinate_rows"] += 1
            if last is not None and last.index != emitted[key]:
                stats["output_rows"] += 1
                yield last.output(False)
            previous.pop(key, None)
            emitted.pop(key, None)
            continue
        reason = "first_or_after_invalid" if last is None else break_reason(last, current, max_gap)
        changed = last is None or current.map_state != last.map_state
        if reason or changed:
            if last is not None and last.index != emitted[key]:
                stats["output_rows"] += 1
                yield last.output(False)
            stats["output_rows"] += 1
            if reason:
                stats["segments"] += 1
                stats[f"break_{reason}"] += 1
            yield current.output(bool(reason))
            emitted[key] = current.index
        previous[key] = current
    for key, last in previous.items():
        if last.index != emitted[key]:
            stats["output_rows"] += 1
            yield last.output(False)
    stats["services"] = len(services)
    stats["removed_repeat_rows"] = (stats["input_rows"] - stats["output_rows"]
                                    - stats["invalid_coordinate_rows"])


def export(source: Path, destination: Path, max_gap: float = 15.0) -> dict:
    """Write a new CSV atomically; refuse to replace any existing file."""
    if destination.exists():
        raise FileExistsError(destination)
    stats: Counter = Counter()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        opener = gzip.open if source.suffix == ".gz" else open
        with opener(source, "rt", encoding="utf-8-sig", newline="") as incoming:
            reader = csv.DictReader(incoming)
            missing = REQUIRED - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"Missing input columns: {', '.join(sorted(missing))}")
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=destination.parent,
                prefix=f".{destination.name}.", suffix=".part", delete=False,
            ) as outgoing:
                temporary = Path(outgoing.name)
                writer = csv.DictWriter(outgoing, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(compact_rows(reader, stats, max_gap))
                outgoing.flush()
                os.fsync(outgoing.fileno())
        # The hard link atomically publishes the file without overwriting a
        # destination that another process may have created in the meantime.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        **stats, "output_columns": list(FIELDS), "max_gap_seconds": max_gap,
        "source_bytes": source.stat().st_size,
        "output_bytes": destination.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Full Latvia CSV or CSV.gz")
    parser.add_argument("destination", type=Path, help="New compact CSV")
    parser.add_argument("--max-gap-seconds", type=float, default=15.0)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.destination, args.max_gap_seconds), indent=2))


if __name__ == "__main__":
    main()
