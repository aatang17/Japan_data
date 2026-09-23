# -*- coding: utf-8 -*-
"""The daily refresh of the US deep-coverage companies, pinned down.

Two things must hold for the US company pages to stay current in production:

  1. app/backfill.py pulls the companies every cycle, on a copy of
     data/sec.duckdb that is swapped in — and never swaps in a copy the pull
     did not reach, or writes the served file in place.
  2. A pull that finds a company's file unchanged is still recorded, so the
     health row (and the page's stale banner) measures "last reached the
     SEC", not "last found a new filing". A quiet fortnight is not a fault.

No network: the SEC fetch and the child process are both stood in for.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_us_companies_refresh
"""
import datetime
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import unittest

import duckdb

from app import backfill, heartbeat

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location(
        "sec_companyfacts", str(ROOT / "equity" / "sec_companyfacts.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DOC = {
    "cik": 320193, "entityName": "Apple Inc.",
    "facts": {"us-gaap": {
        "Assets": {"label": "Assets", "description": "Total assets.", "units": {"USD": [
            {"end": "2025-09-27", "val": 100, "accn": "0000320193-25-000079",
             "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2025-10-31"}]}},
        "LiabilitiesAndStockholdersEquity": {"label": "L+E", "units": {"USD": [
            {"end": "2025-09-27", "val": 100, "accn": "0000320193-25-000079",
             "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2025-10-31"}]}},
    }},
}


class FakeFetcher(object):
    def __init__(self, body):
        self.body = body

    def get(self, url):
        return self.body


class UnchangedPullTest(unittest.TestCase):
    """An unchanged file loads nothing but is recorded as contact."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cf = load_script()
        self.cf.RAW_ROOT = os.path.join(self.dir, "raw")
        self.con = duckdb.connect(os.path.join(self.dir, "sec.duckdb"))
        self.addCleanup(self.con.close)
        self.con.execute(self.cf.SCHEMA_SQL)
        self.body = json.dumps(DOC).encode()

    def pulls(self):
        return self.con.execute(
            "SELECT status, sha256 FROM sec_cf_pulls ORDER BY pull_id").fetchall()

    def test_second_identical_pull_is_recorded_as_unchanged(self):
        f = FakeFetcher(self.body)
        self.assertTrue(self.cf.load_company(self.con, f, 320193, "AAPL", "IT", None)
                        .startswith("loaded"))
        self.assertEqual(self.cf.load_company(self.con, f, 320193, "AAPL", "IT", None),
                         "unchanged")
        rows = self.pulls()
        self.assertEqual([r[0] for r in rows], ["ok", "unchanged"])
        self.assertEqual(rows[0][1], rows[1][1])

    def test_unchanged_pull_adds_no_facts(self):
        f = FakeFetcher(self.body)
        self.cf.load_company(self.con, f, 320193, "AAPL", "IT", None)
        n = self.con.execute("SELECT count(*) FROM sec_cf_facts").fetchone()[0]
        self.cf.load_company(self.con, f, 320193, "AAPL", "IT", None)
        self.assertEqual(self.con.execute("SELECT count(*) FROM sec_cf_facts").fetchone()[0], n)

    def test_a_changed_file_after_an_unchanged_one_still_loads(self):
        """The sha comparison reads the last 'ok' pull, so an 'unchanged' row
        in between must not hide a real change."""
        f = FakeFetcher(self.body)
        self.cf.load_company(self.con, f, 320193, "AAPL", "IT", None)
        self.cf.load_company(self.con, f, 320193, "AAPL", "IT", None)
        doc = json.loads(self.body)
        doc["facts"]["us-gaap"]["Assets"]["units"]["USD"].append(
            {"end": "2026-06-27", "val": 120, "accn": "0000320193-26-000010",
             "fy": 2026, "fp": "Q3", "form": "10-Q", "filed": "2026-07-31"})
        f.body = json.dumps(doc).encode()
        self.assertTrue(self.cf.load_company(self.con, f, 320193, "AAPL", "IT", None)
                        .startswith("loaded 1 facts new"))


class RefreshUsCompaniesTest(unittest.TestCase):
    """app/backfill.refresh_us_companies: copy, pull, swap only on contact."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.dir), True)
        saved = {n: getattr(backfill, n) for n in ("LIVE_SEC", "DATA_DIR", "_run")}
        self.addCleanup(lambda: [setattr(backfill, n, v) for n, v in saved.items()])
        backfill.LIVE_SEC = self.dir / "sec.duckdb"
        backfill.DATA_DIR = self.dir
        real_journal = heartbeat.JOURNAL_PATH
        heartbeat.JOURNAL_PATH = self.dir / "refresh_journal.json"
        self.addCleanup(setattr, heartbeat, "JOURNAL_PATH", real_journal)
        self.ua = os.environ.get("EDGAR_USER_AGENT")
        os.environ["EDGAR_USER_AGENT"] = "Test test@example.com"
        self.addCleanup(self._restore_ua)
        backfill._stopping = False
        self.cf = load_script()
        self.calls = []

    def _restore_ua(self):
        if self.ua is None:
            os.environ.pop("EDGAR_USER_AGENT", None)
        else:
            os.environ["EDGAR_USER_AGENT"] = self.ua

    def make_live(self, pulls=1):
        con = duckdb.connect(str(backfill.LIVE_SEC))
        con.execute(self.cf.SCHEMA_SQL)
        for _ in range(pulls):
            self.pull_row(con, "ok")
        con.close()

    def pull_row(self, con, status):
        pid = con.execute("SELECT nextval('sec_cf_pull_seq')").fetchone()[0]
        con.execute("INSERT INTO sec_cf_pulls (pull_id, cik, fetched_at, status) "
                    "VALUES (?, 1, now(), ?)", [pid, status])

    def fake_run(self, statuses, rc=0):
        """Stand in for the child: record pulls into the --db it was given."""
        def run(cmd, env, cwd):
            self.calls.append(cmd)
            db = cmd[cmd.index("--db") + 1]
            con = duckdb.connect(db)
            con.execute(self.cf.SCHEMA_SQL)
            for s in statuses:
                self.pull_row(con, s)
            con.close()
            return rc
        return run

    def live_pulls(self):
        con = duckdb.connect(str(backfill.LIVE_SEC), read_only=True)
        try:
            return [r[0] for r in con.execute(
                "SELECT status FROM sec_cf_pulls ORDER BY pull_id").fetchall()]
        finally:
            con.close()

    def outcome(self):
        return heartbeat.journal()["sec-companyfacts"]["outcome"]

    def test_unchanged_pulls_are_swapped_in(self):
        self.make_live()
        backfill._run = self.fake_run(["unchanged", "unchanged"])
        backfill.refresh_us_companies()
        self.assertEqual(self.live_pulls(), ["ok", "unchanged", "unchanged"])
        self.assertEqual(self.outcome(), "published")
        self.assertFalse((self.dir / "sec.companyfacts.duckdb").exists())

    def test_partial_failure_still_lands_the_rest(self):
        self.make_live()
        backfill._run = self.fake_run(["ok", "failed"], rc=1)
        backfill.refresh_us_companies()
        self.assertEqual(self.live_pulls(), ["ok", "ok", "failed"])
        self.assertEqual(self.outcome(), "failed")

    def test_nothing_recorded_leaves_the_served_file_alone(self):
        self.make_live()
        before = backfill.LIVE_SEC.stat().st_mtime_ns
        backfill._run = self.fake_run([], rc=1)
        backfill.refresh_us_companies()
        self.assertEqual(backfill.LIVE_SEC.stat().st_mtime_ns, before)
        self.assertEqual(self.live_pulls(), ["ok"])
        self.assertEqual(self.outcome(), "failed")
        self.assertFalse((self.dir / "sec.companyfacts.duckdb").exists())

    def test_the_child_writes_the_copy_never_the_served_file(self):
        self.make_live()
        backfill._run = self.fake_run(["unchanged"])
        backfill.refresh_us_companies()
        db = self.calls[0][self.calls[0].index("--db") + 1]
        self.assertNotEqual(pathlib.Path(db), backfill.LIVE_SEC)

    def test_first_pull_on_an_empty_volume_builds_the_file(self):
        backfill._run = self.fake_run(["ok"])
        backfill.refresh_us_companies()
        self.assertEqual(self.live_pulls(), ["ok"])

    def test_no_user_agent_means_no_request_and_a_recorded_fault(self):
        os.environ.pop("EDGAR_USER_AGENT", None)
        self.make_live()
        backfill._run = self.fake_run(["ok"])
        backfill.refresh_us_companies()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.outcome(), "failed")


class HealthCountsUnchangedTest(unittest.TestCase):
    """The health row dates freshness from any pull that reached the SEC."""

    def setUp(self):
        from app import sec_api
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        cf = load_script()
        self.con = duckdb.connect(os.path.join(self.dir, "sec.duckdb"))
        self.addCleanup(self.con.close)
        self.con.execute(cf.SCHEMA_SQL)
        self._cur = sec_api._cur
        sec_api._cur = lambda: self.con
        self.addCleanup(setattr, sec_api, "_cur", self._cur)

    def add(self, pid, status, days_ago):
        at = datetime.datetime.utcnow() - datetime.timedelta(days=days_ago)
        self.con.execute("INSERT INTO sec_cf_pulls (pull_id, cik, fetched_at, status) "
                         "VALUES (?, 320193, ?, ?)", [pid, at, status])

    def row(self):
        from app import sec_deep_api
        self.con.execute("INSERT INTO sec_cf_companies (cik, ticker, first_filed, last_filed) "
                         "VALUES (320193, 'AAPL', '2009-07-22', '2026-07-31')")
        return sec_deep_api.health()[0]

    def test_recent_unchanged_pull_is_fresh(self):
        self.add(1, "ok", 20)
        self.add(2, "unchanged", 0)
        r = self.row()
        self.assertFalse(r["stale"])
        self.assertEqual(r["status"], "ok")

    def test_no_contact_for_days_is_stale(self):
        self.add(1, "ok", 20)
        self.assertTrue(self.row()["stale"])

    def test_failure_after_an_unchanged_pull_is_flagged(self):
        self.add(1, "unchanged", 0)
        self.add(2, "failed", 0)
        r = self.row()
        self.assertEqual(r["status"], "attention")
        self.assertTrue(r["shape_flags"])


if __name__ == "__main__":
    unittest.main()
