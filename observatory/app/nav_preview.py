# -*- coding: utf-8 -*-
"""What the header's Data menu shows when a reader points at a page.

One call, ``/api/v1/catalog/previews``, answers for every page in the menu at
once: the page's main series as a small chart (the last three years or so),
its latest value and period, the unit and the credit line — or, for a page
with no single series (company pages, screens), a one-line description and how
far its filings run. It sits under /api/v1, so the release-versioned response
cache serves it and a new ingest refreshes it; the menu fetches it once, on
first open.

Where the series comes from, in order:

1. ``PAGE_SPECS`` — pages that front several datasets, name no headline, or
   need a figure the page itself calculates (a trade page's world total, the
   foreigners' net buying on the flows page). A calculated figure says so:
   ``trust`` is "derived" and ``calc`` gives the formula.
2. The page's dataset card: the series its PRESENTATION calls the headline.

Every number is read through the same functions that serve /api/v1, so a
preview never shows a figure the page would not. Price indices are shown as
their change on a year earlier — the figure a reader looks for on an inflation
page — and say so; everything else is shown as published.
"""
import logging

from fastapi import APIRouter, HTTPException

from . import api, registry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog"])

# page -> a spec: ("series", dataset, code or None, measure or None),
#                 ("trade", dataset), ("net", dataset, purchases, sales, name)
PAGE_SPECS = {
    "/macro.html": ("series", "cpi-jp", None, "yoy"),
    "/cpi.html": ("series", "cpi-jp", None, "yoy"),
    "/explorer.html": ("series", "cpi-jp-items", None, "yoy"),
    "/banks.html": ("series", "boj-loan-rates", "DLLR2CIRBNL1", "index"),
    "/fiscal.html": ("series", "govt-debt-jp", "total", "index"),
    "/rates.html": ("series", "jgb-yields", "10Y", "index"),
    "/us-treasury.html": ("series", "ust-yields", "10Y", "index"),
    "/us-explorer.html": ("series", "cpi-us", None, "yoy"),
    "/inbound.html": ("series", "jnto-visitors", "total", "index"),
    "/population.html": ("series", "population-jp-history", "00.A1101", "index"),
    "/accommodation.html": ("series", "accommodation-jp", "nights.jp", "index"),
    "/lodging-regions.html": ("series", "accommodation-jp", "nights.jp", "index"),
    "/margin.html": ("series", "margin-jp", "total.purchases.value", "index"),
    "/flows.html": ("net", "investor-flows-jp", "prime.foreigners.purchases.value",
                    "prime.foreigners.sales.value", "Foreigners' net buying, TSE Prime"),
    "/semis.html": ("trade", "trade-semis"),
    "/autos.html": ("trade", "trade-autos"),
    "/energy.html": ("trade", "trade-energy"),
    "/machinery.html": ("trade", "trade-machinery"),
    "/pharma.html": ("trade", "trade-pharma"),
    "/food.html": ("trade", "trade-food"),
}

# company datasets whose freshness report goes by another name
EXTRACTOR_ALIAS = {"large-shareholdings": "5pct-filings", "earnings-releases": "tdnet"}

TAIL = {"monthly": 37, "quarterly": 13, "annual": 11, "fiscal_year": 11, "semiannual": 11,
        "weekly": 157, "daily": 780}


def _headline_code(dataset):
    """The code of the series the dataset's own card calls its headline."""
    adapter = api.ADAPTERS.get(dataset)
    if adapter is None:
        return None
    rows = adapter.PRESENTATION.get("main_series") or []
    if not rows:
        return None
    head = next((r for r in rows if r.get("role") == "headline"), rows[0])
    if head.get("code"):
        return head["code"]
    con = api._con()
    try:
        for s in api._series_map(con, dataset):
            if s.get("name_ja") == head.get("name_ja"):
                return s["code"]
    finally:
        con.close()
    return None


def _measure_for(dataset):
    adapter = api.ADAPTERS[dataset]
    if dataset.startswith("cpi") and "weights" not in dataset and \
            api._index_key(adapter.PRESENTATION) is not None:
        return "yoy"
    return "index"


def _credit(adapter):
    manifest = getattr(adapter, "MANIFEST", None) or {}
    return ((manifest.get("source") or {}).get("credit")
            or adapter.PRESENTATION.get("credit_line")
            or "Source: %s." % adapter.DATASET.get("agency", ""))


def _tail(points, freq):
    pts = points[-TAIL.get(freq, 37):]
    if freq == "daily":
        pts = pts[::5] + ([pts[-1]] if pts and (len(pts) - 1) % 5 else [])
    return pts


def _packet(dataset, code, name, unit, measure, trust, points, credit, release, calc=None):
    adapter = api.ADAPTERS[dataset]
    freq = adapter.DATASET.get("frequency") or "monthly"
    pts = _tail(points, freq)
    have = [p for p in pts if p[1] is not None]
    if len(have) < 3:
        return None
    out = {"kind": "series", "dataset": dataset, "code": code, "measure": measure, "name": name,
           "unit": unit, "trust": trust, "frequency": freq, "points": pts,
           "latest": {"period": have[-1][0], "value": have[-1][1]},
           "credit": credit, "release": release}
    if calc:
        out["calc"] = calc
    return out


def _obs(dataset, code, measure):
    return api.observations(dataset, series=code, measure=measure, start=None, end=None,
                            as_of=None, period=None, fy_end=3, format="json", request=None)


def _series_preview(dataset, code, measure):
    code = code or _headline_code(dataset)
    if not code:
        return None
    measure = measure or _measure_for(dataset)
    body = _obs(dataset, code, measure)
    s = body["series"][0]
    return _packet(dataset, code, s.get("name_en") or code, body.get("unit"), measure,
                   body.get("trust"), s["points"], _credit(api.ADAPTERS[dataset]),
                   (body.get("release") or {}).get("label"))


def _net_preview(dataset, buy, sell, name):
    """Purchases less sales, week by week: what the flows page leads with."""
    b = _obs(dataset, buy, "index")
    s = _obs(dataset, sell, "index")
    sold = dict((p[0], p[1]) for p in s["series"][0]["points"])
    pts = []
    for period, v in b["series"][0]["points"]:
        w = sold.get(period)
        pts.append([period, None if v is None or w is None else round(v - w, 6)])
    return _packet(dataset, buy + "-" + sell, name, b.get("unit"), "net", "derived", pts,
                   _credit(api.ADAPTERS[dataset]), (b.get("release") or {}).get("label"),
                   calc="purchases − sales, from the published weekly values")


def _trade_preview(dataset):
    """The page's default commodity, world total — the sum the page shows."""
    r = api.trade(dataset, flow=None, commodity=None)
    key = r["flow"] + "." + r["commodity"]["code"]
    vals = r["world"].get(key) or []
    pts = [[p, v] for p, v in zip(r["periods"], vals)]
    flow = next((f["label"] for f in r["flows"] if f["key"] == r["flow"]), r["flow"])
    name = "%s, %s, all partners" % (r["commodity"].get("short") or r["commodity"]["label"],
                                     flow.lower())
    return _packet(dataset, key, name, (r.get("units") or {}).get("value"), "sum",
                   r.get("world_trust") or "derived", pts, r.get("credit_line") or "",
                   (r.get("release") or {}).get("label"), calc=r.get("world_calc"))


def _one_line(text, limit=180):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _through():
    """{company dataset: the last day its filings are read through}."""
    try:
        rows = api.health().get("equity_extractors") or []
    except Exception:  # noqa: BLE001 — freshness is a nicety here
        return {}
    return dict((r["dataset"], r.get("archive_read_through")) for r in rows)


def _run(spec):
    kind = spec[0]
    if kind == "series":
        return _series_preview(spec[1], spec[2], spec[3])
    if kind == "trade":
        return _trade_preview(spec[1])
    if kind == "net":
        return _net_preview(*spec[1:])
    return None


def build():
    """{page path: preview} for every page a dataset card or a spec names."""
    from . import prerender
    cards = {}
    for i in registry.ids():
        card = registry.get(i) or {}
        page = card.get("page")
        if page and registry.available(i):
            cards.setdefault(page.split("?")[0], []).append(card)
    pages = set(cards) | set(PAGE_SPECS) | set(
        "/" + name for name in getattr(prerender, "DESCRIPTIONS", {}) if name.endswith(".html"))
    through = None
    out = {}
    for page in sorted(pages):
        group = cards.get(page, [])
        specs = [PAGE_SPECS[page]] if page in PAGE_SPECS else []
        specs += [("series", c["id"], None, None) for c in group
                  if c.get("shape") == "series" and c["id"] in api.ADAPTERS]
        preview = None
        for spec in specs:
            try:
                preview = _run(spec)
            except HTTPException:
                preview = None
            except Exception:  # noqa: BLE001 — one page must not empty the menu
                log.warning("nav preview for %s (%s) failed", page, spec, exc_info=True)
                preview = None
            if preview:
                break
        if preview is None:
            desc = getattr(prerender, "DESCRIPTIONS", {}).get(page.lstrip("/"))
            card = group[0] if group else {}
            text = desc or card.get("summary")
            if not text:
                continue
            preview = {"kind": "text", "name": (card.get("name") or {}).get("en") or page,
                       "text": _one_line(text)}
            company = [c["id"] for c in group if c.get("shape") in ("company", "events")]
            if company:
                if through is None:
                    through = _through()
                dates = [through.get(EXTRACTOR_ALIAS.get(c, c)) for c in company]
                dates = [d for d in dates if d]
                if dates:
                    preview["through"] = max(dates)
        out[page] = preview
    return out


@router.get("/previews", summary="What the Data menu shows for each page",
            openapi_extra={"x-example": "/api/v1/catalog/previews"})
def previews():
    """For each page in the site's Data menu: its main series as a short run
    of points with the latest value, unit and credit line — or a one-line
    description (and, for filings, the date they run through) where a page has
    no single series. Values are as published; a price index is given as its
    change on a year earlier, and a figure the page calculates (a world total,
    a net flow) is marked derived with its formula in `calc`."""
    return {"pages": build()}
