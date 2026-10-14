# Development instructions

Python 3.11+, standard library plus websocket-client. Install requirements and
run `python -m unittest discover -s tests -v` before changing the collector.

Never commit, print, log, or echo API keys or authenticated WebSocket URLs.
Read OXYFI_API_KEY only from the environment or a hidden interactive prompt.
Use one live Oxyfi connection per key. Do not add a scheduled live job unless
explicitly requested. Never classify synthetic or replayed records as live.

Retain original source messages and receipt timestamps, validate RMC checksums,
keep vehicle identity separate from service numbers, preserve void-fix flags,
and return a nonzero result when no valid positions were collected. Measure
update cadence per vehicle, not over the combined stream. Record untested live
behavior honestly in reports/VALIDATION.md. Keep code and transit-data licensing
separate. Live coverage is not proven by passing mocked transport tests.
