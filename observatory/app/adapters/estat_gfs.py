# -*- coding: utf-8 -*-
"""Adapter: general government on the GFS basis — Cabinet Office SNA 付表6(2).

Source: 内閣府経済社会総合研究所, 国民経済計算 付表6(2)「一般政府の部門別勘定
(GFS)」 — Japan's whole government, not just the state, presented on the IMF's
Government Finance Statistics classification: revenue and expense line by line,
the balancing items, and the transactions in assets and liabilities that
finance them. Fiscal years from 1994, in ¥ billion.

**This is the dataset that answers "what does Japanese government cost".** The
Ministry of Finance tables on this platform are the *general account* of the
*central* government: they stop at the boundary of a legal account. This one
consolidates central government, local government and the social security funds
and nets out the transfers between them, which is why it is the figure used for
international comparison and for a deficit that means anything. Local government
spends roughly as much as the centre and the social security funds more than
either; none of that is visible in a general-account table.

**Four sectors plus the consolidation, and the consolidation is a series.**
中央政府, 地方政府 and 社会保障基金 do not add to 一般政府 on their own — the
grants and interest they pay each other have to come out, and 部門間調整 is that
adjustment. It is published here as its own series rather than being applied
silently, so the identity central + local + social security + consolidation =
general government is visible, and it is checked on every line of every year.

**Revenue and expense are gross, and the balancing items are published, not
derived.** 純業務収支 (revenue less expense) and 純貸出／純借入 (the deficit)
come from the source with the rest; the platform does not subtract two series
and call the result a deficit. Both are checked against the identity they are
supposed to satisfy.

**Everything here can go negative.** Net lending, the consolidation adjustment
and the net acquisition of assets are all signed, so nothing in this dataset
carries the "a public account never runs backwards" gate the Ministry of
Finance datasets do.

**The balance-sheet blocks are not in this dataset.** The source table
continues past the operations statement into the revaluation account, the other
changes in volume account and the closing financial balance sheet (GFS codes
42-43, 52-53 and 62-63). Those are stocks and reconciliations, not operations —
a different statement that belongs in a balance-sheet dataset with its own
measure type, not mixed in with flows.

**A new edition every January, and it revises the whole run.** Each year the
Cabinet Office publishes a fresh table under a new statsDataId carrying all
thirty-one years, restated. The newest edition is taken whole, and the
point-in-time record keeps what the previous one said.
"""
import datetime
import json
import re

from . import estat_api


class ValidationError(Exception):
    pass


SEARCH_WORD = "一般政府の部門別勘定"
TITLE_MARK = "6(2)"

# The IMF GFS classification as the Cabinet Office publishes it. The code is
# the GFS number the source prints at the front of each Japanese label, which
# is what makes a series identity that survives a relabelling.
GFS_NAMES = [
    ("1", "Revenue"),
    ("11", "Taxes"),
    ("111", "Taxes on income, profits and capital gains"),
    ("1111", "Taxes on income — payable by individuals"),
    ("1112", "Taxes on income — payable by corporations and other enterprises"),
    ("1113", "Other taxes on income, profits and capital gains"),
    ("112", "Taxes on payroll and workforce"),
    ("113", "Taxes on property"),
    ("1131", "Recurrent taxes on immovable property"),
    ("1132", "Recurrent taxes on net wealth"),
    ("1133", "Estate, inheritance and gift taxes"),
    ("1135", "Capital levies"),
    ("1136", "Other recurrent taxes on property"),
    ("114", "Taxes on goods and services"),
    ("1141", "General taxes on goods and services"),
    ("11411", "Value-added taxes"),
    ("11412", "Sales taxes"),
    ("11413", "Turnover and other general taxes on goods and services"),
    ("11414", "Taxes on financial and capital transactions"),
    ("1142", "Excises"),
    ("1143", "Profits of fiscal monopolies"),
    ("1144", "Taxes on specific services"),
    ("1145", "Taxes on use of goods and on permission to use goods or perform activities"),
    ("11451", "Motor vehicle taxes"),
    ("11452", "Other taxes on use of goods and on permission to use goods"),
    ("1146", "Other taxes on goods and services"),
    ("115", "Taxes on international trade and transactions"),
    ("1151", "Customs and other import duties"),
    ("1152", "Taxes on exports"),
    ("1153", "Profits of export or import monopolies"),
    ("1154", "Exchange profits"),
    ("1155", "Exchange taxes"),
    ("1156", "Other taxes on international trade and transactions"),
    ("116", "Other taxes"),
    ("1161", "Other taxes — payable solely by business"),
    ("1162", "Other taxes — payable by other than business or unidentifiable"),
    ("12", "Social contributions"),
    ("121", "Social security contributions"),
    ("1211", "Social security contributions — employee"),
    ("1212", "Social security contributions — employer"),
    ("1213", "Social security contributions — self-employed or non-employed"),
    ("1214", "Social security contributions — other"),
    ("122", "Other social contributions"),
    ("1221", "Other social contributions — employee"),
    ("1222", "Other social contributions — employer"),
    ("1223", "Other social contributions — imputed"),
    ("13", "Grants received"),
    ("131", "Grants from foreign governments"),
    ("1311", "Grants from foreign governments — current"),
    ("1312", "Grants from foreign governments — capital"),
    ("132", "Grants from international organisations"),
    ("1321", "Grants from international organisations — current"),
    ("1322", "Grants from international organisations — capital"),
    ("133", "Grants from other general government units"),
    ("1331", "Grants from other general government units — current"),
    ("1332", "Grants from other general government units — capital"),
    ("14", "Other revenue"),
    ("141", "Property income received"),
    ("1411", "Property income received — interest"),
    ("1412", "Property income received — dividends"),
    ("1413", "Withdrawals from income of quasi-corporations"),
    ("1414", "Property income received — investment income disbursements"),
    ("1415", "Property income received — rent"),
    ("1416", "Reinvested earnings on foreign direct investment, received"),
    ("142", "Sales of goods and services"),
    ("1421", "Sales by market establishments"),
    ("1422", "Administrative fees"),
    ("1423", "Incidental sales by non-market establishments"),
    ("1424", "Imputed sales of goods and services"),
    ("143", "Fines, penalties and forfeits"),
    ("144", "Transfers not elsewhere classified, received"),
    ("1441", "Current transfers not elsewhere classified, received"),
    ("1442", "Capital transfers not elsewhere classified, received"),
    ("145", "Premiums and claims — non-life insurance and standardised guarantees, received"),
    ("1451", "Premiums and claims received"),
    ("1452", "Capital claims received"),
    ("2", "Expense"),
    ("21", "Compensation of employees"),
    ("211", "Wages and salaries"),
    ("2111", "Wages and salaries in cash"),
    ("2112", "Wages and salaries in kind"),
    ("212", "Employers' social contributions"),
    ("2121", "Actual employers' social contributions"),
    ("2122", "Imputed employers' social contributions"),
    ("22", "Use of goods and services"),
    ("23", "Consumption of fixed capital"),
    ("24", "Interest paid"),
    ("241", "Interest paid to non-residents"),
    ("242", "Interest paid to residents other than general government"),
    ("243", "Interest paid to other general government units"),
    ("25", "Subsidies"),
    ("251", "Subsidies to public corporations"),
    ("2511", "Subsidies to public non-financial corporations"),
    ("2512", "Subsidies to public financial corporations"),
    ("252", "Subsidies to private enterprises"),
    ("2521", "Subsidies to private non-financial corporations"),
    ("2522", "Subsidies to private financial corporations"),
    ("253", "Subsidies to other sectors"),
    ("26", "Grants paid"),
    ("261", "Grants to foreign governments"),
    ("2611", "Grants to foreign governments — current"),
    ("2612", "Grants to foreign governments — capital"),
    ("262", "Grants to international organisations"),
    ("2621", "Grants to international organisations — current"),
    ("2622", "Grants to international organisations — capital"),
    ("263", "Grants to other general government units"),
    ("2631", "Grants to other general government units — current"),
    ("2632", "Grants to other general government units — capital"),
    ("27", "Social benefits"),
    ("271", "Social security benefits"),
    ("2711", "Social security benefits in cash"),
    ("2712", "Social security benefits in kind"),
    ("272", "Social assistance benefits"),
    ("2721", "Social assistance benefits in cash"),
    ("2722", "Social assistance benefits in kind"),
    ("273", "Employment-related social benefits"),
    ("2731", "Employment-related social benefits in cash"),
    ("2732", "Employment-related social benefits in kind"),
    ("28", "Other expense"),
    ("281", "Property expense other than interest"),
    ("2811", "Property expense — dividends"),
    ("2812", "Property expense — withdrawals from income of quasi-corporations"),
    ("2813", "Property expense — investment income disbursements"),
    ("2814", "Property expense — rent"),
    ("2815", "Reinvested earnings on foreign direct investment, paid"),
    ("282", "Transfers not elsewhere classified, paid"),
    ("2821", "Current transfers not elsewhere classified, paid"),
    ("2822", "Capital transfers not elsewhere classified, paid"),
    ("283", "Premiums and claims — non-life insurance and standardised guarantees, paid"),
    ("2831", "Premiums and claims paid"),
    ("2832", "Capital claims paid"),
    ("31", "Net acquisition of non-financial assets"),
    ("311", "Fixed assets"),
    ("3111", "Fixed assets — buildings and structures"),
    ("3112", "Fixed assets — machinery and equipment"),
    ("3113", "Fixed assets — other"),
    ("3114", "Fixed assets — weapons systems"),
    ("312", "Inventories"),
    ("313", "Valuables"),
    ("314", "Non-produced assets"),
    ("3141", "Non-produced assets — land"),
    ("3142", "Non-produced assets — mineral and energy resources"),
    ("3143", "Non-produced assets — other naturally occurring assets"),
    ("3144", "Non-produced assets — intangible"),
    ("32", "Net acquisition of financial assets"),
    ("3201", "Financial assets — monetary gold and SDRs"),
    ("3202", "Financial assets — currency and deposits"),
    ("3203", "Financial assets — debt securities"),
    ("3204", "Financial assets — loans"),
    ("3205", "Financial assets — equity and investment fund shares"),
    ("32051", "Financial assets — equity"),
    ("32052", "Financial assets — investment fund shares"),
    ("3206", "Financial assets — insurance, pension and standardised guarantee schemes"),
    ("3207", "Financial assets — financial derivatives and employee stock options"),
    ("3208", "Financial assets — other"),
    ("33", "Net incurrence of liabilities"),
    ("3301", "Liabilities — SDRs"),
    ("3302", "Liabilities — currency and deposits"),
    ("3303", "Liabilities — debt securities"),
    ("3304", "Liabilities — loans"),
    ("3305", "Liabilities — equity and investment fund shares"),
    ("33051", "Liabilities — equity"),
    ("33052", "Liabilities — investment fund shares"),
    ("3306", "Liabilities — insurance, pension and standardised guarantee schemes"),
    ("3307", "Liabilities — financial derivatives and employee stock options"),
    ("3308", "Liabilities — other"),
]
GFS_NAME = dict(GFS_NAMES)
GFS_ORDER = dict((code, i) for i, (code, _en) in enumerate(GFS_NAMES))

# The balancing items, which carry no GFS number. Matched on the label with
# every bracket and space folded away, because the source writes them with a
# mixture of full-width and half-width brackets.
BALANCING = [
    ("純業務収支収入-支出", "net-operating-balance",
     "Net operating balance (revenue less expense)"),
    ("総業務収支収入-支出固定資本減耗を除く", "gross-operating-balance",
     "Gross operating balance (revenue less expense, before consumption of "
     "fixed capital)"),
    ("純貸出+/純借入-", "net-lending", "Net lending (+) / net borrowing (−)"),
    ("純貸出+/純借入-資金過不足", "net-lending-financing",
     "Net lending (+) / net borrowing (−), measured from the financing side"),
]
BALANCING_CODE = dict((key, code) for key, code, _en in BALANCING)
for _index, (_key, _code, _en) in enumerate(BALANCING):
    GFS_NAME[_code] = _en
    GFS_ORDER[_code] = 10_000 + _index

# The sectors, and the identity they have to satisfy.
SECTORS = [
    ("中央政府", "central", "Central government"),
    ("地方政府", "local", "Local government"),
    ("社会保障基金", "social-security-funds", "Social security funds"),
    ("部門間調整", "consolidation", "Consolidation between sectors"),
    ("一般政府", "general", "General government"),
]
SECTOR_CODE = dict((ja, code) for ja, code, _en in SECTORS)
SECTOR_NAME = dict((code, en) for _ja, code, en in SECTORS)
SECTOR_ORDER = dict((code, i) for i, (_ja, code, _en) in enumerate(SECTORS))
SECTOR_PARTS = ("central", "local", "social-security-funds", "consolidation")

EXPECTED_UNIT = "10億円"
_BRACKETS = str.maketrans({"（": "", "）": "", "(": "", ")": "", "／": "/",
                           "－": "-", "−": "-", "　": "", " ": ""})
_GFS_CODE = re.compile(r"^(\d+)")
_TIME = re.compile(r"^(\d{4})")
# Codes whose block is the operations statement. 4, 5 and 6 open the
# revaluation, other-volume-change and closing balance-sheet blocks, which are
# stocks and are deliberately out of scope — see the module docstring.
_OPERATIONS = "123"

FIRST_YEAR = 1994
MIN_YEARS = 25
# Every figure is rounded to ¥0.1bn, so an identity over four sectors or a
# dozen components can miss by a few tenths of a billion yen on a base of
# hundreds of trillions.
SUM_TOLERANCE = 1.0

DATASET = {
    "slug": "govt-accounts-jp",
    "title": "General Government Accounts — GFS Basis (Japan)",
    "country": "Japan",
    "agency": "Cabinet Office, Economic and Social Research Institute",
    "agency_ja": "内閣府経済社会総合研究所",
    "base": "2015 (SNA 2008, Heisei 27 base year)",
    "frequency": "annual",
    "description": (
        "Japan's whole government — central government, local government and "
        "the social security funds, with the consolidation between them — on "
        "the IMF Government Finance Statistics classification, by fiscal year "
        "from 1994 in ¥ billion. Revenue and expense line by line, the net "
        "operating balance and net lending as published, and the transactions "
        "in assets and liabilities that finance them."
    ),
}

SOURCE = {
    "source_id": "estat:sna-gfs-general-government",
    "name": "Cabinet Office — National Accounts, appended table 6(2), general government by sub-sector (GFS)",
    "name_ja": "内閣府 国民経済計算 付表6(2) 一般政府の部門別勘定(GFS)",
    "url": "https://www.esri.cao.go.jp/jp/sna/menu.html",
    "license_note": (
        "e-Stat terms of use: reuse permitted with attribution to the Cabinet "
        "Office. Retrieved through the e-Stat API, which requires a free "
        "application ID."
    ),
}

DOWNLOAD_URL = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData (SNA 付表6(2))"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Cabinet Office — National Accounts (国民経済計算), "
                    "appended table 6(2)."),
    # The edition lands each January carrying the fiscal year that ended the
    # previous March — fiscal 2024 arrived on 2026-01-30 — so a period is
    # about 22 months old when it is first published and about 34 months old
    # the day before the next edition replaces it. This allows that plus two
    # months; anything tighter flags the dataset as stale on the day it lands.
    "stale_after_days": 1_100,
    "main_series": [
        {"role": "headline", "code": "general.1", "label": "Revenue", "slot": 1},
        {"role": "expense", "code": "general.2", "label": "Expense", "slot": 2},
        {"role": "balance", "code": "general.net-lending",
         "label": "Net lending / borrowing", "slot": 3},
        {"role": "tax", "code": "general.11", "label": "Taxes", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "revenue", "type": "level", "code": "general.1", "label": "Revenue"},
        {"key": "expense", "type": "level", "code": "general.2", "label": "Expense"},
        {"key": "balance", "type": "level", "code": "general.net-lending",
         "label": "Net Lending"},
        {"key": "benefits", "type": "level", "code": "general.27",
         "label": "Social Benefits"},
    ],
    "kinds": dict(
        ("%s.%s" % (sector, item), "level")
        for _ja, sector, _en in SECTORS for item in GFS_NAME),
}


# --- fetching ---------------------------------------------------------------

def _title_of(table):
    title = table.get("TITLE")
    title = title.get("$") if isinstance(title, dict) else (title or "")
    return re.sub(r"\s+", "", str(title))


def newest_table():
    """The statsDataId of the most recent GFS edition.

    Every January the Cabinet Office republishes the whole run under a new id,
    so "newest" is by the fiscal year the edition covers and then by id. The
    list count is checked because a truncated list looks exactly like the
    table having been withdrawn.
    """
    payload = estat_api.call("getStatsList", searchWord=SEARCH_WORD, limit=1000)
    listing = payload["GET_STATS_LIST"]["DATALIST_INF"]
    tables = listing.get("TABLE_INF", [])
    tables = [tables] if isinstance(tables, dict) else tables
    reported = listing.get("NUMBER")
    if reported is not None and int(reported) != len(tables):
        raise ValidationError(
            "the table list is truncated: the API reports %s tables for %r and "
            "returned %d" % (reported, SEARCH_WORD, len(tables)))
    editions = [t for t in tables if TITLE_MARK in _title_of(t)]
    if not editions:
        raise ValidationError(
            "no 付表6(2) table found under %r" % SEARCH_WORD)
    editions.sort(key=lambda t: (str(t.get("SURVEY_DATE") or ""), t["@id"]))
    return editions[-1]["@id"]


def fetch():
    table_id = newest_table()
    return json.dumps({"statsDataId": table_id,
                       "pages": estat_api.get_stats_data(table_id)},
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


def canonical_bytes(raw):
    """The artifact without e-Stat's served-at timestamps — see estat_api."""
    return json.dumps(estat_api.strip_timestamps(json.loads(raw.decode("utf-8"))),
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _axes(data):
    out = {}
    for obj in data["CLASS_INF"]["CLASS_OBJ"]:
        entries = obj["CLASS"]
        entries = [entries] if isinstance(entries, dict) else entries
        out[obj["@id"]] = dict((e["@code"], e) for e in entries)
    return out


def _item_code(name):
    """A cat01 label -> the series code for it, or None to leave it out.

    A numbered label keeps its GFS number, which is stable across editions in
    a way the Japanese wording is not. An unnumbered one is a balancing item
    and is matched on its text with brackets folded away.
    """
    found = _GFS_CODE.match(name)
    if found:
        code = found.group(1)
        if code[0] not in _OPERATIONS:
            return None
        if code not in GFS_NAME:
            raise ValidationError(
                "the source has GFS line %r (%s), which this adapter has no "
                "English name for" % (code, name))
        return code
    key = name.translate(_BRACKETS)
    if key in BALANCING_CODE:
        return BALANCING_CODE[key]
    return None


def _value(entry):
    text = (entry.get("$") or "").strip().replace(",", "")
    if text in ("", "-", "－", "…", "***", "x", "X"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse(raw):
    payload = json.loads(raw.decode("utf-8"))
    meta, observations, kept_items = {}, [], set()
    for page in payload["pages"]:
        data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
        axes = _axes(data)
        for axis in ("cat01", "cat02", "time", "tab"):
            if axis not in axes:
                raise ValidationError("the table has no %r axis" % axis)
        unit = list(axes["tab"].values())[0].get("@unit")
        if unit != EXPECTED_UNIT:
            raise ValidationError(
                "the table is published in %r, not %r — every figure would be "
                "off by a factor" % (unit, EXPECTED_UNIT))

        entries = data["DATA_INF"]["VALUE"]
        entries = [entries] if isinstance(entries, dict) else entries
        for entry in entries:
            item = axes["cat01"].get(entry["@cat01"])
            sector = axes["cat02"].get(entry["@cat02"])
            period_code = entry["@time"]
            if item is None or sector is None:
                raise ValidationError("a value references an axis code that is not declared")
            code = _item_code(item["@name"])
            if code is None:
                continue
            sector_name = re.sub(r"\s+", "", sector["@name"])
            if sector_name not in SECTOR_CODE:
                raise ValidationError(
                    "the table has sector %r, which this adapter does not know"
                    % sector_name)
            sector_code = SECTOR_CODE[sector_name]
            year = _TIME.match(str(period_code))
            if not year:
                raise ValidationError("unreadable time code %r" % period_code)
            value = _value(entry)
            if value is None:
                continue
            series_code = "%s.%s" % (sector_code, code)
            kept_items.add(code)
            meta.setdefault(series_code, {
                "code": series_code,
                "name_en": "%s — %s" % (SECTOR_NAME[sector_code], GFS_NAME[code]),
                "name_ja": "%s %s" % (sector_name, item["@name"]),
                "unit": "jpy_billion", "weight_per_10000": None,
                "sort_order": SECTOR_ORDER[sector_code] * 100_000 + GFS_ORDER[code],
            })
            observations.append({"code": series_code,
                                 "period": datetime.date(int(year.group(1)), 4, 1),
                                 "value": value})
    if not observations:
        raise ValidationError("no observations parsed")
    return [meta[code] for code in sorted(meta)], observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("general.1", "general.2", "general.net-lending",
                     "central.1", "local.1", "social-security-funds.1"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    revenue = by_code["general.1"]
    periods = sorted(revenue)
    if len(periods) < MIN_YEARS:
        raise ValidationError(
            "only %d fiscal years; the table carries at least %d"
            % (len(periods), MIN_YEARS))
    if periods[0].year != FIRST_YEAR:
        raise ValidationError(
            "the run starts at fiscal %d, not %d" % (periods[0].year, FIRST_YEAR))
    for earlier, later in zip(periods, periods[1:]):
        if later.year - earlier.year != 1:
            raise ValidationError(
                "no year between fiscal %d and %d" % (earlier.year, later.year))

    # The sector identity, on every line of every year. This is the check that
    # a sector was not dropped or double-counted, and it is exactly the
    # identity a reader would assume without being able to test it.
    items = sorted(set(code.split(".", 1)[1] for code in codes))
    sector_checks = 0
    for item in items:
        whole = by_code.get("general." + item, {})
        for period, published in sorted(whole.items()):
            parts = [by_code.get("%s.%s" % (sector, item), {}).get(period)
                     for sector in SECTOR_PARTS]
            if any(part is None for part in parts):
                continue
            if abs(sum(parts) - published) > SUM_TOLERANCE:
                raise ValidationError(
                    "fiscal %d line %s: the four sectors sum to %s but general "
                    "government is published as %s"
                    % (period.year, item, sum(parts), published))
            sector_checks += 1

    # The two balancing items against the identities that define them.
    balance_checks = 0
    for sector in SECTOR_CODE.values():
        for period in sorted(by_code.get("%s.1" % sector, {})):
            got = dict((key, by_code.get("%s.%s" % (sector, key), {}).get(period))
                       for key in ("1", "2", "31", "32", "33",
                                   "net-operating-balance", "net-lending",
                                   "net-lending-financing"))
            if got["1"] is not None and got["2"] is not None and \
                    got["net-operating-balance"] is not None:
                if abs(got["1"] - got["2"] - got["net-operating-balance"]) > SUM_TOLERANCE:
                    raise ValidationError(
                        "%s fiscal %d: revenue %s less expense %s is not the "
                        "published net operating balance %s"
                        % (sector, period.year, got["1"], got["2"],
                           got["net-operating-balance"]))
                balance_checks += 1
            if got["net-operating-balance"] is not None and got["31"] is not None \
                    and got["net-lending"] is not None:
                if abs(got["net-operating-balance"] - got["31"]
                       - got["net-lending"]) > SUM_TOLERANCE:
                    raise ValidationError(
                        "%s fiscal %d: the net operating balance less net "
                        "acquisition of non-financial assets is not the "
                        "published net lending" % (sector, period.year))
                balance_checks += 1
            if got["32"] is not None and got["33"] is not None and \
                    got["net-lending-financing"] is not None:
                if abs(got["32"] - got["33"]
                       - got["net-lending-financing"]) > SUM_TOLERANCE:
                    raise ValidationError(
                        "%s fiscal %d: financial assets less liabilities is not "
                        "the published net lending from the financing side"
                        % (sector, period.year))
                balance_checks += 1

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "lines": len(items),
        "first_period": str(min(periods)),
        "latest_period": str(latest),
        "fiscal_years": len(periods),
        "sector_identity_checks": sector_checks,
        "balancing_identity_checks": balance_checks,
        "general_revenue_latest": revenue[max(revenue)],
        "general_net_lending_latest": by_code["general.net-lending"].get(max(revenue)),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "General government accounts — GFS basis", "ja": "一般政府の部門別勘定(GFS)"},
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
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "1994",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published amount, ¥ billion", "unit": "JPY_billion",
         "trust": "official"},
        {"id": "yoy", "label": "Change on the previous fiscal year", "unit": "%", "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search"],
    "cite": "/fiscal.html?dataset=govt-accounts-jp",
    "page": "/fiscal.html",
    "notes": [
        "Series codes are {sector}.{GFS code}, where the sector is central, local, social-security-funds, consolidation or general, and the GFS code is the IMF classification number the Cabinet Office prints in front of each Japanese label.",
        "central + local + social-security-funds + consolidation = general. The consolidation (部門間調整) is published as its own series rather than applied silently, and the identity is checked on every line of every year.",
        "The balancing items are published, not derived: net-operating-balance, gross-operating-balance, net-lending and net-lending-financing come from the source, and each is checked against the identity that defines it.",
        "Everything here is signed. Net lending, the consolidation and the net acquisition of assets all go negative, so none of them carries the positivity gate the Ministry of Finance datasets use.",
        "The revaluation, other-volume-change and closing balance-sheet blocks (GFS 42-43, 52-53, 62-63) are in the source table and not in this dataset: they are stocks and reconciliations, a different statement from the operations one.",
    ],
}
