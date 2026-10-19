# Baltic train capture

Portable version of the Latvia/Estonia ten-minute prototype used on 17 October
2026. This records **passenger** services. It is a bounded capture tool; the
continuous Mac mini service is the next implementation task described in
[MAC_MINI_HANDOFF.md](MAC_MINI_HANDOFF.md).

## Mac quick start

From the repository root, using a native Python 3.11+ installation:

```sh
git pull --ff-only origin main
python3 -m venv baltic/.venv
source baltic/.venv/bin/activate
python -m pip install -r baltic/requirements.txt
python baltic/collect_10min.py --seconds 600 --output-dir data/baltic/sample
```

Choose a new output directory for each run. Omitting `--output-dir` creates a
UTC-named run folder under `data/baltic/`. Exit status is nonzero if either feed
produces no valid positions. HTTP/connect timeouts can extend the wall-clock
duration slightly beyond `--seconds`. Ctrl+C closes capture files.

Each run produces `latvia.csv`, `estonia.csv`, per-country `.summary.json` files
and `.raw.jsonl.gz` raw archives. Latvia raw records preserve exact WebSocket
text (or base64 for binary messages); Estonia preserves base64 protobuf bytes.
The original prototype stored parsed Latvia JSON, so the new raw payload wrapper
is different. All records retain receipt timestamps.

```sh
python baltic/summarize.py data/baltic/sample/latvia.csv data/baltic/sample/estonia.csv --output data/baltic/sample/gaps.json
python baltic/build_map.py data/baltic/sample/latvia.csv data/baltic/sample/estonia.csv --output data/baltic/sample/map.html
open data/baltic/sample/map.html
```

The map includes all valid saved coordinates, service selection and a switchable
railway layer. It needs internet access to fetch uncached OSM/OpenRailwayMap tiles
when built, and D3 from jsDelivr when opened. It caches tiles under
`data/baltic/tile-cache`; use `--cache-dir` to change this. It is a snapshot with
fixed-resolution tiles, not a live map or a rail-snapped reconstruction. Use
bounded capture windows rather than mapping an entire long-term archive.

## Feeds and interpretation

| Country | Feed | Counting and timing |
| --- | --- | --- |
| Latvia | `wss://trainmap.pv.lv/ws` ([Vivi map](https://trainmap.vivi.lv/)) | One row per train per received snapshot, including repeats. `updaterTimeStamp` is a map-updater timestamp, not a verified onboard GPS-fix time. |
| Estonia | [Elron community GTFS-RT relay](https://jbb.ghsq.de/gtfs/elron/VehiclePositions) | Polls every second by default; `--poll-interval` changes this. Deduplicates trip/date/source timestamp/coordinates. Polling frequency does not imply fresh positions at that frequency. |

Neither source needed an API key during testing. Availability and source schemas
can change. Estonia uses a community relay, not an operator-guaranteed API.
Code licensing does not grant rights to provider data; live-feed redistribution
terms have not been established here. Captured data is excluded from this commit.

CSV columns:

```text
country,source,received_at_utc,source_time_utc,timestamp_kind,service_date,train_id,vehicle_id,route_label,latitude,longitude,coordinates_valid,is_gps_active,position_method,animated_latitude,animated_longitude,source_url
```

`train_id` identifies a trip/service, not necessarily a physical trainset. Group
history by source, service date and service ID. `vehicle_id` remains separate and
may be empty. Latitude/longitude are provider `position`; animated coordinates
are stored separately. Basic coordinate validity does not establish GPS accuracy.
Latvia's GPS flag is the provider's assertion; missing flags remain unknown.
Source timestamps retain their provided representation/offset in the prototype;
receipt timestamps use UTC. `service_date` currently follows each feed's format
(Latvia ISO date, Estonia GTFS YYYYMMDD).

The map breaks paths at receipt gaps over 15 seconds, Latvia quality changes,
and Estonia source gaps over 15 seconds or backward timestamps. It uses separate
styles for reported, GPS-active, inactive/estimated and unknown positions. The
gap summary measures successive reports within each service; it does not
subtract timestamps from unrelated trains.

## Validation and next steps

See [validation notes](../reports/VALIDATION.md) for what was actually tested.
The original ten-minute capture recorded 9,946 Latvia rows and 4,764 Estonia
observations across 37 service instances. Original CSVs and raw archives remain
separate from the repository.

The collector still has in-memory sets, fixed retry delays and no rotation,
durable restart state, service installer or long-running health monitoring.
Do not simply set an enormous duration and treat it as the completed always-on
service. Follow the Mac handoff to implement and test that service locally.
