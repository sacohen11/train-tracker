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
