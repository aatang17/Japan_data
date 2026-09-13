"""Adapter: Financial Statements Statistics of Corporations — Japan (MOF).

Source: 財務省 法人企業統計調査 (Hōjin Kigyō Tōkei), the quarterly survey of
the balance sheets and income statements of Japanese companies with
capital of ¥10 million or more, read from e-Stat's time-series table
0003060191 — 時系列データ 金融業、保険業以外の業種 (原数値) — quarterly from
April–June 1954. This is the source of the corporate profit, investment and
cash figures the sell side quotes and the SNA's own business-investment
input; the quarterly is published about two months after the quarter ends.

The table is 23 million values wide: 235 line items × 62 industries × 9
capital-size classes × 289 quarters. This adapter takes a pinned subset —
the lines an analyst reads (sales, operating and ordinary profit, capital
investment, cash, the balance-sheet totals, headcount) across the 31
industry aggregates that are still published and four capital classes —
and asks the API for only those cells (~580,000 values, six pages, about
90 seconds). Everything else is left where it is.

Facts the parser and the gates rely on:

- **Not seasonally adjusted.** The Ministry's 原数値. The platform's
  year-on-year measure is the right way to read it and the page says so;
  quarter-on-quarter on these levels is mostly seasonality.
- Time codes are ``YYYYQ`` with Q = 1 for January–March. The name is
  checked against the code. A quarter is dated by its first month.
- Amounts are in 百万円 (¥ million) exactly as published; counts of
  companies and people are counts. Nothing is rescaled.
- The industry list carries pairs like 繊維工業 / 繊維工業(H20年度まで):
  a reclassification in fiscal 2008 split several series. Only the current
  definitions are taken; the "up to fiscal 2008" legacy lines are not.
- The ratios the Ministry publishes (売上高営業利益率 and its kin) are not
  stored: the platform calculates margins and shows the formula.
- Three identities hold and are gated: total assets equal liabilities plus
  net assets (the Ministry's 負債計 already contains the reserves under
  special laws, so those are not added again); manufacturing plus
  non-manufacturing equal all industries; and the three capital classes
  sum to all sizes. All to the ¥ million, save for the estimated company
  count, which is rounded by class.

Levels and flows, not indices: ``weight_per_10000`` stays NULL.
"""
import datetime
import json

from . import estat_api

STATS_DATA_ID = "0003060191"


class ValidationError(Exception):
    pass


# --- what is taken ------------------------------------------------------------

# (e-Stat cat01 code, key, English, kind, unit)
ITEMS = [
    ("001", "companies", "Companies in the population", "stock", "count"),
    ("078", "sales", "Sales", "flow", "jpy_million"),
    ("081", "operating_profit", "Operating profit", "flow", "jpy_million"),
    ("086", "ordinary_profit", "Ordinary profit", "flow", "jpy_million"),
    ("093", "personnel_costs", "Personnel costs", "flow", "jpy_million"),
    ("090", "director_pay", "Directors' remuneration", "flow", "jpy_million"),
    ("088", "employees", "Employees", "stock", "persons"),
    ("040", "capex", "Capital investment (new fixed assets, incl. software)", "flow", "jpy_million"),
    ("225", "capex_ex_software", "Capital investment excluding software", "flow", "jpy_million"),
    ("058", "depreciation", "Depreciation", "flow", "jpy_million"),
    ("002", "cash", "Cash and deposits", "stock", "jpy_million"),
    ("164", "inventories", "Inventories", "stock", "jpy_million"),
    ("071", "equity_holdings", "Shares held as investments", "stock", "jpy_million"),
    ("013", "total_assets", "Total assets", "stock", "jpy_million"),
    ("171", "total_liabilities", "Total liabilities", "stock", "jpy_million"),
    ("172", "net_assets", "Net assets", "stock", "jpy_million"),
    ("028", "liabilities_and_net_assets", "Liabilities and net assets", "stock", "jpy_million"),
    ("167", "short_term_borrowings", "Short-term borrowings", "stock", "jpy_million"),
    ("169", "long_term_borrowings", "Long-term borrowings", "stock", "jpy_million"),
    ("019", "bonds", "Corporate bonds outstanding", "stock", "jpy_million"),
    ("027", "retained_earnings", "Retained earnings", "stock", "jpy_million"),
]
ITEM_BY_CODE = dict((i[0], i) for i in ITEMS)
ITEM_ORDER = dict((i[1], n) for n, i in enumerate(ITEMS))
# The Ministry's unit for each item, checked on every value.
ITEM_UNIT_JA = {"count": "社", "persons": "人", "jpy_million": "百万円"}

# (e-Stat cat02 code, key, English). The first three are the aggregates the
# reconciliation gate works on; the rest are the published industry lines
# still in use, in the Ministry's own order.
INDUSTRIES = [
    ("104", "all", "All industries (excluding finance and insurance)"),
    ("108", "manufacturing", "Manufacturing"),
    ("144", "non_manufacturing", "Non-manufacturing"),
    ("109", "food", "Food"),
    ("115", "chemicals", "Chemicals"),
    ("116", "petroleum_coal", "Petroleum and coal products"),
    ("117", "ceramics", "Ceramics, stone and clay"),
    ("118", "iron_steel", "Iron and steel"),
    ("119", "nonferrous", "Non-ferrous metals"),
    ("120", "metal_products", "Metal products"),
    ("154", "general_machinery", "General-purpose machinery"),
    ("121", "production_machinery", "Production machinery"),
    ("124", "business_machinery", "Business-oriented machinery"),
    ("122", "electrical_machinery", "Electrical machinery"),
    ("145", "ict_equipment", "Information and communication equipment"),
    ("146", "transport_equipment", "Transport equipment"),
    ("123", "motor_vehicles", "Motor vehicles and parts"),
    ("126", "other_manufacturing", "Other manufacturing"),
    ("107", "construction", "Construction"),
    ("135", "electricity", "Electricity"),
    ("142", "information_communication", "Information and communications"),
    ("134", "transport_postal", "Transport and postal"),
    ("129", "wholesale_retail", "Wholesale and retail"),
    ("127", "wholesale", "Wholesale"),
    ("128", "retail", "Retail"),
    ("155", "real_estate_leasing", "Real estate and goods leasing"),
    ("130", "real_estate", "Real estate"),
    ("137", "services", "Services"),
    ("156", "accommodation_food", "Accommodation and food services"),
    ("158", "pure_holding", "Pure holding companies"),
    ("152", "medical_welfare", "Medical and welfare"),
]
INDUSTRY_BY_CODE = dict((i[0], i) for i in INDUSTRIES)
INDUSTRY_ORDER = dict((i[1], n) for n, i in enumerate(INDUSTRIES))

# (e-Stat cat03 code, key, English) — capital-size classes. The survey's
# universe is capital of ¥10 million and over, so the three classes sum to
# all sizes.
SIZES = [
    ("26", "all", "All sizes"),
    ("25", "large", "Capital ¥1 billion and over"),
    ("24", "medium", "Capital ¥100 million to under ¥1 billion"),
    ("19", "small", "Capital ¥10 million to under ¥100 million"),
]
SIZE_BY_CODE = dict((s[0], s) for s in SIZES)
SIZE_ORDER = dict((s[1], n) for n, s in enumerate(SIZES))

DATASET = {
    "slug": "corporate-finance-jp",
    "title": "Financial Statements Statistics of Corporations, Quarterly — Japan (MOF)",
    "country": "Japan",
    "agency": "Ministry of Finance, Policy Research Institute",
    "agency_ja": "財務省財務総合政策研究所",
    "base": None,
    "frequency": "quarterly",
    "description": (
        "The balance sheets and income statements of Japanese companies with "
        "capital of ¥10 million or more, from the Ministry of Finance's "
        "quarterly corporate survey: sales, operating and ordinary profit, "
        "capital investment, depreciation, cash, borrowings, equity holdings "
        "and headcount, by industry and by capital size, quarterly from 1954, "
        "in ¥ million as published and not seasonally adjusted. Margins and "
        "growth rates are calculated on the platform and carry their formula."
    ),
}

SOURCE = {
    "source_id": "e-stat:" + STATS_DATA_ID,
    "name": ("Financial Statements Statistics of Corporations by Industry, "
             "Quarterly — time series, industries other than finance and "
             "insurance, original values"),
    "name_ja": "法人企業統計調査 時系列データ 金融業、保険業以外の業種（原数値）",
    "url": "https://www.e-stat.go.jp/dbview?sid=" + STATS_DATA_ID,
    "license_note": (
        "e-Stat terms of use: reuse permitted with attribution to the Ministry "
        "of Finance. Retrieved through the e-Stat API, which requires a free "
        "application ID."
    ),
}

DOWNLOAD_URL = ("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
                "?statsDataId=" + STATS_DATA_ID)

RAW_SUFFIX = ".json"


# --- fetch ------------------------------------------------------------------

def fetch():
    """The pinned cells, as the API returned them, page by page."""
    pages = estat_api.get_stats_data(
        STATS_DATA_ID,
        cdCat01=",".join(i[0] for i in ITEMS),
        cdCat02=",".join(i[0] for i in INDUSTRIES),
        cdCat03=",".join(s[0] for s in SIZES))
    return json.dumps(pages, ensure_ascii=False, sort_keys=True).encode("utf-8")


def canonical_bytes(raw):
    """The artifact without the API's served-at timestamps — see estat_api."""
    return json.dumps(estat_api.strip_timestamps(json.loads(raw.decode("utf-8"))),
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- parse ------------------------------------------------------------------

def _quarter_start(time_code, time_name):
    """'20262' / '2026年4 - 6 月' -> date(2026, 4, 1)."""
    if len(time_code) != 5 or not time_code.isdigit():
        raise ValidationError("unreadable time code %r" % time_code)
    year, q = int(time_code[:4]), int(time_code[4])
    if q not in (1, 2, 3, 4):
        raise ValidationError("time code %r is not a quarter" % time_code)
    first = (q - 1) * 3 + 1
    digits = "".join(ch if ch.isdigit() else " " for ch in time_name).split()
    if len(digits) < 2 or int(digits[0]) != year or int(digits[1]) != first:
        raise ValidationError(
            "time code %r disagrees with its name %r" % (time_code, time_name))
    if not (1950 <= year <= 2100):
        raise ValidationError("implausible year %d" % year)
    return datetime.date(year, first, 1)


def _value(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _code(item, industry, size):
    return "%s.%s.%s" % (item, industry, size)


def parse(raw_bytes):
    pages = json.loads(raw_bytes.decode("utf-8"))
    if not pages:
        raise ValidationError("no pages in the artifact")
    series = {}
    observations = []
    for page in pages:
        data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
        item_names = estat_api.class_values(data, "cat01")
        ind_names = estat_api.class_values(data, "cat02")
        size_names = estat_api.class_values(data, "cat03")
        times = estat_api.class_values(data, "time")
        values = data["DATA_INF"]["VALUE"]
        if isinstance(values, dict):
            values = [values]
        for v in values:
            item = ITEM_BY_CODE.get(v["@cat01"])
            ind = INDUSTRY_BY_CODE.get(v["@cat02"])
            size = SIZE_BY_CODE.get(v["@cat03"])
            if item is None or ind is None or size is None:
                raise ValidationError(
                    "the API returned a cell that was not asked for: %s/%s/%s"
                    % (v["@cat01"], v["@cat02"], v["@cat03"]))
            if v.get("@unit") != ITEM_UNIT_JA[item[4]]:
                raise ValidationError(
                    "%s is published in %r, expected %r — the line changed"
                    % (item[2], v.get("@unit"), ITEM_UNIT_JA[item[4]]))
            value = _value(v.get("$"))
            if value is None:
                continue
            period = _quarter_start(v["@time"], times[v["@time"]])
            code = _code(item[1], ind[1], size[1])
            if code not in series:
                series[code] = {
                    "code": code,
                    "name_en": "%s — %s, %s" % (item[2], ind[2], size[2].lower()),
                    "name_ja": "%s %s %s" % (
                        item_names.get(v["@cat01"], "").split("(")[0],
                        ind_names.get(v["@cat02"], ""),
                        size_names.get(v["@cat03"], "")),
                    "unit": item[4],
                    "weight_per_10000": None,
                    "sort_order": (ITEM_ORDER[item[1]] * 1000
                                   + INDUSTRY_ORDER[ind[1]] * 10 + SIZE_ORDER[size[1]]),
                }
            observations.append({"code": code, "period": period, "value": value})
    if not observations:
        raise ValidationError("no values parsed")
    return sorted(series.values(), key=lambda s: s["sort_order"]), observations


# --- validate ---------------------------------------------------------------

# Every anchor series must run unbroken from here to the newest quarter.
ANCHOR_FROM = datetime.date(1975, 1, 1)
ANCHORS = ["sales", "ordinary_profit", "capex", "total_assets", "companies"]
# Yen totals are sums of company figures already in ¥ million and add
# exactly; the company count is an estimate rounded within each class, so
# the classes can miss the total by a few. Expressed per ten thousand of
# the total so it scales with the line.
SUM_TOLERANCE_PER_10000 = {"jpy_million": 0.5, "persons": 0.5, "count": 5.0}
# All-industry quarterly sales have run ¥250–400tn on this survey; this
# band catches a wrong unit or a wrong class, not a recession.
SALES_BAND = (150_000_000.0, 700_000_000.0)
# Published about two months after the quarter ends, so a quarter dated by
# its first month is ~150 days old on arrival and ~240 the day before the
# next release. Grace on top.
STALE_AFTER_DAYS = 270


def _tolerance(unit, total):
    return abs(total) * SUM_TOLERANCE_PER_10000[unit] / 10000.0 + 1.0


def validate(series, observations):
    value = {}
    for o in observations:
        key = (o["code"], o["period"])
        if key in value:
            raise ValidationError("duplicate observation %s %s" % key)
        value[key] = o["value"]
    unit_of = dict((s["code"], s["unit"]) for s in series)
    # Indexed once: the gates below look up a few thousand series and a
    # scan of 580,000 observations per lookup took the better part of a
    # minute.
    by_code = {}
    for (c, p), v in value.items():
        by_code.setdefault(c, {})[p] = v

    def col(item, industry, size):
        return by_code.get(_code(item, industry, size), {})

    # 1. Coverage of the anchors, and a newest quarter the Ministry could
    #    actually have published.
    latest = None
    for item in ANCHORS:
        c = col(item, "all", "all")
        if not c:
            raise ValidationError("no all-industry series for %s" % item)
        quarters = sorted(q for q in c if q >= ANCHOR_FROM)
        if not quarters or quarters[0] != ANCHOR_FROM:
            raise ValidationError("%s does not run from %s" % (item, ANCHOR_FROM))
        span = ((quarters[-1].year - quarters[0].year) * 4
                + (quarters[-1].month - quarters[0].month) // 3 + 1)
        if len(quarters) != span:
            raise ValidationError("%s: %d quarters over a span of %d — a gap"
                                  % (item, len(quarters), span))
        if latest is None or quarters[-1] > latest:
            latest = quarters[-1]
    if (datetime.date.today() - latest).days > 400:
        raise ValidationError("newest quarter %s is implausibly old" % latest)
    for item in ANCHORS:
        if max(col(item, "all", "all")) != latest:
            raise ValidationError("%s ends before %s" % (item, latest))

    # 2. The balance sheet balances: assets = liabilities + net assets, for
    #    every industry, size and quarter published. (The Ministry's 負債計
    #    already holds the reserves under special laws — adding them again
    #    broke this identity by exactly their amount on the first attempt.)
    checked_bs = 0
    for _c, ind, _e in INDUSTRIES:
        for _c2, size, _e2 in SIZES:
            assets = col("total_assets", ind, size)
            both = col("liabilities_and_net_assets", ind, size)
            liab = col("total_liabilities", ind, size)
            net = col("net_assets", ind, size)
            for q, a in assets.items():
                if q not in both or q not in liab or q not in net:
                    continue
                if abs(a - both[q]) > _tolerance("jpy_million", a):
                    raise ValidationError(
                        "%s/%s %s: assets %.0f but liabilities and net assets %.0f"
                        % (ind, size, q, a, both[q]))
                rhs = liab[q] + net[q]
                if abs(both[q] - rhs) > _tolerance("jpy_million", both[q]):
                    raise ValidationError(
                        "%s/%s %s: liabilities %.0f + net assets %.0f = %.0f, "
                        "published total %.0f"
                        % (ind, size, q, liab[q], net[q], rhs, both[q]))
                checked_bs += 1
    if checked_bs < 1000:
        raise ValidationError("only %d balance-sheet identities checked" % checked_bs)

    # 3. Manufacturing + non-manufacturing = all industries; and the three
    #    capital classes = all sizes. Every item, every quarter both sides
    #    publish.
    checked_sum = 0
    worst = {"industry": 0.0, "size": 0.0}
    for _c, item, _e, _k, unit in ITEMS:
        for _c2, size, _e2 in SIZES:
            total = col(item, "all", size)
            m, n = col(item, "manufacturing", size), col(item, "non_manufacturing", size)
            for q, t in total.items():
                if q in m and q in n:
                    gap = abs(t - (m[q] + n[q]))
                    if gap > _tolerance(unit, t):
                        raise ValidationError(
                            "%s/%s %s: manufacturing %.0f + non-manufacturing %.0f "
                            "≠ all industries %.0f" % (item, size, q, m[q], n[q], t))
                    worst["industry"] = max(worst["industry"], gap)
                    checked_sum += 1
        for _c2, ind, _e2 in INDUSTRIES:
            total = col(item, ind, "all")
            parts = [col(item, ind, s) for s in ("large", "medium", "small")]
            for q, t in total.items():
                xs = [p.get(q) for p in parts]
                if any(x is None for x in xs):
                    continue
                gap = abs(t - sum(xs))
                if gap > _tolerance(unit, t):
                    raise ValidationError(
                        "%s/%s %s: capital classes sum to %.0f, all sizes %.0f"
                        % (item, ind, q, sum(xs), t))
                worst["size"] = max(worst["size"], gap)
                checked_sum += 1
    if checked_sum < 10000:
        raise ValidationError("only %d reconciliations checked" % checked_sum)

    # 4. Sanity on the newest all-industry reading.
    sales = col("sales", "all", "all")[latest]
    if not (SALES_BAND[0] <= sales <= SALES_BAND[1]):
        raise ValidationError("all-industry sales %.0f ¥mn at %s outside the sanity band"
                              % (sales, latest))
    if col("companies", "all", "all")[latest] <= 0:
        raise ValidationError("no companies in the population at %s" % latest)

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "anchor_from": ANCHOR_FROM.isoformat(),
        "balance_sheets_checked": checked_bs,
        "reconciliations_checked": checked_sum,
        "worst_sum_gap": worst,
        "sales_latest": sales,
        "units": sorted(set(unit_of.values())),
    }


# --- presentation -----------------------------------------------------------

KIND = dict((_code(i[1], ind[1], s[1]), i[3])
            for i in ITEMS for ind in INDUSTRIES for s in SIZES)

PRESENTATION = {
    "credit_line": ("Source: Ministry of Finance — Financial Statements "
                    "Statistics of Corporations by Industry, Quarterly."),
    "stale_after_days": STALE_AFTER_DAYS,
    "main_series": [
        {"role": "headline", "code": "ordinary_profit.all.all",
         "label": "Ordinary profit, all industries", "slot": 1},
        {"role": "sales", "code": "sales.all.all",
         "label": "Sales, all industries", "slot": 2},
        {"role": "capex", "code": "capex.all.all",
         "label": "Capital investment, all industries", "slot": 3},
        {"role": "cash", "code": "cash.all.all",
         "label": "Cash and deposits, all industries", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "profit", "type": "level", "code": "ordinary_profit.all.all",
         "label": "Ordinary Profit"},
        {"key": "sales", "type": "level", "code": "sales.all.all", "label": "Sales"},
        {"key": "capex", "type": "level", "code": "capex.all.all",
         "label": "Capital Investment"},
        {"key": "cash", "type": "level", "code": "cash.all.all",
         "label": "Cash and Deposits"},
    ],
    "kinds": KIND,
    # The three axes, so a page can build its controls from the payload
    # rather than repeating this list.
    "items": [{"code": i[1], "label": i[2], "kind": i[3], "unit": i[4]} for i in ITEMS],
    "industries": [{"code": i[1], "label": i[2]} for i in INDUSTRIES],
    "sizes": [{"code": s[1], "label": s[2]} for s in SIZES],
}


MANIFEST = {
    "id": DATASET["slug"],
    "section": "corporate",
    "name": {"en": "Corporate financial statements, quarterly — by industry and size",
             "ja": "法人企業統計調査（四半期）業種別・規模別"},
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
        "as_of_supported": True, "history_from": "1954",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published amount (¥ million; companies and persons as counts)",
         "unit": "JPY_million", "trust": "official"},
        {"id": "yoy", "label": "Change on the same quarter a year earlier", "unit": "%",
         "trust": "derived",
         "where": "quarterly, not seasonally adjusted: t−12 months is the same quarter last year",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "margin", "label": "Ordinary profit margin", "unit": "%", "trust": "derived",
         "calc": "margin % = ordinary profit ÷ sales × 100"},
        {"id": "ttm", "label": "Trailing four quarters", "unit": "JPY_million",
         "trust": "derived",
         "calc": "ttm = sum of the four most recent published quarters, flows only"},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "overview": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/corporate.html",
    "page": "/corporate.html",
    "notes": [
        "Not seasonally adjusted. Read it year on year; a quarter-on-quarter "
        "change on these levels is mostly seasonality.",
        "A pinned subset of the Ministry's table: 21 lines × 31 industry "
        "aggregates × 4 capital classes. The 'up to fiscal 2008' legacy industry "
        "lines and the Ministry's published ratios are not carried; margins are "
        "calculated on the platform.",
        "Companies with capital under ¥10 million are outside the survey. The "
        "company count is an estimate for the population, rounded within each "
        "capital class, so the classes can miss the total by a few.",
        "A quarter is dated by its first month: 2026-04-01 is April–June 2026.",
        "Finance and insurance are a separate table with a different line "
        "structure and are not included.",
    ],
}
