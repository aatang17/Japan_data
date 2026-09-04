"""Adapter: Bank of Japan — monetary base and the BOJ's transactions (MD09).

Source: BOJ Time-Series Data Search API, database MD09 — end-of-month
stocks and during-month flows of the Bank's principal balance-sheet
items, in units of 100 million yen, July 1996 to the latest month.

Two things make this dataset unlike the CPI adapters:
- values are yen levels (stocks) and net transactions (flows), not
  index points; flows go negative — JGB redemptions carry a minus sign
  and a negative net flow is balance-sheet runoff (QT) — so positivity
  gates apply to stock series only;
- `weight_per_10000` has no meaning here and stays NULL.

Curated series only, never the whole database. Stocks and flows are
distinct measure kinds and must never be mixed in one chart or ranking.

Known data facts the gates rely on:
- stock[t] - stock[t-1] equals the net flow[t] for JGBs in every month
  since May 2001 (April 2001 has a reclassification break), so the
  identity is enforced over recent months only;
- gross purchases + redemptions + other transactions do NOT sum to the
  net JGB flow in all months — the repo-sales-to-government component
  has no live flow series — so no gate (and no chart) may treat those
  three as a complete decomposition.
"""
from . import boj_ts
from .boj_ts import ValidationError  # noqa: F401 — part of the adapter contract
from .boj_ts import canonical_bytes  # noqa: F401 — idempotency: response embeds a timestamp

DB = "MD09"

# (code, kind, name_en); kind: 'stock' = end of month, 'flow' = during month.
# Order here is the explorer sort order: JGBs first, then the rest of the
# asset side, then the monetary-base liabilities, then flows.
SERIES = [
    ("MA03021034S", "stock", "JGB holdings"),
    ("MA030210341S", "stock", "JGB holdings — from outright purchases"),
    ("MA030210022S", "stock", "JGB holdings — from other transactions"),
    ("MA03021035S", "stock", "Treasury discount bill holdings"),
    ("MA030210315S", "stock", "Corporate bond holdings"),
    ("MA030210316S", "stock", "ETF holdings (held as trust property)"),
    ("MA030210317S", "stock", "J-REIT holdings (held as trust property)"),
    ("MA03021019S", "stock", "Equity holdings (held as trust property; through Oct 2025)"),
    ("MA030210314S", "stock", "CP holdings (through Dec 2025)"),
    ("MA03021017S", "stock", "Loans and discounts"),
    ("MA03021036S", "stock", "Funds-supplying operations against pooled collateral"),
    ("MA03021033S", "stock", "Loan Support Program"),
    ("MA03021001S", "stock", "Monetary base"),
    ("MA03021022S", "stock", "Banknotes in circulation"),
    ("MA03021024S", "stock", "Current account balances"),
    ("MA030210242S", "stock", "Reserve balances"),
    ("MA03021034F", "flow", "JGBs — net flow"),
    ("MA030210341F", "flow", "JGBs — outright purchases (gross)"),
    ("MA030210342F", "flow", "JGBs — redemptions (−)"),
    ("MA030210022F", "flow", "JGBs — other transactions, net"),
    ("MA03021035F", "flow", "Treasury discount bills — net flow"),
    ("MA030210351F", "flow", "Treasury discount bills — outright purchases (gross)"),
    ("MA030210352F", "flow", "Treasury discount bills — redemptions (−)"),
]

KIND = {code: kind for code, kind, _name in SERIES}

DATASET = {
    "slug": "boj-assets",
    "title": "Bank of Japan — Asset Holdings and Transactions",
    "country": "Japan",
    "agency": "Bank of Japan",
    "agency_ja": "日本銀行",
    "base": None,
    "frequency": "monthly",
    "description": (
        "End-of-month stocks and during-month flows of the Bank of Japan's "
        "principal balance-sheet items — JGB holdings with gross outright "
        "purchases and redemptions, Treasury discount bills, corporate "
        "bonds, ETFs, J-REITs, loans, and the monetary base — in units of "
        "¥100 million, July 1996 to the latest month. Flows can be "
        "negative: a negative JGB net flow is balance-sheet runoff (QT). "
        "Source database MD09, 'Monetary Base and the Bank of Japan's "
        "Transactions'."
    ),
}

SOURCE = {
    "source_id": "boj:MD09",
    "name": ("BOJ Time-Series Data Search — MD09: Monetary Base and the "
             "Bank of Japan's Transactions"),
    "name_ja": None,
    "url": "https://www.stat-search.boj.or.jp/",
    "license_note": (
        "BOJ Time-Series Data Search API terms: no redistribution "
        "restriction. Two mandatory obligations — display the credit line "
        "(\"%s\") wherever the data appears, including exports, and notify "
        "the BOJ Research and Statistics Department by email when a service "
        "using the API is released." % boj_ts.CREDIT_LINE
    ),
}

DOWNLOAD_URL = boj_ts.data_code_url(DB, [code for code, _kind, _name in SERIES])

RAW_SUFFIX = ".json"

# Presentation config for the API/front-end layer (consumed when the BOJ
# dashboard lands; the credit line is a display obligation, not decoration).
PRESENTATION = {
    "credit_line": boj_ts.CREDIT_LINE,
    "main_series": [
        {"role": "headline", "code": "MA03021034S",
         "label": "BOJ JGB holdings", "slot": 1},
        {"role": "purchases", "code": "MA030210341F",
         "label": "JGB outright purchases (gross)", "slot": 2},
        {"role": "redemptions", "code": "MA030210342F",
         "label": "JGB redemptions", "slot": 3},
    ],
    # The stat strip: what is the JGB book, how far below peak, how fast is it
    # moving, and what is still being bought. Types are generic (api.py);
    # levels are official, the drawdown and trailing average are derived.
    # Labels are strip-cell width at phone size (~15 chars before ellipsis);
    # the full definition rides on the cell's title tooltip.
    "overview_tiles": [
        {"key": "holdings", "type": "level",
         "code": "MA03021034S", "label": "JGB Holdings"},
        {"key": "from_peak", "type": "drawdown",
         "code": "MA03021034S", "label": "From Peak"},
        {"key": "pace_12m", "type": "rolling_avg", "window": 12,
         "code": "MA03021034F", "label": "Net Flow, 12m"},
        {"key": "purchases", "type": "level",
         "code": "MA030210341F", "label": "Gross Purchases"},
    ],
    "kinds": KIND,
    # released early in the following month; well beyond that is stale
    "stale_after_days": 75,
}

# 'Other JGB transactions' is a net position, not a physical holding: it
# was genuinely negative in 52 months during 1996–2000 (min −¥1.0tn),
# when sales to the government exceeded purchases on this line. Every
# other stock series is a true holding and must stay non-negative.
NET_POSITION_STOCKS = {"MA030210022S"}

# April 2001 reclassification: the stock series jumps ~¥21tn with no
# matching flow. The stock-flow identity gate starts after the break.
IDENTITY_GATE_MONTHS = 24
JGB_STOCK, JGB_FLOW = "MA03021034S", "MA03021034F"


def fetch():
    return boj_ts.fetch_bytes(DOWNLOAD_URL)


def parse(raw_bytes):
    data = boj_ts.parse_getdatacode(raw_bytes)
    series, observations = [], []
    for order, (code, _kind, name_en) in enumerate(SERIES, start=1):
        if code not in data:
            continue  # validate() reports the complete missing set
        series.append({
            "code": code,
            "name_en": name_en,
            "name_ja": None,
            "unit": "jpy_100mn",
            "weight_per_10000": None,
            "sort_order": order,
        })
        for period, value in data[code]["observations"]:
            observations.append({"code": code, "period": period, "value": value})
    return series, observations


def _month_index(d):
    return d.year * 12 + d.month


def validate(series, observations):
    import datetime

    expected = set(code for code, _kind, _name in SERIES)
    got = set(s["code"] for s in series)
    missing = sorted(expected - got)
    if missing:
        raise ValidationError("series missing from response: %s" % ", ".join(missing))
    if len(observations) < 6000:
        raise ValidationError("only %d observations parsed" % len(observations))

    by_code = {}
    seen = set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    for code, obs in by_code.items():
        periods = sorted(obs)
        span = _month_index(periods[-1]) - _month_index(periods[0]) + 1
        if span != len(periods):
            raise ValidationError(
                "%s: gap in monthly coverage (%d months span, %d present)"
                % (code, span, len(periods)))
        if (KIND[code] == "stock" and code not in NET_POSITION_STOCKS
                and min(obs.values()) < 0):
            raise ValidationError("%s: negative value in a stock series" % code)

    latest = max(o["period"] for o in observations)
    today = datetime.date.today()
    if (today - latest).days > 120:
        raise ValidationError(
            "latest period %s is implausibly old for a changed file" % latest)

    jgb = by_code[JGB_STOCK]
    jgb_latest = jgb[max(jgb)]
    if not (1_000_000 <= jgb_latest <= 10_000_000):
        raise ValidationError(
            "JGB holdings %s ¥100mn outside sanity range" % jgb_latest)

    # stock-flow identity over recent months (¥1 hundred-million tolerance)
    flow = by_code[JGB_FLOW]
    months = sorted(jgb)[-(IDENTITY_GATE_MONTHS + 1):]
    for prev, cur in zip(months, months[1:]):
        if cur not in flow:
            raise ValidationError("JGB flow missing for %s" % cur)
        if abs((jgb[cur] - jgb[prev]) - flow[cur]) > 1:
            raise ValidationError(
                "stock-flow identity broken in %s: Δstock %s vs flow %s"
                % (cur, jgb[cur] - jgb[prev], flow[cur]))

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "jgb_holdings_latest_100mn": jgb_latest,
        "jgb_net_flow_latest_100mn": flow[max(flow)],
    }


# The dataset's card. Levels and flows in ¥100mn — a different measure type
# from the price indices, never ranked or charted against them.
MANIFEST = {
    "id": DATASET["slug"],
    "section": "monetary",
    "name": {"en": "Bank of Japan — asset holdings and transactions",
             "ja": "日本銀行 資産保有・取引（マネタリーベースと日本銀行の取引）"},
    "shape": "series",
    "summary": ("End-of-month stocks and during-month flows of the Bank of "
                "Japan's principal balance-sheet items — JGBs with gross "
                "purchases and redemptions, T-bills, corporate bonds, ETFs, "
                "J-REITs, loans and the monetary base — in ¥100 million, "
                "monthly from July 1996."),
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
        "as_of_supported": True, "history_from": "1996-07",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published level (stock) or flow, ¥100mn",
         "unit": "JPY_100mn", "trust": "official"},
        {"id": "delta_1m", "label": "Change on the month", "unit": "JPY_100mn",
         "trust": "derived",
         "calc": "value[t] − value[t−1 month], from published values."},
        {"id": "delta_12m", "label": "Change on the year", "unit": "JPY_100mn",
         "trust": "derived",
         "calc": "value[t] − value[t−12 months], from published values."},
        {"id": "avg_12m", "label": "Trailing 12-month average", "unit": "JPY_100mn",
         "trust": "derived",
         "calc": "mean(value[t−11] … value[t]) over the trailing 12 published monthly values."},
        {"id": "sum_12m", "label": "Trailing 12-month sum", "unit": "JPY_100mn",
         "trust": "derived",
         "calc": "sum(value[t−11] … value[t]) over the trailing 12 published monthly values."},
        {"id": "drawdown", "label": "Distance from the all-time peak", "unit": "JPY_100mn",
         "trust": "derived",
         "calc": ("value[latest] − max(value[m]) over all published months m; "
                  "percent: (value[latest] / max − 1) × 100. From published values.")},
        {"id": "rolling_avg", "label": "Trailing average (window in the tile)",
         "unit": "JPY_100mn", "trust": "derived",
         "calc": ("mean(value[t−(w−1)] … value[t]) over the trailing w published "
                  "monthly values (w in the tile's 'window' field).")},
        {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
         "where": "stock series only; refused on flows, which cross zero",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "mom", "label": "Month over month", "unit": "%", "trust": "derived",
         "where": "stock series only; refused on flows, which cross zero",
         "calc": "(value[t] / value[t−1 month] − 1) × 100, from published values."},
        {"id": "ann3m", "label": "3-month annualized", "unit": "%", "trust": "derived",
         "where": "stock series only; refused on flows, which cross zero",
         "calc": "((value[t] / value[t−3 months]) ^ 4 − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/boj.html",
    "page": "/boj.html",
    "notes": [
        "Flows can be negative: a negative JGB net flow is balance-sheet runoff (QT).",
        "Stocks are levels and flows are net purchases — different measure types, "
        "never summed or ranked against each other or against a price index.",
        "The BOJ's credit line must be displayed wherever the data appears, "
        "including exports.",
    ],
}
