# -*- coding: utf-8 -*-
u"""Business risks (事業等のリスク): cutting the section into items and serving it.

Self-contained: the parser tests run on strings and a zip built in memory, and
the API tests build a small database of their own, so nothing here needs the
archive or the equity file.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_risks
"""
import datetime
import html
import importlib.util
import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import zipfile

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


risk_extract = _load("risk_extract", ROOT / "equity" / "risk_extract.py")

from app import risk_api  # noqa: E402


def package(block_html):
    """A t1 zip whose instance carries one BusinessRisksTextBlock."""
    x = (u'<xbrli:xbrl><jpcrp_cor:BusinessRisksTextBlock contextRef="FilingDateInstant">'
         + html.escape(block_html) + u'</jpcrp_cor:BusinessRisksTextBlock></xbrli:xbrl>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("XBRL/PublicDoc/jpcrp030000-asr-001_E1.xbrl", x.encode("utf-8"))
    return buf.getvalue()


def p(*lines):
    return u"".join(u"<p>%s</p>" % l for l in lines)


class SplitTest(unittest.TestCase):
    def test_two_levels_and_the_preamble(self):
        st, det, by, lines, pre, items = risk_extract.parse(package(
            u"<h3>３【事業等のリスク】</h3>" + p(
                u"文中の将来に関する事項は、当連結会計年度末現在において判断したものです。",
                u"（１）市場に関するリスク", u"①為替変動", u"円高が進むと利益が減少します。",
                u"②原材料価格", u"価格が上昇する可能性があります。",
                u"（２）法的規制", u"規制が変更される可能性があります。")))
        self.assertEqual((st, by), ("clean", "number"))
        self.assertEqual(len(pre), 1)       # the title line is dropped, the caveat kept
        self.assertEqual([(i["level"], i["heading"]) for i in items],
                         [(1, u"（１）市場に関するリスク"), (2, u"①為替変動"),
                          (2, u"②原材料価格"), (1, u"（２）法的規制")])
        self.assertEqual(items[1]["parent"], 0)
        self.assertEqual(items[3]["parent"], None)

    def test_a_number_out_of_sequence_never_opens_an_item(self):
        # A body list restarting at (1) inside item (2) is body text.
        st, _, _, _, _, items = risk_extract.parse(package(p(
            u"(1) 競合", u"本文。", u"(2) 人材", u"(1) 採用が難しい。", u"(3) 災害", u"本文。")))
        self.assertEqual([i["heading"] for i in items if i["level"] == 1],
                         [u"(1) 競合", u"(2) 人材", u"(3) 災害"])

    def test_nothing_is_lost(self):
        _, _, _, lines, pre, items = risk_extract.parse(package(p(
            u"前置き。", u"1. 為替", u"本文一。", u"2. 金利", u"本文二。")))
        self.assertEqual(pre + [l for i in items for l in i["lines"]], lines)

    def test_bracketed_headings_when_there_are_no_numbers(self):
        st, _, by, _, _, items = risk_extract.parse(package(p(
            u"前置き。", u"（景気動向）", u"本文。", u"（為替レートの変動）", u"本文。")))
        self.assertEqual((st, by, len(items)), ("clean", "heading", 2))

    def test_repeated_labels_are_not_headings(self):
        st, _, _, lines, pre, items = risk_extract.parse(package(p(
            u"（リスク）", u"本文。", u"（対応策）", u"本文。", u"（リスク）", u"本文。")))
        self.assertEqual((st, items), ("unsplit", []))
        self.assertEqual(pre, lines)

    def test_no_block_is_reported(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("XBRL/PublicDoc/x.xbrl", b"<xbrli:xbrl></xbrli:xbrl>")
        self.assertEqual(risk_extract.parse(buf.getvalue())[0], "no_block")

    def test_table_rows_become_lines(self):
        _, _, _, lines, _, _ = risk_extract.parse(package(
            u"<table><tr><td>リスク</td><td>影響度</td></tr><tr><td>為替</td><td>大</td></tr></table>"))
        self.assertEqual(lines, [u"リスク | 影響度", u"為替 | 大"])


def build(path):
    con = duckdb.connect(path)
    con.execute(risk_extract.SCHEMA_SQL)
    for doc, pe, fd, heads in (
            ("D1", "2025-03-31", "2025-06-20", [u"(1) 為替変動", u"(2) 旧いリスク"]),
            ("D2", "2026-03-31", "2026-06-20", [u"(1) 為替変動", u"(2) 関税"])):
        con.execute("INSERT INTO eq_risk_filings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [doc, "E1", "1001", u"アルファ株式会社", pe, fd, "sha", "risk-1",
                     "clean", None, "number", 100, 2, 2, u"前置き。", None])
        for i, h in enumerate(heads):
            con.execute("INSERT INTO eq_risk_items VALUES (?,?,?,?,?,?,?,?,?)",
                        [doc, i, 1, None, h[:3], h, False, u"本文に為替の話。", 10])
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
        cls._cur = risk_api._cur
        risk_api._cur = lambda: cls.con.cursor()

    @classmethod
    def tearDownClass(cls):
        risk_api._cur = cls._cur
        cls.con.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_latest_report_is_compared_with_the_previous_one(self):
        d = risk_api.company("1001", year="")
        self.assertEqual(d["doc_id"], "D2")
        self.assertEqual(d["name_en"], "Alpha Corp")
        self.assertEqual([i["new"] for i in d["items"]], [False, True])
        self.assertEqual(d["dropped"], [u"(2) 旧いリスク"])
        self.assertIsNone(d["full_text"])          # itemised: the text is the items

    def test_the_earliest_report_has_nothing_to_compare_with(self):
        d = risk_api.company("1001", year="2025")
        self.assertEqual(d["doc_id"], "D1")
        self.assertEqual([i["new"] for i in d["items"]], [None, None])
        self.assertIsNone(d["dropped"])

    def test_unknown_company_and_year_are_404(self):
        with self.assertRaises(HTTPException):
            risk_api.company("9999", year="")
        with self.assertRaises(HTTPException):
            risk_api.company("1001", year="2019")

    def test_search_reads_only_the_latest_report(self):
        d = risk_api.search(q=u"関税", limit=100)
        self.assertEqual(d["companies_matched"], 1)
        self.assertEqual(risk_api.search(q=u"旧いリスク", limit=100)["companies_matched"], 0)

    def test_heading_key_ignores_renumbering(self):
        self.assertEqual(risk_api.heading_key(u"（３）為替 変動"), risk_api.heading_key(u"(4) 為替変動"))
        self.assertEqual(risk_api.heading_key(u"③為替変動"), u"為替変動")


if __name__ == "__main__":
    unittest.main()
