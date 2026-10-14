"""Generate clearly synthetic multi-vehicle messages, never actual telemetry."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def make_records():
    start = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
    for second in range(10):
        instant = start + timedelta(seconds=second)
        for i in range(3):
            fields = ["GPRMC", instant.strftime("%H%M%S"), "A",
                      f"{5900 + i*100 + 10 + second*0.001:09.4f}", "N",
                      f"{1300 + i*100 + 20 + second*0.001:010.4f}", "E",
                      str(20+i*10), "45.0", instant.strftime("%d%m%y"), "", ""]
            payload = ",".join(fields)
            checksum = 0
            for char in payload:
                checksum ^= ord(char)
            message = f"${payload}*{checksum:02X},,{990001+i}.trains.se,,{8801+i}.public.trains.se@2020-01-01,synthetic-fixture"
            yield {"capture_mode": "synthetic",
                   "received_at_utc": (instant + timedelta(milliseconds=75)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                   "message": message}


if __name__ == "__main__":
    target = Path(__file__).with_name("synthetic.jsonl")
    target.write_text("".join(json.dumps(record) + "\n" for record in make_records()), encoding="utf-8")
    print(f"Wrote 30 SYNTHETIC records to {target}")
