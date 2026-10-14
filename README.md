# Train Tracker

A Python proof of concept for collecting **all reporting vehicles** from Sweden's
Oxyfi Trainpos WebSocket into CSV. One connection receives interleaved updates
from multiple vehicles; there is no single-train or single-line subscription.

**Validation status:** 26 automated tests pass locally. The live connection
attempt on October 14, 2026 failed at DNS resolution in the development runtime,
before authentication. **No live train positions have been captured or verified
by this initial implementation.** `examples/synthetic.csv` is explicitly
synthetic test data, not a substitute for a successful live capture. See
[`reports/VALIDATION.md`](reports/VALIDATION.md).

## Run a real two-minute capture

Requires Python 3.11+ and network access to `api.oxyfi.com` over WSS/443.

```bash
git clone https://github.com/sacohen11/train-tracker.git
cd train-tracker
python -m venv .venv
```

Activate the environment on macOS/Linux:

```bash
source .venv/bin/activate
```

Or, without changing PowerShell execution policy, use the environment's Python
explicitly on Windows: replace `python` below with `.venv\Scripts\python.exe`.

```bash
python -m pip install -r requirements.txt
python collect_oxyfi.py --seconds 120 --output data/first_batch.csv
```

The collector securely prompts for your API key when run in an interactive
terminal. The key is hidden during entry, is not saved, and is not a command-line
argument. For unattended execution, supply the `OXYFI_API_KEY` environment
variable through your secret manager. `.env.example` is only a template; `.env`
files are **not** automatically loaded. Do not put your key in source code,
workflow inputs, GitHub issues, URLs in logs, or committed files.

Run only **one collector per key**. The provider closes an existing connection
when another subscription uses that same key.

## Outputs

For `data/first_batch.csv`, the collector creates:

| File | Contents |
| --- | --- |
| `first_batch.csv` | Parsed rows with decimal coordinates and validation flags |
| `first_batch.raw.jsonl` | Original messages, receipt timestamps and capture mode; any key is redacted |
| `first_batch.errors.jsonl` | Parse-error types and original message indices |
| `first_batch.summary.json` | Counts, connection errors and per-vehicle sampling statistics |

An empty/erroring feed produces **zero data rows and a nonzero exit code**, not
invented positions. Files are flushed after each message. Existing output files
are protected; `--overwrite` explicitly replaces the CSV and its companion
files. Do not replay from an output file that you are about to overwrite.
Use `--seconds 0` to collect until Ctrl+C; there is no automatic file rotation,
so monitor disk usage for long captures. Bounded runs include connection and
retry time in their duration and may stop earlier on a terminal error.

Exit codes: `0` = at least one valid position; `2` = usage/file error;
`3` = no valid positions; `130` = interrupted. A successful exit does not by
itself prove multi-vehicle coverage or that every observation was valid.

### CSV schema

| Column(s) | Meaning |
| --- | --- |
| `capture_mode` | `live`, `replay`, or `synthetic` |
| `received_at_utc`, `gps_time_utc` | Collector receipt time and onboard GPS fix time |
| `vehicle_id`, `vehicle_ref` | Physical vehicle identity, distinct from a train service number |
| `public_train_numbers`, `internal_train_numbers`, `train_refs` | Semicolon-separated service references; may be empty or multiple |
| `latitude`, `longitude` | Decimal degrees converted from NMEA degrees/minutes; numeric precision is not an accuracy guarantee |
| `speed_knots`, `speed_kmh`, `heading_deg` | Reported ground speed and true-north heading |
| `fix_status`, `checksum_valid`, `valid_position` | NMEA fix status and local validation flags |
| `latency_seconds` | Receipt time minus GPS time; includes clock error and source timestamp precision, not just network delay |
| `source`, `raw_nmea` | Source tag and original extended RMC message |

Filter `valid_position == True` for structurally valid active fixes with valid
checksums. A valid flag does not guarantee the physical location is correct or
fresh; separately check timestamps, outliers, and the supplied service mapping.
A recognizable row with a void fix or bad checksum is retained and flagged.
A structurally malformed message goes into raw JSONL and the error log, not CSV.

Per-vehicle summaries count repeated and out-of-order GPS timestamps. Their
min/mean/max interval statistics use successive increasing source timestamps,
not the overall number of messages arriving across all trains. Receipt-clock
synchronization matters when interpreting latency. A physical train can contain
multiple reporting units, so distinct vehicle IDs do not necessarily equal
distinct train services, lines, or independently moving trains.

## Capture on GitHub Actions instead

The manually triggered **Capture Oxyfi sample** workflow runs one short batch on
a GitHub runner. It is not a background service and has no scheduled trigger.

1. Open repository **Settings -> Secrets and variables -> Actions -> New
   repository secret**. Name it `OXYFI_API_KEY` and enter your key there.
2. Open **Actions -> Capture Oxyfi sample -> Run workflow**, select a duration
   (default: 120 seconds), and run it on `main`.
3. When it finishes, download the `oxyfi-sample-<run-id>` artifact. It contains
   CSV, raw JSONL, errors and summary JSON. A failed connection still produces
   diagnostics when available.

The workflow serializes its own runs so they do not steal each other's stream;
it cannot prevent a local collector using the same key. Stop other collectors
first. Do not pass the API key as a manual workflow input. Artifacts from this
public repository should be treated as public data; the workflow scans capture
files for the key before uploading them. Code is checked out with Git credentials
not persisted, and workflow permissions are read-only. Only the capture step and
its secret scan receive the Oxyfi key. The repository secret was **not** set by
the initial implementation.

## Tests and reproducible synthetic example

```bash
python -m unittest discover -s tests -v
python collect_oxyfi.py --replay tests/fixtures/synthetic.jsonl --output data/synthetic.csv
```

The fixture contains 30 **fabricated** messages for three made-up vehicle IDs,
with synthetic 2020 timestamps and one-second spacing. Neither that cadence nor
its artificial latency measures the real service. Every output row is labelled
`synthetic`. Regenerate the fixture with:

```bash
python tests/fixtures/generate.py
```

The tests cover coordinate conversion, timestamps, checksums, invalid fixes,
multiple vehicles, service references, reconnection errors, secret redaction,
output safety, replay labelling and interval summaries. The mocked transport
checks software behavior, **not** live endpoint availability. CI runs these
checks without API credentials. Replaying a real capture labels output `replay`,
not `live`.

## Feed documentation and limitations

Provider specification: https://www.trafiklab.se/api/our-apis/oxyfi/

Endpoint (the collector adds the key privately):

```text
wss://api.oxyfi.com/trainpos/listen?v=1&key=YOUR_KEY
```

The provider documents onboard GPS updates about once per second for each
powered, connected reporting vehicle. It is a participating-fleet feed, not all
Swedish trains, and live vehicle count and availability must be measured. The
provider also warns that the vehicle-to-service assignment is not verified.
No live coverage, delivery-latency or geographic-accuracy benchmark has yet been
performed for this repository. The source format is extended NMEA RMC, not JSON;
unsupported changes are retained in raw capture and flagged rather than guessed.

GitHub secrets documentation:
https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

The MIT license covers this project's code and synthetic fixtures, not Oxyfi or
other third-party data. Review provider terms before redistributing real captures.
