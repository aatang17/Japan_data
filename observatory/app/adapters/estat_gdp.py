"""Adapter: quarterly GDP estimates — Japan (Cabinet Office, via e-Stat).

Source: 内閣府経済社会総合研究所 (ESRI), 四半期別ＧＤＰ速報 (Quarterly Estimates of
GDP), the three expenditure-side tables that carry the numbers everyone
quotes — real, nominal and the deflator, all seasonally adjusted, quarterly
from 1994 Q1 on the 2020 base:

    0003109750  実質季節調整系列   real, chained 2020 prices, ¥ billion
    0003109785  名目季節調整系列   nominal, ¥ billion
    0003109787  四半期デフレーター季節調整系列   deflator, 2020 = 100

Read through the e-Stat JSON API. The three table ids are STABLE: the
Cabinet Office overwrites them in place at every release (first preliminary
about six weeks after the quarter ends, second about ten), so one ingest a
month is enough to catch each release, and every release that changes a
number lands in the vintage history as a new release. That is the point of
carrying this dataset at all: Japan has no public archive of what GDP was
said to be on a given date, and the estimates are revised at every one of
those releases.

What is stored: the published LEVELS only — quarterly amounts at seasonally
adjusted annual rates, in the ¥ billion the Cabinet Office publishes. The
growth rates the Cabinet Office also publishes (前期比, 前期比年率) are
deliberately not stored: the platform computes them from the levels and
shows the formula, per the trust contract. A rate computed from published
(rounded) levels can differ from the Cabinet Office's own by a tenth of a
point; the methodology page says so.

Facts the parser and the gates rely on:

- Time codes look like ``2026000406``: the year, then the first and last
  month of the quarter. A quarter is dated by its first month.
- The real table carries a line the nominal one does not: 開差, the
  chain-linking discrepancy. In chained-price accounts the components do
  not add to the total; the discrepancy is what makes them, and the gate
  checks that identity with it in. The nominal identity holds without it.
- The deflator is published to one decimal from unrounded levels, so
  nominal ÷ real × 100 from the rounded levels lands within a tenth or two
  of it. The gate allows that and no more — it is what ties the three
  tables to one release.
- The <参考> reference lines (GNI, domestic demand, trading gains …) are
  published alongside and are kept, marked as reference aggregates.

Levels, not indices: ``weight_per_10000`` stays NULL.
"""
import datetime
import json

from . import estat_api


class ValidationError(Exception):
    pass


# The three tables, keyed by the basis they carry. The basis is the second
# half of every series code, so "gdp.real_sa", "gdp.nominal_sa" and
# "gdp.deflator_sa" are the same concept on three bases.
TABLES = [
    ("real_sa", "0003109750", "Real, seasonally adjusted (chained 2020 prices)", "jpy_billion"),
    ("nominal_sa", "0003109785", "Nominal, seasonally adjusted", "jpy_billion"),
    ("deflator_sa", "0003109787", "Deflator, seasonally adjusted (2020 = 100)", "index"),
]
TABLE_BASIS = dict((tid, basis) for basis, tid, _label, _unit in TABLES)
BASIS_LABEL = dict((basis, label) for basis, _tid, label, _unit in TABLES)
BASIS_UNIT = dict((basis, unit) for basis, _tid, _label, unit in TABLES)

# Expenditure-side lines, matched by the Japanese name e-Stat publishes —
# NOT by the numeric code, which is renumbered per table (the nominal table
# drops three lines and shifts everything after them up). The code in the
# first column is the real table's, kept for reference only. A name the API
# serves that is not in this list fails the ingest rather than being served
# under a guessed English name. `reference` marks the <参考> lines.
CONCEPTS = [
    # (real-table code, key, English, Japanese as published, reference?)
    ("11", "gdp", "Gross domestic product (expenditure side)", "国内総生産(支出側)", False),
    ("12", "private_consumption", "Private final consumption expenditure", "民間最終消費支出", False),
    ("13", "household_consumption", "Household final consumption expenditure",
     "民間最終消費支出_家計最終消費支出", False),
    ("14", "household_consumption_ex_rent",
     "Household final consumption expenditure, excluding imputed rent",
     "民間最終消費支出_家計最終消費支出_除く持ち家の帰属家賃", False),
    ("15", "residential_investment", "Private residential investment", "民間住宅", False),
    ("16", "business_investment", "Private non-residential investment", "民間企業設備", False),
    ("17", "private_inventories", "Change in private inventories", "民間在庫変動", False),
    ("18", "government_consumption", "Government final consumption expenditure",
     "政府最終消費支出", False),
    ("19", "public_investment", "Public fixed capital formation", "公的固定資本形成", False),
    ("20", "public_inventories", "Change in public inventories", "公的在庫変動", False),
    ("21", "net_exports", "Net exports of goods and services", "財貨・サービス_純輸出", False),
    ("22", "exports", "Exports of goods and services", "財貨・サービス_輸出", False),
    ("23", "imports", "Imports of goods and services", "財貨・サービス_輸入", False),
    ("24", "chain_discrepancy", "Chain-linking discrepancy", "開差", False),
    ("25", "trading_gains", "Trading gains from terms of trade", "<参考>交易利得", True),
    ("26", "gross_domestic_income", "Gross domestic income", "<参考>国内総所得", True),
    ("27", "net_income_from_abroad", "Net income from the rest of the world",
     "<参考>海外からの所得_純受取", True),
    ("28", "income_from_abroad_receipts", "Income from the rest of the world, receipts",
     "<参考>海外からの所得_受取", True),
    ("29", "income_from_abroad_payments", "Income from the rest of the world, payments",
     "<参考>海外からの所得_支払", True),
    ("30", "gross_national_income", "Gross national income", "<参考>国民総所得", True),
    ("31", "domestic_demand", "Domestic demand", "<参考>国内需要", True),
    ("32", "private_demand", "Private demand", "<参考>民間需要", True),
    ("33", "public_demand", "Public demand", "<参考>公的需要", True),
    ("34", "gross_fixed_capital_formation", "Gross fixed capital formation",
     "<参考>総固定資本形成", True),
    ("35", "final_demand", "Final demand", "<参考>最終需要", True),
]
CONCEPT_BY_NAME = dict((c[3], c) for c in CONCEPTS)
CONCEPT_BY_KEY = dict((c[1], c) for c in CONCEPTS)
CONCEPT_ORDER = dict((c[1], i) for i, c in enumerate(CONCEPTS))

# What each table is published with, as concept keys. Checked, not assumed:
# a table that gains or loses a line has changed, and the ingest says so.
_ALL = [c[1] for c in CONCEPTS]
EXPECTED = {
    "real_sa": _ALL,
    # No chain-linking discrepancy, trading gains or domestic income on the
    # nominal table: those three exist only because prices move.
    "nominal_sa": [k for k in _ALL if k not in
                   ("chain_discrepancy", "trading_gains", "gross_domestic_income")],
    # A deflator exists only for a line that is a quantity of something:
    # not for inventories, net exports, discrepancies or net income.
    "deflator_sa": ["gdp", "private_consumption", "household_consumption",
                    "household_consumption_ex_rent", "residential_investment",
                    "business_investment", "government_consumption",
                    "public_investment", "exports", "imports",
                    "income_from_abroad_receipts", "income_from_abroad_payments",
                    "gross_national_income", "domestic_demand", "private_demand",
                    "public_demand", "gross_fixed_capital_formation", "final_demand"],
}

# The identity every expenditure-side table must satisfy. The nominal one
# holds exactly; the real one only once the chain-linking discrepancy is in.
COMPONENTS = ["private_consumption", "residential_investment", "business_investment",
              "private_inventories", "government_consumption", "public_investment",
              "public_inventories", "net_exports"]

DATASET = {
    "slug": "gdp-jp",
    "title": "Quarterly GDP Estimates — Japan (Cabinet Office)",
    "country": "Japan",
    "agency": "Cabinet Office, Economic and Social Research Institute",
    "agency_ja": "内閣府経済社会総合研究所",
    "base": "2020 (chained prices; deflator 2020 = 100)",
    "frequency": "quarterly",
    "description": (
        "Japan's quarterly GDP estimates on the expenditure side — gross "
        "domestic product and every demand component, real (chained 2020 "
        "prices), nominal and the deflator, all seasonally adjusted at annual "
        "rates in ¥ billion — quarterly from 1994 Q1, exactly as the Cabinet "
        "Office publishes them and revised at every release. Growth rates are "
        "calculated on the platform from these levels and carry their formula."
    ),
}

SOURCE = {
    "source_id": "e-stat:qe-gdp-2020",
    "name": "Quarterly Estimates of GDP — expenditure side, seasonally adjusted (2020 base)",
    "name_ja": "四半期別ＧＤＰ速報 国内総生産（支出側）及び各需要項目 季節調整系列（2020暦年基準）",
    "url": "https://www.e-stat.go.jp/dbview?sid=0003109750",
    "license_note": (
        "e-Stat terms of use: reuse permitted with attribution to the Cabinet "
        "Office. Retrieved through the e-Stat API, which requires a free "
        "application ID."
    ),
}

DOWNLOAD_URL = ("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
                "?statsDataId=0003109750,0003109785,0003109787")

RAW_SUFFIX = ".json"


# --- fetch ------------------------------------------------------------------

def fetch():
    """All three tables, as the API returned them, in one artifact.

    One release changes all three at once, so one artifact is the right
    unit of evidence: a vintage is a set of levels that were published
    together, never a real table from one release beside a nominal one from
    the next.
    """
    out = {}
    for basis, tid, _label, _unit in TABLES:
        out[basis] = {"statsDataId": tid, "pages": estat_api.get_stats_data(tid)}
    return json.dumps(out, ensure_ascii=False, sort_keys=True).encode("utf-8")


def canonical_bytes(raw):
    """The artifact without the API's served-at timestamps — see estat_api."""
    return json.dumps(estat_api.strip_timestamps(json.loads(raw.decode("utf-8"))),
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- parse ------------------------------------------------------------------

def _quarter_start(time_code, time_name):
    """'2026000406' / '2026年4～6月期' -> date(2026, 4, 1).

    Both the code and the name are read and must agree, so a change in
    either convention is caught rather than silently shifting a quarter.
    """
    if len(time_code) != 10 or not time_code.isdigit():
        raise ValidationError("unreadable time code %r" % time_code)
    year = int(time_code[:4])
    first, last = int(time_code[6:8]), int(time_code[8:10])
    if first not in (1, 4, 7, 10) or last != first + 2:
        raise ValidationError("time code %r is not a calendar quarter" % time_code)
    digits = "".join(ch if ch.isdigit() else " " for ch in time_name).split()
    if len(digits) < 3 or int(digits[0]) != year or int(digits[1]) != first:
        raise ValidationError(
            "time code %r disagrees with its name %r" % (time_code, time_name))
    # Wide on purpose. This band exists to catch a garbled time code, not to
    # police where a table starts: the live tables begin in 1994 Q1 and
    # validate() checks that exactly, while the archived releases this parser
    # is shared with (app/gdp_vintages.py) carry quarters back to 1980.
    if not (1950 <= year <= 2100):
        raise ValidationError("implausible year %d" % year)
    return datetime.date(year, first, 1)


def _value(text):
    """A published number, or None for e-Stat's not-available marks."""
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(raw_bytes):
    doc = json.loads(raw_bytes.decode("utf-8"))
    series, observations = [], []
    for basis, tid, _label, unit in TABLES:
        entry = doc.get(basis)
        if not entry or entry.get("statsDataId") != tid or not entry.get("pages"):
            raise ValidationError("artifact lacks the %s table (%s)" % (basis, tid))
        seen = set()
        for page in entry["pages"]:
            data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
            names = estat_api.class_values(data, "cat01")
            times = estat_api.class_values(data, "time")
            values = data["DATA_INF"]["VALUE"]
            if isinstance(values, dict):
                values = [values]
            for v in values:
                code = v["@cat01"]
                concept = CONCEPT_BY_NAME.get(names.get(code))
                if concept is None:
                    raise ValidationError(
                        "%s table carries line %s named %r, which this adapter "
                        "does not know" % (basis, code, names.get(code)))
                published_unit = v.get("@unit")
                if unit == "jpy_billion" and published_unit != "10億円":
                    raise ValidationError(
                        "%s line %s is published in %r, not 10億円"
                        % (basis, code, published_unit))
                value = _value(v.get("$"))
                if value is None:
                    continue
                period = _quarter_start(v["@time"], times[v["@time"]])
                key = concept[1]
                if key not in seen:
                    seen.add(key)
                    series.append({
                        "code": "%s.%s" % (key, basis),
                        "name_en": "%s — %s" % (concept[2], BASIS_LABEL[basis]),
                        "name_ja": "%s %s" % (concept[3].replace("<参考>", ""),
                                              _basis_ja(basis)),
                        "unit": unit,
                        "weight_per_10000": None,
                        "sort_order": CONCEPT_ORDER[key] * 10
                                      + [b for b, _t, _l, _u in TABLES].index(basis),
                    })
                observations.append(
                    {"code": "%s.%s" % (key, basis), "period": period, "value": value})
        missing = sorted(set(EXPECTED[basis]) - seen)
        extra = sorted(seen - set(EXPECTED[basis]))
        if missing or extra:
            raise ValidationError(
                "%s table lines changed: missing %s, unexpected %s"
                % (basis, missing, extra))
    if not observations:
        raise ValidationError("no values parsed")
    return sorted(series, key=lambda s: s["sort_order"]), observations


def _basis_ja(basis):
    return {"real_sa": "実質季節調整系列", "nominal_sa": "名目季節調整系列",
            "deflator_sa": "デフレーター季節調整系列"}[basis]


# --- validate ---------------------------------------------------------------

FIRST_QUARTER = datetime.date(1994, 1, 1)
# Real GDP has run between ¥430tn and ¥600tn on this base; nominal is
# higher on the way up. Wide enough for a decade of growth, narrow enough
# to catch a table read in the wrong unit.
REAL_GDP_BAND = (400_000.0, 750_000.0)
NOMINAL_GDP_BAND = (400_000.0, 900_000.0)
# Levels are published to a tenth of a billion; a sum of nine of them can
# miss by a few tenths of rounding and no more.
IDENTITY_TOLERANCE = 1.0
# The deflator is published to one decimal from unrounded levels.
DEFLATOR_TOLERANCE = 0.25
# Second preliminary estimates land ~70 days after the quarter; the next
# first preliminary ~135 days after it. A quarter dated by its first month
# is therefore up to ~230 days old the day before the next release lands.
STALE_AFTER_DAYS = 260


def validate(series, observations):
    value = {}
    for o in observations:
        key = (o["code"], o["period"])
        if key in value:
            raise ValidationError("duplicate observation %s %s" % key)
        value[key] = o["value"]

    by_code = {}
    for (c, p), v in value.items():
        by_code.setdefault(c, {})[p] = v

    def col(concept, basis):
        return by_code.get("%s.%s" % (concept, basis), {})

    # 1. Coverage: every quarter from 1994 Q1 to the newest, with no gap, on
    #    all three bases; and the newest is a quarter the Cabinet Office
    #    could actually have published.
    latest = None
    for basis in ("real_sa", "nominal_sa", "deflator_sa"):
        gdp = col("gdp", basis)
        if not gdp:
            raise ValidationError("no GDP series on the %s basis" % basis)
        quarters = sorted(gdp)
        if quarters[0] != FIRST_QUARTER:
            raise ValidationError(
                "%s GDP starts %s, expected %s" % (basis, quarters[0], FIRST_QUARTER))
        expected = (quarters[-1].year - quarters[0].year) * 4 \
            + (quarters[-1].month - quarters[0].month) // 3 + 1
        if len(quarters) != expected:
            raise ValidationError(
                "%s GDP has %d quarters over a span of %d — a gap"
                % (basis, len(quarters), expected))
        if latest is None:
            latest = quarters[-1]
        elif quarters[-1] != latest:
            raise ValidationError(
                "the three tables end in different quarters (%s vs %s): not "
                "one release" % (latest, quarters[-1]))
    if (datetime.date.today() - latest).days > 400:
        raise ValidationError("newest quarter %s is implausibly old" % latest)

    # 2. The expenditure identity, both bases. The real one needs the
    #    chain-linking discrepancy; the nominal one has none and holds without.
    for basis, with_discrepancy in (("real_sa", True), ("nominal_sa", False)):
        gdp = col("gdp", basis)
        parts = [col(k, basis) for k in COMPONENTS]
        disc = col("chain_discrepancy", basis) if with_discrepancy else {}
        worst = 0.0
        for q, total in gdp.items():
            xs = [p.get(q) for p in parts]
            if any(x is None for x in xs):
                raise ValidationError("%s: a component is missing for %s" % (basis, q))
            s = sum(xs) + (disc.get(q, 0.0) if with_discrepancy else 0.0)
            gap = abs(total - s)
            worst = max(worst, gap)
            if gap > IDENTITY_TOLERANCE:
                raise ValidationError(
                    "%s %s: components sum to %.1f, GDP is %.1f (off by %.1f)"
                    % (basis, q, s, total, gap))
    # 3. Net exports are exports less imports, on both money bases.
    for basis in ("real_sa", "nominal_sa"):
        nx, ex, im = col("net_exports", basis), col("exports", basis), col("imports", basis)
        for q, v in nx.items():
            if abs(v - (ex[q] - im[q])) > IDENTITY_TOLERANCE:
                raise ValidationError(
                    "%s %s: net exports %.1f but exports − imports = %.1f"
                    % (basis, q, v, ex[q] - im[q]))

    # 4. The deflator ties the three tables to one release: nominal ÷ real
    #    must reproduce it to the tenth it is published to.
    real, nominal, deflator = col("gdp", "real_sa"), col("gdp", "nominal_sa"), col("gdp", "deflator_sa")
    worst_deflator = 0.0
    for q, d in deflator.items():
        implied = nominal[q] / real[q] * 100.0
        gap = abs(implied - d)
        worst_deflator = max(worst_deflator, gap)
        if gap > DEFLATOR_TOLERANCE:
            raise ValidationError(
                "%s: published deflator %.1f, nominal ÷ real gives %.2f — the "
                "tables are not from one release" % (q, d, implied))

    # 5. Sanity bands on the newest levels.
    if not (REAL_GDP_BAND[0] <= real[latest] <= REAL_GDP_BAND[1]):
        raise ValidationError("real GDP %.1f ¥bn at %s is outside the sanity band"
                              % (real[latest], latest))
    if not (NOMINAL_GDP_BAND[0] <= nominal[latest] <= NOMINAL_GDP_BAND[1]):
        raise ValidationError("nominal GDP %.1f ¥bn at %s is outside the sanity band"
                              % (nominal[latest], latest))

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "first_quarter": FIRST_QUARTER.isoformat(),
        "quarters": len(real),
        "worst_identity_gap": round(worst, 3),
        "worst_deflator_gap": round(worst_deflator, 3),
        "real_gdp_latest": real[latest],
        "nominal_gdp_latest": nominal[latest],
    }


# --- presentation -----------------------------------------------------------

KIND = dict(("%s.%s" % (c[1], basis), "index" if basis == "deflator_sa" else "level")
            for c in CONCEPTS for basis, _t, _l, _u in TABLES)

PRESENTATION = {
    "credit_line": ("Source: Cabinet Office, Economic and Social Research "
                    "Institute — Quarterly Estimates of GDP."),
    "stale_after_days": STALE_AFTER_DAYS,
    "main_series": [
        {"role": "headline", "code": "gdp.real_sa",
         "label": "Real GDP", "slot": 1},
        {"role": "nominal", "code": "gdp.nominal_sa",
         "label": "Nominal GDP", "slot": 2},
        {"role": "deflator", "code": "gdp.deflator_sa",
         "label": "GDP deflator", "slot": 3},
    ],
    "overview_tiles": [
        {"key": "real", "type": "level", "code": "gdp.real_sa", "label": "Real GDP"},
        {"key": "nominal", "type": "level", "code": "gdp.nominal_sa", "label": "Nominal GDP"},
        {"key": "consumption", "type": "level", "code": "private_consumption.real_sa",
         "label": "Private Consumption"},
        {"key": "capex", "type": "level", "code": "business_investment.real_sa",
         "label": "Business Investment"},
    ],
    "kinds": KIND,
    # The demand components a contributions view decomposes GDP into, and
    # the reference lines it leaves out. Served so a page never guesses.
    "components": [
        {"code": k, "label": CONCEPT_BY_KEY[k][2]} for k in COMPONENTS],
    "reference_lines": [c[1] for c in CONCEPTS if c[4]],
}


MANIFEST = {
    "id": DATASET["slug"],
    "section": "national-accounts",
    "name": {"en": "Quarterly GDP estimates — expenditure side",
             "ja": "四半期別ＧＤＰ速報（支出側）"},
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
        {"id": "index", "label": "Published level (¥ billion, seasonally adjusted "
                                 "annual rate; deflator 2020 = 100)",
         "unit": "JPY_billion", "trust": "official"},
        {"id": "ann3m", "label": "Quarter on quarter, annualized", "unit": "%",
         "trust": "derived",
         "where": "quarterly series: t−3 months is the previous quarter",
         "calc": "((value[t] / value[t−3 months]) ^ 4 − 1) × 100, from published values."},
        {"id": "yoy", "label": "Year on year", "unit": "%", "trust": "derived",
         "where": "quarterly series: t−12 months is the same quarter a year earlier",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "qoq", "label": "Quarter on quarter", "unit": "%", "trust": "derived",
         "calc": "qoq % = (level[t] ÷ level[t − 1 quarter] − 1) × 100"},
        {"id": "contribution", "label": "Contribution to real GDP growth", "unit": "pp",
         "trust": "derived",
         "calc": "contribution pp = (component[t] − component[t − 1 quarter]) ÷ GDP[t − 1 quarter] × 100"},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "overview": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search"],
    "cite": "/gdp.html",
    "page": "/gdp.html",
    "notes": [
        "Levels only. The Cabinet Office's own growth rates are computed from "
        "unrounded levels and can differ from a rate computed here by about a "
        "tenth of a point; the formula shown is what was done.",
        "A quarter is dated by its first month: 2026-04-01 is April–June 2026.",
        "Real components do not sum to real GDP in chained-price accounts; the "
        "published chain-linking discrepancy (開差) is carried as its own line "
        "and closes the identity. Contributions are computed on the previous "
        "quarter's GDP and do not sum exactly for the same reason.",
        "The same three table ids are overwritten at every release, so every "
        "revision is captured as a new vintage from the first ingest onward. "
        "Releases before that date are not yet in the history.",
    ],
}
