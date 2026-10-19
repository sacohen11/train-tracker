# Mac mini implementation handoff

Prepared 19 October 2026. The user wants an always-on recorder for Latvia and
Estonia passenger-train positions, using their existing always-running Mac mini
to build historical data. This repository contains the working bounded capture
prototype and map builder. Nothing has yet been installed or verified on the Mac.

## Task for the local Mac assistant

Implement and install a reliable continuous recorder using `collect_10min.py`
as the feed-parsing reference. Preserve raw source evidence, timestamps and
position-quality flags. Save daily archives and provide normal CSV exports by
country and time range. Configure automatic startup/recovery, document status
and stop commands, and test actual behavior on this Mac. Do not include the
Sweden or Ireland collectors in this deployment unless separately requested.

The user wants high temporal resolution, ideally one second, all available
trains and records, and maps with a railway-track overlay. Polling and repeated
snapshots must not be represented as newly measured one-second GPS fixes.
The earlier 25 MB export limit applied to a Sweden download, not this archive.

## Preserve the feed semantics

- Latvia: connect to `wss://trainmap.pv.lv/ws`, no subscription message or API key
  was needed. Train snapshots have `type == "back-end"`; each `data` item has a
  `returnValue`. Preserve `id`, `train`, `departureTime`, `position` (latitude,
  longitude), `animatedCoord`, `updaterTimeStamp`, and `isGpsActive`. Retain
  non-train raw messages too. The updater time is not verified as an onboard
  GPS-fix time. Unknown GPS flags must stay unknown.
- Estonia: fetch `https://jbb.ghsq.de/gtfs/elron/VehiclePositions` and decode
  `google.transit.gtfs_realtime_pb2.FeedMessage`. Preserve vehicle trip ID and
  start date, position, source timestamp, vehicle ID/label and route ID when
  supplied. The direct operator map endpoint previously returned HTTP 403;
  the successful collection used this community relay.
- Estonia deduplication currently uses `(trip_id, start_date, timestamp,
  latitude, longitude)`. Keep stationary reports with new timestamps. Define
  treatment of missing identity/time fields and changed quality metadata before
  designing persistent uniqueness constraints. Keep raw snapshots separately.
- Keep receipt time separate from source time. Preserve original time strings
  in raw data and normalize derived timestamps to UTC. Resolve service dates
  using source-local trip semantics (Europe/Riga and Europe/Tallinn), including
  overnight trips. Do not substitute the computer's date for service date.
- These are passenger feeds. No equivalent free public Baltic freight GPS feed
  was verified. No unrestricted live-data redistribution licence was verified.

## Reference capture and observed cadence

On 17 October 2026, roughly 09:14:47–09:24:47 UTC:

| | Latvia | Estonia |
| --- | ---: | ---: |
| CSV rows | 9,946 snapshot rows | 4,764 distinct observations |
| Service instances | 17 | 20 |
| Median receipt gap within service | 1.001 s | 2.029 s |
| Median positive source timestamp gap | 3.053 s | 2 s |
| 95th percentile positive source timestamp gap | 8.077 s | 4 s |
| Maximum positive source timestamp gap | 12.965 s | 55 s |

Latvia had 6,289 GPS-flag-active and 3,657 inactive rows; its coordinate-change
interval median was about 3.044 seconds. Estonia skipped 5,797 repeated
observations over 591 polls and had one backward source-time step. Both recorded
zero capture errors. These are short-sample measurements, not service guarantees.
There were 14,710 combined observations across 37 services.

The original capture and transfer ZIP are separate artifacts, not committed
here. The map uses recorded positions without snapping to track geometry and
disconnects gaps over 15 seconds. Latvia raw data used about 14.7 MB compressed
in ten minutes, so measure actual storage growth before choosing retention.

## Continuous recorder requirements

1. Run feeds independently so an outage in one does not stop the other. Add
   timeouts, exponential backoff with jitter and rate-limit handling. Distinguish
   healthy empty feeds from stale connections.
2. Replace unbounded seen-key, service-ID and error collections with bounded or
   persistent state. SQLite plus chunked raw archives and CSV exports is a
   reasonable starting point; a server database is not required.
3. Rotate raw archives hourly/daily and keep frequent durable checkpoints.
   Handle SIGTERM, interrupted writes, restarts and date boundaries. Ensure
   only one recorder instance runs. Preserve history on upgrades.
4. Parse bad/missing fields defensively without dropping valid trains elsewhere
   in a batch. Surface backward/stale source timestamps and gaps; do not invent
   missed observations or interpolate them into the raw dataset.
5. Expose per-feed last successful response, last fresh source observation, row
   counts, recent errors, uptime and disk space. Bound logs. Agree on retention
   before deleting historical data; configure and verify backups to a chosen
   second destination.
6. Provide ordinary CSV export by country/date/time range and bounded-window
   maps. Retain provenance if importing historical data from elsewhere.

The port in this commit removes fixed dates/Windows paths and adds CLI controls;
it does not implement the service requirements above. Python dependencies are
reference pins tested on Windows, not proof of macOS deployment.

## macOS deployment and acceptance checks

Inspect the actual macOS version, processor, native Python, permissions and free
disk space first. Install a Mac-native virtual environment. Use `launchd`; choose
a LaunchDaemon if operation must be independent of login, or a LaunchAgent if a
login-bound service is acceptable. Run the collector under an unprivileged
account. Document install, start, stop, status, export, update and uninstall.

Prevent system sleep while allowing display sleep. Test recovery after restart
and power failure; inspect FileVault/unlock behavior rather than assuming that
an unattended cold boot reaches a running collector. No inbound public port or
public website is needed.

Run bounded live checks for both sources, then test network loss/reconnection,
process crash/restart, midnight rotation, clean shutdown, repeated snapshots,
stationary fresh reports, malformed rows and backup restoration. Check the
service survives closing Terminal and behaves as documented after logout and
reboot. Report what actually passed and what remains untested on the Mac.

## Possible historical backfill

As checked on 19 October 2026, the [European Train Archive Elron page](https://www.train-archive.eu/providers/ee-elron?service=VehiclePosition)
listed VehiclePosition history from 28 September. Its [connection guide](https://www.train-archive.eu/connect)
describes downloads/API access and public object storage. A range request
verified a Parquet header for the 18 October file, but a complete day was not
analysed. General archive polling is described as 30 seconds to 2 minutes; exact
Elron cadence remains unmeasured. Recheck current coverage and access details.
Keep archive provenance separate from the higher-frequency local capture.

No public Latvia historical position archive was verified. Vivi timetable
history does not reconstruct measured train locations. Start collecting now;
an older export would require finding another archive or asking the operator.
