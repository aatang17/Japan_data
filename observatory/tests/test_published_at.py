"""A backfilled release sits in history where the AGENCY published it.

`releases.published_at` exists for one reason: loading an estimate the
Cabinet Office issued in 2011 must put it in 2011, not at the moment we
happened to fetch it. Every as-of read therefore orders by
COALESCE(published_at, ingested_at), and if any one of them is left ordering
by ingest time alone, the archive silently answers with today's numbers for
every date in its span — a failure that looks like working software.

These tests build a tiny database in a temporary file rather than mocking:
the thing under test is SQL, so a fake would prove nothing.
"""
import datetime
import os
import pathlib
import tempfile
import unittest

import duckdb


def _build(path, rows):
    """A minimal dataset with one series and the given releases.

    rows: [(label, ingested_at, published_at, status, value)] oldest first.
    """
    from app import db as db_module
    con = duckdb.connect(str(path))
    con.execute(db_module.SCHEMA)
    for statement in db_module.MIGRATIONS:
        con.execute(statement)
    con.execute("INSERT INTO datasets VALUES ('d','T','Japan','A',NULL,NULL,'quarterly',NULL)")
    con.execute("INSERT INTO sources VALUES ('s','d','n',NULL,'u',NULL)")
    con.execute(
        "INSERT INTO source_artifacts (source_id, url, retrieved_at, sha256, path, bytes) "
        "VALUES ('s','u', TIMESTAMP '2026-01-01', 'sha', 'p', 1)")
    artifact = con.execute("SELECT artifact_id FROM source_artifacts").fetchone()[0]
    series_id = con.execute(
        "INSERT INTO series (dataset, code, name_en, unit) "
        "VALUES ('d','c','C','index') RETURNING series_id").fetchone()[0]
    period = datetime.date(2010, 1, 1)
    for label, ingested, published, status, value in rows:
        release_id = con.execute(
            "INSERT INTO releases (dataset, artifact_id, label, latest_period, "
            "ingested_at, published_at, status, validation) "
            "VALUES ('d',?,?,?,?,?,?,NULL) RETURNING release_id",
            [artifact, label, period, ingested, published, status]).fetchone()[0]
        con.execute(
            "INSERT INTO observation_vintages (series_id, period, value, release_id) "
            "VALUES (?,?,?,?)", [series_id, period, value, release_id])
    con.close()


class PublishedAtTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "t.duckdb"
        self.addCleanup(self.dir.cleanup)

    def _con(self):
        return duckdb.connect(str(self.path), read_only=True)

    def _compact(self):
        """Run compact() against this test's database, then put the module
        back. db.DB_PATH is module state: leaving it pointed at a temporary
        file makes every later test in the process read the wrong database,
        which is a failure that only appears when the suite runs in order."""
        from app import db as db_module, vintages
        previous = db_module.DB_PATH
        db_module.DB_PATH = pathlib.Path(self.path)
        try:
            vintages.compact()
        finally:
            db_module.DB_PATH = previous

    def test_archive_is_read_at_its_publication_date_not_its_ingest(self):
        """The whole point. Both releases were fetched today; one of them was
        published in 2011 and must answer for 2011, not for today."""
        from app import vintages
        _build(self.path, [
            # the live release: fetched today, no agency date
            ("live", datetime.datetime(2026, 9, 13), None, "published", 600.0),
            # the archive: also fetched today, but published in March 2011
            ("2010 Q4 1st", datetime.datetime(2026, 9, 13),
             datetime.datetime(2011, 2, 13, 23, 50), "archived", 540.0),
        ])
        con = self._con()
        try:
            as_2011 = vintages.values_as_of(con, "d", datetime.date(2011, 6, 1))
            as_today = vintages.values_as_of(con, "d", datetime.date(2026, 9, 13))
            self.assertEqual(as_2011["c"][datetime.date(2010, 1, 1)], 540.0)
            self.assertEqual(as_today["c"][datetime.date(2010, 1, 1)], 600.0)
        finally:
            con.close()

    def test_a_date_before_every_release_sees_nothing(self):
        from app import vintages
        _build(self.path, [
            ("2010 Q4 1st", datetime.datetime(2026, 9, 13),
             datetime.datetime(2011, 2, 13, 23, 50), "archived", 540.0),
        ])
        con = self._con()
        try:
            self.assertEqual(vintages.values_as_of(con, "d", datetime.date(2010, 1, 1)), {})
        finally:
            con.close()

    def test_revisions_are_ordered_by_publication_and_say_whose_date_it_is(self):
        from app import vintages
        _build(self.path, [
            # inserted newest-first on purpose: release_id order must not
            # decide history when publication dates disagree with it.
            ("live", datetime.datetime(2026, 9, 13), None, "published", 600.0),
            ("2010 Q4 2nd", datetime.datetime(2026, 9, 13),
             datetime.datetime(2011, 3, 9, 23, 50), "archived", 545.0),
            ("2010 Q4 1st", datetime.datetime(2026, 9, 13),
             datetime.datetime(2011, 2, 13, 23, 50), "archived", 540.0),
        ])
        con = self._con()
        try:
            rows = vintages.revisions(con, "d", "c")
            self.assertEqual([r[3] for r in rows], ["2010 Q4 1st", "2010 Q4 2nd", "live"])
            # published_at present on the two archived rows, absent on ours
            self.assertEqual([r[5] is not None for r in rows], [True, True, False])
        finally:
            con.close()

    def test_compact_keeps_a_value_that_changed_and_changed_back(self):
        """The one that bit. `compact` drops a row restating the value already
        in force — which means the IMMEDIATELY preceding one. A value that went
        540 -> 545 -> 540 was revised twice and every row carries information.

        The bug was a predicate that tested "is there anything in between" by
        ingest time while testing "is it earlier" by publication time. A
        backfilled archive shares one ingest timestamp, so "anything in
        between" was never true and the test collapsed into "did any earlier
        release ever carry this value" — which deleted real revisions.
        """
        from app import vintages
        _build(self.path, [
            ("first", datetime.datetime(2026, 9, 13, 13),
             datetime.datetime(2011, 2, 13), "archived", 540.0),
            ("second", datetime.datetime(2026, 9, 13, 13),
             datetime.datetime(2011, 3, 9), "archived", 545.0),
            # Back to the original value, and fetched EARLIER than the two
            # above — exactly the shape a backfill leaves behind.
            ("third", datetime.datetime(2026, 9, 13, 4),
             datetime.datetime(2011, 5, 18), "archived", 540.0),
        ])
        self._compact()
        con = duckdb.connect(str(self.path), read_only=True)
        try:
            self.assertEqual(
                con.execute("SELECT count(*) FROM observation_vintages").fetchone()[0], 3,
                "a value that changed and changed back lost a real revision")
            # And the as-of reads still say the right thing at each date.
            for when, expect in ((datetime.date(2011, 2, 20), 540.0),
                                 (datetime.date(2011, 4, 1), 545.0),
                                 (datetime.date(2011, 6, 1), 540.0)):
                got = vintages.values_as_of(con, "d", when)["c"][datetime.date(2010, 1, 1)]
                self.assertEqual(got, expect, when)
        finally:
            con.close()

    def test_compact_still_drops_a_true_restatement(self):
        """The other half: a row that restates the value immediately in force
        carries nothing and must go, or /revisions reports a revision that
        never happened."""
        _build(self.path, [
            ("first", datetime.datetime(2026, 9, 13), datetime.datetime(2011, 2, 13),
             "archived", 540.0),
            ("second", datetime.datetime(2026, 9, 13), datetime.datetime(2011, 3, 9),
             "archived", 540.0),
        ])
        self._compact()
        con = duckdb.connect(str(self.path), read_only=True)
        try:
            self.assertEqual(
                con.execute("SELECT count(*) FROM observation_vintages").fetchone()[0], 1)
        finally:
            con.close()

    def test_reads_still_work_where_the_column_does_not_exist(self):
        """The serving process opens the database read-only and cannot migrate
        it. On a file written before the column existed, an as-of read must
        answer from ingest time rather than raise."""
        from app import db as db_module, vintages
        # The schema as it was before the column existed. It cannot be dropped
        # afterwards — observation_vintages depends on releases — so the older
        # shape is built directly, which is what an existing volume holds.
        older = db_module.SCHEMA.replace("    published_at  TIMESTAMP,\n", "")
        # The column declaration is gone; the comments above it still mention
        # the name, which is why this asserts on the declaration itself.
        self.assertNotIn("published_at  TIMESTAMP", older)
        con = duckdb.connect(str(self.path))
        con.execute(older)
        con.close()
        _con = duckdb.connect(str(self.path), read_only=True)
        try:
            self.assertEqual(vintages.known_at(_con), "r.ingested_at")
            self.assertEqual(vintages.published_col(_con), "NULL")
            self.assertEqual(vintages.values_as_of(_con, "d", datetime.date(2026, 1, 1)), {})
        finally:
            _con.close()


if __name__ == "__main__":
    unittest.main()
