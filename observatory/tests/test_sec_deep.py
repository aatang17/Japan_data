# -*- coding: utf-8 -*-
"""The US deep-coverage API over the company-facts tables in data/sec.duckdb.

Runs against the real file and skips cleanly when the tables are not loaded
(equity/sec_companyfacts.py builds them).

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_sec_deep
"""
import datetime
import unittest

import duckdb
from fastapi.testclient import TestClient

B = "/api/v1/us/financials/deep"


class DeepApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import sec_api
        from app.main import app
        if not sec_api.DB_PATH.exists():
            raise unittest.SkipTest("data/sec.duckdb not built")
        con = duckdb.connect(str(sec_api.DB_PATH), read_only=True)
        try:
            names = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
        finally:
            con.close()
        if "sec_cf_facts" not in names:
            raise unittest.SkipTest("company-facts tables not loaded")
        cls.client = TestClient(app)
        r = cls.client.get(B)
        assert r.status_code == 200, r.text
        cls.universe = r.json()
        cls.ticker = cls.universe["companies"][0]["ticker"]

    def test_universe_links_predecessors_not_as_companies(self):
        tickers = [c["ticker"] for c in self.universe["companies"]]
        self.assertEqual(len(tickers), len(set(tickers)))
        for c in self.universe["companies"]:
            for p in c["predecessors"]:
                self.assertLessEqual(c["history_from"], p["first_filed"])

    def test_concepts_menu(self):
        r = self.client.get("%s/%s" % (B, self.ticker))
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertGreater(d["count"], 50)
        self.assertTrue(all(c["units"] for c in d["concepts"]))

    def test_indicators_name_their_source(self):
        d = self.client.get("%s/%s/indicators?limit=5" % (B, self.ticker)).json()
        self.assertTrue(d["panel"])
        for row in d["panel"]:
            for field, value in row["values"].items():
                src = row["sources"][field]
                # Missing is null with no source, never 0 with a made-up one.
                self.assertEqual(value is None, src is None, field)
                if src:
                    self.assertTrue(src["accn"] and src["tag"] and src["filed"])

    def test_as_of_never_leaks_a_later_filing(self):
        ceiling = "2020-01-01"
        for basis in ("latest", "first", "all"):
            d = self.client.get("%s/%s/series?tag=Assets&freq=all&basis=%s&as_of=%s"
                                % (B, self.ticker, basis, ceiling)).json()
            for v in d.get("values", []):
                self.assertLessEqual(v["filed"], ceiling)
        d = self.client.get("%s/%s/indicators?as_of=%s" % (B, self.ticker, ceiling)).json()
        for row in d.get("panel", []):
            for src in row["sources"].values():
                if src:
                    self.assertLessEqual(src["filed"], ceiling)

    def test_first_and_latest_are_both_filed_values(self):
        first = self.client.get("%s/%s/series?tag=Assets&basis=first" % (B, self.ticker)).json()
        allv = self.client.get("%s/%s/series?tag=Assets&basis=all" % (B, self.ticker)).json()
        filed = {(v["period_end"], v["value"]) for v in allv["values"]}
        for v in first["values"]:
            self.assertIn((v["period_end"], v["value"]), filed)

    def test_bad_input(self):
        self.assertEqual(self.client.get(B + "/NOSUCH").status_code, 404)
        self.assertEqual(self.client.get("%s/%s/indicators?freq=weekly" % (B, self.ticker)).status_code, 400)
        self.assertEqual(self.client.get("%s/%s/series?tag=Assets&as_of=soon" % (B, self.ticker)).status_code, 400)

    def test_health_row(self):
        from app import sec_deep_api
        rows = sec_deep_api.health()
        self.assertEqual(rows[0]["dataset"], "sec-companyfacts")
        datetime.date.fromisoformat(rows[0]["archive_read_through"])


if __name__ == "__main__":
    unittest.main()
