# -*- coding: utf-8 -*-
"""The observations endpoint as CSV: same numbers as the JSON, under a
metadata block that states source, release, formula and vintage.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_observations_csv
Skips without data/observatory.duckdb.
"""
import pathlib
import unittest

from fastapi.testclient import TestClient

from app.main import app

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "observatory.duckdb"
URL = "/api/v1/cpi-jp/observations?series=0001,0161&measure=yoy&start=2024-01"


@unittest.skipUnless(DATA.exists(), "no macro database")
class ObservationsCsv(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_csv_matches_json(self):
        js = self.client.get(URL).json()
        r = self.client.get(URL + "&format=csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/csv"))
        self.assertIn('filename="cpi-jp-yoy.csv"', r.headers["content-disposition"])
        meta = [l for l in r.text.splitlines() if l.startswith("#")]
        rows = [l.split(",") for l in r.text.splitlines() if not l.startswith("#")]
        self.assertEqual(rows[0], ["period", "0001", "0161"])
        # Trust contract in file form: formula, release, source, vintage note.
        text = "\n".join(meta)
        self.assertIn(js["calc"], text)
        self.assertIn(js["release"]["sha256"], text)
        self.assertIn("Source: Statistics Bureau of Japan", text)
        self.assertIn("as_of=", text)
        want = {p[:7]: ("" if v is None else repr(v)) for p, v in js["series"][0]["points"]}
        self.assertEqual({r[0]: r[1] for r in rows[1:]}, want)

    def test_as_of_is_stated(self):
        r = self.client.get("/api/v1/cpi-jp/observations?series=0001&as_of=2026-08-20&format=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("# Point in time: the data as it stood on 2026-08-20", r.text)
        self.assertIn("asof-2026-08-20.csv", r.headers["content-disposition"])

    def test_bad_format(self):
        r = self.client.get("/api/v1/cpi-jp/observations?series=0001&format=xlsx")
        self.assertEqual(r.status_code, 400)
