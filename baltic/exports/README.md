# Latvia CSV downloads

Use the **corrected v2 map ZIPs** below. Each contains one ordinary CSV with
eight columns and a short guide. Every original row is preserved in its
original order, with exactly the original timestamp strings, coordinates,
identifiers and GPS flags. Only columns are removed.

| Berlin calendar date | Corrected download | Plain CSV | Original rows retained | Services |
| --- | --- | ---: | ---: | ---: |
| 26 October 2026 | [v2 ZIP](latvia-2026-10-26-Berlin-map-v2.zip), 6.55 MB | 117.31 MB | 985,805 | 223 |
| 27 October 2026 | [v2 ZIP](latvia-2026-10-27-Berlin-map-v2.zip), 9.92 MB | 176.88 MB | 1,486,429 | 323 |

The plain CSVs total 294.19 MB instead of 1,437.14 MB: **79.53% smaller**.
The ZIPs total 16.47 MB instead of 57.11 MB: **71.16% smaller**. Sizes use
decimal MB. An overnight service can appear in both files, so the service
counts should not be added to obtain a unique two-day count.

## Correction from the first map export

The earlier `-map.zip` files removed intermediate stationary reports,
reformatted timestamps with variable fractional precision, and buffered rows
in a way that changed the overall receipt-time order. This introduced large
apparent gaps and could cause datetime import failures. They are superseded
by `-map-v2.zip` and removed from the current repository tree. Old versions
remain in Git history; use the v2 files for new work.

The v2 exporter does not thin, deduplicate, sort, normalize or interpolate
records. It preserves repeated positions and their timestamps, including
exact duplicate reports if present. It also retains missing or invalid
values if present instead of silently deleting those rows. All coordinates
in these two particular source files passed the original validity checks.
The live collector and full source archives are unchanged.

## Eight original columns

| Column | Meaning |
| --- | --- |
| `received_at_utc` | Receipt time. Use this for playback chronology. |
| `source_time_utc` | Vivi map-updater timestamp; not a verified onboard GPS-fix timestamp. |
| `service_date` | Original source service date, preserved across midnight. |
| `train_id` | Original internal service identifier; keep as text. |
| `route_label` | Public train/service number shown by Vivi; keep as text. |
| `latitude` | Provider position, with the exact saved precision. |
| `longitude` | Provider position, with the exact saved precision. |
| `is_gps_active` | Original provider assertion: `True`, `False`, or blank for unknown. |

Group tracks by **(`service_date`, `train_id`)** and label them with
`route_label`. This identifies a service instance, not a physical trainset.
Different trains are interleaved in the CSV; group them before connecting
points. All rows remain in the original global receipt-time order. There is
no derived `service_id` or `segment_start` field in v2.

Both timestamp columns retain the original ISO 8601 spelling with six
fractional digits and `+00:00`, for example
`2026-10-26T09:05:05.110318+00:00`. Import them as timezone-aware UTC values.
Filenames use Berlin calendar days: the 27 October file begins at 23:00 UTC
on 26 October. A source service date can also be earlier than the filename
for an overnight service. These differences are intentional and unchanged.

Source timestamps can repeat or move backward. There are 79 backward steps
on 26 October and 280 on 27 October, already present in the original data.
Receipt times in these files never move backward. For playback use
`received_at_utc`, retaining `source_time_utc` as separate source evidence.

## Gaps and coverage

The corrected files have exactly the original per-service receipt gaps:

| Date | Gaps over 15 seconds | Longest gap within a service |
| --- | ---: | ---: |
| 26 October | 53 | 333.650 seconds |
| 27 October | 66 | 53.315 seconds |

These are between consecutive recorded reports for the same service within
each file. They do not measure missing time before the first or after the
last report. The first 26 October report is at 09:05:05 UTC; no earlier
positions are reconstructed. No additional gaps are introduced by the v2
export, and no real gaps are filled. Choose line breaks in the plotting
application based on receipt gaps and the quality flags.

For the complete original 38 columns, the unchanged full archives are:
[26 October](latvia-2026-10-26-Berlin.zip) and
[27 October](latvia-2026-10-27-Berlin.zip).

## Reproduce and verify

```sh
python3 baltic/compact_csv.py full-latvia.csv map-latvia-v2.csv
python3 -m unittest discover -s baltic/tests -p 'test_compact_csv.py' -v
```

The exporter also accepts a full `.csv.gz` and refuses to overwrite an
existing destination. It preserves the selected values as strings and never
parses timestamps or converts coordinates.

Validation on both complete files compared **all 19,777,872 selected cells
across 2,472,234 rows** with the originals, in order: zero changed values,
zero missing rows and zero extra rows. Original CSV checksums were unchanged.
Every value in both timestamp columns parsed successfully with pandas 2.2.3.
Eleven focused regression tests passed, including interleaved trains,
stationary reports, original timestamp precision, overnight service identity,
source-time regressions, unknown flags, malformed input and safe publication.
ZIP contents were checked against the CSV SHA-256 hashes below.

| Date | CSV SHA-256 |
| --- | --- |
| 26 October | `12b1accf575ae97ee3b8592e05d89114e6339cc278766eca21fc08e54d03f843` |
| 27 October | `0c18e61b8eea17bebc27e68f38d4243ec0e67670a4f5aae668dc0fd0caba806b` |

Source: the public Vivi map stream, `wss://trainmap.pv.lv/ws`. Repository code
licensing does not grant rights to provider data; live-feed redistribution
terms have not been verified.
