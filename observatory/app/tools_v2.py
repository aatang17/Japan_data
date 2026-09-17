# -*- coding: utf-8 -*-
"""Six generic tools over the dataset registry — the MCP v2 surface.

The v1 tools in tools.py are one hand-written function per question per
dataset; every new dataset meant new tools, new names, new instructions. Here
the *dataset* is an argument, resolved through its manifest (registry.py), and
the six tools cover every dataset the registry knows:

    list_datasets      what is published, compactly
    describe_dataset   one dataset's card plus live coverage
    search             companies and series, across datasets, one ranked list
    get_company        one company in one dataset — or, with no dataset, a
                       compact profile across every dataset that knows it
    get_series         a series' history (series-shaped datasets), with as_of
    screen             a ranked cross-section (the dataset's own screens)

Same layer discipline as tools.py: every tool dispatches to the functions
that serve /api/v1, so an assistant can only ever see numbers the public API
publishes, from the same release. Dataset number seventeen needs a manifest
and a row in the dispatch tables below — not a tool.

Every result is the same envelope:

    tool · dataset · data · provenance · calc · vintage · cite · coverage
    (· truncated, when a row budget cut the data)

No-data is a valid answer, never a JSON-RPC error: a company with no rows in a
dataset comes back with `data: null` and a `missing` reason. Unknown dataset
ids and screen sorts answer with the valid list, so a caller can correct
itself in one step.
"""
import datetime
import importlib
import json

from . import api, asof, registry
from .tools import (DEFAULT_MONTHS, POINT_BUDGET, _cite, _fail, _record,
                    _release_of, _trim_points, _window_start, call_api)

# Tool results are an assistant's input tokens. Lists longer than this are
# cut, and the envelope says so and by how much.
ROW_BUDGET = 50
MAX_LIMIT = 100
SEARCH_LIMIT = 25
# Long enough for a US filer written `cik:NNNNNNNNNN`; a Japanese code is 4.
COMPANY_CODE_MAX = 16


def _mod(name):
    return importlib.import_module("." + name, __package__)


def _fmt_date(v):
    return v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def _parse_as_of(as_of):
    """None, a date, or an error string."""
    if not as_of:
        return None, None
    try:
        return datetime.date.fromisoformat(str(as_of)), None
    except ValueError:
        return None, "as_of must be a date, YYYY-MM-DD (got %r)" % as_of


def _detail(exc):
    """The message of an HTTPException or any other failure."""
    detail = getattr(exc, "detail", None)
    return str(detail) if detail else str(exc)


def _status(exc):
    return getattr(exc, "status_code", None)


# ---------------------------------------------------------------------------
# Dispatch — which function answers which capability for which dataset.
#
# Only equity datasets need a table: their read functions are module-specific.
# Every series dataset goes through the generic api.py surface. Each entry is
# a callable taking keyword arguments the tool already validated.
# ---------------------------------------------------------------------------

def _bound(mid, attr):
    return registry.bound(mid, attr)


def _company_fn(mid):
    return _bound(mid, "company")


def _summary_fn(mid):
    return _bound(mid, "summary")


def _search_fn(mid):
    return _bound(mid, "companies")


def _eq(name):
    return _mod(name)


def _screen_cross_shareholdings(sort, f, limit):
    if sort == "reclassified":
        return _eq("equity_api").reclassified(year=f.get("year", ""), limit=limit)
    return _eq("equity_api").unwind(year=f.get("year", ""))


def _screen_register(sort, f, limit):
    return call_api(_eq("ownership_api").screen,
        metric=sort, order=f.get("order", "desc"), year=f.get("year", ""),
        listed=f.get("listed", "true"), min_shareholders=int(f.get("min_shareholders", 0) or 0),
        cohort=str(f.get("cohort", "") or ""), limit=limit)


def _screen_stakes(sort, f, limit):
    return _eq("lvh_api").holders(
        limit=limit, by="entity" if sort == "entity" else "group",
        filer_type=f.get("filer_type", ""), group=f.get("group", ""),
        activist="true" if sort == "activist" or f.get("activist") else "")


def _screen_shorts(sort, f, limit):
    m = _eq("short_api")
    if sort == "holders":
        return m.holders(limit=limit)
    if sort == "recent":
        return call_api(m.recent, limit=limit,
                        min_ratio=float(f.get("min_ratio", 0) or 0),
                        min_change=float(f.get("min_change", 0) or 0),
                        closing=str(f.get("closing", "") or ""))
    return call_api(m.companies, q=f.get("q", ""),
                    sort=str(f.get("sort", "disclosed_pct") or "disclosed_pct"),
                    limit=limit)


def _screen_boards(sort, f, limit):
    return call_api(_eq("governance_api").screen, metric=sort, year=f.get("year", ""),
                    listed=f.get("listed", ""),
                    cohort=str(f.get("cohort", "") or ""), limit=limit)


def _screen_buybacks(sort, f, limit):
    return call_api(_eq("buyback_api").programs,
        lifecycle=f.get("lifecycle", ""), q=f.get("q", ""),
        min_authorised_yen=float(f.get("min_authorised_yen", 0) or 0), sort=sort, limit=limit)


def _screen_facilities(sort, f, limit):
    m = _eq("facility_api")
    if sort.startswith("rental_"):
        return m.rental_ranking(metric=sort[len("rental_"):], year=f.get("year", ""),
                                limit=limit)
    return m.ranking(metric=sort, year=f.get("year", ""), limit=limit)


# `cohort` is handled separately: it is not a financials filter but the shared
# peer-group narrowing every screen takes (app/cohorts.py).
_SCREENER_FILTERS = ("industry", "standard", "min_revenue_yen", "min_assets_yen",
                     "roe_min", "roe_max", "roa_min", "operating_margin_min",
                     "equity_ratio_min", "equity_ratio_max", "revenue_growth_min",
                     "pbr_implied_max", "dividend_yield_min", "cash_to_assets_min")


def _screen_financials(sort, f, limit):
    m = _eq("financials_api")
    if sort.startswith("filed:"):
        return m.screen(metric=sort[len("filed:"):], year=f.get("year", ""), limit=limit)
    kw = dict((k, str(f.get(k, "") or "")) for k in _SCREENER_FILTERS)
    return m.screener(sort=sort, order=f.get("order", "desc"),
                      cohort=str(f.get("cohort", "") or ""),
                      limit=limit, offset=0, **kw)


def _screen_agm(sort, f, limit):
    m = _eq("agm_api")
    if sort == "proposals":
        return m.proposals(category=f.get("category", ""),
                           shareholder="true" if f.get("shareholder") else "",
                           limit=limit, include_unverified="")
    kind = "dismissal" if sort == "dismissal" else "election"
    order = "highest" if sort in ("highest", "dismissal") else "lowest"
    return m.directors(limit=limit, order=order, max_pct=float(f.get("max_pct", 100) or 100),
                       sec_code=str(f.get("sec_code", "") or ""),
                       year=int(f.get("year", 0) or 0), kind=kind, include_unverified="")


def _screen_segments(sort, f, limit):
    m = _eq("segments_api")
    # One payload carries both views: filers ranked by their dependence on a
    # named customer, and customers by how many suppliers name them.
    return m.concentration(min_share=float(f.get("min_share", 0) or 0))


def _screen_sec(sort, f, limit):
    return _eq("sec_api").screen(metric=sort, fy=str(f.get("fy", "") or ""),
                                 order=str(f.get("order", "desc") or "desc"),
                                 unit=str(f.get("unit", "USD") or "USD"), limit=limit)


def _screen_fns():
    return {
        "sec-financials": _screen_sec,
        "segments": _screen_segments,
        "cross-shareholdings": _screen_cross_shareholdings,
        "shareholder-register": _screen_register,
        "large-shareholdings": _screen_stakes,
        "short-positions": _screen_shorts,
        "boards-and-pay": _screen_boards,
        "buybacks": _screen_buybacks,
        "facilities": _screen_facilities,
        "financials": _screen_financials,
        "agm-votes": _screen_agm,
    }


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _provenance(m):
    src = m["source"]
    return {"trust": "official", "publisher": src["publisher"], "credit": src["credit"],
            "document": src["document"], "note": ("Official values are exactly as "
                                                    "published or filed; every calculated "
                                                    "figure is listed under `calc` with its "
                                                    "formula.")}


def _calc(m, only=None):
    out = {}
    for meas in m["measures"]:
        if meas["trust"] == "derived" and (only is None or meas["id"] in only):
            out[meas["id"]] = meas["calc"]
    return out


def _macro_vintage(dataset, as_of):
    con = api._con()
    try:
        rel = api._release(con, dataset, as_of=as_of)
    finally:
        con.close()
    return {"unit": "release", "basis": "release-in-force",
            "as_of": as_of.isoformat() if as_of else None,
            "release_id": rel["release_id"], "label": rel["label"],
            "latest_period": rel["latest_period"],
            "published_at": _fmt_date(rel["ingested_at"]),
            "source_sha256": rel["sha256"]}, rel


def _equity_vintage(as_of):
    return asof.vintage()


def _cite_for(m, **params):
    path = m["cite"]
    for k, v in params.items():
        path = path.replace("{%s}" % k, str(v))
        if k == "sec_code":                 # the US shelf keys on a CIK
            path = path.replace("{cik}", str(v).split(":")[-1])
    return _cite(path)


def _budget(data, limit):
    """Cut every top-level list to `limit` rows; report what was cut."""
    truncated = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and len(v) > limit:
                truncated[k] = {"returned": limit, "total": len(v)}
                data[k] = v[:limit]
    return truncated


def _envelope(tool, m, data, calc=None, vintage=None, cite=None, coverage=None,
              truncated=None, missing=None, **extra):
    out = {"tool": tool, "dataset": m["id"], "section": m["section"],
           "shape": m["shape"], "data": data,
           "provenance": _provenance(m),
           "calc": calc if calc is not None else _calc(m),
           "vintage": vintage, "cite": cite or _cite_for(m),
           "coverage": coverage}
    if truncated:
        out["truncated"] = truncated
    if missing:
        out["missing"] = missing
    out.update(extra)
    return out


def _unknown_dataset(dataset):
    return _fail("Unknown dataset %r. Valid ids: %s" % (dataset, ", ".join(registry.ids())))


def _manifest_or_fail(dataset):
    m = registry.get(dataset)
    if m is None:
        return None, _unknown_dataset(dataset)
    return m, None


def _unavailable(m):
    return _fail("The %s dataset is not published on this server yet." % m["id"])


# ---------------------------------------------------------------------------
# The six tools
# ---------------------------------------------------------------------------

def _compact_row(m):
    row = {"id": m["id"], "section": m["section"], "name": m["name"]["en"],
           "name_ja": m["name"]["ja"], "shape": m["shape"], "summary": m["summary"],
           "frequency": m["frequency"], "capabilities": m["capabilities"],
           "available": m.get("available", registry.available(m["id"])),
           "history_from": m["vintage"]["history_from"],
           "as_of_supported": m["vintage"]["as_of_supported"],
           "screens": [s["id"] for s in m.get("screens", [])]}
    if m["shape"] == "series" and row["available"]:
        try:
            row["latest_period"] = _release_of(m["id"])["latest_period"]
        except Exception:  # noqa: BLE001 — coverage is a convenience, not a gate
            pass
    return row


def list_datasets(section=""):
    """Every published dataset, compactly — ids, shapes, capabilities, coverage."""
    _record("list_datasets", {"section": section or None})
    section = (section or "").strip()
    if section and section not in registry.SECTION_IDS:
        return _fail("Unknown section %r. Valid sections: %s"
                     % (section, ", ".join(registry.SECTION_IDS)))
    rows = [_compact_row(m) for m in registry.datasets()
            if not section or m["section"] == section]
    return _dumps({"tool": "list_datasets", "count": len(rows),
                   "sections": registry.by_section() if not section else section,
                   "datasets": rows, "cite": _cite("/")})


def _scalars(d):
    return dict((k, _fmt_date(v)) for k, v in d.items()
                if not isinstance(v, (list, dict)) and not k.endswith("_note"))


def describe_dataset(dataset):
    """One dataset's manifest — source, measures, formulas, endpoints — plus
    what this server actually holds of it."""
    _record("describe_dataset", {"dataset": dataset})
    m, err = _manifest_or_fail(dataset)
    if err:
        return err
    m["available"] = registry.available(dataset)
    coverage = None
    if m["available"]:
        try:
            if m["shape"] == "series":
                rel = _release_of(dataset)
                coverage = {"from": rel.get("coverage_start"), "to": rel["latest_period"],
                            "release": rel["label"], "published_at": _fmt_date(rel["ingested_at"])}
            else:
                fn = _summary_fn(dataset) or _bound(dataset, "coverage")
                coverage = _scalars(call_api(fn)) if fn else None
        except Exception as exc:  # noqa: BLE001 — the card still describes the dataset
            coverage = {"error": _detail(exc)}
    m["coverage"] = coverage
    m["tools"] = {
        "get_series": m["shape"] == "series",
        "get_company": "company" in m["capabilities"],
        "screen": "screen" in m["capabilities"],
        "search": "search" in m["capabilities"] or m["shape"] == "series",
    }
    m["cite"] = _cite_for(m)
    return _dumps(m)


def _series_hits(dataset, needle, limit):
    con = api._con()
    try:
        smap = api._series_map(con, dataset)
    finally:
        con.close()
    needle = needle.lower()
    hits = []
    for s in smap:
        exact = needle == s["code"].lower()
        if exact or needle in (s["name_en"] or "").lower() or needle in (s["name_ja"] or "").lower():
            hits.append({"kind": "series", "dataset": dataset, "code": s["code"],
                         "name_en": s["name_en"], "name_ja": s["name_ja"],
                         "unit": s.get("unit"), "exact": exact})
        if len(hits) >= limit * 4:
            break
    hits.sort(key=lambda h: (not h["exact"], h["name_en"] or ""))
    for h in hits:
        h.pop("exact", None)
    return hits[:limit]


def _company_hits(dataset, needle, limit):
    fn = _search_fn(dataset)
    if fn is None:
        return []
    raw = call_api(fn, q=needle)
    out = []
    for c in raw.get("companies", [])[:limit]:
        out.append({"kind": "company", "dataset": dataset,
                    "sec_code": c.get("sec_code"),
                    "name": c.get("name") or c.get("filer_name"),
                    "name_en": c.get("name_en") or c.get("filer_name_en")})
    return out


def search(query, dataset="", limit=SEARCH_LIMIT):
    """Find companies (by name or securities code) and series (by name or
    code) across datasets — one ranked list, each hit saying where it lives."""
    args = {"query": query, "dataset": dataset or None, "limit": limit}
    _record("search", args)
    needle = (query or "").strip()
    if not needle:
        return _fail("Give a query: a company name, a securities code, or a series name.")
    limit = max(1, min(int(limit or SEARCH_LIMIT), MAX_LIMIT))
    targets = registry.ids()
    if dataset:
        m, err = _manifest_or_fail(dataset)
        if err:
            return err
        targets = [dataset]
    companies = {}
    series = []
    failed = []
    for mid in targets:
        m = registry.get(mid)
        if not registry.available(mid):
            continue
        try:
            if m["shape"] == "series":
                series.extend(_series_hits(mid, needle, limit))
            elif "search" in m["capabilities"]:
                for h in _company_hits(mid, needle, limit):
                    key = h["sec_code"] or h["name"]
                    row = companies.setdefault(key, {
                        "kind": "company", "sec_code": h["sec_code"], "name": h["name"],
                        "name_en": h["name_en"], "datasets": []})
                    row["datasets"].append(mid)
                    if not row["name_en"] and h["name_en"]:
                        row["name_en"] = h["name_en"]
        except Exception as exc:  # noqa: BLE001 — one dataset failing must not empty the list
            failed.append({"dataset": mid, "error": _detail(exc)})
    rows = sorted(companies.values(),
                  key=lambda r: (needle != (r["sec_code"] or ""), -len(r["datasets"]),
                                 r["name"] or ""))
    company_rows = rows[:limit]
    series_rows = series[:limit]
    return _dumps({"tool": "search", "query": needle,
                   "companies": company_rows, "series": series_rows,
                   "count": {"companies": len(rows), "series": len(series)},
                   "truncated": len(rows) > limit or len(series) > limit,
                   "failed": failed or None,
                   "note": ("A company hit lists every dataset that knows it; pass one of "
                            "those ids to get_company. A series hit gives the code for "
                            "get_series."),
                   "cite": _cite("/")})


def _company_block(m, code, as_of, tool):
    """One dataset's answer for one company, as an envelope — or a missing block."""
    fn = _company_fn(m["id"])
    if fn is None:
        return None, "no company view"
    try:
        raw = call_api(fn, sec_code=code)
    except Exception as exc:  # noqa: BLE001
        status = _status(exc)
        if status == 404:
            return None, _detail(exc)
        if status == 503:
            return None, "not published on this server"
        raise
    return raw, None


def _compact(raw):
    """Facts only: scalars, plus how many rows each table has."""
    facts = _scalars(raw)
    tables = dict((k, len(v)) for k, v in raw.items() if isinstance(v, list))
    for k, v in raw.items():
        if isinstance(v, dict) and k not in ("calc", "provenance"):
            for kk, vv in v.items():
                if not isinstance(vv, (list, dict)):
                    facts["%s.%s" % (k, kk)] = _fmt_date(vv)
    return {"facts": facts, "tables": tables}


def get_company(code, dataset="", as_of="", limit=ROW_BUDGET):
    """One company. With a dataset: that dataset's full company view. Without:
    a compact profile from every dataset that knows the company, with a
    coverage matrix of which do and which do not."""
    args = {"code": code, "dataset": dataset or None, "as_of": as_of or None}
    _record("get_company", args)
    code = (code or "").strip()
    if not code or len(code) > COMPANY_CODE_MAX:
        return _fail("Give a securities code (e.g. 7974). Use search to find one.")
    p_as_of, err = _parse_as_of(as_of)
    if err:
        return _fail(err)
    limit = max(1, min(int(limit or ROW_BUDGET), MAX_LIMIT))

    if dataset:
        m, err = _manifest_or_fail(dataset)
        if err:
            return err
        if "company" not in m["capabilities"]:
            return _fail("%s has no company view; datasets with one: %s"
                         % (dataset, ", ".join(i for i in registry.ids()
                                               if "company" in registry.get(i)["capabilities"])))
        if not registry.available(dataset):
            return _unavailable(m)
        with asof.scope(p_as_of):
            raw, missing = _company_block(m, code, p_as_of, "get_company")
        if missing:
            return _dumps(_envelope("get_company", m, None, vintage=_equity_vintage(p_as_of),
                                    cite=_cite_for(m, sec_code=code), missing=missing,
                                    code=code))
        truncated = _budget(raw, limit)
        return _dumps(_envelope("get_company", m, raw, vintage=_equity_vintage(p_as_of),
                                cite=_cite_for(m, sec_code=code), truncated=truncated,
                                code=code))

    # Composed: the same document /api/v1/company/{code} serves, in its
    # compact form. One implementation, so the tool and the endpoint can never
    # disagree about what a company looks like.
    from . import company_api
    try:
        doc = company_api.compose(code, compact=True, as_of=p_as_of)
    except Exception as exc:  # noqa: BLE001
        return _fail(_detail(exc))
    doc["tool"] = "get_company"
    doc["cite"] = _cite(doc["cite"])
    for block in doc["datasets"].values():
        block["cite"] = _cite(block["cite"])
    return _dumps(doc)


def get_series(dataset, series, measure="index", start="", end="", as_of="",
               months=DEFAULT_MONTHS):
    """History for up to six series of a series-shaped dataset, as the
    published value or a rate of change, optionally as it stood on a date."""
    args = {"dataset": dataset, "series": series, "measure": measure,
            "start": start or None, "end": end or None, "as_of": as_of or None}
    m, err = _manifest_or_fail(dataset)
    if err:
        _record("get_series", args, note="unknown dataset")
        return err
    if m["shape"] != "series":
        _record("get_series", args, note="not a series dataset")
        return _fail("%s is %s-shaped; use get_company or screen. Series datasets: %s"
                     % (dataset, m["shape"],
                        ", ".join(i for i in registry.ids()
                                  if registry.get(i)["shape"] == "series")))
    if not registry.available(dataset):
        return _unavailable(m)
    codes = ",".join([c.strip() for c in (series or "").split(",") if c.strip()][:6])
    if not codes:
        return _fail("Give one to six series codes, comma-separated. Use search to find them.")
    measure = (measure or "index").strip()
    known = [x["id"] for x in m["measures"] if x["id"] in registry.GENERIC_MEASURES]
    if measure not in known:
        return _fail("Unknown measure %r for %s; one of %s" % (measure, dataset, ", ".join(known)))
    p_as_of, err = _parse_as_of(as_of)
    if err:
        return _fail(err)
    try:
        vintage, rel = _macro_vintage(dataset, p_as_of)
        from_month = start or _window_start(rel, int(months or DEFAULT_MONTHS))
        raw = call_api(api.observations, dataset=dataset, series=codes,
                       measure=measure, start=from_month, end=end or None,
                       as_of=p_as_of.isoformat() if p_as_of else None)
    except Exception as exc:  # noqa: BLE001
        _record("get_series", args, note="failed")
        return _fail(_detail(exc))
    dp = 4 if measure == "index" else 2
    out = [{"code": s["code"], "name_en": s["name_en"], "name_ja": s["name_ja"],
            "points": [[p, None if v is None else round(v, dp)] for p, v in s["points"]]}
           for s in raw["series"]]
    cut = _trim_points(out, POINT_BUDGET)
    _record("get_series", args, rel, note="%s, from %s" % (measure, from_month))
    trust = "official" if measure == "index" else "derived"
    return _dumps(_envelope(
        "get_series", m,
        {"measure": measure, "unit": raw["unit"], "trust": trust,
         "from": from_month, "to": end or rel["latest_period"], "series": out},
        calc={measure: raw["calc"]}, vintage=vintage,
        # The dataset's own page, from its manifest — /explorer.html was
        # hardcoded here and only ever knew the CPI item tables, so every
        # other series dataset cited a page that cannot render it.
        cite=_cite_for(m, dataset=dataset) if m.get("cite") else _cite("/"),
        coverage={"from": rel.get("coverage_start"), "to": rel["latest_period"]},
        truncated={"points": "trimmed to the most recent %d" % POINT_BUDGET} if cut else None))


def screen(dataset, sort="", filters=None, limit=ROW_BUDGET, as_of=""):
    """A ranked cross-section from one dataset's own screens — validated
    against the sorts its manifest declares."""
    args = {"dataset": dataset, "sort": sort or None, "filters": filters or None,
            "limit": limit, "as_of": as_of or None}
    _record("screen", args)
    m, err = _manifest_or_fail(dataset)
    if err:
        return err
    # A series dataset has no hand-written screens; it is ranked on the
    # numeric columns its own series listing publishes.
    if m["shape"] == "series":
        if not registry.available(dataset):
            return _unavailable(m)
        return _screen_series(m, dataset, sort, filters, limit)
    screens = m.get("screens", [])
    if "screen" not in m["capabilities"] or not screens:
        return _fail("%s has no screens; datasets with screens: %s"
                     % (dataset, ", ".join(i for i in registry.ids()
                                           if registry.get(i).get("screens"))))
    if not registry.available(dataset):
        return _unavailable(m)
    valid = [s["id"] for s in screens]
    sort = (sort or "").strip() or valid[0]
    if sort not in valid:
        return _fail("Unknown sort %r for %s. Valid sorts: %s"
                     % (sort, dataset, "; ".join("%s (%s)" % (s["id"], s["title"])
                                                 for s in screens)))
    if filters is not None and not isinstance(filters, dict):
        return _fail("filters must be an object of field → value.")
    p_as_of, err = _parse_as_of(as_of)
    if err:
        return _fail(err)
    limit = max(1, min(int(limit or ROW_BUDGET), MAX_LIMIT))
    fn = _screen_fns().get(dataset)
    if fn is None:
        return _fail("%s declares screens but none are bound yet." % dataset)
    try:
        with asof.scope(p_as_of):
            raw = fn(sort, filters or {}, limit)
    except Exception as exc:  # noqa: BLE001
        if _status(exc) == 503:
            return _unavailable(m)
        return _fail(_detail(exc))
    truncated = _budget(raw, limit)
    title = next(s["title"] for s in screens if s["id"] == sort)
    return _dumps(_envelope("screen", m, raw, vintage=_equity_vintage(p_as_of),
                            truncated=truncated, sort=sort, title=title,
                            filters=filters or {}))


# ---------------------------------------------------------------------------
# Cohorts — the seventh tool, and the only one that is not per-dataset
# ---------------------------------------------------------------------------
# A cohort is a peer group, not a dataset: the same TOPIX band or basket of
# codes narrows the financials screener, the board screen and the register
# screen alike. `screen` already takes it as filters.cohort. This adds the one
# thing the six generic tools cannot express — the shape of a cohort's
# distribution, which is what turns a company's number into a position.

def list_cohorts(as_of=""):
    """Every peer group that can be compared within, with member counts."""
    _record("list_cohorts", {"as_of": as_of or None})
    m = registry.get("financials") or {}
    try:
        raw = call_api(_mod("cohorts_api").catalogue, as_of=as_of or "")
    except Exception as exc:  # noqa: BLE001
        return _fail(_detail(exc))
    return _dumps({
        "tool": "list_cohorts",
        "data": raw,
        "how": ("Pass any `spec` as filters.cohort on `screen`, or as `cohort` on "
                "compare_cohort. A basket is a cohort too: codes:7203,6758,…"),
        "cite": "/cohorts.html",
    })


def compare_cohort(cohort, metric="roe_pct", highlight="", order="desc",
                   limit=ROW_BUDGET, as_of=""):
    """One metric across one peer group: every member ranked, with the
    cohort's own quartiles, and a named company's percentile within it."""
    _record("compare_cohort", {"cohort": cohort, "metric": metric,
                               "highlight": highlight or None, "order": order,
                               "limit": limit, "as_of": as_of or None})
    limit = max(1, min(int(limit or ROW_BUDGET), MAX_LIMIT))
    try:
        raw = call_api(_mod("cohorts_api").compare, cohort=cohort, metric=metric,
                       highlight=highlight or "", order=order or "desc",
                       limit=limit, as_of=as_of or "")
    except Exception as exc:  # noqa: BLE001
        return _fail(_detail(exc))
    return _dumps({
        "tool": "compare_cohort",
        "data": raw,
        "calc": raw.get("calc"),
        "provenance": raw.get("provenance"),
        "cite": "/cohorts.html?cohort=%s&metric=%s%s" % (
            cohort, metric, ("&c=" + highlight) if highlight else ""),
    })


# ---------------------------------------------------------------------------
# Registry of tools, and their MCP descriptors
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Vintages, the headline reading, and the cuts a dataset serves beyond series
# ---------------------------------------------------------------------------

# PRESENTATION key that gates the surface -> (api function name, selector
# argument, one line saying what the cut answers). These are the endpoints
# under /api/v1/{dataset}/ that are not /observations: each is one dataset
# family's own extra cut of the same release, and each had no tool at all
# before — an assistant could read a trade dataset's series one code at a
# time but could not ask for a commodity's partner breakdown, which is the
# question the dataset exists to answer.
BREAKDOWNS = {
    "groups_ja": ("contributions", None,
                  "each major group's contribution, in percentage points, to the "
                  "headline year-on-year rate"),
    "breadth": ("breadth", None,
                "how widely prices are rising: the share of individually priced "
                "items above and below a year-on-year threshold"),
    "curve": ("curve", None,
              "the whole published yield curve — every date by every maturity"),
    "arrivals": ("arrivals", None,
                 "arrivals by market with the hierarchy that relates them"),
    "trade": ("trade", "commodity",
              "one commodity's trade with every partner country, plus world "
              "totals for every commodity"),
    "accommodation": ("accommodation", "area",
                      "one area's guest nights and occupancy in full, with the "
                      "backbone for all 58 areas"),
    "prefectures": ("prefectures", "prefecture",
                    "every prefecture by every measure and period, with the "
                    "geography a map needs"),
}
# Arguments a caller may pass through to a cut, by the api function that takes
# them. Anything else is refused by name rather than silently dropped.
_BREAKDOWN_ARGS = {
    "contributions": ("start", "end"),
    "breadth": ("threshold",),
    "curve": (),
    "arrivals": (),
    "trade": ("flow", "commodity"),
    "accommodation": ("area",),
    "prefectures": ("prefecture",),
}


def _breakdowns_for(dataset):
    """[(cut id, api function, what it answers)] the dataset actually serves."""
    adapter = api.ADAPTERS.get(dataset)
    if adapter is None:
        return []
    pres = adapter.PRESENTATION
    out = []
    for key, (fn, _sel, what) in BREAKDOWNS.items():
        if not pres.get(key):
            continue
        # Contributions need the headline as well as the groups.
        if fn == "contributions" and not pres.get("main_series"):
            continue
        out.append((fn, fn, what))
    return out


def get_vintages(dataset, series="", period=""):
    """The release history of a dataset, or how one series has been revised.

    The point-in-time store is the platform's reason to exist and it was the
    one thing the tool surface could not reach: `as_of` on get_series reads
    the data as it stood, but nothing could say which vintages exist or what
    changed between them — while every dataset card advertised /releases and
    /revisions as endpoints.
    """
    args = {"dataset": dataset, "series": series or None, "period": period or None}
    _record("get_vintages", args)
    m, err = _manifest_or_fail(dataset)
    if err:
        return err
    if not registry.available(dataset):
        return _unavailable(m)
    try:
        if series:
            raw = call_api(api.revisions, dataset=dataset, series=series.strip(),
                           period=period or None)
            data = {"mode": "revisions", "series": series.strip(),
                    "period": period or None, "revisions": raw}
            calc = raw.get("calc") if isinstance(raw, dict) else None
        else:
            raw = call_api(api.releases, dataset=dataset)
            rows = raw["releases"] if isinstance(raw, dict) and "releases" in raw else raw
            cut = _budget(rows, ROW_BUDGET)
            data = {"mode": "releases", "count": len(rows), "releases": rows}
            calc = None
    except Exception as exc:  # noqa: BLE001
        _record("get_vintages", args, note="failed")
        return _fail(_detail(exc))
    return _dumps(_envelope(
        "get_vintages", m, data,
        calc=calc if calc else {"releases": "Accepted releases as recorded at ingest, "
                                            "newest first. Not computed."},
        cite=_cite_for(m, dataset=dataset) if m.get("cite") else None))


def get_overview(dataset):
    """A dataset's headline reading — the tiles its own page leads with.

    The v1 tool of this name served cpi-jp alone; every other series dataset
    had no way to ask 'what is the current reading' short of pulling raw
    series and doing the arithmetic. This dispatches to the same function
    that serves /api/v1/{dataset}/overview, so it covers whichever shape the
    dataset is — index tiles or published levels.
    """
    args = {"dataset": dataset}
    _record("get_overview", args)
    m, err = _manifest_or_fail(dataset)
    if err:
        return err
    if m["shape"] != "series":
        return _fail("%s is a %s dataset; get_overview is for series datasets. "
                     "Use get_company or screen." % (dataset, m["shape"]))
    if not registry.available(dataset):
        return _unavailable(m)
    try:
        raw = call_api(api.overview, dataset=dataset)
    except Exception as exc:  # noqa: BLE001
        _record("get_overview", args, note="failed")
        return _fail(_detail(exc))
    rel = raw.get("release") or {}
    _record("get_overview", args, rel)
    data = dict((k, v) for k, v in raw.items() if k not in ("release", "dataset"))
    return _dumps(_envelope(
        "get_overview", m, data,
        calc=raw.get("calc") or _calc(m),
        vintage={"unit": "release", "basis": "release-in-force", "as_of": None,
                 "release_id": rel.get("release_id"), "label": rel.get("label"),
                 "latest_period": rel.get("latest_period"),
                 "published_at": rel.get("ingested_at"),
                 "source_sha256": rel.get("sha256")},
        cite=_cite_for(m, dataset=dataset) if m.get("cite") else None,
        coverage={"from": rel.get("coverage_start"), "to": rel.get("latest_period")}))


def get_breakdown(dataset, cut="", **params):
    """One of the dataset's own cuts: contributions, breadth, the curve,
    arrivals, a commodity's partners, an area's guest nights, the prefectures.

    With no `cut`, answers with the ones this dataset serves rather than
    failing, so a caller can correct itself in one step.
    """
    args = dict({"dataset": dataset, "cut": cut or None}, **params)
    _record("get_breakdown", args)
    m, err = _manifest_or_fail(dataset)
    if err:
        return err
    available = _breakdowns_for(dataset)
    if not available:
        return _fail("%s serves no breakdown beyond its series; use get_series." % dataset)
    names = [c for c, _fn, _w in available]
    if not cut:
        return _dumps({"tool": "get_breakdown", "dataset": dataset,
                       "cuts": [{"cut": c, "answers": w} for c, _fn, w in available],
                       "note": "Pass one of these as `cut`."})
    if cut not in names:
        return _fail("%s has no %r breakdown; it serves: %s"
                     % (dataset, cut, ", ".join(names)))
    if not registry.available(dataset):
        return _unavailable(m)
    allowed = _BREAKDOWN_ARGS.get(cut, ())
    extra = [k for k in params if k not in allowed]
    if extra:
        return _fail("%r takes %s; got %s"
                     % (cut, ", ".join(allowed) or "no arguments", ", ".join(sorted(extra))))
    kwargs = dict((k, v) for k, v in params.items() if v not in ("", None))
    try:
        raw = call_api(getattr(api, cut), dataset=dataset, **kwargs)
    except Exception as exc:  # noqa: BLE001
        _record("get_breakdown", args, note="failed")
        return _fail(_detail(exc))
    rel = raw.get("release") if isinstance(raw, dict) else None
    data = dict((k, v) for k, v in raw.items()
                if k not in ("release", "dataset")) if isinstance(raw, dict) else raw
    _record("get_breakdown", args, rel or {})
    return _dumps(_envelope(
        "get_breakdown", m, dict(data, cut=cut) if isinstance(data, dict) else data,
        calc=(raw.get("calc") if isinstance(raw, dict) else None) or _calc(m),
        vintage={"unit": "release", "basis": "release-in-force", "as_of": None,
                 "release_id": (rel or {}).get("release_id"),
                 "label": (rel or {}).get("label"),
                 "latest_period": (rel or {}).get("latest_period"),
                 "published_at": (rel or {}).get("ingested_at"),
                 "source_sha256": (rel or {}).get("sha256")} if rel else None,
        cite=_cite_for(m, dataset=dataset) if m.get("cite") else None))


# Numeric columns a series listing carries, and so the sorts a series-shaped
# dataset can be ranked on. Which exist depends on the dataset's shape; the
# tool reports the ones actually present rather than guessing.
SERIES_SORTS = ("latest", "delta_1m", "delta_12m", "avg_12m", "sum_12m",
                "yoy", "mom", "ann3m", "weight")


def _screen_series(m, dataset, sort, filters, limit):
    """Rank every series in a series dataset by one of its own columns.

    `screen` covered the ten company and events datasets only, so 'which
    prefecture has the worst real balance' or 'which item is rising fastest'
    had no tool — the caller had to pull series one batch at a time and sort
    them itself, which is both slow and a place to get the arithmetic wrong.
    This ranks the same listing /api/v1/{dataset}/series publishes.
    """
    q = str((filters or {}).get("q") or "")
    order = str((filters or {}).get("order") or "desc").lower()
    if order not in ("desc", "asc"):
        return _fail("order must be desc or asc.")
    try:
        raw = call_api(api.series_list, dataset=dataset, q=q)
    except Exception as exc:  # noqa: BLE001
        return _fail(_detail(exc))
    rows = raw.get("series", [])
    present = [c for c in SERIES_SORTS
               if any(isinstance(r.get(c), (int, float)) for r in rows)]
    if not present:
        return _fail("%s publishes no numeric column to rank on." % dataset)
    sort = (sort or present[0]).strip()
    if sort not in present:
        return _fail("Unknown sort %r for %s; one of %s"
                     % (sort, dataset, ", ".join(present)))
    ranked = [r for r in rows if isinstance(r.get(sort), (int, float))]
    skipped = len(rows) - len(ranked)
    ranked.sort(key=lambda r: r[sort], reverse=(order == "desc"))
    limit = max(1, min(int(limit or ROW_BUDGET), MAX_LIMIT))
    out = ranked[:limit]
    keep = ("code", "name_en", "name_ja", "unit", "kind", "as_of", "discontinued")
    data = {"sort": sort, "order": order, "ranked_on": present,
            "count": len(ranked),
            "not_ranked": skipped or None,
            "rows": [dict([(k, r.get(k)) for k in keep if r.get(k) is not None],
                          **{sort: r[sort]}) for r in out]}
    rel = raw.get("release") or {}
    _record("screen", {"dataset": dataset, "sort": sort, "limit": limit}, rel)
    return _dumps(_envelope(
        "screen", m, data,
        calc=raw.get("calc") or _calc(m),
        vintage={"unit": "release", "basis": "release-in-force", "as_of": None,
                 "release_id": rel.get("release_id"), "label": rel.get("label"),
                 "latest_period": rel.get("latest_period"),
                 "published_at": rel.get("ingested_at"),
                 "source_sha256": rel.get("sha256")},
        cite=_cite_for(m, dataset=dataset) if m.get("cite") else None,
        truncated={"rows": "showing %d of %d" % (len(out), len(ranked))}
        if len(ranked) > len(out) else None,
        missing={"not_ranked": "%d series publish no %s and are excluded, never "
                               "counted as zero" % (skipped, sort)} if skipped else None))


IMPLS = {
    "list_cohorts": list_cohorts,
    "compare_cohort": compare_cohort,
    "list_datasets": list_datasets,
    "describe_dataset": describe_dataset,
    "search": search,
    "get_company": get_company,
    "get_series": get_series,
    "get_overview": get_overview,
    "get_breakdown": get_breakdown,
    "get_vintages": get_vintages,
    "screen": screen,
}


def run_tool(name, args):
    """Run one tool with a dict of arguments; never raises. Same contract as
    tools.run_tool: (text, is_error)."""
    impl = IMPLS.get(name)
    if impl is None:
        return _fail("Unknown tool '%s'." % name), True
    if not isinstance(args, dict):
        return _fail("Arguments for '%s' must be an object." % name), True
    try:
        text = impl(**args)
    except TypeError as exc:  # unexpected or missing argument names
        return _fail(str(exc)), True
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not raised
        return _fail(_detail(exc)), True
    return text, text.startswith('{"error":')


def _cohort_metric_ids():
    """Metric ids for the tool schema, read from the one registry that has them."""
    try:
        return [m[0] for m in _mod("cohorts_api").METRICS]
    except Exception:  # noqa: BLE001 — a schema is not worth failing tools/list over
        return []


def _str(desc, **extra):
    d = {"type": "string", "description": desc}
    d.update(extra)
    return d


def descriptors():
    """MCP tool descriptors, with enums drawn from the live registry so the
    assistant sees the real dataset ids."""
    # Only what this deployment can actually serve. A dataset whose manifest
    # is registered but which has no data here (the US shelf, when the SEC
    # quarter files are not on the volume) used to sit in every enum and
    # answer "not published on this server yet" — advertising a capability
    # the server does not have is worse than not advertising it.
    ids = [i for i in registry.ids() if registry.available(i)]
    series_ids = [i for i in ids if registry.get(i)["shape"] == "series"]
    company_ids = [i for i in ids if "company" in registry.get(i)["capabilities"]]
    screen_ids = [i for i in ids
                  if registry.get(i).get("screens")
                  or registry.get(i)["shape"] == "series"]
    overview_ids = [i for i in series_ids
                    if (api.ADAPTERS.get(i) and
                        (api.ADAPTERS[i].PRESENTATION.get("overview_tiles")
                         or api.ADAPTERS[i].PRESENTATION.get("main_series")))]
    breakdown_ids = [i for i in series_ids if _breakdowns_for(i)]
    all_cuts = sorted(set(c for i in breakdown_ids for c, _f, _w in _breakdowns_for(i)))
    ro = {"readOnlyHint": True, "openWorldHint": False}
    return [
        {"name": "list_datasets", "title": "List datasets",
         "description": ("Every dataset this server publishes, compactly: id, section, "
                         "shape (series / company / events), what it covers, which tools "
                         "apply, and its screens. Call this first when unsure which "
                         "dataset holds what a question needs."),
         "inputSchema": {"type": "object", "properties": {
             "section": _str("Restrict to one section.", enum=registry.SECTION_IDS)},
             "required": []},
         "annotations": ro},
        {"name": "describe_dataset", "title": "Describe a dataset",
         "description": ("One dataset's full card: source and credit line, every measure "
                         "with its trust label and — for calculated ones — its formula, "
                         "the endpoints, screens, notes an analyst must know, and what "
                         "this server holds of it."),
         "inputSchema": {"type": "object", "properties": {
             "dataset": _str("Dataset id.", enum=ids)}, "required": ["dataset"]},
         "annotations": ro},
        {"name": "search", "title": "Search companies and series",
         "description": ("Find a company by name (Japanese or English) or securities code, "
                         "or a data series by name or code, across every dataset. Each "
                         "company hit lists the datasets that know it; each series hit "
                         "gives the code get_series needs."),
         "inputSchema": {"type": "object", "properties": {
             "query": _str("Company name, securities code, or series name/code."),
             "dataset": _str("Restrict to one dataset.", enum=ids),
             "limit": {"type": "integer", "description": "Max hits per kind (up to 100)."}},
             "required": ["query"]},
         "annotations": ro},
        {"name": "get_company", "title": "Get a company",
         "description": ("One company by securities code. With `dataset`, the full company "
                         "view from that dataset (holdings, register, board and pay, "
                         "buybacks, facilities, financials, AGM votes…). Without it, a "
                         "compact profile across every dataset that knows the company, "
                         "with a coverage list of which do not — use that to decide which "
                         "dataset to open next."),
         "inputSchema": {"type": "object", "properties": {
             "code": _str("Securities code, e.g. 7974."),
             "dataset": _str("Dataset id for the full view.", enum=company_ids),
             "as_of": _str("YYYY-MM-DD: the filings that existed on EDINET by "
                           "that date. Applies to the whole answer or none of it."),
             "limit": {"type": "integer",
                       "description": "Rows per table in the full view (default 50, max 100)."}},
             "required": ["code"]},
         "annotations": ro},
        {"name": "get_series", "title": "Get series history",
         "description": ("History for up to six series of a series-shaped dataset (prices, "
                         "BOJ, yields, arrivals, population, trade) as the published value "
                         "(measure=index) or a calculated rate (yoy, mom, ann3m where the "
                         "dataset serves them). `as_of` returns the data as it stood on "
                         "that date, from the vintage history."),
         "inputSchema": {"type": "object", "properties": {
             "dataset": _str("Series dataset id.", enum=series_ids),
             "series": _str("One to six series codes, comma-separated (from search)."),
             "measure": _str("index (published value) or a rate the dataset serves.",
                             enum=list(registry.GENERIC_MEASURES)),
             "start": _str("YYYY-MM inclusive; default the last 36 months."),
             "end": _str("YYYY-MM inclusive."),
             "as_of": _str("YYYY-MM-DD: the data as published on that date."),
             "months": {"type": "integer", "description": "Window when start is empty."}},
             "required": ["dataset", "series"]},
         "annotations": ro},
        {"name": "screen", "title": "Ranked screen",
         "description": ("A ranked cross-section from a dataset's own screens — e.g. "
                         "oldest boards, largest unspent buybacks, cheapest land per m², "
                         "lowest director approval, highest ROE. For a SERIES dataset "
                         "it ranks every series on one of its own columns instead — "
                         "which prefecture settled the worst balance, which item is "
                         "rising fastest — with filters.q to narrow the list and "
                         "filters.order for direction. Sorts are the ids in "
                         "describe_dataset's `screens`; an unknown sort answers with the "
                         "valid ones. `filters` are the dataset's own query fields "
                         "(year, listed, order, industry, lifecycle, min_shareholders…)."),
         "inputSchema": {"type": "object", "properties": {
             "dataset": _str("Dataset id with screens, or any series dataset.",
                             enum=screen_ids),
             "sort": _str("Screen id from describe_dataset, or for a series "
                          "dataset a column: latest, delta_12m, yoy, sum_12m…; "
                          "default the first."),
             "filters": {"type": "object", "description": "Field → value filters."},
             "limit": {"type": "integer", "description": "Rows (default 50, max 100)."},
             "as_of": _str("YYYY-MM-DD: the filings that existed on EDINET by that date.")},
             "required": ["dataset"]},
         "annotations": ro},
        {"name": "list_cohorts", "title": "List peer groups",
         "description": ("The peer groups a company can be compared within: the TOPIX "
                         "scale bands (Core30, Large70, Mid400, Small 1/2), JPX market "
                         "segments (Prime, Standard, Growth), the 33- and 17-industry "
                         "classifications, and — where the deployment is entitled to it "
                         "— index membership. Each comes back with a `spec` string you "
                         "pass to compare_cohort or to screen's filters.cohort."),
         "inputSchema": {"type": "object", "properties": {
             "as_of": _str("YYYY-MM-DD: the classification as it stood then.")},
             "required": []},
         "annotations": ro},
        {"name": "compare_cohort", "title": "Compare within a peer group",
         "description": ("One metric across one peer group, ranked, with the group's own "
                         "median and quartiles — the answer to 'is this normal for a "
                         "company like this?'. `cohort` is a spec from list_cohorts "
                         "(size:core30, ind33:3650, segment:prime, index:nk225) or a "
                         "basket you define: codes:7203,6758,9984. `highlight` returns "
                         "one company's rank and percentile inside the group. Companies "
                         "that do not report the metric are excluded from the ranking "
                         "and listed with the reason — never counted as zero."),
         "inputSchema": {"type": "object", "properties": {
             "cohort": _str("Cohort spec, e.g. size:core30 or codes:7203,6758."),
             "metric": _str("Metric id; see the metrics list on /api/v1/equity/cohorts/metrics.",
                            enum=_cohort_metric_ids()),
             "highlight": _str("Securities code to locate within the cohort."),
             "order": _str("desc (default) or asc.", enum=["desc", "asc"]),
             "limit": {"type": "integer", "description": "Rows (default 50, max 100)."},
             "as_of": _str("YYYY-MM-DD: the classification as it stood then.")},
             "required": ["cohort"]},
         "annotations": ro},
        {"name": "get_overview", "title": "Headline reading",
         "description": ("A series dataset's headline reading — the stat tiles its own "
                         "page leads with, each with its latest value, the change and "
                         "the trust label. The quickest answer to 'where is this now'; "
                         "use get_series for the history behind a tile."),
         "inputSchema": {"type": "object", "properties": {
             "dataset": _str("Series dataset id.", enum=overview_ids)},
             "required": ["dataset"]},
         "annotations": ro},
        {"name": "get_breakdown", "title": "A dataset's own cut",
         "description": ("The cut a dataset exists to serve, beyond its raw series: "
                         "contributions to headline inflation, the breadth of price "
                         "rises, the whole yield curve, arrivals by market, one "
                         "commodity's trade with every partner, one area's guest nights, "
                         "every prefecture's counts. Call with no `cut` to see which "
                         "this dataset serves."),
         "inputSchema": {"type": "object", "properties": {
             "dataset": _str("Dataset id.", enum=breakdown_ids),
             "cut": _str("Which cut; omit to list the ones this dataset serves.",
                         enum=all_cuts),
             "commodity": _str("trade: the published commodity code."),
             "flow": _str("trade: exp or imp.", enum=["exp", "imp"]),
             "area": _str("accommodation: two-digit JIS prefecture or region code."),
             "prefecture": _str("prefectures: two-digit JIS code, e.g. 13 for Tokyo."),
             "threshold": {"type": "number",
                           "description": "breadth: the YoY percent above which an item counts as rising."},
             "start": _str("contributions: first period, YYYY-MM."),
             "end": _str("contributions: last period, YYYY-MM.")},
             "required": ["dataset"]},
         "annotations": ro},
        {"name": "get_vintages", "title": "Releases and revisions",
         "description": ("The point-in-time record. With no `series`, every accepted "
                         "release of the dataset newest first — label, the period it "
                         "reached, when it was known, and the SHA-256 of the archived "
                         "source file. With a `series`, how that series has been revised "
                         "release by release, and by how much. Pair with get_series's "
                         "`as_of` to read the data as it stood on a date."),
         "inputSchema": {"type": "object", "properties": {
             "dataset": _str("Dataset id.", enum=ids),
             "series": _str("One series code — its revision history instead of the "
                            "release list."),
             "period": _str("With `series`: one period, YYYY-MM; omit for every "
                            "revised period.")},
             "required": ["dataset"]},
         "annotations": ro},
    ]


# ---------------------------------------------------------------------------
# Instructions — generated from the registry, so they name every dataset
# ---------------------------------------------------------------------------

_RULES = (
    "Ground every figure you state in a tool result from this conversation — the data "
    "is revised and extended continuously, so never answer from memory. Missing values "
    "are missing, never zero. Every measure is either OFFICIAL (exactly as published by "
    "the agency or filed by the company) or CALCULATED by this platform from official "
    "inputs; calculated figures carry their formula in `calc`, and you must keep the "
    "two distinct when quoting. Never rank, sum or chart across measure types: an index "
    "is not a yen level, a stock is not a flow, a count of people is not a price. Every "
    "result carries a `cite` URL — a permanent page showing the same view — link it when "
    "you present numbers, and give the `provenance.credit` line as the source."
)

_HOW = (
    "Start with list_datasets (or describe_dataset for one you already know), find "
    "codes with search, then get_series for series datasets, get_company for a company "
    "(without a dataset first, to see which datasets know it), and screen for ranked "
    "cross-sections using the sorts describe_dataset lists."
)


def instructions():
    parts = ["This server is the Plover Analytics: Japanese official statistics and "
             "company disclosures, deep on one market. Datasets by section:"]
    by = dict((s["id"], s) for s in registry.by_section())
    for sec in registry.SECTIONS:
        ids = [i for i in by[sec["id"]]["datasets"] if registry.available(i)]
        if not ids:
            continue
        lines = []
        for i in ids:
            m = registry.get(i)
            lines.append("%s — %s. %s Credit: %s" % (i, m["name"]["en"], m["summary"],
                                                    m["source"]["credit"]))
        parts.append("%s: %s" % (sec["label"].upper(), " | ".join(lines)))
    parts.append(_RULES)
    parts.append(_HOW)
    return "\n\n".join(parts)
