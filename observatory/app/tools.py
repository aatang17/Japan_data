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
from . import equity_api, governance_api

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
        "cite": _cite("/cpi.html"),
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
        "cite": _cite("/cpi.html") + "#h-contrib",
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
        "cite": _cite("/cpi.html") + "#h-breadth",
        "points": points[-POINT_BUDGET:],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# visitor arrivals (jnto-visitors)
#
# A count of people — a different measure from a price index, a yen level, a
# stock or a flow. Nothing here may be ranked or combined with CPI or
# balance-sheet figures.
#
# These wrap /api/v1/jnto-visitors/arrivals, which publishes the counts and the
# market hierarchy. Growth, share, recovery and rank are calculated from that
# published payload by the same formulas the inbound page shows under "Show
# calculation", and every response carries the formula it used.
# ---------------------------------------------------------------------------

ARRIVALS_DATASET = "jnto-visitors"

ARRIVALS_CALCS = {
    "count": "Published arrivals in persons, exactly as released. Not recomputed.",
    "yoy": ("(arrivals[t] / arrivals[t−12 months] − 1) × 100, in percent, "
            "from published counts."),
    "recovery": ("(arrivals[t] / arrivals[same month of the baseline year]) "
                 "× 100. The baseline is 2019, the last full year before the "
                 "border closed; comparing like months removes the seasonality."),
    "share": ("(arrivals[market] / arrivals[Total]) × 100, both for the same "
              "month, from published counts."),
}


def _arrivals_raw():
    return api.arrivals(ARRIVALS_DATASET)


def _arrivals_index(raw):
    return dict((p, i) for i, p in enumerate(raw["periods"]))


def _latest_complete(raw):
    """Newest month carrying every top-level series.

    The two most recent months are estimates covering a subset of markets, so
    a share or a ranking taken there would compare markets across different
    months. Rankings therefore use this month, and say so.
    """
    i = len(raw["periods"]) - 1
    while i > 0 and not all(raw["values"].get(c, [])[i] is not None
                            for c in raw["regions"]):
        i -= 1
    return i


def _baseline_index(raw, idx, pidx):
    iso = raw["periods"][idx]
    return pidx.get("%d%s" % (raw["baseline_year"], iso[4:]))


def get_arrivals(markets="total", measure="count", start="", end=""):
    """Monthly foreign visitor arrivals to Japan, by market."""
    args = {"markets": markets, "measure": measure,
            "start": start or None, "end": end or None}
    if measure not in ARRIVALS_CALCS or measure == "share":
        return _fail("measure must be 'count', 'yoy' or 'recovery'.")
    try:
        raw = _arrivals_raw()
    except Exception as exc:  # noqa: BLE001
        _record("get_arrivals", args, note="failed")
        return _fail(str(exc))

    known = dict((m["code"], m) for m in raw["markets"])
    codes = [c.strip() for c in markets.split(",") if c.strip()][:6] or ["total"]
    unknown = [c for c in codes if c not in known]
    if unknown:
        return _fail("Unknown market code(s): %s. Call get_arrivals_ranking to "
                     "see the codes." % ", ".join(unknown))

    pidx = _arrivals_index(raw)
    lo = start + "-01" if start else _window_start(raw["release"], DEFAULT_MONTHS) + "-01"
    hi = (end + "-01") if end else None

    out = []
    for code in codes:
        col = raw["values"][code]
        points = []
        for i, iso in enumerate(raw["periods"]):
            if iso < lo or (hi and iso > hi):
                continue
            v = col[i]
            if measure == "count":
                points.append([iso[:7], v])
                continue
            if v is None:
                points.append([iso[:7], None])
                continue
            if measure == "yoy":
                b = pidx.get("%d%s" % (int(iso[:4]) - 1, iso[4:]))
            else:
                b = _baseline_index(raw, i, pidx)
            prev = col[b] if b is not None else None
            if not prev:
                points.append([iso[:7], None])
            elif measure == "yoy":
                points.append([iso[:7], _round((v / prev - 1) * 100, 2)])
            else:
                points.append([iso[:7], _round((v / prev) * 100, 1)])
        out.append({"code": code, "name_en": known[code]["name_en"],
                    "name_ja": known[code]["name_ja"],
                    "parent": known[code]["parent"], "points": points})

    truncated = _trim_points(out, POINT_BUDGET)
    _record("get_arrivals", args, raw["release"],
            note="%s, %d market(s)" % (measure, len(out)))
    return json.dumps({
        "dataset": ARRIVALS_DATASET,
        "measure": measure,
        "unit": "persons" if measure == "count" else
                ("%" if measure == "yoy" else "index, baseline = 100"),
        "trust": "official" if measure == "count" else "calculated",
        "calc": ARRIVALS_CALCS[measure],
        "baseline_year": raw["baseline_year"],
        "truncated_to_recent": truncated,
        "as_of_release": raw["release"]["latest_period"],
        "estimate_months": [p[:7] for p in raw["provisional_periods"]],
        "estimate_note": (
            "Months listed in estimate_months are JNTO estimates: official, "
            "rounded to the nearest 100, covering only the largest markets, "
            "and superseded by a provisional and then a definitive figure."),
        "credit": "Japan National Tourism Organization (JNTO)",
        "cite": _cite("/inbound.html"),
        "series": out,
    }, ensure_ascii=False)


def get_arrivals_ranking(order="highest", metric="arrivals", limit=15,
                         group="markets"):
    """Rank the markets sending visitors to Japan, at one comparable month."""
    args = {"order": order, "metric": metric, "limit": limit, "group": group}
    if order not in ("highest", "lowest"):
        return _fail("order must be 'highest' or 'lowest'.")
    if metric not in ("arrivals", "yoy", "share", "recovery"):
        return _fail("metric must be 'arrivals', 'yoy', 'share' or 'recovery'.")
    try:
        raw = _arrivals_raw()
    except Exception as exc:  # noqa: BLE001
        _record("get_arrivals_ranking", args, note="failed")
        return _fail(str(exc))

    pidx = _arrivals_index(raw)
    i = _latest_complete(raw)
    iso = raw["periods"][i]
    y1 = pidx.get("%d%s" % (int(iso[:4]) - 1, iso[4:]))
    b = _baseline_index(raw, i, pidx)
    total = raw["values"]["total"][i]

    rows = []
    for m in raw["markets"]:
        if group == "markets" and m["kind"] not in ("market", "group"):
            continue
        if group == "regions" and m["kind"] not in ("region", "total"):
            continue
        col = raw["values"][m["code"]]
        cur = col[i]
        if cur is None:
            continue
        prev = col[y1] if y1 is not None else None
        base = col[b] if b is not None else None
        rows.append({
            "code": m["code"], "name_en": m["name_en"], "name_ja": m["name_ja"],
            "parent": m["parent"], "kind": m["kind"],
            "arrivals": int(cur),
            "yoy": _round((cur / prev - 1) * 100, 2) if prev else None,
            "share": _round(cur / total * 100, 2) if total else None,
            "recovery": _round(cur / base * 100, 1) if base else None,
        })

    ranked = [r for r in rows if r[metric] is not None]
    ranked.sort(key=lambda r: r[metric], reverse=(order == "highest"))
    limit = max(1, min(int(limit), 60))
    _record("get_arrivals_ranking", args, raw["release"],
            note="%s by %s, %s" % (order, metric, iso[:7]))
    return json.dumps({
        "dataset": ARRIVALS_DATASET,
        "period": iso[:7],
        "period_note": (
            "The latest month with a complete market breakdown. Later months "
            "exist but are estimates covering only the largest markets, so a "
            "ranking or a share taken there would not compare like with like."),
        "order": order, "metric": metric, "group": group,
        "counted": len(ranked), "returned": min(limit, len(ranked)),
        "trust": {"arrivals": "official", "yoy": "calculated",
                  "share": "calculated", "recovery": "calculated"}[metric],
        "calc": ARRIVALS_CALCS[{"arrivals": "count", "yoy": "yoy",
                                "share": "share", "recovery": "recovery"}[metric]],
        "baseline_year": raw["baseline_year"],
        "hierarchy_note": (
            "A region is the sum of its member markets and a group (Middle "
            "East, Nordic Countries) is the sum of its members — never add a "
            "parent to its children."),
        "as_of_release": raw["release"]["latest_period"],
        "credit": "Japan National Tourism Organization (JNTO)",
        "cite": _cite("/inbound.html") + "#h-markets",
        "markets": ranked[:limit],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# JGB yield curve and Bank of Japan balance sheet
#
# Percent-per-year yields and ¥100mn levels and flows. Both are published
# values; the spreads and the distance from peak are calculated and say so.
# ---------------------------------------------------------------------------

def get_yield_curve(date=""):
    """The JGB constant-maturity curve on one business day, with key spreads."""
    args = {"date": date or None}
    try:
        raw = api.curve("jgb-yields")
    except Exception as exc:  # noqa: BLE001
        _record("get_yield_curve", args, note="failed")
        return _fail(str(exc))

    dates = raw["dates"]
    if date:
        on_or_before = [d for d in dates if d <= date]
        if not on_or_before:
            return _fail("No published curve on or before %s; the series "
                         "starts %s." % (date, dates[0]))
        idx = len(on_or_before) - 1
    else:
        idx = len(dates) - 1

    curve = []
    by_code = {}
    for m in raw["maturities"]:
        v = raw["values"][m["code"]][idx]
        by_code[m["code"]] = v
        curve.append({"code": m["code"], "years": m["years"],
                      "yield_pct": _round(v, 3)})

    spreads = []
    for s in raw["spreads"]:
        lo, hi = by_code.get(s["short"]), by_code.get(s["long"])
        spreads.append({
            "key": s["key"], "label": s["label"],
            "spread_pp": _round(hi - lo, 3) if (lo is not None and hi is not None)
                         else None,
        })

    _record("get_yield_curve", args, raw["release"], note="curve on %s" % dates[idx])
    return json.dumps({
        "dataset": "jgb-yields", "date": dates[idx],
        "requested_date": date or None,
        "unit": "% per year", "trust": "official", "calc": raw["calc"],
        "spread_calc": ("spread = long-maturity yield − short-maturity yield, "
                        "in percentage points, from published yields."),
        "missing_note": ("A maturity absent on a date was not yet issued or "
                         "not quoted; it is null, never zero. Yields can be "
                         "genuinely negative."),
        "as_of_release": raw["release"]["latest_period"],
        "cite": _cite("/rates.html", d=dates[idx]),
        "curve": curve, "spreads": spreads,
    }, ensure_ascii=False)


def get_boj_balance_sheet():
    """The Bank of Japan's JGB holdings and flows at the latest month."""
    try:
        raw = api.overview("boj-assets")
    except Exception as exc:  # noqa: BLE001
        _record("get_boj_balance_sheet", {}, note="failed")
        return _fail(str(exc))
    _record("get_boj_balance_sheet", {}, raw["release"])
    return json.dumps({
        "dataset": "boj-assets",
        "latest_period": raw["release"]["latest_period"],
        "source": raw["release"]["source_name"],
        "stale": raw["stale"],
        "unit_note": ("Levels are stocks and flows in ¥100 million as "
                      "published. A net flow is negative during balance-sheet "
                      "runoff; a negative value is real, not missing. These are "
                      "yen levels and must never be ranked against a price "
                      "index or a count."),
        "tiles": raw["tiles"],
        "credit": ("This service uses the API provided by the 'Bank of Japan "
                   "Time-Series Data Search.' The Bank of Japan does not "
                   "guarantee the content of the service."),
        "cite": _cite("/boj.html"),
    }, ensure_ascii=False)


TOOL_IMPLS = {
    "list_datasets": list_datasets,
    "search_series": search_series,
    "get_series_values": get_series_values,
    "get_overview": get_overview,
    "get_contributions": get_contributions,
    "get_breadth": get_breadth,
    "get_arrivals": get_arrivals,
    "get_arrivals_ranking": get_arrivals_ranking,
    "get_yield_curve": get_yield_curve,
    "get_boj_balance_sheet": get_boj_balance_sheet,
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
        "names_note": raw["names_note"],
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
    raw, err = _eq_guard(lambda: equity_api.unwind(year=""))
    if err:
        return _fail(err)
    raw["trust"] = "official"
    raw["unit"] = "book values in yen, as filed"
    raw["cite"] = _cite("/holdings.html")
    return json.dumps(raw, ensure_ascii=False, default=str)


def get_holdings_summary():
    """Coverage and totals of the cross-shareholding dataset on this server."""
    raw, err = _eq_guard(lambda: equity_api.summary(year=""))
    if err:
        return _fail(err)
    raw["cite"] = _cite("/holdings.html")
    return json.dumps(raw, ensure_ascii=False, default=str)


def _gov_guard(fn):
    """Same translation as _eq_guard, for the boards-and-pay endpoints."""
    return _eq_guard(fn)


def get_governance_summary(year=""):
    """Coverage and market aggregates for the boards-and-pay dataset."""
    raw, err = _gov_guard(lambda: governance_api.summary(year=year or "", listed=""))
    if err:
        return _fail(err)
    raw["cite"] = _cite("/holdings.html")
    return json.dumps(raw, ensure_ascii=False, default=str)


def get_company_board(sec_code, year=""):
    """One company's board, officer pay table and named individuals."""
    code = (sec_code or "").strip()
    if not code:
        return _fail("No securities code given.")
    raw, err = _gov_guard(lambda: governance_api.company(code, year=year or ""))
    if err:
        return _fail(err)
    raw["trust"] = "official"
    raw["unit"] = "pay in yen, as filed"
    raw["cite"] = _cite("/holdings.html", c=code)
    return json.dumps(raw, ensure_ascii=False, default=str)


def get_board_history(sec_code):
    """One company's board and pay across every extracted fiscal year."""
    code = (sec_code or "").strip()
    if not code:
        return _fail("No securities code given.")
    raw, err = _gov_guard(lambda: governance_api.history(sec_code=code))
    if err:
        return _fail(err)
    raw["cite"] = _cite("/holdings.html", c=code)
    return json.dumps(raw, ensure_ascii=False, default=str)


def get_governance_screen(metric="oldest_boards", year="", listed="true", limit=25):
    """Ranked cross-section of boards and pay, one filing per company."""
    raw, err = _gov_guard(lambda: governance_api.screen(
        metric=metric or "oldest_boards", year=year or "", listed=listed or "",
        limit=max(1, min(int(limit or 25), 200))))
    if err:
        return _fail(err)
    raw["cite"] = _cite("/holdings.html")
    return json.dumps(raw, ensure_ascii=False, default=str)


def get_top_paid_officers(year="", limit=25):
    """Highest-paid named individuals — consolidated basis."""
    raw, err = _gov_guard(lambda: governance_api.named(
        year=year or "", listed="", limit=max(1, min(int(limit or 25), 200)), min_yen=0))
    if err:
        return _fail(err)
    raw["trust"] = "official"
    raw["cite"] = _cite("/holdings.html")
    return json.dumps(raw, ensure_ascii=False, default=str)


EQUITY_TOOL_IMPLS = {
    "get_governance_summary": get_governance_summary,
    "get_company_board": get_company_board,
    "get_board_history": get_board_history,
    "get_governance_screen": get_governance_screen,
    "get_top_paid_officers": get_top_paid_officers,
    "search_companies": search_companies,
    "get_company_holdings": get_company_holdings,
    "get_unwind_ranking": get_unwind_ranking,
    "get_holdings_summary": get_holdings_summary,
}

# Same OpenAI function shape as TOOL_SCHEMAS; mcp.py reshapes both. Kept in a
# separate list because the ask agent (a CPI product surface) must not see
# these.
# Shared warnings. An assistant that misses these will state something false
# with total confidence, so they are repeated in every pay tool's description.
_CONSOLIDATED_WARNING = (
    "Named individual pay is 連結報酬等 — CONSOLIDATED, including pay from "
    "group companies. It is a DIFFERENT BASIS from the officer-category pay "
    "table on the same filing: people appear who do not sit on that board (a "
    "subsidiary's chief executive named in the parent's report), and the named "
    "total can exceed the whole category total. Never net, subtract or divide "
    "one by the other, and never describe consolidated pay as salary from the "
    "listed parent. ")
_COMPONENTS_WARNING = (
    "The category total is the filed, published number; the components beside "
    "it often do not sum to it, because filers differ on whether 非金銭報酬等 "
    "is additive or an 'of which' memo and print figures rounded to ¥mn. Quote "
    "the total, and check components_reconcile before quoting a component. ")

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
                "Find companies in the cross-shareholding data by name — "
                "English or Japanese — or by securities code. Returns each "
                "match with its as-filed Japanese name, its English name where "
                "one exists, and how many named holdings it files and how many "
                "filers hold it. Use the sec_code it returns with "
                "get_company_holdings."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": ("Company name substring in English or "
                                        "Japanese, or securities code — e.g. "
                                        "'8306', 'Mitsubishi UFJ' or '三菱'. "
                                        "English matching is case-insensitive."),
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
                "Company names come back as filed in both languages: the "
                "Japanese name from the filing, and the English name the "
                "company states on its own annual report cover page. "
                "Figures are exactly as filed; the reverse view's coverage is "
                "limited to filers extracted so far. "
                "Also returns `reclassified` — holdings the filer moved from a "
                "policy shareholding to 純投資目的 (pure investment), as filed, "
                "with the fiscal year and the filer's stated reason. These "
                "leave the named holdings table WITHOUT being sold, so never "
                "describe a fall in named holdings as selling or unwinding "
                "without checking this list and `flows`, which carries the "
                "filing's own sale proceeds and acquisition costs. `notes` "
                "holds the filing's own footnotes to the table, where share "
                "splits and mergers are explained. `pct_outstanding` on each "
                "position is calculated, not filed — shares held divided by the "
                "issuer's issued shares less treasury, taken from the issuer's "
                "own annual report nearest that position's fiscal year end. It "
                "is null where the issuer files no annual report in this "
                "archive, and where the share base cannot be pinned down — a "
                "split or issue straddling the two dates — in which case "
                "`pct_unavailable` gives the reason. Never fill a null by "
                "computing the percentage yourself from other fields: the "
                "reason it is missing is that the two share counts are not "
                "measured on the same basis. "
                "`scale` sizes the whole policy book against the filer's own "
                "balance sheet: `policy_total_yen` (the filing's own total for "
                "the entire policy bucket) with `pct_of_equity` and "
                "`pct_of_assets`, and `scale_history` gives the same per "
                "fiscal year. NEVER answer 'how much does this company hold in "
                "cross-shareholdings' by summing the named holdings — those "
                "cover only the largest issues and run about three quarters of "
                "the true total, as little as half at some filers. Use "
                "`policy_total_yen`. Read `equity_basis` before comparing two "
                "companies: a `parent_only` denominator is the holding company "
                "alone, not the group, and is not comparable with a "
                "consolidated one. The percentages are calculated, not filed, "
                "and are null where the filing gives no usable denominator — "
                "report that as unknown, never as zero. "
                "Each individual position also carries `pct_of_holder_equity` "
                "and `pct_of_holder_assets` — that one holding as a share of "
                "the holder's own equity or assets, the mirror of "
                "`pct_outstanding`. Keep the two straight: `pct_outstanding` is "
                "how much of the ISSUER the holder owns, `pct_of_holder_equity` "
                "is how much of ITSELF the holder has committed to that name. "
                "A value above 100 is possible and is sometimes genuine, so do "
                "not treat it as an error on its own; check `implausible` and "
                "the filing."),
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
    {
        "type": "function",
        "function": {
            "name": "get_governance_summary",
            "description": (
                "Coverage and market aggregates for the Japanese boards-and-pay "
                "dataset extracted from annual securities reports: companies, "
                "board seats, median board size, average director age, share of "
                "directors aged 70+, female officer ratio, boards with no women, "
                "median employee salary and gender wage gap, median pay per "
                "inside director, and the count of individuals disclosed at "
                "¥100m or more. Call this FIRST and state its coverage with any "
                "aggregate you quote — extraction_status shows how many filings "
                "are clean, partial, or carry no tagged board. "
                + _CONSOLIDATED_WARNING),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "string",
                        "description": ("Fiscal year, e.g. '2026'. Omit for each "
                                        "company's latest filing."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_board",
            "description": (
                "One company's board and pay from its annual securities report: "
                "every director with title, role, age, date of birth and shares "
                "held; the officer-category pay table with headcounts and "
                "components; and the individuals whose consolidated pay is "
                "disclosed. English director names are the FILER's own "
                "romanisation from its XBRL, not a translation. "
                + _CONSOLIDATED_WARNING + _COMPONENTS_WARNING +
                "The tagged table is the board (取締役会); in a committee-system "
                "company the filer's own 役員 count also includes executive "
                "officers who are not individually disclosed — officers_untagged "
                "is that gap. Pay-table headcounts count officers PAID during "
                "the year including mid-year leavers, so they differ from board "
                "size legitimately. If pay_consistency_flag is set, the filing's "
                "own pay figures contradict the ¥100m disclosure rule — say so "
                "rather than quoting the number bare. Use search_companies to "
                "find the securities code."),
            "parameters": {
                "type": "object",
                "properties": {
                    "sec_code": {"type": "string",
                                 "description": "4-digit securities code, e.g. '7203'."},
                    "year": {"type": "string",
                             "description": "Fiscal year; omit for the latest filing."},
                },
                "required": ["sec_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_board_history",
            "description": (
                "One company's board and pay across every extracted fiscal year: "
                "board size, average director age, directors aged 70+, female "
                "officers, employees, average salary, pay per officer and the "
                "count and sum of named individuals. Use this for any trend "
                "about one company — comparing a company to itself is the only "
                "sound way to read a change, since coverage differs by year. A "
                "missing year means the filing was not extractable, not that the "
                "company stopped filing."),
            "parameters": {
                "type": "object",
                "properties": {
                    "sec_code": {"type": "string",
                                 "description": "4-digit securities code, e.g. '7203'."},
                },
                "required": ["sec_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_governance_screen",
            "description": (
                "Ranked cross-section of Japanese boards and pay, one filing per "
                "company. metric is one of: oldest_boards, youngest_boards, "
                "no_women, most_female, largest_boards, oldest_directors, "
                "highest_paid_boards, highest_pay_per_officer, "
                "highest_employee_pay, widest_gender_pay_gap. Defaults to listed "
                "companies only. Rows carry pay_consistency_flag where the "
                "filer's own pay figures contradict the ¥100m individual-"
                "disclosure rule — those are filer scale errors, published as "
                "filed; never present a flagged row as the highest-paying "
                "company without saying so."),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string",
                               "description": "Screen name; see the description."},
                    "year": {"type": "string",
                             "description": "Fiscal year; omit for latest filings."},
                    "listed": {"type": "string",
                               "description": ("'true' (default) for listed filers "
                                               "only, 'false' for unlisted, empty "
                                               "for both.")},
                    "limit": {"type": "integer",
                              "description": "Rows to return, 1-200. Default 25."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_paid_officers",
            "description": (
                "The highest-paid individuals named in Japanese annual securities "
                "reports, with their company and whether they sit on its board. "
                + _CONSOLIDATED_WARNING +
                "¥100m is the mandatory disclosure trigger, not a floor — some "
                "filers name officers voluntarily below it "
                "(voluntary_below_100m). Yen amounts are levels as filed; never "
                "rank or combine them with CPI index numbers."),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "string",
                             "description": "Fiscal year; omit for latest filings."},
                    "limit": {"type": "integer",
                              "description": "Rows to return, 1-200. Default 25."},
                },
                "required": [],
            },
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
    {
        "type": "function",
        "function": {
            "name": "get_arrivals",
            "description": (
                "Monthly foreign visitor arrivals to Japan by market, as "
                "published by the Japan National Tourism Organization: the "
                "national total ('total'), six regional totals, and named "
                "markets. Use measure='count' for the published number of "
                "people, 'yoy' for year-over-year growth, or 'recovery' to "
                "index each month against the same month of 2019. Arrivals "
                "are a count of people and must never be ranked against a "
                "price index or a yen level. Call get_arrivals_ranking first "
                "if you need the market codes."),
            "parameters": {
                "type": "object",
                "properties": {
                    "markets": {
                        "type": "string",
                        "description": (
                            "Comma-separated market codes, up to 6, e.g. "
                            "'total' or 'cn,kr,tw'. Defaults to 'total'."),
                    },
                    "measure": {
                        "type": "string",
                        "enum": ["count", "yoy", "recovery"],
                        "description": (
                            "'count' for published arrivals in persons, 'yoy' "
                            "for year-over-year %, 'recovery' for an index "
                            "against the same month of 2019 (= 100)."),
                    },
                    "start": {
                        "type": "string",
                        "description": (
                            "First month as 'YYYY-MM'. Defaults to the most "
                            "recent 36 months. History starts 2003-01."),
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
            "name": "get_arrivals_ranking",
            "description": (
                "Rank the markets sending visitors to Japan — biggest, "
                "fastest-growing, fastest-shrinking, or furthest above or "
                "below their 2019 level. Answers \"which markets are up or "
                "down the most\" and returns the market codes for use with "
                "get_arrivals. All rows are the same month: the latest one "
                "with a complete market breakdown, because a share or a rank "
                "taken on an estimate month would not compare like with "
                "like."),
            "parameters": {
                "type": "object",
                "properties": {
                    "order": {
                        "type": "string",
                        "enum": ["highest", "lowest"],
                        "description": "Sort direction on the chosen metric.",
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["arrivals", "yoy", "share", "recovery"],
                        "description": (
                            "'arrivals' = published count of people; 'yoy' = "
                            "year-over-year %; 'share' = % of the national "
                            "total; 'recovery' = index against the same month "
                            "of 2019 (= 100)."),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum rows to return, up to 60.",
                    },
                    "group": {
                        "type": "string",
                        "enum": ["markets", "regions"],
                        "description": (
                            "'markets' ranks individual markets, 'regions' "
                            "ranks the six regional totals. Never mix them: a "
                            "region is the sum of its markets."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_yield_curve",
            "description": (
                "The Japanese government bond constant-maturity yield curve "
                "on one business day — 15 tenors from 1 to 40 years in "
                "percent per year, as published by the Ministry of Finance — "
                "with the 2s10s and 10s30s spreads calculated from them. "
                "Yields can be genuinely negative."),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "Business day as 'YYYY-MM-DD'. The latest curve "
                            "on or before it is returned. Defaults to the "
                            "latest published day. History starts 1974-09-24."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_boj_balance_sheet",
            "description": (
                "The Bank of Japan's JGB holdings and monthly flows at the "
                "latest published month: the holdings level, its distance "
                "from the November 2023 peak, the trailing net flow (negative "
                "during balance-sheet runoff) and gross purchases. Levels are "
                "yen and must never be ranked against a price index or a "
                "count of people."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]
