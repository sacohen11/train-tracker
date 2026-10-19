"""Summarize observation gaps within each country/source/service/date series."""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def distribution(values):
    if not values:
        return {'count': 0, 'median_seconds': None, 'p95_seconds': None, 'max_seconds': None}
    values = sorted(values)
    return dict(count=len(values), median_seconds=round(statistics.median(values), 3),
                p95_seconds=round(values[math.ceil(.95 * len(values)) - 1], 3),
                max_seconds=round(values[-1], 3))


def summarize(paths):
    groups = defaultdict(list)
    for path in paths:
        with path.open(newline='', encoding='utf8') as handle:
            for row in csv.DictReader(handle):
                key = tuple(row[k] for k in ('country', 'source', 'service_date', 'train_id'))
                groups[key].append(row)
    results = []
    for (country, source, date, train_id), rows in sorted(groups.items()):
        rows.sort(key=lambda row: stamp(row['received_at_utc']))
        receipts, sources = [], []
        backwards = repeated = changes = 0
        for previous, current in zip(rows, rows[1:]):
            receipts.append(stamp(current['received_at_utc']) - stamp(previous['received_at_utc']))
            if previous['source_time_utc'] and current['source_time_utc']:
                gap = stamp(current['source_time_utc']) - stamp(previous['source_time_utc'])
                if gap > 0:
                    sources.append(gap)
                elif gap < 0:
                    backwards += 1
                else:
                    repeated += 1
            changes += (previous['latitude'], previous['longitude']) != (current['latitude'], current['longitude'])
        results.append(dict(country=country, source=source, service_date=date, train_id=train_id,
                            rows=len(rows), valid_coordinate_rows=sum(r['coordinates_valid'] == 'True' for r in rows),
                            first_received_utc=rows[0]['received_at_utc'], last_received_utc=rows[-1]['received_at_utc'],
                            receipt_gaps=distribution(receipts), positive_source_timestamp_gaps=distribution(sources),
                            backwards_source_timestamp_steps=backwards, repeated_source_timestamp_steps=repeated,
                            coordinate_changes=changes))
    return dict(rows=sum(r['rows'] for r in results), service_instances=len(results), services=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_files', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = json.dumps(summarize(args.csv_files), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + '\n', encoding='utf8')
    else:
        print(output)


if __name__ == '__main__':
    main()
