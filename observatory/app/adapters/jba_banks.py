"""Adapter: every bank's financial statements — JBA 全国銀行財務諸表分析.

Source: 一般社団法人全国銀行協会 (Japanese Bankers Association), 全国銀行財務諸表
分析 — the association's half-yearly compilation of the balance sheet and
income statement of every member bank, on both the non-consolidated (単体)
and consolidated (連結) basis, plus the same statements aggregated by type of
bank (all banks, city banks, the regional banks of each association, trust
banks, other). Fiscal-year editions carry about 215 lines a bank; the
interim editions carry an abridged balance sheet and the first-half income
statement, about 105 lines.

This is the one public source that covers the **unlisted** banks — the
regional and second-tier regional banks that do not file a securities report
of their own — on the same chart of accounts as the megabanks, every half
year since fiscal 2006. Each bank is keyed by its 金融機関コード, which
survives renamings (0117 is 青森銀行 in 2006 and 青森みちのく銀行 in 2025) and
lets a merged bank's history be read as one series. History runs from
March 2002; the fiscal-1996 to 2000 editions are archived but are Excel
5/95 files the platform's reader does not open.

**Every edition is one point in time, so every edition is read.** An edition
carries the current period and a comparison column, nothing older. The
adapter downloads the aggregate workbook and the per-bank workbook of every
edition the association lists (fiscal 2006 onward, terminal and interim) and
stitches them. Editions before fiscal 2024 are legacy .xls; both formats are
read with the platform's own readers, so no history is dropped.

**Lines are keyed by the association's own reference codes**, which have
been stable since the fiscal-2014 edition (A015 is deposits, E800 ordinary
profit, F850 net income); the Reference Code sheet of the newest edition
supplies the English name of every code. Editions before fiscal 2014 used a
different numbering (Ａ010 was deposits) and their consolidated sheets carry
no codes at all, so those editions are matched by the *name* of the line
within its section of the statement. A line whose name has no modern
counterpart is dropped and counted; the ingest stops if an edition loses more
than a small share of its lines that way.

**Amounts are 百万円 exactly as published.** Nothing is rescaled and nothing
is derived: the share and change columns the association prints beside each
figure are not stored.

**Flows are split by length.** The income statement is the full fiscal year
in a terminal edition and the first half in an interim one, so every
income-statement line is two series: `.fy` on March points and `.h1` on
September points. Balance-sheet lines are point-in-time and stay one series.
A period is dated to the first day of its closing month: fiscal 2025's
terminal statements are 2026-03-01, its interim ones 2025-09-01.

**Trust-account (信託財産) sheets are not ingested.** They are the assets a
trust bank administers for others, not its own balance sheet, and the
association prints them as a reference table without codes.
"""
import base64
import datetime
import io
import json
import re
import zipfile

from . import boj_ts, xls, xlsx


class ValidationError(Exception):
    pass


INDEX_URL = "https://www.zenginkyo.or.jp/stats/year2-02/"
_EDITION_RE = re.compile(r'href="(/stats/year2-02/account(\d{4})[-_](terminal|interim)/)"')
_FILE_RE = re.compile(r'href="(/fileadmin/[^"]*/(sogo|kobetsu)[^"/]*\.(?:xlsx?|zip))"')

# Column headers of the aggregate workbook: a letter, the group, its count.
GROUPS = {
    "全国銀行": ("all", "All banks", "全国銀行"),
    "都市銀行": ("city", "City banks", "都市銀行"),
    "地方銀行": ("regional", "Regional banks", "地方銀行"),
    "地方銀行Ⅱ": ("regional-2", "Second-association regional banks", "地方銀行Ⅱ"),
    "信託銀行": ("trust", "Trust banks", "信託銀行"),
    "その他": ("other", "Other banks", "その他"),
}
_GROUP_HEADER = re.compile(
    r"^[Ａ-ＦA-F][\s　]*(全国銀行|都市銀行|地方銀行Ⅱ|地方銀行|信託銀行|その他)[\s　]*[（(]\s*(\d+)\s*[）)]")
_BANK_HEADER = re.compile(r"^(\d{4})[\s　]+(\S.*)$")
_CODE = re.compile(r"^[A-Za-z]\d{3}$")
_NUMERIC = re.compile(r"^[-－△▲\d,.\s　]+$")
_SECTION = {"負債の部": "liabilities", "純資産の部": "net-assets", "資産の部": "assets",
            "資本の部": "net-assets", "少数株主持分": "net-assets"}
_FULLWIDTH = dict(zip(
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌ０１２３４５６７８９",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl0123456789"))
_CIRCLED = re.compile(r"[①-⑳⑴-⒇]")
_THREE_MONTHS = re.compile(r"(３|3|三)[カヵヶかケ]?月")

DATASET = {
    "slug": "jba-banks",
    "title": "Bank Financial Statements — Every Member Bank (Japan)",
    "country": "Japan",
    "agency": "Japanese Bankers Association",
    "agency_ja": "全国銀行協会",
    "base": None,
    "frequency": "semiannual",
    "description": (
        "The balance sheet and income statement of every member bank of the "
        "Japanese Bankers Association — city, regional, second-tier regional, "
        "trust and other banks, listed and unlisted — on the non-consolidated "
        "and consolidated basis, every half-year from March 2002, with the "
        "same statements aggregated by type of bank. About 215 lines a bank "
        "in a fiscal-year edition, in millions of yen as published, keyed by "
        "the association's reference codes and each bank's 金融機関コード."
    ),
}

SOURCE = {
    "source_id": "jba:financial-statements",
    "name": "JBA — Analysis of Financial Statements of All Banks (全国銀行財務諸表分析)",
    "name_ja": "全国銀行協会 全国銀行財務諸表分析",
    "url": INDEX_URL,
    "license_note": (
        "Published by the Japanese Bankers Association for public reference; "
        "the association accepts no liability for errors and figures reflect "
        "reports received by its compilation date. Credit the association."
    ),
}

DOWNLOAD_URL = INDEX_URL + " (sogo + kobetsu of every edition)"
RAW_SUFFIX = ".json"


class _Kinds(dict):
    """Stock or flow, read off the series code — the universe is data-driven."""

    def get(self, code, default=None):
        if not isinstance(code, str):
            return default
        return "flow" if code.endswith((".fy", ".h1")) else "stock"

    def __len__(self):
        return 1


PRESENTATION = {
    "credit_line": ("Source: Japanese Bankers Association — Analysis of Financial "
                    "Statements of All Banks (全国銀行財務諸表分析)."),
    # A fiscal year's statements land in August (fiscal 2025 on 2026-08-13)
    # and the interim ones in February, so the newest period is about eleven
    # months old the day before the next edition. Allows two more.
    "stale_after_days": 400,
    "main_series": [
        {"role": "headline", "code": "s.all.a015", "label": "Deposits, all banks", "slot": 1},
        {"role": "loans", "code": "s.all.d395", "label": "Loans, all banks", "slot": 2},
    ],
    "overview_tiles": [
        {"key": "deposits", "type": "level", "code": "s.all.a015", "label": "Deposits"},
        {"key": "loans", "type": "level", "code": "s.all.d395", "label": "Loans"},
        {"key": "ordinary", "type": "level", "code": "s.all.e800.fy", "label": "Ordinary Profit"},
        {"key": "net", "type": "level", "code": "s.all.f850.fy", "label": "Net Income"},
    ],
    "kinds": _Kinds(),
    # /series is a search here (?q=), never a dump: ~40,000 series.
    "series_requires_query": True,
}


# --- fetching ---------------------------------------------------------------

def _html(url):
    return boj_ts.fetch_bytes(url).decode("utf-8", "replace")


def discover():
    """{"2025-terminal": {"sogo": url, "kobetsu": url}, ...} from the index."""
    pages = {}
    for path, year, kind in _EDITION_RE.findall(_html(INDEX_URL)):
        pages.setdefault("%s-%s" % (year, kind), "https://www.zenginkyo.or.jp" + path)
    if len(pages) < 30:
        raise ValidationError(
            "the JBA index lists only %d editions; expected at least 30" % len(pages))
    out = {}
    for key, page in sorted(pages.items()):
        files = {}
        for path, which in _FILE_RE.findall(_html(page)):
            files.setdefault(which, "https://www.zenginkyo.or.jp" + path)
        # The fiscal-1996 edition is the aggregate workbook alone; per-bank
        # workbooks begin with fiscal 1997. Either file is worth having.
        if "sogo" not in files and "kobetsu" not in files:
            raise ValidationError("edition %s lacks both a sogo and a kobetsu file" % key)
        out[key] = files
    return out


def fetch():
    """Both workbooks of every edition, verbatim, in one deterministic envelope."""
    editions = discover()
    envelope = {}
    for key, files in sorted(editions.items()):
        envelope[key] = {}
        for which, url in sorted(files.items()):
            envelope[key][which] = {
                "url": url,
                "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii"),
            }
    return json.dumps({"editions": envelope}, sort_keys=True).encode("utf-8")


# --- workbook reading -------------------------------------------------------

def _workbook(raw):
    """Bytes of a .xlsx, .xls or a .zip holding one of them -> sheets."""
    if raw[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            z = None
        if z is not None and not any(n.startswith("xl/") for n in z.namelist()):
            inner = [n for n in z.namelist() if n.lower().endswith((".xls", ".xlsx"))]
            if len(inner) != 1:
                raise ValidationError("archive holds %d workbooks, expected one" % len(inner))
            raw = z.read(inner[0])
    return (xlsx if raw[:2] == b"PK" else xls).sheets(raw)


def _colnum(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _colname(n):
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _text(cells, col):
    cell = cells.get(col)
    return (cell[0] if cell else "") or ""


def _ascii(text):
    return "".join(_FULLWIDTH.get(c, c) for c in text)


def _norm(text):
    return re.sub(r"[\s　]+", "", text or "")


def _code_of(text):
    text = _ascii(_norm(text))
    return text if _CODE.match(text) else None


def _line_key(name):
    """A line's name reduced to what is stable across editions.

    Whitespace, the circled numerals some editions prefix, the 中間 (interim)
    wording of the half-year income statement and the spelling of "three
    months" all vary; none changes what the line is.
    """
    key = _CIRCLED.sub("", _ascii(_norm(name)))
    key = key.replace("中間", "当期")
    key = _THREE_MONTHS.sub("三月", key)
    return key


def _value(text):
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "－", "…", "***", "△", "▲", "x", "X"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_sheet(grid):
    """One statement sheet -> [(entity id, entity label, section, code, name, value)].

    Nothing is addressed by row or column number. A header is any row with
    cells that read like a bank (a four-digit code and a name) or a group
    (a letter, a group name and a count); a line is any later row with a
    reference code or a name in the columns before the first entity; the
    value of a line for an entity is the cell one column to the right of
    the entity's header cell. Section markers (負債の部, 損益計算書 ...) are
    tracked so a name can be resolved within its part of the statement.
    """
    out = []
    entities = None
    first_entity_col = None
    section = None
    consolidated = False
    for row in sorted(grid):
        cells = grid[row]
        english = "".join(_text(cells, c) for c in cells).upper()
        # Editions before fiscal 2018 print the aggregate statements on one
        # sheet, non-consolidated first, consolidated after an English title.
        if "NON-CONSOLIDATED" in english or "NONCONSOLIDATED" in english:
            consolidated = False
            section = None
            continue
        if "CONSOLIDATED" in english:
            consolidated = True
            section = None
            continue
        if "FINANCIAL STATEMENTS" in english:
            consolidated = False
            section = None
            continue
        found = {}
        for col in sorted(cells, key=_colnum):
            text = _norm(_text(cells, col))
            m = _BANK_HEADER.match(_ascii(_text(cells, col)).strip())
            if m and m.group(1).isdigit():
                found[col] = (m.group(1), _norm(m.group(2)))
                continue
            m = _GROUP_HEADER.match(_text(cells, col).strip())
            if m:
                found[col] = (GROUPS[m.group(1)][0], m.group(1))
        if found:
            entities = found
            first_entity_col = min(_colnum(c) for c in found)
            continue
        joined = _norm("".join(_text(cells, c) for c in cells))
        if "損益計算書" in joined:
            section = "pl"
            continue
        if "貸借対照表" in joined:
            section = None
            continue
        for marker, name in _SECTION.items():
            if ("（%s）" % marker) in joined or ("(%s)" % marker) in joined:
                section = name
                break
        if entities is None:
            continue
        code, names = None, []
        for col in sorted(cells, key=_colnum):
            n = _colnum(col)
            if n < 2 or n >= first_entity_col:
                continue
            text = _text(cells, col).strip()
            if not text:
                continue
            if code is None and _code_of(text):
                code = _code_of(text)
                continue
            if _NUMERIC.match(text):
                continue
            names.append(text)
        name = "".join(names)
        if not name or name.startswith(("（", "(", "【", "〔")):
            continue
        for col, (entity, label) in entities.items():
            value = _value(_text(cells, _colname(_colnum(col) + 1)))
            if value is not None:
                out.append((entity, label, section, code, name, value, consolidated))
    return out


def _edition_period(key, title):
    """"2025-terminal" -> 2026-03-01; "2025-interim" -> 2025-09-01.

    The title cell of the workbook (2025年度・決算期 or 平成18年度・中間期) is
    checked against the key so a page that links the wrong file is caught.
    """
    year, kind = key.split("-")
    year = int(year)
    text = _ascii(_norm(title))
    m = re.search(r"(平成|令和)?(\d+)年度", text)
    if m:
        got = int(m.group(2))
        if m.group(1) == "平成":
            got += 1988
        elif m.group(1) == "令和":
            got += 2018
        if got != year:
            raise ValidationError("edition %s: workbook title says %r" % (key, title))
    if kind == "terminal":
        if "中間" in text:
            raise ValidationError("edition %s: workbook title says interim (%r)" % (key, title))
        return datetime.date(year + 1, 3, 1)
    if "中間" not in text:
        raise ValidationError("edition %s: workbook title does not say interim (%r)" % (key, title))
    return datetime.date(year, 9, 1)


def _statement_sheets(book):
    """(basis, grid) for every bank or group statement sheet, in book order."""
    for name, grid in book.items():
        if "Code" in name or "信託財産" in name:
            continue
        if "連結" in name:
            yield "c", grid
        elif "単体" in name or "総合財務諸表" in name:
            yield "s", grid
        else:
            yield "s", grid


def _english_lines(book):
    """{code: English name} from the Reference Code sheet."""
    out = {}
    for name, grid in book.items():
        if "Reference" not in name:
            continue
        for row in sorted(grid):
            cells = grid[row]
            for col in sorted(cells, key=_colnum):
                code = _code_of(_text(cells, col))
                if code:
                    nxt = _text(cells, _colname(_colnum(col) + 1)).strip()
                    if nxt:
                        out[code] = re.sub(r"\s+", " ", nxt)
    return out


def _english_banks(book):
    """{金融機関コード: English name} from the Financial Institution Code sheet."""
    out = {}
    for name, grid in book.items():
        if "Institution" not in name:
            continue
        for row in sorted(grid):
            cells = grid[row]
            for col in sorted(cells, key=_colnum):
                text = _text(cells, col).strip()
                if not re.match(r"^\d{4}$", text):
                    continue
                for step in (1, 2, 3):
                    nxt = _text(cells, _colname(_colnum(col) + step)).strip()
                    if nxt and not re.match(r"^\d{4}$", nxt):
                        out[text] = re.sub(r"\s+", " ", nxt)
                        break
    return out


# --- parsing ----------------------------------------------------------------

def _reference(book, key):
    """The modern chart of accounts, from the newest terminal edition.

    {basis: {code: {"ja", "section", "flow", "order"}}} plus the reverse map
    {basis: {(section, line key): code}} used to place older editions.
    """
    lines = {"s": {}, "c": {}}
    by_name = {"s": {}, "c": {}}
    for sheet_basis, grid in _statement_sheets(book):
        for entity, _label, section, code, name, _value, consolidated in _read_sheet(grid):
            basis = "c" if consolidated else sheet_basis
            if code is None or code in lines[basis]:
                continue
            lines[basis][code] = {"ja": name, "section": section,
                                  "flow": section == "pl", "order": len(lines[basis])}
            by_name[basis].setdefault((section, _line_key(name)), []).append(code)
    for basis in lines:
        if not lines[basis]:
            raise ValidationError("edition %s: no %s statement lines found" % (key, basis))
    return lines, by_name


def _is_modern(book):
    """Editions from fiscal 2014 code deposits A015; earlier ones Ａ010."""
    for _basis, grid in _statement_sheets(book):
        for _e, _l, _s, code, name, _v, _c in _read_sheet(grid):
            if _line_key(name) == "預金":
                return code == "A015"
    return False


def _resolve(basis, section, code, name, modern, lines, by_name, nth):
    """A line as printed -> its modern code, or None.

    `nth` is how many times this name has already appeared in this section
    for this entity: the chart of accounts prints 投資損失引当金 twice in the
    assets section (D380 under securities, D980 as the closing deduction), in
    the same order in every edition, so the nth printing is the nth code.
    """
    key = _line_key(name)
    if modern and code is not None and code in lines[basis]:
        # A code is trusted only while it still names the same line: the
        # consolidated memorandum block was renumbered between editions
        # (g900 was 正常債権 in fiscal 2021 and is another line today).
        modern_key = _line_key(lines[basis][code]["ja"])
        if modern_key in (key, key.rstrip("額")):
            return code
    for candidate in (key, key.rstrip("額")):
        hits = by_name[basis].get((section, candidate))
        if hits and nth < len(hits):
            return hits[nth]
    if section is not None:
        return None
    # Only a sheet with no section markers at all falls back to a name that
    # is unique across the whole statement.
    for candidate in (key, key.rstrip("額")):
        hits = [c for (s, k), codes in by_name[basis].items() for c in codes
                if k == candidate]
        if len(hits) == 1:
            return hits[0]
    return None


def parse(raw):
    editions = json.loads(raw.decode("utf-8"))["editions"]
    keys = sorted((k for k in editions if int(k[:4]) >= FIRST_FISCAL_YEAR),
                  key=lambda k: (int(k[:4]), k.endswith("terminal")))
    books = {}
    unreadable = []
    for key in keys:
        entry = editions[key]
        books[key] = {}
        for which in ("kobetsu", "sogo"):
            if which not in entry:
                continue
            try:
                books[key][which] = _workbook(base64.b64decode(entry[which]["b64"]))
            except xls.FormatError:
                # Editions up to about fiscal 2000 are Excel 5/95 (BIFF5)
                # workbooks, which the platform's reader does not open. They
                # are archived with everything else and counted here, so the
                # day a BIFF5 reader exists the history simply appears.
                unreadable.append(key + "/" + which)
    newest = [k for k in keys if k.endswith("terminal") and "kobetsu" in books[k]][-1]
    lines, by_name = _reference(books[newest]["kobetsu"], newest)
    # The aggregate workbook uses the same codes; register any it alone carries.
    for sheet_basis, grid in _statement_sheets(books[newest]["sogo"]):
        for _e, _l, section, code, name, _v, consolidated in _read_sheet(grid):
            basis = "c" if consolidated else sheet_basis
            if code and code not in lines[basis]:
                lines[basis][code] = {"ja": name, "section": section,
                                      "flow": section == "pl", "order": len(lines[basis])}
                by_name[basis].setdefault((section, _line_key(name)), []).append(code)
    english = _english_lines(books[newest]["kobetsu"])

    bank_en, bank_ja, bank_order = {}, {}, {}
    values = {}       # code -> {period: value}
    dropped = {}      # edition -> (unmatched lines, total lines)
    for key in keys:
        for which in ("kobetsu", "sogo"):
            if which not in books[key]:
                continue
            book = books[key][which]
            first = list(book.values())[0]
            title = _text(first.get(1, {}), "B") or _text(first.get(1, {}), "A")
            period = _edition_period(key, title)
            bank_en.update(_english_banks(book))
            modern = _is_modern(book)
            miss = total = 0
            for sheet_basis, grid in _statement_sheets(book):
                printed = {}
                for entity, label, section, code, name, value, consolidated in _read_sheet(grid):
                    basis = "c" if consolidated else sheet_basis
                    total += 1
                    slot = (basis, entity, section, _line_key(name))
                    nth = printed.get(slot, 0)
                    printed[slot] = nth + 1
                    line = _resolve(basis, section, code, name, modern, lines, by_name, nth)
                    if line is None:
                        miss += 1
                        continue
                    if entity not in GROUPS_BY_SLUG:
                        bank_ja[entity] = label          # newest edition wins
                        bank_order.setdefault(entity, len(bank_order))
                    series_code = "%s.%s.%s" % (basis, entity, line.lower())
                    if lines[basis][line]["flow"]:
                        series_code += ".fy" if period.month == 3 else ".h1"
                    previous = values.setdefault(series_code, {}).get(period)
                    if previous is not None and previous != value:
                        raise ValidationError(
                            "edition %s: %s at %s is printed twice with different "
                            "values (%s, %s) — %s" % (key, series_code, period, previous,
                                                      value, name))
                    values[series_code][period] = value
            dropped[key + "/" + which] = (miss, total)
            if total == 0:
                raise ValidationError("edition %s: %s workbook yielded no lines" % (key, which))
            allowed = MAX_DROPPED_SHARE if int(key[:4]) >= 2006 else MAX_DROPPED_SHARE_OLD
            if miss > total * allowed:
                raise ValidationError(
                    "edition %s: %d of %d %s lines have no modern counterpart — the "
                    "chart of accounts has drifted further than name matching can "
                    "follow" % (key, miss, total, which))

    # Bank order: as the newest edition prints them (city, regional, second
    # association, trust, other), banks that have since disappeared after.
    newest_order = {}
    for _basis, grid in _statement_sheets(books[newest]["kobetsu"]):
        for entity, _l, _s, _c, _n, _v, _cons in _read_sheet(grid):
            newest_order.setdefault(entity, len(newest_order))
    group_order = dict((slug, i) for i, slug in enumerate(g[0] for g in GROUPS.values()))

    series = []
    for series_code in values:
        basis, entity, line = series_code.split(".")[:3]
        suffix = series_code.split(".")[3] if series_code.count(".") == 3 else None
        code = _upper_if_needed(basis, line, lines)
        info = lines[basis][code]
        line_en = english.get(code) or info["ja"]
        if entity in GROUPS_BY_SLUG:
            ent_en, ent_ja = GROUPS_BY_SLUG[entity][1], GROUPS_BY_SLUG[entity][2]
            ent_en += " (aggregate)"
            order = 10_000_000 + group_order[entity] * 10_000
        else:
            ent_en = bank_en.get(entity) or bank_ja.get(entity, entity)
            ent_ja = bank_ja.get(entity, entity)
            order = (newest_order.get(entity, 1_000 + bank_order.get(entity, 0))) * 10_000
        if basis == "c":
            ent_en += " (consolidated)"
            ent_ja += "（連結）"
            order += 5_000
        name_en = "%s — %s" % (ent_en, line_en)
        name_ja = "%s %s" % (ent_ja, info["ja"])
        if suffix == "fy":
            name_en += " (fiscal year)"
            name_ja += "（通期）"
        elif suffix == "h1":
            name_en += " (first half)"
            name_ja += "（中間期）"
        series.append({
            "code": series_code, "name_en": name_en, "name_ja": name_ja,
            "unit": "jpy_million", "weight_per_10000": None,
            "sort_order": order + info["order"] * 2 + (1 if suffix == "h1" else 0),
        })
    series.sort(key=lambda s: (s["sort_order"], s["code"]))
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    parse.dropped = dropped      # for the validation summary
    parse.unreadable = unreadable
    return series, observations


def _upper_if_needed(basis, line, lines):
    """Series codes are lower case; the association's are mixed."""
    if line in lines[basis]:
        return line
    if line.upper() in lines[basis]:
        return line.upper()
    raise ValidationError("series line %s.%s is not in the chart of accounts" % (basis, line))


GROUPS_BY_SLUG = dict((v[0], v) for v in GROUPS.values())
MAX_DROPPED_SHARE = 0.15
# Before the 2006 company-law change the balance sheet had a 資本の部, not a
# 純資産の部, and a fifth of its lines have no name in today's chart. Those
# editions are read for the lines that do carry over.
MAX_DROPPED_SHARE_OLD = 0.25
# The fiscal-2001 edition is the first the platform's readers open in full;
# earlier ones are Excel 5/95 files, and the one readable 1998 workbook lays
# its columns out differently and misreads. History starts at March 2002.
FIRST_FISCAL_YEAR = 2001


# --- validation -------------------------------------------------------------

MIN_BANKS = 95
MIN_EDITIONS = 30
# Every edition from fiscal 2003 opens; before that some are Excel 5/95 files
# the reader cannot read, so the run may have holes there and nowhere else.
FIRST_CONTINUOUS = datetime.date(2003, 3, 1)
# All-bank deposits: ¥550tn in 2006, ¥1,085tn in 2026, in 百万円.
DEPOSITS_FLOOR, DEPOSITS_CEILING = 4e8, 3e9


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("s.all.a015", "s.all.d395", "s.all.e800.fy", "s.all.f850.fy",
                     "s.0001.a015", "s.0005.a015", "s.0009.a015"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    deposits = by_code["s.all.a015"]
    periods = sorted(deposits)
    if len(periods) < MIN_EDITIONS:
        raise ValidationError(
            "all-bank deposits cover %d half-years; expected at least %d"
            % (len(periods), MIN_EDITIONS))
    for a, b in zip(periods, periods[1:]):
        if a >= FIRST_CONTINUOUS and (b.year - a.year) * 12 + b.month - a.month != 6:
            raise ValidationError("no edition between %s and %s" % (a, b))
    for period, value in deposits.items():
        if not (DEPOSITS_FLOOR <= value <= DEPOSITS_CEILING):
            raise ValidationError(
                "%s: all-bank deposits of %s 百万円 are outside the plausible range"
                % (period, value))

    latest = periods[-1]
    banks = set(c.split(".")[1] for c in codes
                if c.startswith("s.") and c.endswith(".a015")
                and c.split(".")[1] not in GROUPS_BY_SLUG
                and latest in by_code[c])
    if len(banks) < MIN_BANKS:
        raise ValidationError(
            "only %d banks carry deposits at %s; expected at least %d"
            % (len(banks), latest, MIN_BANKS))

    # The five group aggregates must add up to the all-bank aggregate, and
    # the per-bank workbook must carry at least every bank in it: the
    # 信託・その他 sheet also prints a few institutions outside the association's
    # all-bank total (農林中央金庫 among them), so the banks may sum to a little
    # more than the aggregate, never less.
    parts = [by_code.get("s.%s.a015" % g, {}).get(latest)
             for g in ("city", "regional", "regional-2", "trust", "other")]
    if all(p is not None for p in parts):
        if abs(sum(parts) - deposits[latest]) > deposits[latest] * 0.001:
            raise ValidationError(
                "%s: the five group aggregates' deposits sum to %s but the all-bank "
                "aggregate is %s" % (latest, sum(parts), deposits[latest]))
    total = sum(by_code["s.%s.a015" % b][latest] for b in banks)
    if not (deposits[latest] <= total <= deposits[latest] * 1.10):
        raise ValidationError(
            "%s: the %d banks' deposits sum to %s against an all-bank aggregate of %s"
            % (latest, len(banks), total, deposits[latest]))

    # Each bank's balance sheet must balance: total liabilities and net assets
    # (C500) equals total assets (D-section total) at the newest period.
    unbalanced = []
    for bank in banks:
        both = by_code.get("s.%s.c500" % bank, {}).get(latest)
        assets = by_code.get("s.%s.d990" % bank, {}).get(latest)
        if both is not None and assets is not None and both != assets:
            unbalanced.append(bank)
    if unbalanced:
        raise ValidationError(
            "%s: liabilities plus net assets do not equal assets for %s"
            % (latest, unbalanced[:5]))

    # Column alignment, every edition: a bank's deposits are part of its
    # total liabilities and can never exceed them. (Assets are no ceiling —
    # Ashikaga Bank carried negative net assets after its 2003 nationalisation,
    # so deposits genuinely exceeded assets.) A value read from the wrong
    # column — a share, a change — fails this at once.
    for code, vals in by_code.items():
        parts = code.split(".")
        if parts[0] != "s" or parts[2] != "a015" or len(parts) != 3:
            continue
        liabilities = by_code.get("s.%s.a980" % parts[1], {})
        for period, value in vals.items():
            total = liabilities.get(period)
            if total is not None and value > total:
                raise ValidationError(
                    "%s %s: deposits of %s exceed total liabilities of %s — a column "
                    "is misaligned" % (parts[1], period, value, total))

    dropped = getattr(parse, "dropped", {})
    return {
        "series": len(codes),
        "observations": len(observations),
        "editions": len(periods),
        "banks_at_latest": len(banks),
        "first_period": periods[0].isoformat(),
        "latest_period": latest.isoformat(),
        "latest_all_bank_deposits_jpy_million": deposits[latest],
        "latest_all_bank_net_income_fy_jpy_million":
            by_code["s.all.f850.fy"].get(max(by_code["s.all.f850.fy"])),
        "lines_without_modern_counterpart":
            sum(m for m, _t in dropped.values()),
        "lines_read": sum(t for _m, t in dropped.values()),
        "unreadable_workbooks": sorted(getattr(parse, "unreadable", [])),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "banking",
    "name": {"en": "Bank financial statements — every member bank",
             "ja": "全国銀行財務諸表分析（各行別・業態別）"},
    "shape": "series",
    "summary": DATASET["description"],
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"],
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": "semiannual",
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "2002-03",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published amount, millions of yen",
         "unit": "JPY_million", "trust": "official"},
        {"id": "yoy", "label": "Change on the same half-year a year earlier", "unit": "%",
         "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/banks.html",
    "page": "/banks.html",
    "notes": [
        "Series codes are {basis}.{bank}.{line}: basis s (non-consolidated) or c "
        "(consolidated); bank is the 金融機関コード (0001 Mizuho, 0005 MUFG Bank, "
        "0009 SMBC) or a group — all, city, regional, regional-2, trust, other — "
        "for the association's aggregates; line is the association's reference "
        "code in lower case (a015 deposits, d395 loans, e800 ordinary profit, "
        "f850 net income). The Reference Code sheet of any edition is the key.",
        "Income-statement lines are the full fiscal year on March points (.fy) "
        "and the first half on September points (.h1) — two series, never one. "
        "Balance-sheet lines are one series with both.",
        "A period is dated to the first day of its closing month: fiscal 2025's "
        "terminal statements are 2026-03-01, its interim statements 2025-09-01.",
        "Amounts are millions of yen exactly as published. The share and change "
        "columns the association prints are not stored; they are calculations.",
        "Editions before fiscal 2014 numbered the lines differently and their "
        "consolidated sheets carry no codes, so they are matched by line name "
        "within the section of the statement; a line with no modern counterpart "
        "is dropped and counted in the release's validation record. Before "
        "fiscal 2006 the balance sheet had a 資本の部 rather than a 純資産の部 "
        "and about a fifth of its lines do not carry over; the aggregate "
        "workbook for September 2002 is an Excel 5/95 file the platform cannot "
        "read, so the group aggregates have a gap there.",
        "Editions before fiscal 2001 are archived but not read: they are Excel "
        "5/95 workbooks.",
        "A bank keeps its code through renamings and absorbs the history of a "
        "bank it merged with only from the merger date; the association's "
        "利用上の注意 sheet in each edition names that period's mergers.",
        "The consolidated sheets cover only banks that prepare consolidated "
        "statements; a bank with no subsidiaries has non-consolidated series only.",
        "Trust-account (信託財産) tables are not ingested: they are assets "
        "administered for others, not the bank's own balance sheet.",
    ],
}
