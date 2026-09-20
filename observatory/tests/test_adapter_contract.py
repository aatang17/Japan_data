"""The contract between an adapter and the store.

One rule so far, and it earned its place the hard way: an observation is
dated with a datetime.date. ust-yields and ust-real-yields emitted strings
that looked like dates, which cost six days of failed ingests and surfaced as
a primary key violation on a 1990 row — a very long way from the two lines
that caused it.
"""
import datetime
import unittest

from app import ingest
from app.adapters import ust_yields


class Adapter(object):
    """Stands in for a real adapter: the checker needs only its error type."""
    ValidationError = ust_yields.ValidationError


class CheckPeriodsTest(unittest.TestCase):
    def check(self, observations):
        ingest._check_periods(Adapter, "test-dataset", observations)

    def test_dates_pass(self):
        self.check([{"code": "10Y", "period": datetime.date(2026, 9, 18),
                     "value": 5.01}])

    def test_empty_passes(self):
        """An adapter that legitimately parsed nothing is validate()'s
        business, not this check's."""
        self.check([])

    def test_a_string_that_looks_like_a_date_is_rejected(self):
        with self.assertRaises(ust_yields.ValidationError) as caught:
            self.check([{"code": "10Y", "period": "2026-09-18", "value": 5.01}])
        self.assertIn("datetime.date", str(caught.exception))

    def test_a_datetime_is_rejected_too(self):
        """A datetime is a date subclass, so an isinstance check would wave it
        through and store a silent midnight."""
        with self.assertRaises(ust_yields.ValidationError):
            self.check([{"code": "10Y",
                         "period": datetime.datetime(2026, 9, 18, 0, 0),
                         "value": 5.01}])

    def test_one_bad_row_among_many_is_caught(self):
        rows = [{"code": "10Y", "period": datetime.date(2026, 9, d), "value": 5.0}
                for d in range(1, 19)]
        rows.append({"code": "10Y", "period": "2026-09-19", "value": 5.0})
        with self.assertRaises(ust_yields.ValidationError):
            self.check(rows)

    def test_the_message_names_the_dataset_and_what_arrived(self):
        """The old failure said 'duplicate key 667660, 1990-01-02, 65'. This
        one has to be readable at 3am."""
        with self.assertRaises(ust_yields.ValidationError) as caught:
            self.check([{"code": "10Y", "period": "1990-01-02", "value": 7.9}])
        message = str(caught.exception)
        self.assertIn("test-dataset", message)
        self.assertIn("1990-01-02", message)
        self.assertIn("str", message)


class TreasuryParseTest(unittest.TestCase):
    """The specific adapters that had it wrong."""

    CSV = (b'Date,"1 Mo","3 Mo","10 Yr"\n'
           b"09/18/2026,4.10,4.14,5.01\n"
           b"09/17/2026,4.11,4.15,4.99\n")

    def test_parse_file_dates_rows_with_a_date(self):
        parsed = ust_yields._parse_file(self.CSV, "test")
        for period in parsed:
            self.assertIsInstance(period, datetime.date)
            self.assertNotIsInstance(period, str)

    def test_the_date_is_read_american_style(self):
        """09/18/2026 is 18 September, not a malformed 9 for month 18."""
        parsed = ust_yields._parse_file(self.CSV, "test")
        self.assertIn(datetime.date(2026, 9, 18), parsed)


if __name__ == "__main__":
    unittest.main()
