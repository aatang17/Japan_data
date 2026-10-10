# -*- coding: utf-8 -*-
"""The DigitalOcean server's refresher and backups (docs/plans/PLAN-DROPLET-ZERO-DOWNTIME.md).

None of this runs on Railway: start.sh does not use app/refresher.py, and
every switch below is off unless its environment variable is set.
"""
import datetime
import os
import subprocess
import sys
import unittest
from unittest import mock

import duckdb

from app import data_backup, db, refresher, research_backup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Schedule(unittest.TestCase):
    def test_next_run_is_the_next_refresh_time(self):
        with mock.patch.dict(os.environ, {"REFRESH_AT": "13:00"}):
            self.assertEqual(refresher.next_run(datetime.datetime(2026, 10, 10, 9, 0)),
                             datetime.datetime(2026, 10, 10, 13, 0))
            self.assertEqual(refresher.next_run(datetime.datetime(2026, 10, 10, 13, 0)),
                             datetime.datetime(2026, 10, 11, 13, 0))
            self.assertEqual(refresher.next_run(datetime.datetime(2026, 10, 10, 22, 30)),
                             datetime.datetime(2026, 10, 11, 13, 0))

    def test_a_restart_does_not_repeat_todays_refresh(self):
        # 2026-10-09: every Railway deploy re-ran the hour-long copy pass and
        # the research desk stalled; a deploy replacing the refresher must not
        now = datetime.datetime(2026, 10, 10, 9, 0)
        for stamp, due in (("2026-10-10T07:00:00Z", False), ("2026-10-09T09:00:00Z", True),
                           (None, True), ("not a time", True)):
            with self.subTest(stamp=stamp), \
                    mock.patch.object(refresher.heartbeat, "read", return_value={"at": stamp}):
                self.assertEqual(refresher.due_at_start(now), due)

    def test_every_registered_dataset_is_refreshed_once_curated_first(self):
        from app.ingest import ADAPTERS
        order = refresher.datasets()
        self.assertEqual(sorted(order), sorted(ADAPTERS))
        self.assertEqual(len(order), len(set(order)))
        self.assertEqual(order[0], "cpi-jp")


class Backups(unittest.TestCase):
    def test_daily_copies_kept_fourteen_days(self):
        today = datetime.date(2026, 10, 20)
        days = ["2026-10-%02d" % d for d in range(1, 21)] + ["junk"]
        self.assertEqual(data_backup.expired_days(days, today),
                         ["2026-10-%02d" % d for d in range(1, 7)])

    def test_monthly_copies_kept_twelve_months(self):
        months = ["2025-%02d" % m for m in range(1, 13)] + ["2026-%02d" % m for m in range(1, 11)]
        self.assertEqual(data_backup.expired_months(months, datetime.date(2026, 10, 20)),
                         ["2025-%02d" % m for m in range(1, 11)])
        self.assertEqual(data_backup.expired_months(["2026-09", "2026-10"], datetime.date(2026, 10, 1)), [])

    def test_a_rehearsal_never_writes_production_backups(self):
        env = {"EDINET_S3_BUCKET": "b", "EDINET_S3_ENDPOINT": "https://example.invalid",
               "EDINET_S3_KEY_ID": "k", "EDINET_S3_SECRET": "s", "OFFSITE_BACKUPS": "0"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(research_backup._s3(), (None, None))
            self.assertFalse(data_backup.enabled())
            with mock.patch.object(data_backup, "_tell"):
                self.assertIn("off", data_backup.run()["error"])
        with mock.patch.dict(os.environ, {"OFFSITE_BACKUPS": "1"}):
            self.assertTrue(data_backup.enabled())


class MemoryCap(unittest.TestCase):
    def setting(self, value):
        con = duckdb.connect()
        with mock.patch.dict(os.environ, {"DUCKDB_MEMORY_LIMIT": value}):
            db.limit_memory(con)
        try:
            return con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
        finally:
            con.close()

    def test_the_cap_applies_when_set_and_is_ignored_when_malformed(self):
        default = self.setting("")
        self.assertIn(self.setting("512MB"), ("488.2 MiB", "512.0 MiB", "512 MB"))
        self.assertEqual(self.setting("lots; DROP TABLE x"), default)


class SharedLoginSecret(unittest.TestCase):
    def secret(self, value):
        env = dict(os.environ, ADMIN_SESSION_SECRET=value)
        code = "from app import admin_api; print(admin_api._SECRET.hex())"
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_two_copies_of_the_site_sign_cookies_alike_only_when_set(self):
        # during a deploy the old and new copies run side by side
        self.assertEqual(self.secret("same"), self.secret("same"))
        self.assertNotEqual(self.secret(""), self.secret(""))


if __name__ == "__main__":
    unittest.main()
