#!/usr/bin/env python3
"""Remove unneeded Latvia CSV columns while preserving every original record."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator


FIELDS = (
    "received_at_utc", "source_time_utc", "service_date", "train_id",
    "route_label", "latitude", "longitude", "is_gps_active",
)
REQUIRED = set(FIELDS) | {"country", "source"}


def compact_rows(rows: Iterable[dict[str, str]], stats: Counter) -> Iterator[dict[str, str]]:
    """Project columns only. Never parse, normalize, filter, buffer, or sort values.

    In particular, a new timestamp at an unchanged position is still an original
    report. Keep it, along with its exact timestamp spelling and global order.
    """
    for index, row in enumerate(rows, start=1):
        if None in row or any(row.get(key) is None for key in REQUIRED):
            raise ValueError(f"Input record {index}: missing columns or malformed CSV row")
        if row["country"] != "LV" or row["source"] != "Vivi public map stream":
            raise ValueError(f"Input record {index}: expected a Latvia Vivi recording")
        stats["input_rows"] += 1
        stats["output_rows"] += 1
        yield {key: row[key] for key in FIELDS}


def export(source: Path, destination: Path) -> dict:
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
            if len(reader.fieldnames or ()) != len(set(reader.fieldnames or ())):
                raise ValueError("Duplicate input column names")
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
                writer.writerows(compact_rows(reader, stats))
                outgoing.flush()
                os.fsync(outgoing.fileno())
        # The hard link atomically publishes the file without overwriting a
        # destination that another process may have created in the meantime.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        **stats, "output_columns": list(FIELDS), "removed_rows": 0,
        "source_bytes": source.stat().st_size,
        "output_bytes": destination.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Full Latvia CSV or CSV.gz")
    parser.add_argument("destination", type=Path, help="New eight-column CSV, with all rows")
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.destination), indent=2))


if __name__ == "__main__":
    main()
