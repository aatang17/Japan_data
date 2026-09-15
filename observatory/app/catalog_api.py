"""The catalog of dataset manifests — what the registry knows, served.

Three read-only endpoints under /api/v1/catalog, additive to the existing
/catalog/datasets (the Railway healthcheck path, deliberately untouched) and
/catalog/health. Plain GETs, so the release cache in cache.py covers them.

Every manifest is served with `available`: whether this server actually has
the dataset. A dataset that is not here is still LISTED — a catalog that
silently omitted it would teach a client the dataset does not exist.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import registry

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog"])


@router.get("/manifests", openapi_extra={"x-example": "/api/v1/catalog/manifests"})
def manifests():
    """Every dataset's manifest, in section order."""
    rows = registry.datasets()
    return {"count": len(rows), "sections": registry.by_section(), "datasets": rows}


@router.get("/manifests/{dataset_id}", openapi_extra={"x-example": "/api/v1/catalog/manifests/cpi-jp"})
def manifest(dataset_id: str):
    """One dataset's manifest. An unknown id answers with the valid ones —
    never a bare 404 that leaves a client guessing at spellings."""
    m = registry.get(dataset_id)
    if m is None:
        return JSONResponse(status_code=404, content={
            "detail": "Unknown dataset '%s'" % dataset_id,
            "valid_ids": registry.ids(),
        })
    m["available"] = registry.available(dataset_id)
    return m


@router.get("/sections", openapi_extra={"x-example": "/api/v1/catalog/sections"})
def sections():
    """The fixed section list, each with its dataset ids, in display order."""
    return {"sections": registry.by_section()}


# ---------------------------------------------------------------------------
# Coverage: the platform-wide counts the home page states.
#
# These used to be assembled in the browser from whichever endpoint happened to
# be nearest — "filings parsed" read the 5% tape's own summary and so reported
# 74,266 when the extractors had actually parsed about 125,000 documents, and
# "datasets" counted only the macro series, leaving every filing-derived
# dataset out of its own total. A number stated on the front page has to be
# defensible, so it is computed once, here, next to its definition, and served
# with the breakdown that reconciles it.
# ---------------------------------------------------------------------------

# One row per document, by family. The annual-report family is six extractors
# reading the SAME 有価証券報告書, so its members are counted as one set of
# documents, not six.
FILING_FAMILIES = [
    ("large_shareholding", "5% large-shareholding filings", ["eq_lvh_filings"]),
    ("agm", "AGM voting results", ["eq_agm_meetings"]),
    ("annual_report", "Annual securities reports", [
        "eq_filings", "eq_own_filings", "eq_fin_filings",
        "eq_seg_filings", "eq_fac_filings", "eq_rental_filings"]),
    ("buyback", "Buyback filings", ["eq_buyback_filings"]),
]

# (table, column) pairs carrying the date a document was filed.
FILED_DATE_COLUMNS = [
    ("eq_filings", "filed_date"),
    ("eq_lvh_filings", "filed_date"),
    ("eq_agm_meetings", "filed_date"),
    ("eq_buyback_filings", "submitted"),
]


def _tables_present(cur, names):
    """The subset of `names` this database actually has.

    An extractor that has not run yet leaves its table absent. Skipping it
    lowers the count, which is true; failing the request would blank four
    numbers on the home page because one dataset is young.
    """
    have = set(r[0] for r in cur.execute(
        "SELECT table_name FROM information_schema.tables").fetchall())
    return [n for n in names if n in have]


def _distinct_documents(cur, tables):
    if not tables:
        return 0
    # Table names come from FILING_FAMILIES above, never from a request.
    sql = " UNION ".join("SELECT doc_id FROM %s" % t for t in tables)
    return cur.execute("SELECT count(*) FROM (%s)" % sql).fetchone()[0]


@router.get("/coverage", openapi_extra={"x-example": "/api/v1/catalog/coverage"})
def coverage():
    """How much of Japan this server actually holds: datasets, publishers,
    listed companies and documents parsed.

    `filings` counts distinct EDINET documents, so an annual report read by
    six extractors counts once rather than six times. `filings_by_family`
    breaks that total down by document type, which is how a reader checks it.

    The company and filing counts are `null` — never 0 — when the filings
    database is not on this server, so a caller can tell "none" from "not
    here".
    """
    rows = [m for m in registry.datasets() if m.get("available", True)]
    publishers = sorted(set(
        (m.get("source") or {}).get("publisher") for m in rows
        if (m.get("source") or {}).get("publisher")))
    out = {
        "datasets": len(rows),
        "sources": len(publishers),
        "publishers": publishers,
        "companies": None,
        "filings": None,
        "filings_by_family": {},
        "latest_filing": None,
        "definitions": {
            "datasets": "Datasets available on this server, across every section.",
            "sources": "Distinct publishing bodies behind those datasets.",
            "companies": "Listed companies in the filings database, each with at "
                         "least one parsed filing.",
            "filings": "Distinct company filings parsed from EDINET. A document "
                       "read by several extractors counts once.",
        },
    }
    from . import equity_api
    try:
        cur = equity_api._cur()
    except Exception:  # noqa: BLE001 — no filings database is "unknown", not a fault
        return out

    total_tables = []
    for key, label, tables in FILING_FAMILIES:
        present = _tables_present(cur, tables)
        if not present:
            continue
        out["filings_by_family"][key] = {
            "label": label, "documents": _distinct_documents(cur, present)}
        total_tables.extend(present)
    if total_tables:
        out["filings"] = _distinct_documents(cur, total_tables)
    if _tables_present(cur, ["eq_entities"]):
        out["companies"] = cur.execute(
            "SELECT count(*) FROM eq_entities WHERE listed").fetchone()[0]
    dates = []
    for table, column in FILED_DATE_COLUMNS:
        if _tables_present(cur, [table]):
            d = cur.execute("SELECT max(%s) FROM %s" % (column, table)).fetchone()[0]
            if d is not None:
                dates.append(d)
    if dates:
        out["latest_filing"] = max(dates).isoformat()
    return out
