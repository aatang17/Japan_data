# -*- coding: utf-8 -*-
"""The two bank parsers on the layouts that bit during development.

bank_extract reads the maturity ladder and the securities note out of the
annual report's HTML tables; irrbb_collect reads the IRRBB1 table out of a
PDF's text. Both are table parses with no tagged numbers behind them, so the
fixtures here are the shapes that actually appear: a ladder with the
securities line left blank and only its parts printed, a five-bucket ladder
with an open-ended 7年超, a securities table with no 種類 column, and the
IRRBB1 text as pdftotext lays it out with two tables side by side.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "equity"))

import bank_extract as b        # noqa: E402
import irrbb_collect as irr     # noqa: E402


def _table(rows):
    return "<table>" + "".join(
        "<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>" for r in rows) + "</table>"


LADDER = [
    ["", "１年以内", "１年超３年以内", "３年超５年以内", "５年超７年以内", "７年超10年以内", "10年超"],
    ["有価証券", "", "", "", "", "", ""],
    ["満期保有目的の債券", "1,000", "2,000", "－", "－", "－", "－"],
    ["うち国債", "1,000", "2,000", "－", "－", "－", "－"],
    ["その他有価証券のうち満期があるもの", "10,000", "20,000", "30,000", "5,000", "5,000", "40,000"],
    ["うち国債", "4,000", "8,000", "12,000", "－", "2,000", "30,000"],
    ["地方債", "6,000", "12,000", "18,000", "5,000", "3,000", "10,000"],
    ["貸出金(*)", "100,000", "90,000", "80,000", "50,000", "40,000", "70,000"],
    ["合計", "111,000", "112,000", "110,000", "55,000", "45,000", "110,000"],
]


def test_ladder_with_blank_securities_line_passes_the_gate():
    cells, _ = b.grid_of(_table(LADDER))
    hdr, cols = b.bucket_columns(cells)
    assert hdr == 0 and len(cols) == 6
    rows = b.parse_maturity(cells, hdr, cols)
    keys = [(r[1], r[2]) for r in rows]
    assert ("securities", None) in keys
    assert ("htm", "securities") in keys and ("afs", "securities") in keys
    assert ("jgb", "htm") in keys and ("jgb", "afs") in keys
    assert ("municipal", "afs") in keys and ("loans", None) in keys
    # the blank 有価証券 line takes the sum of its printed parts, and 合計 reconciles
    assert b.maturity_gate(rows) is None
    sec = [r for r in rows if r[1] == "securities"][0]
    assert b.top_value(sec, rows, "within_1y") == 11000.0
    assert sec[3]["within_1y"] is None            # stored as printed: blank


def test_five_bucket_ladder_is_marked_open_ended():
    five = [["", "1年以内", "1年超3年以内", "3年超5年以内", "5年超7年以内", "7年超"],
            ["有価証券", "1", "2", "3", "4", "5"],
            ["貸出金", "10", "20", "30", "40", "50"],
            ["合計", "11", "22", "33", "44", "55"]]
    cells, _ = b.grid_of(_table(five))
    hdr, cols = b.bucket_columns(cells)
    assert "over_10y" not in cols and cols["y7_10"] == 5
    rows = b.parse_maturity(cells, hdr, cols)
    assert b.maturity_gate(rows) is None


def test_securities_table_without_a_type_column():
    afs = [["", "連結貸借対照表計上額（百万円）", "取得原価（百万円）", "差額（百万円）"],
           ["連結貸借対照表計上額が取得原価を超えるもの", "", "", ""],
           ["株式", "300", "100", "200"],
           ["債券", "50", "49", "1"],
           ["国債", "50", "49", "1"],
           ["小計", "350", "149", "201"],
           ["連結貸借対照表計上額が取得原価を超えないもの", "", "", ""],
           ["株式", "20", "30", "△10"],
           ["債券", "1,000", "1,100", "△100"],
           ["国債", "1,000", "1,100", "△100"],
           ["うち外国債券", "－", "－", "－"],
           ["小計", "1,020", "1,130", "△110"],
           ["合計", "1,370", "1,279", "91"]]
    cells, _ = b.grid_of(_table(afs))
    category, rows = b.parse_securities(cells)
    assert category == "afs"
    by = {(r[0], r[2]): r for r in rows}
    assert by[("below", "bonds")][6] == -100.0
    assert by[("below", "foreign")][3] is None       # "－" is missing, not zero
    assert by[("total", "total")][3] == 1370.0
    assert b.securities_gate(rows) is None


IRRBB_TEXT = u"""IRRBB：銀行勘定の金利リスク
【連結】                                   （単位：百万円）
項番                    ⊿EVE                  ⊿NII
                  2025年度末   2024年度末   2025年度末  2024年度末
 1   上方パラレルシフト      37,904     30,548     13,171     8,071
 2   下方パラレルシフト      99,328     85,597     14,973    11,716
 3   スティープ化          15,610      7,875
 4   フラット化           57,237     51,818
 5   短期金利上昇          18,462     13,025
 6   短期金利低下               1          1
 7   最大値             99,328     85,597     14,973    11,716
 8   Tier1資本の額                  568,281              520,253
"""


def test_irrbb_table_reads_rows_max_and_tier1():
    tables = irr.find_tables(IRRBB_TEXT)
    assert len(tables) == 1
    t = tables[0]
    assert t["unit"] == u"百万円"
    assert t["as_of"].isoformat() == "2026-03-31"     # 2025年度末 is March 2026
    assert t["basis"] == "consolidated"
    rows, reason, t1_cur, t1_prior = irr.interpret(t)
    assert reason is None
    assert (t1_cur, t1_prior) == (568281.0, 520253.0)
    got = {r[0]: r for r in rows}
    assert got["parallel_down"][1:] == (99328.0, 85597.0, 14973.0, 11716.0)
    assert got["steepener"][1:] == (15610.0, 7875.0, None, None)
    assert got["max"][1] == 99328.0


def test_irrbb_side_by_side_tables_split_into_two():
    two = u"\n".join(
        (ln + u"        " + ln.replace(u"37,904", u"30,000").replace(u"99,328", u"90,000")
         .replace(u"568,281", u"500,000")) if ln.strip()[:1].isdigit() else ln
        for ln in IRRBB_TEXT.replace(u"【連結】", u"【連結】             【単体】").split(u"\n"))
    tables = irr.find_tables(two)
    assert [t["basis"] for t in tables] == ["consolidated", "non-consolidated"]
    left, _r1, t1l, _ = irr.interpret(tables[0])
    right, _r2, t1r, _ = irr.interpret(tables[1])
    assert {r[0]: r[1] for r in left}["parallel_up"] == 37904.0
    assert {r[0]: r[1] for r in right}["parallel_up"] == 30000.0
    assert (t1l, t1r) == (568281.0, 500000.0)


def test_irrbb_max_mismatch_is_reported_not_fixed():
    bad = IRRBB_TEXT.replace(u"7   最大値             99,328", u"7   最大値             12,345")
    t = irr.find_tables(bad)[0]
    _rows, reason, _a, _b = irr.interpret(t)
    assert reason and reason.startswith("max_mismatch")


# Layouts from the September 2026 re-collection, as pdftotext prints them.

SPACED_PRIOR_FIRST = u"""IRRBB１：金利リスク
                                                ⊿EVE                          ⊿NII
 項    番
                                         2024年度    2025年度              2024年度    2025年度
  １       上   方    パ   ラ レ ル   シ フ   ト     6,210      5,746              1,826     1,280
  ２       下   方    パ   ラ レ ル   シ フ   ト    60,606     53,775                  0        32
  ３       ス       テ    ィ   ー    プ    化     3,715      4,113
  ４       フ        ラ     ッ     ト     化
  ５       短       期    金   利    上    昇
  ６       短       期    金   利    低    下
  ７       最              大           値    60,606     53,775                1,826      1,280
                                               2024年度                          2025年度
  ８       自       己    資   本   の     額              361,627                         378,276
"""


def test_irrbb_spaced_labels_and_prior_year_first():
    # 十六: every label letter-spaced, and the earlier year printed first
    t = irr.find_tables(u"（単位：百万円）\n" + SPACED_PRIOR_FIRST)[0]
    assert t["as_of"].isoformat() == "2026-03-31"      # the 2025年度 column
    rows, reason, t1_cur, t1_prior = irr.interpret(t)
    assert reason is None
    got = {r[0]: r for r in rows}
    assert got["parallel_down"][1:] == (53775.0, 60606.0, 32.0, 0.0)
    assert got["max"][1] == 53775.0
    assert (t1_cur, t1_prior) == (378276.0, 361627.0)


def test_irrbb_wrapped_label_with_numbers_between_halves():
    # 福島: 上方パラレ / numbers / ルシフト on three lines
    text = u"""IRRBB1:金利リスク                                  （単位：百万円）
                      ⊿EVE                   ⊿NII
                 当期末       前期末         当期末          前期末
1 上方パラレ
                 2,425           578    1,206            851
  ルシフト
2 下方パラレ
                       0          0          0             0
  ルシフト
3 スティープ化               0          0
4 フラット化           516         1,150
5 短期金利上昇         1,365           989
6 短期金利低下               0          0
7 最大値            2,425        1,150     1,206            851
    自己資本の額（連結）               31,882                 31,393
"""
    rows, reason, t1_cur, _ = irr.interpret(irr.find_tables(text)[0])
    assert reason is None
    assert {r[0]: r for r in rows}["parallel_up"][1:] == (2425.0, 578.0, 1206.0, 851.0)
    assert t1_cur == 31882.0


def test_irrbb_bar_printed_for_long_vowel():
    # 福岡: スティ―プ化 with U+2015 where ー belongs; a minus sign is untouched
    assert irr.squeeze(u"3   スティ―プ化    14,469   −5   ―") == u"3   スティープ化    14,469   −5   ―"


def test_irrbb_prose_mentioning_a_shock_is_not_a_table():
    prose = (u"IRRBB\n⊿EVEは、下方パラレルシフトが前期末比260億円減少し、\n"
             u"上方パラレルシフトが最大となりました 70\n")
    assert irr.find_tables(prose) == []


def _t(page, tier1):
    import datetime
    return {"page": page, "tier1": tier1, "as_of": datetime.date(2026, 3, 31)}


def test_group_book_is_refused_without_pages_and_split_with_them():
    book = [_t(61, [378276.0, 361627.0]),          # the holding company
            _t(122, [328616.0, 321574.0]),         # the bank, consolidated
            _t(136, [320186.0, 313732.0])]         # the bank alone
    log = []
    assert irr.own_tables(book, {}, log) == []
    assert log and log[0].startswith("group document")
    mine = irr.own_tables(book, {"pages": [122, 136]}, [])
    assert [t["page"] for t in mine] == [122, 136]
    # one bank's consolidated and bank-only tables are not a group book
    assert irr.own_tables(book[1:], {}, []) == book[1:]


def test_irrbb_four_row_table_is_still_a_table():
    # トモニ: only the rows it measures, and years in 令和 with the earlier first
    text = u"""■金利リスクに関する事項                         （単位：百万円）
                         ⊿EVE                 ⊿NII
   項番
                  令和６年度       令和７年度      令和６年度     令和７年度
    1     上方パラレルシフト        8,151      6,973     7,387      7,955
    2     下方パラレルシフト        7,299      7,830     8,384      4,712
    3     スティープ化             3,152      2,214
    4     最大値                  8,151      7,830     8,384      7,955
                     令和７年３月期               令和８年３月期
    5     自己資本の額              147,949              153,208
IRRBB
"""
    tables = irr.find_tables(text)
    assert len(tables) == 1
    rows, _reason, t1_cur, t1_prior = irr.interpret(tables[0])
    got = {r[0]: r for r in rows}
    assert got["max"][1:] == (7830.0, 8151.0, 7955.0, 8384.0)
    assert (t1_cur, t1_prior) == (153208.0, 147949.0)
