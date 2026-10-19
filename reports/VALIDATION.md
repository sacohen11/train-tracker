# Initial validation — October 14, 2026

## Actual live attempt: failed before authentication

The exact collector was run against the official Oxyfi WebSocket using a key
supplied privately at runtime. It attempted one connection and received zero
messages. Name resolution in the execution environment failed with
`WebSocketAddressException`; checks against other external hosts also failed.
This does not establish that the Oxyfi service is unavailable or that the key is
invalid. Authentication, active-vehicle count, real update frequency, latency
and geographical accuracy remain unverified.

The saved `live_attempt.summary.json` records this failure. `live_attempt.csv`
contains only the header and **no real position rows**. A standalone connection
attempt also failed; see `live_connection_attempt.json`. Neither file contains
the API key. No alternate feed was silently substituted.

## Offline software validation: passed

`python -m unittest discover -s tests -v` completed 26 tests successfully on
Python 3.13.5 in the development runtime. See `unit_tests.txt` for the test log.
It includes parser, invalid-fix/checksum, file-output, secret-redaction,
multiple-vehicle, reconnect-error and replay tests. WebSocket transport in these
unit tests is mocked and cannot demonstrate provider connectivity.

The CLI replay wrote `examples/synthetic.csv`: 30 rows across three **fabricated**
vehicle IDs with artificial one-second GPS intervals. Every row is marked
`capture_mode=synthetic` and `source=synthetic-fixture`. Coordinates, timestamps,
service numbers, speed and latency are made up for testing. This is evidence of
the parser-to-CSV pipeline working, not evidence of current Swedish trains.

## Complete the live proof of concept

Run the documented 120-second collector locally, or configure the
`OXYFI_API_KEY` repository secret and manually run `Capture Oxyfi sample`.
Inspect the resulting summary for successful connections, valid positions and
multiple unique vehicle IDs. Check source timestamp freshness, checksum/fix
flags and per-vehicle intervals before reporting a live-data success.

The GitHub capture workflow was authored but has not been live-validated with a
repository secret by this initial implementation. No API key has been committed
or stored as a GitHub secret by this implementation.

## Baltic portable capture — October 19, 2026

Added `baltic/` with the Latvia/Estonia bounded collector, gap summary, map
builder, dependency pins and Mac mini handoff. Fixed output dates and Windows
paths were replaced with CLI arguments and fresh run directories. The existing
Sweden changes in the local working tree are outside this Baltic commit.

Using Python 3.13 on Windows in a fresh virtual environment, installed
`baltic/requirements.txt` and ran a 30-second live capture at approximately
20:49:38–20:50:08 UTC. Latvia recorded 261 valid rows across 9 service instances
from 67 WebSocket messages; Estonia recorded 30 valid observations across 2
service instances from 30 polls, skipping 30 duplicates. Both summaries reported
zero errors and complete state; the process exited successfully. Raw archives
and CSVs were written locally under ignored `data/`, not committed. No API keys
were required by these sources.

Rebuilt the recorded-data map and gap summary from the original 17 October
sample. The map encoded all 14,710 valid observations across 37 services. It
uses cached OSM/OpenRailwayMap tiles and loads D3 from a CDN. No rail snapping
or independently verified GPS accuracy is implied by this check.

The existing local Oxyfi suite passed 29 tests before the Baltic changes. Baltic
synthetic summary tests cover service/date/source separation, receipt ordering,
repeated/backward source times and empty input. These tests do not prove live
coverage. CLI validation also checks refusal to overwrite existing output and
rejection of a non-positive capture duration.

macOS execution, launchd installation, restart/reboot recovery, disk handling,
rotation, backups and continuous operation remain untested and unimplemented.
The Mac handoff explicitly lists that next stage. Reference pins were installed
on Windows; native macOS dependency installation still needs validation there.
