# -*- coding: utf-8 -*-
"""M1 — facilities extraction prototype (主要な設備の状況).

Question this prototype answers: can the major-facilities table be parsed
reliably enough to power a map — facility name, city-level location, and the
per-asset-class book values, with land AREA (㎡) where disclosed?

Source is the t1 (full XBRL) package, NOT the t5 CSV the tagged-element
extractors use: the t5 CSV flattens every text block to plain text — <table>
markup stripped, cell boundaries lost — so anything table-shaped inside a
text block (facilities, major customers, geographic segments) is unparseable
there. Both packages are already archived for every annual report; no new
capture. Balance-sheet land is a tagged numeric fact, so the t5 CSV remains
the right source for the cross-check gate.

Sample: 18 filings chosen for maximum layout variance — land-heavy (railways,
steel, refining, real estate) through asset-light (Keyence, a bank holdco),
JGAAP and IFRS, parent-operating and holdco structures.

Traps this parser exists to survive (each found in this sample):
  * One facility spans SEVERAL physical rows. Toyota Boshoku prints the land
    book value on the facility's row and the land AREA on a continuation row
    of its own (every other cell rowspan-carried). Reading physical rows as
    facilities duplicates every such site and loses the area — rows are
    merged by where the name cell ORIGINATES.
  * 面積 subcolumns. Banks and railways put land area in its own column
    under 土地 (and building area under 建物); positional reading sums ㎡
    into yen. A column whose leaf header says 面積 is never a book value.
  * Summary vs detail double-counting. JR East publishes a per-segment
    総括表 AND per-station detail of the same assets; summing every table
    counts the railway twice. A table with neither a name nor a location
    column is a summary — kept for display, excluded from totals.
  * Non-asset tables in the same block. JR East's block carries track
    sections, rolling-stock counts and leased-line tables; only tables with
    a 帳簿価額 column are facilities.
  * 小計/合計/消去又は全社 rows inside the data (SG Holdings) are subtotals,
    not facilities.
  * The land cell is a grammar, not a number — Kobe Steel files leased-in
    area, owned area with an inline ㎡ unit, then book value, in one cell.
  * The same words mean opposite things by layout: Sojitz's 土地 面積(千m2)
    column is areas (its sibling 土地/帳簿価額 holds the money); Toyota
    Boshoku's single 土地(面積m2) column is money with area in parentheses.
  * Trust assets are separate columns: Keihanshin Building files 建物 AND
    信託建物, 土地 AND 信託土地 — and balance-sheet trust land lives in a
    filer-extension element (…LandInTrustPPE), so the gate sums both sides.
  * A 総括表 ends 計 → 消去又は全社 → 合計: the filer's own 合計 row is the
    total; re-summing the segment rows overstates by the elimination.
  * Elimination rows print negatives in parentheses — indistinguishable from
    the (annotation) convention per-cell, so negative-total rows are recorded
    but not gated.
  * 当社グループ in a heading means the GROUP even though 当社 alone means
    the parent (SG Holdings).

Gates (both recompute the filer's own published numbers):
  1. Row gate — where a table has a 合計 column, the asset-class cells must
     sum back to it (tolerance: one rounded unit per summed column).
  2. Balance-sheet gate — land book value across the tables (summaries
     preferred per scope, see above) must not exceed the balance sheet's
     tagged land (jppfs_cor:Land, consolidated). "Major facilities" is a
     subset, so ≤ is the test, not ==. IFRS adopters tag no consolidated
     jppfs Land — recorded as parent_only_bs, not failed.

Outputs: out/facilities.json (every parsed row + gate results) and a printed
report. Python 3.9, stdlib only.
"""
import csv
import glob
import io
import json
import os
import re
import sys
import unicodedata
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "..", "data", "raw", "edinet", "docs")
OUT = os.path.join(HERE, "out")

# docID, filer, period end — all verified present in the local archive.
SAMPLE = [
    ("S100YC7N", "東日本旅客鉄道", "2026-03-31"),        # railway, the land case
    ("S100Y8FK", "東武鉄道", "2026-03-31"),              # railway, private
    ("S100YL5Y", "京成電鉄", "2026-03-31"),              # railway, private
    ("S100YCDA", "神戸製鋼所", "2026-03-31"),            # steel, many plants
    ("S100YCS3", "出光興産", "2026-03-31"),              # refining, huge sites
    ("S100Y992", "味の素", "2026-03-31"),                # food, overseas plants
    ("S100YC72", "ＴＯＴＯ", "2026-03-31"),              # ceramics
    ("S100YCMK", "帝人", "2026-03-31"),                  # chemicals/fibers
    ("S100Y9AH", "トヨタ紡織", "2026-03-31"),            # auto parts
    ("S100Y90T", "ＨＯＹＡ", "2026-03-31"),              # precision, IFRS
    ("S100Y951", "ＺＯＺＯ", "2026-03-31"),              # retail, leased DCs
    ("S100YC9O", "京阪神ビルディング", "2026-03-31"),    # real estate
    ("S100Y9EI", "双日", "2026-03-31"),                  # trading, IFRS
    ("S100YA7J", "十六フィナンシャルグループ", "2026-03-31"),  # bank holdco
    ("S100YAHE", "キーエンス", "2026-03-20"),            # famously asset-light
    ("S100YBT6", "日本郵船", "2026-03-31"),              # shipping: vessels
    ("S100YFIO", "日本航空", "2026-03-31"),              # airline: aircraft
    ("S100Y9P7", "ＳＧホールディングス", "2026-03-31"),  # logistics holdco
]

FACILITIES_MARK = "MajorFacilitiesTextBlock"
NOT_APPLICABLE_RE = re.compile(u"該当(?:事項)?\\s*(?:は)?\\s*(?:あり)?(?:ません|なし|無し)")

PREF_RE = re.compile(
    u"(北海道|東京都|京都府|大阪府|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|"
    u"千葉県|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|兵庫県|"
    u"奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|"
    u"熊本県|大分県|宮崎県|鹿児島県|沖縄県|東京都区内|神戸市|大阪市|京都市|名古屋市|横浜市|川崎市|札幌市|"
    u"仙台市|さいたま市|千葉市|福岡市|広島市)")

SUBTOTAL_RE = re.compile(u"^(小計|合計|計|総合計|消去\\s*又は\\s*全社|セグメント間消去|消去|全社|調整額|セグメント間取引消去|合\\s*計)$")


def norm(s):
    s = (s or "").replace("&#160;", " ").replace("&nbsp;", " ")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    s = unicodedata.normalize("NFKC", s).replace(u" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def strip_tags(s):
    return norm(re.sub(r"<[^>]+>", " ", s))


ANNOT_RE = re.compile(r"<[^>]*>")  # a decoded &lt;36&gt; is an annotation, not data


def to_num(s):
    """Strip trailing annotations rather than reject the cell: Ajinomoto
    writes 2,451 (6) and rejecting it silently drops the asset from the row
    sum — the same trap the buyback extractor documents."""
    s = ANNOT_RE.sub(" ", norm(s))
    while True:
        s2 = re.sub(u"\\s*[（(][^（()）]*[）)]\\s*$", "", s).strip()
        if s2 == s:
            break
        s = s2
    s = s.replace(",", "")
    s = re.sub(u"[%％株円㎡]+$", "", s).strip()
    if not s or s in ("-", u"−", u"―", u"ー", u"—", u"△", "*"):
        return None
    if re.fullmatch(u"[△-]?\\d+(?:\\.\\d+)?", s):
        return float(s.replace(u"△", "-"))
    return None


# ---------------------------------------------------------------- table grid

def grid_of(table_html):
    """Expand rowspan/colspan into a rectangular grid, remembering where each
    cell ORIGINATES. The facilities table is the poster child for merged
    cells, and origin is what separates a new facility from the continuation
    row that carries only its land area."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I)
    grid, origin, taken, max_c = {}, set(), set(), 0
    for r, row in enumerate(rows):
        c = 0
        for m in re.finditer(r"<t([dh])\b([^>]*)>(.*?)</t\1>", row, re.S | re.I):
            attrs, content = m.group(2), m.group(3)
            while (r, c) in taken:
                c += 1
            rs = re.search(r'rowspan="?(\d+)', attrs)
            cs = re.search(r'colspan="?(\d+)', attrs)
            rs = int(rs.group(1)) if rs else 1
            cs = int(cs.group(1)) if cs else 1
            text = strip_tags(content)
            origin.add((r, c))
            for dr in range(rs):
                for dc in range(cs):
                    grid[(r + dr, c + dc)] = text
                    taken.add((r + dr, c + dc))
            c += cs
            max_c = max(max_c, c)
    cells = [[grid.get((r, c), "") for c in range(max_c)] for r in range(len(rows))]
    return cells, origin


# ------------------------------------------------------------- column typing

# Tested in order. segment before name: セグメントの名称 contains 名称 and must
# not steal the name slot. cip before buildings for the same reason (建).
COLUMN_TYPES = [
    ("location", (u"所在地",)),
    ("segment", (u"セグメント",)),
    ("name", (u"事業所名", u"事業所", u"店名", u"店舗名", u"設備等の名称", u"名称", u"会社名", u"物件名")),
    ("contents", (u"設備の内容", u"設備内容", u"設備の 内容")),
    ("cip", (u"建設仮勘定",)),
    ("buildings", (u"建物",)),
    ("structures", (u"構築物",)),
    ("machinery", (u"機械",)),
    ("vessels", (u"船舶",)),
    ("aircraft", (u"航空機",)),
    ("vehicles", (u"車両", u"運搬具")),
    ("land", (u"土地",)),
    ("lease", (u"リース", u"使用権")),
    ("tools", (u"工具", u"器具", u"備品")),
    ("software", (u"ソフト",)),
    ("movables", (u"動産",)),
    ("investment_property", (u"投資不動産",)),
    ("other_assets", (u"その他",)),
    ("total", (u"合計", u"計")),
    ("employees", (u"従業員",)),
]

ASSET_KEYS = ("buildings", "structures", "machinery", "vessels", "aircraft",
              "vehicles", "land", "lease", "tools", "software", "movables",
              "investment_property", "cip", "other_assets")
ASSET_KEYS = ASSET_KEYS + tuple(k + "2" for k in ASSET_KEYS)  # 信託建物 etc.


def classify_column(label):
    for key, kws in COLUMN_TYPES:
        if any(k in label for k in kws):
            return key
    return None


def header_depth(grid):
    """Header rows carry keyword labels; data rows carry numbers or an
    address. The first row with ≥2 numeric cells, or a prefecture in any
    cell, is data. Overseas-subsidiary tables have no prefecture, hence the
    numeric test carries them."""
    for r, row in enumerate(grid):
        nums = sum(1 for c in row if to_num(c) is not None)
        if nums >= 2 or any(PREF_RE.search(c) for c in row):
            return r
    return min(len(grid), 1)


def scope_of(heading):
    t = norm(heading)
    if u"及び連結子会社" in t or u"連結会社" in t or u"当社グループ" in t:
        return "group"
    if u"提出会社" in t or u"当社" in t:
        return "parent"
    if u"在外" in t:
        return "overseas_sub"
    if u"国内" in t or u"子会社" in t or u"連結" in t:
        return "domestic_sub"
    return t[:40] if t else ""


BOOK_UNITS = [(u"百万円", 1e6), (u"千円", 1e3), (u"億円", 1e8)]
AREA_UNITS = [(u"千㎡", 1e3), (u"千m2", 1e3), (u"㎡", 1.0), (u"m2", 1.0)]


def unit_of(text, table):
    for label, mult in table:
        if label in text:
            return label, mult
    return None, None


PAREN_NUM_RE = re.compile(u"[（(]\\s*([\\d,]+(?:\\.\\d+)?)\\s*[）)]")
BRACKET_NUM_RE = re.compile(u"[〔\\[]\\s*([\\d,]+(?:\\.\\d+)?)\\s*[〕\\]]")


LAND_TOKEN_RE = re.compile(u"([（(])?\\s*([\\d,]+(?:\\.\\d+)?)\\s*(千?m2)?\\s*([）)])?")


def parse_land_cell(cell):
    """Land cells are a grammar, not a number. Observed forms:
      2,322 (326,785) <36>              — book, then area in parens (Toyota Boshoku)
      (13,035m2) 5,036,909m2 18,498     — leased-in area, owned area with an
                                          inline ㎡ unit, then book (Kobe Steel)
      777 (231)                          — book, area in the column's 千㎡ unit
    Tokens: a ㎡-suffixed number is area (parenthesized → leased-in); a bare
    parenthesized number is area; the first bare plain number is book. 〔 〕
    is leased-in area. An inline unit means the value is already in ㎡, so the
    caller must not apply the column unit again."""
    raw = ANNOT_RE.sub(" ", norm(cell))
    m = BRACKET_NUM_RE.search(raw)
    leased = float(m.group(1).replace(",", "")) if m else None
    raw = BRACKET_NUM_RE.sub(" ", raw)
    book = area = None
    inline_unit = False
    for m in LAND_TOKEN_RE.finditer(raw):
        if not m.group(2):
            continue
        val = float(m.group(2).replace(",", ""))
        paren = bool(m.group(1) or m.group(4))
        unit = m.group(3)
        if unit:
            val *= 1e3 if u"千" in unit else 1.0
            if paren:
                leased = (leased or 0) + val
            else:
                area, inline_unit = val, True
        elif paren:
            if area is None:
                area = val
        elif book is None:
            book = val
    return book, area, leased, inline_unit


def paren_or_plain_num(cell):
    m = PAREN_NUM_RE.search(norm(cell))
    if m:
        return float(m.group(1).replace(",", ""))
    return to_num(PAREN_NUM_RE.sub("", norm(cell)))


# ---------------------------------------------------------------- table read

def is_pure_area(leaf):
    """A leaf header that is nothing but 面積 + a unit — 面積(m2), 総面積,
    賃貸面積(千m2) — names no asset and is never a book value. A leaf that
    keeps other words after stripping those (使用権資産 (面積千m2), 土地 面積)
    still names something and must be classified."""
    return u"面積" in leaf and re.sub(u"[面積千m2㎡()（）:：総賃貸 ]", "", leaf) == ""


def map_columns(grid, depth):
    """Classify each column by its joined header labels; the LEAF label (the
    deepest header cell) decides what is an area column.

    Land needs its own two-pass resolution because the same words mean
    opposite things by layout: Sojitz files 土地 面積(千m2) NEXT TO
    土地/帳簿価額 (the first is areas), while Toyota Boshoku's single
    土地(面積m2) column is book value with the area in parentheses. With one
    candidate the column is the combined book column; with several, the leaf
    saying 面積 is the area column and the leaf saying 価額/金額 the book."""
    ncols = len(grid[0]) if grid else 0
    cols, land_cands = {}, []
    land_area_col, land_area_mult = None, None
    for c in range(ncols):
        parts = [grid[r][c] for r in range(depth) if grid[r][c]]
        parts = list(dict.fromkeys(parts))
        label = " ".join(parts)
        leaf = parts[-1] if parts else ""
        if u"土地" in label:
            land_cands.append((c, label, leaf))
            continue
        if is_pure_area(leaf):
            continue  # 建物/面積, 賃貸面積 … — never yen
        key = classify_column(label)
        if key:
            # A second column of the same class is a distinct asset, not a
            # duplicate: 信託建物 next to 建物 (Keihanshin Building).
            if key not in cols:
                cols[key] = c
            elif key + "2" not in cols and key in dict(COLUMN_TYPES) and key not in (
                    "name", "location", "segment", "contents", "total", "employees"):
                cols[key + "2"] = c
    if len(land_cands) == 1:
        c, label, leaf = land_cands[0]
        cols["land"] = c
        _, land_area_mult = unit_of(label, AREA_UNITS)
    elif land_cands:
        # 価額/金額 in a leaf marks explicit book columns; everything else is
        # then an area column (Sojitz's 土地 面積(千m2) names the asset but is
        # areas — its sibling 土地/帳簿価額 proves it). With NO explicit book
        # column, the non-pure-area candidates are combined book columns —
        # Keihanshin Building files 土地(面積m2) AND 信託土地(面積m2), two
        # different assets, so a second book column becomes land2.
        book_cands = [(c, label, leaf) for c, label, leaf in land_cands
                      if u"価額" in leaf or u"金額" in leaf]
        if book_cands:
            others = [(c, label, leaf) for c, label, leaf in land_cands
                      if (c, label, leaf) not in book_cands]
        else:
            book_cands = [(c, label, leaf) for c, label, leaf in land_cands
                          if not is_pure_area(leaf)]
            others = [(c, label, leaf) for c, label, leaf in land_cands
                      if is_pure_area(leaf)]
        if book_cands:
            cols["land"] = book_cands[0][0]
            if land_area_mult is None:
                _, land_area_mult = unit_of(book_cands[0][1], AREA_UNITS)
        if len(book_cands) > 1:
            cols["land2"] = book_cands[1][0]
        for c, label, leaf in others:
            if land_area_col is None:
                land_area_col = c
                _, land_area_mult = unit_of(leaf + " " + label, AREA_UNITS)
    return cols, land_area_col, land_area_mult


def logical_rows(grid, origin, depth, anchor_col):
    """Merge physical continuation rows into logical facilities: a new
    facility starts where the anchor (name/location) cell originates; rows
    where it is rowspan-carried only contribute their originating cells,
    appended into the same logical record (Toyota Boshoku's land-area rows)."""
    out = []
    for r in range(depth, len(grid)):
        starts = (r, anchor_col) in origin
        if starts or not out:
            out.append([list(grid[r]), r])
        else:
            merged = out[-1][0]
            for c in range(len(grid[r])):
                if (r, c) in origin and grid[r][c]:
                    merged[c] = (merged[c] + " " + grid[r][c]).strip()
    return [cells for cells, _ in out]


def parse_table(table_html, scope):
    grid, origin = grid_of(table_html)
    if not grid or not grid[0]:
        return None
    depth = header_depth(grid)
    if depth == 0:
        return None
    cols, land_area_col, land_area_mult = map_columns(grid, depth)
    header_text = " ".join(" ".join(r) for r in grid[:depth])
    # Only tables pricing assets belong to this dataset — the same block
    # carries track sections, rolling stock and leased lines (JR East).
    if u"帳簿価額" not in header_text or not any(k in cols for k in ASSET_KEYS):
        return None
    book_unit, book_mult = unit_of(header_text, BOOK_UNITS)
    if u"面積" in header_text and land_area_mult is None:
        m = re.search(u"面積[^）)]{0,6}", header_text)
        _, land_area_mult = unit_of(m.group(0) if m else "", AREA_UNITS)
    anchor = cols.get("name", cols.get("location", 0))
    is_summary = "name" not in cols and "location" not in cols
    rows, subtotal_rows = [], []
    for cells in logical_rows(grid, origin, depth, anchor):
        rec = {"scope": scope}
        for key in ("name", "location", "segment", "contents"):
            if key in cols:
                rec[key] = cells[cols[key]] or None
        for key in ASSET_KEYS:
            if key not in cols:
                continue
            if key in ("land", "land2"):
                book, area, leased, inline = parse_land_cell(cells[cols[key]])
                if key == "land" and land_area_col is not None and area is None:
                    area = paren_or_plain_num(cells[land_area_col])
                rec[key], rec[key + "_area"], rec[key + "_area_leased"] = book, area, leased
                rec["land_area_inline_unit"] = inline
            else:
                rec[key] = to_num(cells[cols[key]])
        if "total" in cols:
            rec["total"] = to_num(cells[cols["total"]])
        if "employees" in cols:
            rec["employees"] = to_num(re.split(u"[（(〔\\[]", norm(cells[cols["employees"]]))[0])
        has_numbers = any(rec.get(k) is not None for k in ASSET_KEYS + ("total",))
        if not has_numbers and not rec.get("location"):
            continue
        first = norm(next((c for c in cells if c), ""))
        if SUBTOTAL_RE.match(first) or SUBTOTAL_RE.match(norm(rec.get("name") or "")):
            subtotal_rows.append(rec)
        else:
            rows.append(rec)
    return {"scope": scope, "columns": sorted(cols), "book_unit": book_unit,
            "book_mult": book_mult,
            "area_mult": land_area_mult or 1.0, "n_header_rows": depth,
            "is_summary": is_summary, "rows": rows, "subtotal_rows": subtotal_rows}


TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.S | re.I)


def parse_block(blob_html):
    """One text block, several tables, each introduced by a heading —
    (1)提出会社 (2)国内子会社 (3)在外子会社 — that lives BETWEEN tables, so the
    scope of a table is the trailing text of the gap before it."""
    tables, pos, scope = [], 0, ""
    for m in TABLE_RE.finditer(blob_html):
        gap = strip_tags(blob_html[pos:m.start()])
        found = re.findall(
            u"(当社及び連結子会社|提出会社及び連結子会社|当社グループ|連結会社|提出会社|国内子会社|在外子会社|当社|連結子会社)", gap)
        if found:
            scope = found[-1]
        t = parse_table(m.group(0), scope_of(scope))
        if t and (t["rows"] or t["subtotal_rows"]):
            tables.append(t)
        pos = m.end()
    return tables


# --------------------------------------------------------------------- gates

def gate_rows(tables):
    """Where the filer publishes a 合計 column, the asset cells must sum back
    to it. Each printed cell is independently rounded, so the tolerance is one
    unit per summed column, not one unit overall."""
    ok = bad = unverified = 0
    examples = []
    for t in tables:
        for rec in t["rows"] + t["subtotal_rows"]:
            stated = rec.get("total")
            parts = [rec.get(k) for k in ASSET_KEYS if rec.get(k) is not None]
            # Elimination rows print negatives in parentheses — the accounting
            # convention collides with the (annotation) convention and no
            # per-cell read can tell them apart, so negative-total rows are
            # recorded, not gated.
            if stated is None or stated < 0 or not parts:
                unverified += 1
                continue
            if abs(sum(parts) - stated) <= max(1.0, len(parts)):
                ok += 1
            else:
                bad += 1
                if len(examples) < 3:
                    examples.append("%s: parts %.0f vs 合計 %.0f"
                                    % ((rec.get("name") or rec.get("location") or "?")[:25],
                                       sum(parts), stated))
    return ok, bad, unverified, examples


def countable_tables(tables):
    """Per scope: when a summary table exists, it IS that scope's total and
    the detail tables are a breakdown of the same assets — count one, never
    both (the JR East trap)."""
    group_summaries = [t for t in tables
                       if t["is_summary"] and t["scope"] in ("group", "")]
    if group_summaries:  # a 総括表 with a group heading — or none — covers all
        return group_summaries
    by_scope = {}
    for t in tables:
        by_scope.setdefault(t["scope"], []).append(t)
    keep = []
    for scope_tables in by_scope.values():
        summaries = [t for t in scope_tables if t["is_summary"]]
        keep.extend(summaries if summaries else scope_tables)
    return keep


def stated_total_row(t):
    """A 総括表 often ends 計 → 消去又は全社 (negative) → 合計. The filer's own
    合計 row IS the table's total; re-summing the segment rows overstates by
    the elimination (Keisei, SG Holdings)."""
    for rec in reversed(t["subtotal_rows"]):
        label = norm(rec.get("name") or rec.get("segment") or rec.get("location") or "")
        if re.match(u"^(合\\s*計|総合計)$", label) and rec.get("land") is not None:
            return rec
    return None


def land_totals(tables):
    book = area = 0.0
    for t in countable_tables(tables):
        stated = stated_total_row(t)
        rows = [stated] if stated else t["rows"]
        for r in rows:
            book += ((r.get("land") or 0) + (r.get("land2") or 0)) * (t["book_mult"] or 0)
            am = 1.0 if r.get("land_area_inline_unit") else (t["area_mult"] or 1.0)
            area += ((r.get("land_area") or 0) + (r.get("land2_area") or 0)) * am
    return book, area


def gate_bs_land(tables, bs_land_yen, consolidated):
    """Facilities land (a 'major' subset) must not exceed balance-sheet land.
    2% headroom absorbs the rounding of every cell to 百万円. IFRS adopters
    tag no consolidated jppfs Land, and comparing a group's facilities to the
    parent-only figure manufactures a false failure — skip, and say why."""
    if bs_land_yen is None:
        return "no_bs_land", None
    if not consolidated:
        return "parent_only_bs", None
    if any(not t["book_mult"] for t in tables):
        return "no_unit", None
    tot, _ = land_totals(tables)
    if tot == 0:
        return "no_land_rows", None
    if tot <= bs_land_yen * 1.02:
        return "clean", "facilities %.1fbn ≤ BS %.1fbn (%.0f%%)" % (
            tot / 1e9, bs_land_yen / 1e9, 100 * tot / bs_land_yen)
    return "exceeds", "facilities %.1fbn > BS %.1fbn" % (tot / 1e9, bs_land_yen / 1e9)


# ------------------------------------------------------------------ per-file

def read_package(doc_id):
    t1 = glob.glob(os.path.join(ARCHIVE, "*", doc_id + "_t1.zip"))
    t5 = glob.glob(os.path.join(ARCHIVE, "*", doc_id + "_t5.zip"))
    if not t1 or not t5:
        raise IOError("not in local archive: " + doc_id)
    blocks = []
    z1 = zipfile.ZipFile(t1[0])
    for n in z1.namelist():
        if "PublicDoc" not in n or not n.endswith(".htm"):
            continue
        h = z1.read(n).decode("utf-8", "replace")
        if FACILITIES_MARK not in h:
            continue
        blocks.extend(re.findall(
            r'<ix:nonNumeric[^>]*name="[^"]*%s"[^>]*>(.*?)</ix:nonNumeric>' % FACILITIES_MARK,
            h, re.S))
    bs_land = {}
    z5 = zipfile.ZipFile(t5[0])
    for n in z5.namelist():
        if not n.endswith(".csv"):
            continue
        text = z5.read(n).decode("utf-16", errors="replace")
        for row in csv.reader(io.StringIO(text), delimiter="\t"):
            if len(row) < 9:
                continue
            element, context, value = row[0], row[2], row[-1]
            # Real-estate filers hold land in trust, tagged under a filer
            # extension (…:LandInTrustPPE) next to jppfs_cor:Land — the
            # facilities table lists both, so the gate must sum both.
            if context in ("CurrentYearInstant", "CurrentYearInstant_NonConsolidatedMember") \
                    and (element == "jppfs_cor:Land" or "LandInTrust" in element):
                v = to_num(value)
                if v is not None:
                    bs_land[context] = bs_land.get(context, 0.0) + v
    land = bs_land.get("CurrentYearInstant", bs_land.get("CurrentYearInstant_NonConsolidatedMember"))
    return list(dict.fromkeys(blocks)), land, ("CurrentYearInstant" in bs_land)


def run_one(doc_id, name, period_end):
    blocks, bs_land_yen, land_consolidated = read_package(doc_id)
    out = {"doc_id": doc_id, "name": name, "period_end": period_end,
           "n_blocks": len(blocks), "tables": []}
    if not blocks:
        out["status"] = "no_text_block"
        return out
    text = strip_tags(" ".join(blocks))
    tables = []
    for b in blocks:
        tables.extend(parse_block(b))
    out["tables"] = tables
    if not tables:
        out["status"] = ("not_applicable" if NOT_APPLICABLE_RE.search(text) and len(text) < 200
                         else "no_table_parsed")
        return out
    rows = [r for t in tables for r in t["rows"]]
    ok, bad, unv, examples = gate_rows(tables)
    bs_status, bs_detail = gate_bs_land(tables, bs_land_yen, land_consolidated)
    with_loc = [r for r in rows if r.get("location")]
    book_yen, area_m2 = land_totals(tables)
    out.update({
        "status": "parsed",
        "n_tables": len(tables),
        "n_summary_tables": sum(1 for t in tables if t["is_summary"]),
        "n_rows": len(rows),
        "n_rows_with_location": len(with_loc),
        "n_rows_pref_matched": sum(1 for r in with_loc if PREF_RE.search(r["location"])),
        "n_land_rows": sum(1 for r in rows if r.get("land") not in (None, 0)),
        "n_area_rows": sum(1 for r in rows if r.get("land_area")),
        "row_gate": {"ok": ok, "bad": bad, "unverified": unv, "examples": examples},
        "bs_land_gate": {"status": bs_status, "detail": bs_detail,
                         "bs_land_yen": bs_land_yen,
                         "consolidated": land_consolidated},
        "total_land_book_yen": book_yen,
        "total_land_area_m2": area_m2,
    })
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    results = []
    for doc_id, name, period_end in SAMPLE:
        try:
            results.append(run_one(doc_id, name, period_end))
        except Exception as e:  # an M1 must show every failure, not die on one
            results.append({"doc_id": doc_id, "name": name, "status": "error",
                            "error": "%s: %s" % (type(e).__name__, e)})
    with io.open(os.path.join(OUT, "facilities.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    print("%-14s %-6s %2s %4s %4s %5s %4s  %-14s %-12s %s" % (
        "filer", "status", "tb", "rows", "loc", "land", "area", "row-gate", "bs-gate", "land detail"))
    for r in results:
        if r["status"] != "parsed":
            print("%-14s %-6s %s" % (r["name"][:13], r["status"], r.get("error", "")))
            continue
        g, b = r["row_gate"], r["bs_land_gate"]
        print("%-14s %-6s %2d %4d %4d %5d %4d  ok%d/bad%d/un%d   %-12s %s | %.1fk m2" % (
            r["name"][:13], "ok", r["n_tables"], r["n_rows"], r["n_rows_pref_matched"],
            r["n_land_rows"], r["n_area_rows"], g["ok"], g["bad"], g["unverified"],
            b["status"], b["detail"] or "", r["total_land_area_m2"] / 1e3))
        for ex in g["examples"]:
            print("     row-gate fail: %s" % ex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
