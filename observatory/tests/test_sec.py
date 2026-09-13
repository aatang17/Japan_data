# -*- coding: utf-8 -*-
"""The US shelf: loading the SEC's Financial Statement Data Sets and serving
them.

The extractor tests build a tiny data-set zip of their own, so they need no
archive and run anywhere. The API tests use data/sec.duckdb when it is
present and skip cleanly when it is not.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_sec
"""
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import unittest
import zipfile

import duckdb
from fastapi.testclient import TestClient

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

_spec = importlib.util.spec_from_file_location(
    "sec_extract", str(ROOT / "equity" / "sec_extract.py"))
sec_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sec_extract)


def _tsv(rows):
    return "\n".join("\t".join("" if v is None else str(v) for v in r) for r in rows) + "\n"


SUB_COLS = sec_extract.MEMBERS["sub"]


def _sub_row(adsh, cik, name, form, period, fy, fp, filed):
    row = {c: "" for c in SUB_COLS}
    row.update({"adsh": adsh, "cik": cik, "name": name, "sic": "3674", "countryba": "US",
                "stprba": "CA", "cityba": "CUPERTINO", "countryinc": "US", "stprinc": "CA",
                "afs": "1-LAF", "wksi": "1", "fye": "0930", "form": form, "period": period,
                "fy": fy, "fp": fp, "filed": filed, "accepted": filed[:4] + "-" + filed[4:6]
                + "-" + filed[6:] + " 16:30:00.0", "prevrpt": "0", "detail": "1",
                "instance": "x_htm.xml", "nciks": "1"})
    return [row[c] for c in SUB_COLS]


def make_zip(path, balanced=True, with_nil=True):
    """Two periodic reports and one 8-K. Filing A balances; filing B does
    not when balanced=False. A nil fact (blank value) rides along."""
    a, b, c = "0000000001-26-000001", "0000000002-26-000001", "0000000003-26-000001"
    sub = [SUB_COLS,
           _sub_row(a, "1", "ALPHA CORP", "10-K", "20251231", "2025", "FY", "20260227"),
           _sub_row(b, "2", "BETA INC", "10-Q", "20260331", "2026", "Q1", "20260505"),
           _sub_row(c, "3", "GAMMA LLC", "8-K", "20260331", "2026", "Q1", "20260401")]
    num = [sec_extract.MEMBERS["num"]]
    v = "us-gaap/2025"

    def fact(adsh, tag, ddate, qtrs, value, uom="USD", segments="", coreg=""):
        num.append([adsh, tag, v, ddate, qtrs, uom, segments, coreg, value, ""])
    fact(a, "Assets", "20251231", 0, "1000")
    fact(a, "Liabilities", "20251231", 0, "600")
    fact(a, "StockholdersEquity", "20251231", 0, "400")
    fact(a, "Assets", "20241231", 0, "900")
    fact(a, "Revenues", "20251231", 4, "5000")
    fact(a, "Revenues", "20241231", 4, "4500")
    fact(a, "NetIncomeLoss", "20251231", 4, "300")
    fact(a, "Revenues", "20251231", 4, "1200", segments="Segment=West;")
    if with_nil:
        fact(a, "CostOfRevenue", "20251231", 4, "")
    fact(b, "Assets", "20260331", 0, "2000")
    fact(b, "LiabilitiesAndStockholdersEquity", "20260331", 0, "2000" if balanced else "1900")
    fact(b, "Revenues", "20260331", 1, "700")
    fact(c, "Revenues", "20260331", 1, "1")           # 8-K: filing row only
    pre = [sec_extract.MEMBERS["pre"],
           [a, 2, 1, "BS", 0, "H", "Assets", v, "Total assets", 0],
           [a, 2, 2, "BS", 0, "H", "Liabilities", v, "Total liabilities", 0],
           [a, 2, 3, "BS", 0, "H", "StockholdersEquity", v, "Total equity", 0],
           [a, 4, 1, "IS", 0, "H", "Revenues", v, "Net sales", 0],
           [a, 4, 2, "IS", 0, "H", "NetIncomeLoss", v, "Net income", 0],
           [b, 2, 1, "BS", 0, "H", "Assets", v, "Total assets", 0],
           [c, 2, 1, "IS", 0, "H", "Revenues", v, "Net sales", 0]]
    tag = [sec_extract.MEMBERS["tag"],
           ["Assets", v, 0, 0, "monetary", "I", "D", "Assets", "Total assets."],
           ["Liabilities", v, 0, 0, "monetary", "I", "C", "Liabilities", ""],
           ["StockholdersEquity", v, 0, 0, "monetary", "I", "C", "Stockholders' Equity", ""],
           ["LiabilitiesAndStockholdersEquity", v, 0, 0, "monetary", "I", "C", "L and E", ""],
           ["Revenues", v, 0, 0, "monetary", "D", "C", "Revenues", ""],
           ["NetIncomeLoss", v, 0, 0, "monetary", "D", "C", "Net Income (Loss)", ""],
           ["CostOfRevenue", v, 0, 0, "monetary", "D", "D", "Cost of Revenue", ""]]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("sub.txt", _tsv(sub))
        z.writestr("num.txt", _tsv(num))
        z.writestr("pre.txt", _tsv(pre))
        z.writestr("tag.txt", _tsv(tag))
        z.writestr("readme.htm", "<html/>")


class Shelf(object):
    """A local us/ shelf in us_capture.py's layout, one quarter at a time."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        (self.root / "latest").mkdir(parents=True)

    def put(self, quarter, sha, **kw):
        day = "2026-09-10"
        p = self.root / day / "sec" / ("fsds_%s.zip" % quarter)
        p.parent.mkdir(parents=True, exist_ok=True)
        make_zip(str(p), **kw)
        rec = {"date": day, "source": "sec", "file": "fsds_%s.zip" % quarter,
               "key": "us/%s/sec/fsds_%s.zip" % (day, quarter), "sha256": sha,
               "content_hash": "zip:" + sha, "status": "ok",
               "captured_at": "2026-09-10T17:38:02.615848+00:00"}
        with open(self.root / "latest" / ("sec__fsds_%s.zip.json" % quarter), "w") as f:
            json.dump(rec, f)


class ExtractorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sec-test-")
        self.shelf = Shelf(os.path.join(self.tmp, "us"))
        self.db = os.path.join(self.tmp, "sec.duckdb")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *extra):
        import subprocess
        import sys
        cmd = [sys.executable, str(ROOT / "equity" / "sec_extract.py"), "--db", self.db] + list(extra)
        env = dict(os.environ, US_ARCHIVE_ROOT=self.shelf.root.as_posix())
        return subprocess.run(cmd, env=env, capture_output=True, text=True)

    def _q(self, sql):
        con = duckdb.connect(self.db, read_only=True)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_loads_verdicts_and_drops_nil(self):
        self.shelf.put("2026q1", "aaa")
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        status = dict(self._q("SELECT adsh, status FROM sec_filings"))
        self.assertEqual(status["0000000001-26-000001"], "clean")
        self.assertEqual(status["0000000002-26-000001"], "clean")
        self.assertEqual(status["0000000003-26-000001"], "skipped")
        # The 8-K keeps its filing row and no facts; the nil fact is gone.
        self.assertEqual(self._q("SELECT count(*) FROM sec_facts WHERE adsh LIKE '0000000003%'")[0][0], 0)
        self.assertEqual(self._q("SELECT count(*) FROM sec_facts WHERE tag = 'CostOfRevenue'")[0][0], 0)
        # Dimensional facts live once in sec_segments and are flagged on the fact.
        seg = self._q("SELECT g.segments FROM sec_facts f JOIN sec_segments g USING (segment_id)")
        self.assertEqual(seg, [("Segment=West;",)])
        self.assertEqual(self._q("SELECT status, sha256 FROM sec_quarters")[0], ("ok", "aaa"))

    def test_unbalanced_filing_is_partial_with_the_gap(self):
        self.shelf.put("2026q1", "aaa", balanced=False)
        self.assertEqual(self._run().returncode, 0)
        row = self._q("SELECT status, note, bs_check, total_assets FROM sec_filings "
                      "WHERE adsh = '0000000002-26-000001'")[0]
        self.assertEqual(row[0], "partial")
        self.assertIn("balance sheet off by 100", row[1])
        self.assertEqual(row[3], 2000.0)

    def test_unchanged_quarter_is_skipped_and_changed_one_reloaded(self):
        self.shelf.put("2026q1", "aaa")
        self.assertEqual(self._run().returncode, 0)
        first = self._q("SELECT loaded_at FROM sec_quarters")[0][0]
        r = self._run()
        self.assertIn("to load: nothing", r.stdout)
        self.assertEqual(self._q("SELECT loaded_at FROM sec_quarters")[0][0], first)
        self.shelf.put("2026q1", "bbb", balanced=False)          # the SEC republished it
        self.assertEqual(self._run().returncode, 0)
        self.assertEqual(self._q("SELECT sha256 FROM sec_quarters")[0][0], "bbb")
        self.assertEqual(self._q("SELECT status FROM sec_filings WHERE cik = 2")[0][0], "partial")
        self.assertEqual(self._q("SELECT count(*) FROM sec_filings")[0][0], 3)

    def test_bad_file_leaves_previous_load_live(self):
        self.shelf.put("2026q1", "aaa")
        self.assertEqual(self._run().returncode, 0)
        # Replace the zip with one missing num.txt, under a new hash.
        p = self.shelf.root / "2026-09-10" / "sec" / "fsds_2026q1.zip"
        with zipfile.ZipFile(str(p), "w") as z:
            z.writestr("sub.txt", _tsv([SUB_COLS]))
        rec = json.load(open(self.shelf.root / "latest" / "sec__fsds_2026q1.zip.json"))
        rec["sha256"] = "ccc"
        json.dump(rec, open(self.shelf.root / "latest" / "sec__fsds_2026q1.zip.json", "w"))
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED", r.stdout)
        q = self._q("SELECT status, sha256, detail FROM sec_quarters")[0]
        self.assertEqual(q[0], "failed")
        self.assertEqual(q[1], "aaa")                       # the live load's hash stands
        self.assertIn("no num.txt", q[2])
        self.assertEqual(self._q("SELECT count(*) FROM sec_facts")[0][0], 11)

    def test_selection_window_and_deepening(self):
        for q in ("2025q3", "2025q4", "2026q1", "2026q2"):
            self.shelf.put(q, "sha-" + q)
        self.assertEqual(self._run("--last", "2").returncode, 0)
        self.assertEqual(sorted(r[0] for r in self._q("SELECT quarter FROM sec_quarters")),
                         ["2026q1", "2026q2"])
        self.assertEqual(self._run("--last", "0", "--deepen", "1").returncode, 0)
        self.assertEqual(sorted(r[0] for r in self._q("SELECT quarter FROM sec_quarters")),
                         ["2025q4", "2026q1", "2026q2"])
        self.assertEqual(self._run("--all").returncode, 0)
        self.assertEqual(self._q("SELECT count(*) FROM sec_quarters")[0][0], 4)


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import sec_api
        from app.main import app
        cls.sec_api = sec_api
        if not sec_api.DB_PATH.exists():
            raise unittest.SkipTest("data/sec.duckdb not built")
        cls.client = TestClient(app)
        r = cls.client.get("/api/v1/us/financials/summary")
        assert r.status_code == 200, r.text
        cls.summary = r.json()

    def test_summary_and_manifest(self):
        self.assertGreater(self.summary["filings"], 0)
        self.assertTrue(self.summary["quarters"])
        r = self.client.get("/api/v1/catalog/manifests/sec-financials")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["section"], "us-reference")

    def _a_company(self):
        r = self.client.get("/api/v1/us/financials/screen?metric=total_assets&limit=1")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["rows"][0]["cik"]

    def test_company_statement_and_facts_round_trip(self):
        cik = self._a_company()
        r = self.client.get("/api/v1/us/financials/company/%d" % cik)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        row = d["panel"][0]
        self.assertEqual(row["tags"]["total_assets"], "Assets")
        self.assertEqual(d["provenance"]["trust"], "official")
        # The statement's total-assets line must equal the panel's figure.
        r = self.client.get("/api/v1/us/financials/statements/%d?statement=BS" % cik)
        self.assertEqual(r.status_code, 200, r.text)
        lines = r.json()["lines"]
        assets = [l for l in lines if l["tag"] == "Assets" and not l["parenthetical"]]
        self.assertTrue(assets)
        self.assertEqual(assets[0]["current"], row["values"]["total_assets"])
        r = self.client.get("/api/v1/us/financials/facts/%d?tag=Assets" % cik)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(row["values"]["total_assets"], [v["value"] for v in r.json()["values"]])

    def test_cik_forms(self):
        cik = self._a_company()
        for form in ("%d" % cik, "cik:%d" % cik, "%010d" % cik):
            r = self.client.get("/api/v1/us/financials/company/%s" % form)
            self.assertEqual(r.status_code, 200, form)
        self.assertEqual(self.client.get("/api/v1/us/financials/company/7203x").status_code, 400)

    def test_health_lists_the_shelf(self):
        r = self.client.get("/api/v1/catalog/health")
        rows = [e for e in r.json()["equity_extractors"] if e["dataset"] == "sec-financials"]
        self.assertEqual(len(rows), 1)
        self.assertIn("archive_read_through", rows[0])


if __name__ == "__main__":
    unittest.main()
