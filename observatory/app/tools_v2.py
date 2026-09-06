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

from . import api, registry
from .tools import (DEFAULT_MONTHS, POINT_BUDGET, _cite, _fail, _record,
                    _release_of, _trim_points, _window_start, call_api)

# Tool results are an assistant's input tokens. Lists longer than this are
# cut, and the envelope says so and by how much.
ROW_BUDGET = 50
MAX_LIMIT = 100
SEARCH_LIMIT = 25
COMPANY_CODE_MAX = 8


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
        limit=limit)


def _screen_stakes(sort, f, limit):
    return _eq("lvh_api").holders(
        limit=limit, by="entity" if sort == "entity" else "group",
        filer_type=f.get("filer_type", ""), group=f.get("group", ""),
        activist="true" if sort == "activist" or f.get("activist") else "")


def _screen_boards(sort, f, limit):
    return call_api(_eq("governance_api").screen, metric=sort, year=f.get("year", ""),
                    listed=f.get("listed", ""), limit=limit)


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


_SCREENER_FILTERS = ("industry", "standard", "min_revenue_yen", "min_assets_yen",
                     "roe_min", "roe_max", "roa_min", "operating_margin_min",
                     "equity_ratio_min", "equity_ratio_max", "revenue_growth_min",
                     "pbr_implied_max", "dividend_yield_min", "cash_to_assets_min")


def _screen_financials(sort, f, limit):
    m = _eq("financials_api")
    if sort.startswith("filed:"):
        return m.screen(metric=sort[len("filed:"):], year=f.get("year", ""), limit=limit)
    kw = dict((k, str(f.get(k, "") or "")) for k in _SCREENER_FILTERS)
    return m.screener(sort=sort, order=f.get("order", "desc"), limit=limit, offset=0, **kw)


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


def _screen_fns():
    return {
        "segments": _screen_segments,
        "cross-shareholdings": _screen_cross_shareholdings,
        "shareholder-register": _screen_register,
        "large-shareholdings": _screen_stakes,
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
    v = {"unit": "filing", "basis": "captured_at", "as_of": None,
         "note": "Latest captured filing per company."}
    if as_of:
        v["as_of_ignored"] = as_of.isoformat()
        v["note"] = ("as_of is not yet supported for filing-based datasets; the "
                     "latest captured filings are served.")
    return v


def _cite_for(m, **params):
    path = m["cite"]
    for k, v in params.items():
        path = path.replace("{%s}" % k, str(v))
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
        doc = company_api.compose(code, compact=True)
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
        cite=_cite("/explorer.html", dataset=dataset, series=codes, measure=measure,
                   **{"from": from_month, "to": end, "as_of": as_of}),
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
# Registry of tools, and their MCP descriptors
# ---------------------------------------------------------------------------

IMPLS = {
    "list_datasets": list_datasets,
    "describe_dataset": describe_dataset,
    "search": search,
    "get_company": get_company,
    "get_series": get_series,
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


def _str(desc, **extra):
    d = {"type": "string", "description": desc}
    d.update(extra)
    return d


def descriptors():
    """MCP tool descriptors, with enums drawn from the live registry so the
    assistant sees the real dataset ids."""
    ids = registry.ids()
    series_ids = [i for i in ids if registry.get(i)["shape"] == "series"]
    company_ids = [i for i in ids if "company" in registry.get(i)["capabilities"]]
    screen_ids = [i for i in ids if registry.get(i).get("screens")]
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
             "as_of": _str("YYYY-MM-DD. Not yet applied to filing-based datasets; "
                           "the response says when it was ignored."),
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
                         "lowest director approval, highest ROE. Sorts are the ids in "
                         "describe_dataset's `screens`; an unknown sort answers with the "
                         "valid ones. `filters` are the dataset's own query fields "
                         "(year, listed, order, industry, lifecycle, min_shareholders…)."),
         "inputSchema": {"type": "object", "properties": {
             "dataset": _str("Dataset id with screens.", enum=screen_ids),
             "sort": _str("Screen id from describe_dataset; default the first."),
             "filters": {"type": "object", "description": "Field → value filters."},
             "limit": {"type": "integer", "description": "Rows (default 50, max 100)."},
             "as_of": _str("YYYY-MM-DD. Not yet applied to filing-based datasets.")},
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
    parts = ["This server is the Japan Data Observatory: Japanese official statistics and "
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
