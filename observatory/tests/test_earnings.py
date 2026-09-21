# -*- coding: utf-8 -*-
u"""Earnings releases (TDnet 決算短信): reading the wire and serving it.

Self-contained: the extractor tests run on strings, and the API tests build a
small database of their own, so nothing here needs the archive or the equity
file.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_earnings
"""
import datetime
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

import duckdb
from fastapi import HTTPException

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "equity"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tdnet_extract = _load("tdnet_extract", ROOT / "equity" / "tdnet_extract.py")
tdnet_capture = _load("tdnet_capture", ROOT.parent / "equity" / "tdnet_capture.py")

from app import asof, earnings_api  # noqa: E402

ROW = (u'<tr> <td class="oddnew-L kjTime" noWrap>16:00</td> '
       u'<td class="oddnew-M kjCode" noWrap>%s</td> '
       u'<td class="oddnew-M kjName" noWrap>%s</td> '
       u'<td class="oddnew-M kjTitle" align="left"><a href="%s" target="_blank">%s</a></td> '
       u'<td class="oddnew-M kjXbrl" noWrap align="center"> </td> '
       u'<td class="oddnew-M kjPlace" noWrap align="left">東 </td> </tr>')


class ListPageTest(unittest.TestCase):
    """The code cell may hold a letter. Reading it as digits only dropped the
    code from 9% of the wire."""

    def test_capture_keeps_an_alphanumeric_code_and_the_name(self):
        html = ROW % (u"588A0", u"Ｓ－アットマークテク", u"140120260918538809.pdf", u"決算短信")
        row = tdnet_capture.parse_list(html)[0]
        self.assertEqual(row["sec_code"], "588A0")
        self.assertEqual(row["name"], u"Ｓ－アットマークテク")

    def test_capture_still_reads_a_numeric_code(self):
        row = tdnet_capture.parse_list(ROW % (u"72030", u"トヨタ", u"a.pdf", u"決算短信"))[0]
        self.assertEqual(row["sec_code"], "72030")

    def test_extractor_recovers_code_name_and_exchange_from_the_archived_page(self):
        pages = [ROW % (u"588A0", u"Ｓ－アットマークテク", u"x/140120260918538809.pdf", u"t")]
        got = tdnet_extract.raw_rows(pages)
        self.assertEqual(got["140120260918538809.pdf"][0], "588A0")
        self.assertEqual(got["140120260918538809.pdf"][2], u"東")
        self.assertEqual(tdnet_extract.sec4("588A0"), "588A")
        self.assertEqual(tdnet_extract.sec4("72030"), "7203")


class FiscalPeriodTest(unittest.TestCase):
    def test_western_year_full_width_digits(self):
        self.assertEqual(tdnet_extract.fiscal_period(u"2027年３月期 第１四半期決算短信"), "2027-03")

    def test_era_year(self):
        self.assertEqual(tdnet_extract.fiscal_period(u"令和９年２月期 第１四半期決算短信"), "2027-02")
        self.assertEqual(tdnet_extract.fiscal_period(u"令和元年12月期 決算短信"), "2019-12")

    def test_nendo_spelling(self):
        self.assertEqual(tdnet_extract.fiscal_period(u"2027年度３月期第１四半期決算短信"), "2027-03")

    def test_a_headline_with_no_month_has_no_fiscal_period(self):
        self.assertIsNone(tdnet_extract.fiscal_period(u"2026年度 第1四半期決算短信〔IFRS〕"))
        self.assertIsNone(tdnet_extract.fiscal_period(u"第３四半期決算短信"))


def _fact(doc, ordn, element, period, nature, value, basis="consolidated", sub=None,
          unit="JPY"):
    return (doc, ordn, element, "ctx", period, "duration", nature, basis, sub, unit, value)


def build(path):
    con = duckdb.connect(path)
    con.execute(tdnet_extract.SCHEMA_SQL)
    fil = ("INSERT INTO eq_tdnet_filings (%s) VALUES (%s)"
           % (tdnet_extract.FILING_NAMES, ",".join(["?"] * tdnet_extract.FILING_COLS)))

    def filing(doc, day, time, code, name, title, period, fiscal="2027-03"):
        con.execute(fil, [doc, day, time, code, name, title, None, period, "sha-" + doc,
                          "td-2", "clean", None, 1, 1, 1, fiscal])

    # 1001: a first release, then a re-issue after the auditor's review.
    filing("A1", "2026-08-03", "15:00", "1001", u"甲社", u"2027年3月期 第1四半期決算短信", "q1")
    filing("A2", "2026-08-06", "15:00", "1001", u"甲社",
           u"2027年3月期 第1四半期決算短信（期中レビューの完了）", "q1")
    # 1002 guides to a range; 1003 forecasts a loss; 1004 gives no forecast.
    filing("B1", "2026-08-04", "15:00", "1002", u"乙社", u"2027年3月期 第1四半期決算短信", "q1")
    filing("C1", "2026-08-04", "15:30", "1003", u"丙社", u"2027年3月期 第1四半期決算短信", "q1")
    filing("D1", "2026-08-05", "15:00", "1004", u"丁社", u"2027年3月期 第1四半期決算短信", "q1")
    facts = []
    for doc, op in (("A1", 100.0), ("A2", 120.0)):
        facts += [_fact(doc, 1, "NetSales", "q1-ytd", "result", 1000.0),
                  _fact(doc, 2, "ChangeInNetSales", "q1-ytd", "result", 0.104, unit="Pure"),
                  _fact(doc, 3, "NetSales", "prior-q1-ytd", "result", 906.0),
                  _fact(doc, 4, "OperatingIncome", "q1-ytd", "result", op),
                  _fact(doc, 5, "NetSales", "year", "forecast", 4000.0),
                  _fact(doc, 6, "OperatingIncome", "year", "forecast", 400.0),
                  _fact(doc, 7, "DividendPerShare", "year", "forecast", 50.0,
                        basis="parent", sub="annual", unit="JPYPerShares")]
    facts += [_fact("B1", 1, "OperatingIncome", "q1-ytd", "result", 50.0),
              _fact("B1", 2, "OperatingIncome", "year", "forecast-upper", 300.0),
              _fact("B1", 3, "OperatingIncome", "year", "forecast-lower", 200.0),
              _fact("C1", 1, "OperatingIncome", "q1-ytd", "result", -10.0),
              _fact("C1", 2, "OperatingIncome", "year", "forecast", -40.0),
              _fact("D1", 1, "OperatingIncome", "q1-ytd", "result", 70.0)]
    con.executemany("INSERT INTO eq_tdnet_facts VALUES (?,?,?,?,?,?,?,?,?,?,?)", facts)
    con.execute(
        "INSERT INTO eq_tdnet_items (disclosed_on, disclosed_at, ord, sec_code, title, kind, "
        "pdf_name, xbrl_name, company_name, exchange) VALUES "
        "('2026-08-03', '15:00', 0, '1001', '決算短信', 'earnings', 'a.pdf', 'A1.zip', '甲社', '東'),"
        "('2026-08-07', '15:00', 0, '1001', '業績予想の修正', 'forecast-revision', 'b.pdf', "
        " NULL, '甲社', '東')")
    # The name lookup every equity API shares reads these two tables.
    con.execute("CREATE TABLE eq_filings (edinet_code VARCHAR, sec_code VARCHAR, "
                "filer_name_en VARCHAR, period_end DATE)")
    con.execute("CREATE TABLE eq_entities (edinet_code VARCHAR, sec_code VARCHAR, "
                "name_en VARCHAR)")
    con.execute("INSERT INTO eq_entities VALUES ('E1', '1001', 'Alpha Corp')")
    con.close()


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        path = os.path.join(cls.tmp, "eq.duckdb")
        build(path)
        cls.con = duckdb.connect(path, read_only=True)
        cls._cur = earnings_api._cur
        earnings_api._cur = lambda: cls.con.cursor()

    @classmethod
    def tearDownClass(cls):
        earnings_api._cur = cls._cur
        cls.con.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def company(self, code, doc_key=""):
        return earnings_api.company(code, doc_key=doc_key, wire=10)

    def line(self, rows, name):
        return next(r for r in rows if r["line"] == name)

    def test_results_and_forecast_stay_apart_and_progress_carries_its_inputs(self):
        d = self.company("1001")
        self.assertEqual(d["name_en"], "Alpha Corp")
        rev = self.line(d["results"], "revenue")
        self.assertEqual((rev["value"], rev["prior_value"], rev["yoy_pct_published"]),
                         (1000.0, 906.0, 10.4))
        self.assertNotIn("forecast", rev)
        op = self.line(d["forecast"], "operating_income")
        self.assertEqual((op["forecast"], op["progress_pct"]), (400.0, 30.0))
        self.assertEqual(d["calc"]["progress_pct"], earnings_api.CALC["progress_pct"])

    def test_a_reissue_is_current_and_the_first_release_is_kept(self):
        d = self.company("1001")
        self.assertEqual(d["release"]["doc_key"], "A2")
        self.assertTrue(d["release"]["review_completed"])
        first = next(r for r in d["releases"] if r["doc_key"] == "A1")
        self.assertEqual((first["is_current"], first["replaced_by"]), (False, "A2"))
        old = self.company("1001", doc_key="A1")
        self.assertEqual(self.line(old["results"], "operating_income")["value"], 100.0)

    def test_as_of_serves_the_release_the_market_had(self):
        with asof.scope("2026-08-04"):
            d = self.company("1001")
        self.assertEqual(d["release"]["doc_key"], "A1")
        self.assertTrue(d["release"]["is_current"])
        self.assertTrue(all(w["filed_date"] <= datetime.date(2026, 8, 4) for w in d["wire"]))
        with asof.scope("2026-08-01"):
            with self.assertRaises(HTTPException) as ctx:
                self.company("1001")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_no_progress_against_a_range_a_loss_or_nothing(self):
        rng = self.line(self.company("1002")["forecast"], "operating_income")
        self.assertEqual((rng["forecast"], rng["forecast_lower"], rng["forecast_upper"]),
                         (None, 200.0, 300.0))
        self.assertIsNone(rng["progress_pct"])
        loss = self.line(self.company("1003")["forecast"], "operating_income")
        self.assertIsNone(loss["progress_pct"])
        # A company that gives no forecast has none: missing, never zero.
        self.assertEqual(self.company("1004")["forecast"], [])

    def test_screen_ranks_current_releases_within_one_period(self):
        d = earnings_api.screen(sort="progress", line="operating_income", period="q1",
                                fiscal_period="", order="desc", limit=50)
        self.assertEqual([(c["sec_code"], c["doc_key"], c["sort_value"]) for c in d["companies"]],
                         [("1001", "A2", 30.0)])
        with self.assertRaises(HTTPException):
            earnings_api.screen(sort="progress", line="operating_income", period="full-year",
                                fiscal_period="", order="desc", limit=50)

    def test_tables_from_the_older_parser_are_not_published_yet_rather_than_an_error(self):
        path = os.path.join(self.tmp, "td1.duckdb")
        con = duckdb.connect(path)
        con.execute("CREATE TABLE eq_tdnet_filings (doc_key VARCHAR, period VARCHAR)")
        con.execute("CREATE TABLE eq_tdnet_items (disclosed_on DATE, title VARCHAR)")
        con.close()
        old = duckdb.connect(path, read_only=True)
        earnings_api._cur = lambda: old.cursor()
        try:
            with self.assertRaises(HTTPException) as ctx:
                earnings_api.summary()
            self.assertEqual(ctx.exception.status_code, 503)
        finally:
            earnings_api._cur = lambda: self.con.cursor()
            old.close()

    def test_wire_filters_by_kind(self):
        d = earnings_api.wire(kind="forecast-revision", q="", day="", limit=10)
        self.assertEqual([w["kind"] for w in d["disclosures"]], ["forecast-revision"])


if __name__ == "__main__":
    unittest.main()
