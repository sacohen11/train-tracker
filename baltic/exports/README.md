# Latvia CSV downloads

Use the **map ZIPs** for plotting train paths and playback over time. Each
contains one ordinary CSV and a short guide. The full 38-column exports remain
available for detailed analysis.

| Berlin calendar date | Map download | Plain map CSV | Retained map points | Original reports | Services |
| --- | --- | ---: | ---: | ---: | ---: |
| 26 October 2026 | [Map ZIP](latvia-2026-10-26-Berlin-map.zip), 2.81 MB | 24.63 MB | 212,514 | 985,805 | 223 |
| 27 October 2026 | [Map ZIP](latvia-2026-10-27-Berlin-map.zip), 4.28 MB | 37.72 MB | 325,368 | 1,486,429 | 323 |

The two CSVs total 62.36 MB instead of 1,437.14 MB (95.66% smaller). Their ZIPs
total 7.09 MB instead of 57.11 MB (87.58% smaller). Sizes use decimal MB.

## Eight columns

| Column | Meaning |
| --- | --- |
| `service_id` | `LV:vivi:service_date:internal_id`; unique service instance, not a physical trainset. The source's service date is preserved across midnight. |
| `train_number` | Public train/service number shown by Vivi; keep it as text. |
| `received_at_utc` | When the recorder received this retained report. |
| `source_time_utc` | Vivi map-updater timestamp; not a verified onboard GPS-fix timestamp. |
| `latitude` | Provider position, with the original saved precision. |
| `longitude` | Provider position, with the original saved precision. |
| `is_gps_active` | Provider assertion: `true`, `false`, or blank for unknown. |
| `segment_start` | `1` starts a new line for this service; `0` continues it. |

All timestamps are UTC. File dates use the Berlin calendar: for example,
27 October includes reports beginning at 23:00 UTC on 26 October. The first
26 October report is at 09:05:05 UTC after a feed outage. No earlier positions
are reconstructed.

## Plotting

Group by `service_id`, sort by `received_at_utc`, and start a new polyline before
each point with `segment_start=1`. Label services with `train_number`. Style or
filter by `is_gps_active`; GPS-inactive reports have not been silently removed.

Use `segment_start` to identify breaks. A long interval between identical
retained points can be a continuous stop, because repeated reports were removed.
Do not infer a new outage solely from a large time difference in this compact
CSV. Interleaved services retain their own reception order. Each file starts
each service with a new segment, including services continuing across midnight.

## What was removed

Repeated source names, URLs, raw-file pointers, message IDs, empty fields,
animated coordinates, and diagnostic columns are omitted. Consecutive reports
at the same position and with the same GPS status and label are reduced to their
first and last actual reports. Intermediate repeated reports and their
individual timestamps are omitted from this derived map view.

Every recorded coordinate change is retained, along with the first and last
reports at each unchanged position. This preserves observed stop timing.
Coordinates are not rounded or snapped to tracks, and no positions or fixes are
interpolated. Segments break on gaps over 15 seconds in the **original** receipt
or source times, time regressions, quality changes, missing-source-time
transitions, invalid positions, and file boundaries. All positions in these
two source files passed the coordinate-validity checks.

For all original reports and timestamps, use the full archives:
[26 October](latvia-2026-10-26-Berlin.zip) and
[27 October](latvia-2026-10-27-Berlin.zip).

## Reproduce and verify

```sh
python3 baltic/compact_csv.py full-latvia.csv map-latvia.csv
python3 -m unittest discover -s baltic/tests -p 'test_compact_csv.py' -v
```

The exporter also accepts a full `.csv.gz` and refuses to overwrite an existing
destination. It does not change the live collector or the source archive.

Validation ran on both complete source files: all 537,882 retained points match
actual original reports; the sequence of every position/quality change and the
first/last timestamps of every unchanged run match the originals; all 1,330
segment starts were checked. ZIP contents were verified against the exported
CSV SHA-256 hashes. Thirteen focused tests cover stop timing, coordinate
precision, GPS unknown/false values, missing source times, gaps, regressions,
service identity, file boundaries, and safe output publication.

Source: the public Vivi map stream, `wss://trainmap.pv.lv/ws`. Repository code
licensing does not grant rights to provider data; live-feed redistribution
terms have not been verified.
