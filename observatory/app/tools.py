"""The shared tool layer over the published datasets.

Two consumers, one set of tools: the ask agent (agent.py) and the MCP endpoint
(mcp.py) both answer data lookups exclusively through the functions here. Every
tool is a thin wrapper over the same functions that serve /api/v1 — so any
number either surface can state is a number the API already publishes, computed
by the same code, from the same release. Keeping the layer in one module is
what enforces that: there is no second path to the data to drift from the
public one.

Every response says what it is: index levels are official statistics and are
tagged so; calculated rates carry their formula in `calc`; and each tool
returns a `cite` URL — the permanent page on the site that shows the same view,
so a caller can link the source of every figure. Missing values stay missing;
nothing here turns a gap into a zero.
"""
import contextvars
import datetime
import json
import os

from urllib.parse import urlencode

from . import api
from . import equity_api

# Tool results are the bulk of an LLM caller's input tokens. These bound how
# much a single lookup can pull into context.
DEFAULT_MONTHS = 36
POINT_BUDGET = 1500
MAX_SEARCH_ROWS = 100

# Absolute base for `cite` URLs. Defaults to the production site so that links
# handed to an external AI client resolve for its readers even when the server
# itself runs elsewhere (local dev, a preview deploy).
SITE_BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://web-production-c9178.up.railway.app").rstrip("/")


def _cite(path, **params):
    """Permanent site URL showing the same view as a tool response."""
    filtered = [(k, v) for k, v in sorted(params.items()) if v]
    return SITE_BASE_URL + path + ("?" + urlencode(filtered) if filtered else "")


# ---------------------------------------------------------------------------
# call recording
# ---------------------------------------------------------------------------

# One list per in-flight request. The endpoint runs in a threadpool worker and
# anyio copies the context into it, so each question gets its own log.
_CALLS = contextvars.ContextVar("agent_calls")


def _log():
    try:
        return _CALLS.get()
    except LookupError:
        return []


def _record(tool, args, release=None, note=None):
    entry = {"tool": tool, "args": {k: v for k, v in args.items() if v is not None}}
    if release:
        entry["release_id"] = release.get("release_id")
        entry["latest_period"] = release.get("latest_period")
        entry["source_name"] = release.get("source_name")
    if note:
        entry["note"] = note
    _log().append(entry)
    return entry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fail(message):
    """Tool-level failure the caller can recover from, not a request failure."""
    return json.dumps({"error": message})


def _round(v, dp):
    return None if v is None else round(v, dp)


def _weight_pct(weight_per_10000):
    """Basket weight as a percent of the basket.

    The stored unit is parts per 10,000, which an LLM reliably mis-scales
    when asked to convert it (a 341 came back as "0.341"). Converting here
    leaves nothing to get wrong — the field name states the unit and the value
    is already in it.
    """
    return None if weight_per_10000 is None else round(weight_per_10000 / 100.0, 2)


def _release_of(dataset):
    con = api._con()
    try:
        return api._release(con, dataset)
    finally:
        con.close()


def _window_start(release, months):
    """ISO 'YYYY-MM' this many months before the release's latest period."""
    latest = datetime.date.fromisoformat(release["latest_period"])
    return api._months_ago(latest, months - 1).strftime("%Y-%m")


def _trim_points(series, budget):
    """Keep the most recent points across all series within a token budget."""
    total = sum(len(s["points"]) for s in series)
    if total <= budget:
        return False
    per = max(12, budget // max(1, len(series)))
    for s in series:
        s["points"] = s["points"][-per:]
    return True


# ---------------------------------------------------------------------------
# tools
#
# api.py's handlers carry FastAPI Query() defaults, which are Query objects
# rather than plain values when the functions are called directly. Every
# parameter is therefore passed explicitly below.
# ---------------------------------------------------------------------------

def list_datasets():
    """List the published datasets, with what each one covers."""
    _record("list_datasets", {})
    try:
        raw = api.catalog()
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not raised
        return _fail(str(exc))
    # The equity namespace is not in the core catalog table, but a caller
    # orienting itself here must still learn it exists — an assistant that
    # sees only the CPI tables concludes, wrongly, that nothing else is
    # published. Tool response only; /api/v1/catalog/datasets is unchanged.
    if equity_available():
        raw["datasets"].append({
            "slug": "equity-holdings",
            "title": ("Cross-shareholdings — policy shareholdings "
                      "(政策保有株式) from EDINET filings"),
            "country": "Japan", "agency": "Company filings on EDINET (FSA)",
            "base": None, "frequency": "per annual filing",
            "description": ("Documents-and-events data, not a time series: "
                            "named holdings with share counts and yen book "
                            "values, both directions. Not served by the CPI "
                            "tools — use get_holdings_summary, "
                            "search_companies, get_company_holdings, and "
                            "get_unwind_ranking."),
        })
    raw["cite"] = _cite("/")
    return json.dumps(raw, ensure_ascii=False)


def search_series(query, dataset="cpi-jp", limit=25):
    """Find series by name (English or Japanese) or exact series code."""
    args = {"query": query, "dataset": dataset, "limit": limit}
    try:
        raw = api.series_list(dataset, q=query or "")
    except Exception as exc:  # noqa: BLE001
        _record("search_series", args, note="failed")
        return _fail(str(exc))
    limit = max(1, min(int(limit), MAX_SEARCH_ROWS))
    rows = []
    for s in raw["series"][:limit]:
        rows.append({
            "code": s["code"], "name_en": s["name_en"], "name_ja": s["name_ja"],
            "basket_weight_pct": _weight_pct(s["weight"]), "as_of": s["as_of"],
            "index": _round(s["index"], 1), "yoy": _round(s["yoy"], 2),
            "mom": _round(s["mom"], 2),
            "discontinued": s["discontinued"],
        })
    _record("search_series", args, raw["release"],
            note="%d of %d matches" % (len(rows), raw["count"]))
    return json.dumps({
        "dataset": dataset, "query": query, "total_matches": raw["count"],
        "returned": len(rows), "as_of_release": raw["release"]["latest_period"],
        "index_trust": "official", "rate_trust": "calculated",
        "cite": _cite("/explorer.html", dataset=dataset, q=query),
        "series": rows,
    }, ensure_ascii=False)


def get_series_values(series_codes, measure="yoy", dataset="cpi-jp",
                      start="", end=""):
    """Get the history of one or more series, as a level or a rate of change."""
    args = {"series_codes": series_codes, "measure": measure, "dataset": dataset,
            "start": start or None, "end": end or None}
    codes = ",".join([c.strip() for c in series_codes.split(",") if c.strip()][:6])
    if not codes:
        return _fail("No series codes given.")
    try:
        from_month = start or _window_start(_release_of(dataset), DEFAULT_MONTHS)
        raw = api.observations(dataset, series=codes, measure=measure,
                               start=from_month, end=end or None)
    except Exception as exc:  # noqa: BLE001
        _record("get_series_values", args, note="failed")
        return _fail(str(exc))
    dp = 1 if measure == "index" else 2
    out = [{
        "code": s["code"], "name_en": s["name_en"], "name_ja": s["name_ja"],
        "points": [[p, _round(v, dp)] for p, v in s["points"]],
    } for s in raw["series"]]
    truncated = _trim_points(out, POINT_BUDGET)
    _record("get_series_values", args, raw["release"],
            note="%s, from %s" % (measure, from_month))
    return json.dumps({
        "dataset": dataset, "measure": measure, "unit": raw["unit"],
        "trust": "official" if measure == "index" else "calculated",
        "calc": raw["calc"], "truncated_to_recent": truncated,
        "as_of_release": raw["release"]["latest_period"],
        "cite": _cite("/explorer.html", dataset=dataset, series=codes,
                      measure=measure, **{"from": from_month, "to": end}),
        "series": out,
    }, ensure_ascii=False)


def get_overview(dataset="cpi-jp"):
    """Get the current state of inflation at the latest published month."""
    try:
        raw = api.overview(dataset)
    except Exception as exc:  # noqa: BLE001
        _record("get_overview", {"dataset": dataset}, note="failed")
        return _fail(str(exc))
    _record("get_overview", {"dataset": dataset}, raw["release"])
    return json.dumps({
        "dataset": dataset,
        "latest_period": raw["release"]["latest_period"],
        "source": raw["release"]["source_name"],
        "stale": raw["stale"],
        "cite": _cite("/"),
        "headline_figures": [{
            "label": t["label"], "series_code": t["series_code"],
            "value": _round(t["value"], 2), "unit": t["unit"],
            "change_vs_prior_month_pp": _round(t["delta_pp"], 2),
            "trust": "official" if t["measure"] == "index" else "calculated",
            "calc": t["calc"],
        } for t in raw["tiles"]],
        "groups": [{
            "code": g["code"], "name_en": g["name_en"], "name_ja": g["name_ja"],
            "basket_weight_pct": _weight_pct(g["weight"]), "yoy": _round(g["yoy"], 2),
            "mom": _round(g["mom"], 2),
        } for g in raw["groups"]],
    }, ensure_ascii=False)


def get_contributions(dataset="cpi-jp", start="", end=""):
    """Split headline year-over-year inflation into percentage points by group."""
    args = {"dataset": dataset, "start": start or None, "end": end or None}
    try:
        from_month = start or _window_start(_release_of(dataset), 13)
        raw = api.contributions(dataset, start=from_month, end=end or None)
    except Exception as exc:  # noqa: BLE001
        _record("get_contributions", args, note="failed")
        return _fail(str(exc))
    groups = [{
        "code": g["code"], "name_en": g["name_en"], "name_ja": g["name_ja"],
        "basket_weight_pct": _weight_pct(g["weight"]),
        "points": [[p, _round(v, 3)] for p, v in g["points"]],
    } for g in raw["groups"]]
    _trim_points(groups, POINT_BUDGET)
    _record("get_contributions", args, raw["release"], note="from %s" % from_month)
    return json.dumps({
        "dataset": dataset, "unit": "pp", "trust": "calculated",
        "calc": raw["calc"],
        "as_of_release": raw["release"]["latest_period"],
        "cite": _cite("/") + "#h-contrib",
        "headline_yoy": {
            "code": raw["headline"]["code"], "name_en": raw["headline"]["name_en"],
            "points": [[p, _round(v, 3)] for p, v in raw["headline"]["points"]],
        },
        "groups": groups,
        "residual": [[p, _round(v, 3)] for p, v in raw["residual"]["points"]],
    }, ensure_ascii=False)


def get_breadth(threshold=2.0, dataset="cpi-jp-items", start="", end=""):
    """Measure how broad inflation is across individually priced items."""
    args = {"threshold": threshold, "dataset": dataset,
            "start": start or None, "end": end or None}
    try:
        raw = api.breadth(dataset, threshold=float(threshold))
    except Exception as exc:  # noqa: BLE001
        _record("get_breadth", args, note="failed")
        return _fail(str(exc))
    from_month = start or _window_start(raw["release"], 60)
    lo, hi = from_month + "-01", (end + "-01") if end else None
    points = [p for p in raw["points"]
              if p["period"] >= lo and (hi is None or p["period"] <= hi)]
    _record("get_breadth", args, raw["release"], note="from %s" % from_month)
    return json.dumps({
        "dataset": dataset, "unit": "%", "trust": "calculated",
        "calc": raw["calc"], "threshold": raw["threshold"],
        "item_universe": raw["item_universe"],
        "as_of_release": raw["release"]["latest_period"],
        "cite": _cite("/") + "#h-breadth",
        "points": points[-POINT_BUDGET:],
    }, ensure_ascii=False)


TOOL_IMPLS = {
    "list_datasets": list_datasets,
    "search_series": search_series,
    "get_series_values": get_series_values,
    "get_overview": get_overview,
    "get_contributions": get_contributions,
    "get_breadth": get_breadth,
}


# ---------------------------------------------------------------------------
# equity tools (cross-shareholdings — product #2's own namespace)
#
# Documents-and-events data, not time series: yen book values and share
# counts as filed, never comparable to or rankable against the CPI indices.
# Same layer discipline as the macro tools — every tool wraps the functions
# behind /api/v1/equity, so an AI client only sees what the API publishes.
# The dataset accumulates filing by filing; every response therefore carries
# its coverage so a caller can state the denominator, and the whole group
# reports "not published yet" cleanly when the equity database is absent
# (as on a server that has not received it).
# ---------------------------------------------------------------------------

def equity_available():
    """True when this server has the cross-shareholding database."""
    return equity_api.DB_PATH.exists()


_EQ_UNAVAILABLE = ("The cross-shareholding dataset is not published on this "
                   "server yet.")


def _eq_guard(fn):
    """Run an equity lookup; translate its HTTP failures into tool failures."""
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not raised
        detail = getattr(exc, "detail", None)
        if getattr(exc, "status_code", None) == 503:
            return None, _EQ_UNAVAILABLE
        return None, str(detail) if detail else str(exc)


def search_companies(query):
    """Find companies in the cross-shareholding data by name or code."""
    raw, err = _eq_guard(lambda: equity_api.companies(q=query or ""))
    if err:
        return _fail(err)
    return json.dumps({
        "query": query, "trust": "official",
        "note": equity_api.PROVENANCE["note"],
        "cite": _cite("/holdings.html"),
        "companies": raw["companies"],
    }, ensure_ascii=False, default=str)


def get_company_holdings(sec_code):
    """Both directions for one company: what it holds, and who holds it."""
    code = (sec_code or "").strip()
    if not code:
        return _fail("No securities code given.")
    raw, err = _eq_guard(lambda: equity_api.company(code))
    if err:
        return _fail(err)
    raw["trust"] = "official"
    raw["unit"] = "book values in yen, as filed"
    raw["cite"] = _cite("/holdings.html", c=code)
    return json.dumps(raw, ensure_ascii=False, default=str)


def get_unwind_ranking():
    """Filers ranked by named policy-holding value, with reduce/increase counts."""
    raw, err = _eq_guard(equity_api.unwind)
    if err:
        return _fail(err)
    raw["trust"] = "official"
    raw["unit"] = "book values in yen, as filed"
    raw["cite"] = _cite("/holdings.html")
    return json.dumps(raw, ensure_ascii=False, default=str)


def get_holdings_summary():
    """Coverage and totals of the cross-shareholding dataset on this server."""
    raw, err = _eq_guard(equity_api.summary)
    if err:
        return _fail(err)
    raw["cite"] = _cite("/holdings.html")
    return json.dumps(raw, ensure_ascii=False, default=str)


EQUITY_TOOL_IMPLS = {
    "search_companies": search_companies,
    "get_company_holdings": get_company_holdings,
    "get_unwind_ranking": get_unwind_ranking,
    "get_holdings_summary": get_holdings_summary,
}

# Same OpenAI function shape as TOOL_SCHEMAS; mcp.py reshapes both. Kept in a
# separate list because the ask agent (a CPI product surface) must not see
# these.
EQUITY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_holdings_summary",
            "description": (
                "Coverage and totals of the Japanese cross-shareholding "
                "(policy shareholding, 政策保有株式) dataset: how many filers "
                "are extracted, named holdings, total book value in yen, and "
                "counts of positions reduced or increased year-on-year. Call "
                "this first to state the dataset's coverage — it grows filing "
                "by filing and is not yet all of the market."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_companies",
            "description": (
                "Find companies in the cross-shareholding data by name "
                "(Japanese) or securities code. Returns each match with how "
                "many named holdings it files and how many filers hold it. "
                "Use the sec_code it returns with get_company_holdings."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": ("Company name substring (Japanese) or "
                                        "securities code, e.g. '8306' or "
                                        "'三菱'."),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_holdings",
            "description": (
                "One company's policy shareholdings in both directions: the "
                "named holdings it discloses (share counts, yen book values, "
                "prior-year figures, stated purpose in Japanese, reciprocity) "
                "and the reverse view — every extracted filer that holds it. "
                "Figures are exactly as filed; the reverse view's coverage is "
                "limited to filers extracted so far."),
            "parameters": {
                "type": "object",
                "properties": {
                    "sec_code": {
                        "type": "string",
                        "description": "4-digit securities code, e.g. '8306'.",
                    },
                },
                "required": ["sec_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unwind_ranking",
            "description": (
                "Extracted filers ranked by total named policy-holding book "
                "value in yen, with prior-year value and counts of positions "
                "reduced versus increased — the cross-shareholding unwind "
                "picture. Yen values are levels as filed; never rank or mix "
                "them with CPI index numbers."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def run_tool(name, args):
    """Run one tool with a dict of arguments; never raises.

    Returns (text, is_error): the tool's JSON string, and whether it is the
    {"error": ...} shape rather than data. _fail() is the only producer of
    that shape, so the prefix test below is exact.
    """
    impl = TOOL_IMPLS.get(name) or EQUITY_TOOL_IMPLS.get(name)
    if impl is None:
        return _fail("Unknown tool '%s'." % name), True
    if not isinstance(args, dict):
        return _fail("Arguments for '%s' must be an object." % name), True
    try:
        text = impl(**args)
    except TypeError as exc:  # unexpected or missing argument names
        return _fail(str(exc)), True
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not raised
        return _fail(str(exc)), True
    return text, text.startswith('{"error":')


# OpenAI-style function-calling schemas — the ask agent hands these to its
# provider as-is; mcp.py reshapes them into MCP tool descriptors. One list,
# two wire formats.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_datasets",
            "description": (
                "List the published datasets, with what each one covers. Use "
                "this when you are unsure which table holds the series a "
                "question needs."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_series",
            "description": (
                "Find series by name, in English or Japanese, or by exact "
                "series code. Returns each match with its code, its basket "
                "weight as a percent of the whole basket, its latest index "
                "value, and its latest year-over-year and month-over-month "
                "rates. Use the code it returns to pull history with "
                "get_series_values."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "English text, Japanese text, or an exact series "
                            "code. Empty returns every series in the dataset."),
                    },
                    "dataset": {
                        "type": "string",
                        "enum": ["cpi-jp", "cpi-jp-items"],
                        "description": (
                            "'cpi-jp' for the ~80 category aggregates, "
                            "'cpi-jp-items' for the ~740 detailed items."),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum rows to return, up to 100.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_series_values",
            "description": (
                "Get the history of one or more series, as a level or a rate "
                "of change."),
            "parameters": {
                "type": "object",
                "properties": {
                    "series_codes": {
                        "type": "string",
                        "description": (
                            "Comma-separated series codes from search_series, "
                            "up to 6."),
                    },
                    "measure": {
                        "type": "string",
                        "enum": ["index", "yoy", "mom", "ann3m"],
                        "description": (
                            "'index' for the published index level (2020 = "
                            "100), 'yoy' for year-over-year %, 'mom' for "
                            "month-over-month %, or 'ann3m' for the 3-month "
                            "annualized rate %."),
                    },
                    "dataset": {"type": "string", "enum": ["cpi-jp", "cpi-jp-items"]},
                    "start": {
                        "type": "string",
                        "description": (
                            "First month as 'YYYY-MM'. Defaults to the most "
                            "recent 36 months."),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "Last month as 'YYYY-MM'. Defaults to the latest "
                            "available."),
                    },
                },
                "required": ["series_codes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overview",
            "description": (
                "Get the current state of inflation at the latest published "
                "month: headline, core, and core-core year-over-year rates, "
                "headline month-over-month and 3-month annualized, and each "
                "major expenditure group's year-over-year rate and basket "
                "weight as a percent. Start here for \"what is inflation "
                "now\" questions."),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "enum": ["cpi-jp"],
                        "description": (
                            "The detailed-item table has no aggregate "
                            "overview."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_contributions",
            "description": (
                "Split headline year-over-year inflation into percentage "
                "points by group. Answers \"what is driving inflation\" — how "
                "much of the headline rate each major expenditure group "
                "accounts for. Contributions sum to the headline rate up to a "
                "small rounding residual, returned separately."),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string", "enum": ["cpi-jp"]},
                    "start": {
                        "type": "string",
                        "description": (
                            "First month as 'YYYY-MM'. Defaults to the most "
                            "recent 13 months."),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "Last month as 'YYYY-MM'. Defaults to the latest "
                            "available."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_breadth",
            "description": (
                "Measure how broad inflation is across individually priced "
                "items: the share up at least the threshold year-over-year, "
                "the share rising at all, and the share falling. Broad "
                "inflation means most items rising rather than a few large "
                "movers."),
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "description": (
                            "Year-over-year % defining \"rising fast\". 2.0 "
                            "is the site default."),
                    },
                    "dataset": {"type": "string", "enum": ["cpi-jp-items"]},
                    "start": {
                        "type": "string",
                        "description": (
                            "First month as 'YYYY-MM'. Defaults to the most "
                            "recent 60 months."),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "Last month as 'YYYY-MM'. Defaults to the latest "
                            "available."),
                    },
                },
                "required": [],
            },
        },
    },
]
