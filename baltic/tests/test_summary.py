"""Synthetic gap-analysis fixtures; these are not live train positions."""
import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('baltic_summary', Path(__file__).parents[1] / 'summarize.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class SummaryTests(unittest.TestCase):
    def analyse(self, records):
        fields = ['country', 'source', 'service_date', 'train_id', 'received_at_utc',
                  'source_time_utc', 'latitude', 'longitude', 'coordinates_valid']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.csv'
            with path.open('w', newline='', encoding='utf8') as handle:
                writer = csv.DictWriter(handle, fields)
                writer.writeheader()
                for record in records:
                    writer.writerow(dict(country='EE', source='synthetic-fixture',
                                         service_date='20260101', train_id='example',
                                         received_at_utc='2026-01-01T00:00:00Z',
                                         source_time_utc='', latitude='58', longitude='25',
                                         coordinates_valid='True') | record)
            return summary.summarize([path])

    def test_separate_services_dates_and_sources_never_create_cross_train_gaps(self):
        records = [dict(train_id='one'), dict(train_id='two'),
                   dict(train_id='one', service_date='20260102'),
                   dict(train_id='one', source='another-synthetic-fixture')]
        result = self.analyse(records)
        self.assertEqual(result['service_instances'], 4)
        for service in result['services']:
            self.assertEqual(service['receipt_gaps']['count'], 0)
            self.assertIsNone(service['positive_source_timestamp_gaps']['median_seconds'])

    def test_receipt_order_and_repeated_backward_source_timestamps(self):
        def row(receipt, source):
            return dict(received_at_utc=f'2026-01-01T00:00:{receipt:02d}Z',
                        source_time_utc=f'2026-01-01T00:00:{source:02d}Z')
        result = self.analyse([row(6, 3), row(0, 0), row(4, 4), row(2, 0)])['services'][0]
        self.assertEqual(result['receipt_gaps']['median_seconds'], 2)
        self.assertEqual(result['positive_source_timestamp_gaps']['median_seconds'], 4)
        self.assertEqual(result['backwards_source_timestamp_steps'], 1)
        self.assertEqual(result['repeated_source_timestamp_steps'], 1)
        self.assertEqual(result['coordinate_changes'], 0)

    def test_empty_capture(self):
        self.assertEqual(self.analyse([]), dict(rows=0, service_instances=0, services=[]))


if __name__ == '__main__':
    unittest.main()
