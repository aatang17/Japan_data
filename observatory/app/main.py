"""Observatory app: JSON API + static frontend in one process.

Run:  ./.venv/bin/uvicorn app.main:app --port 8007
"""
import asyncio
import contextlib
import hashlib
import os
import pathlib

from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware

from . import cache, db, env, prerender, visits

# Before .api, which resolves the /ask provider from the environment.
env.load()

from . import api  # noqa: E402 — must follow env.load()
from .admin_api import router as admin_router  # noqa: E402
from .api import router  # noqa: E402
from .buyback_api import router as buyback_router  # noqa: E402
from .cohorts_api import router as cohorts_router  # noqa: E402
from . import equity_api  # noqa: E402
from .equity_api import router as equity_router  # noqa: E402
from .facility_api import router as facility_router  # noqa: E402
from .financials_api import router as financials_router  # noqa: E402
from .governance_api import router as governance_router  # noqa: E402
from .lvh_api import router as lvh_router  # noqa: E402
from .short_api import router as short_router  # noqa: E402
from .agm_api import router as agm_router  # noqa: E402
from .segments_api import router as segments_router  # noqa: E402
from . import sec_api  # noqa: E402
from .sec_api import router as sec_router  # noqa: E402
from .catalog_api import router as catalog_router  # noqa: E402
from .apportionment_api import router as representation_router  # noqa: E402
from .company_api import router as company_router  # noqa: E402
from . import registry  # noqa: E402
from .ownership_api import router as ownership_router  # noqa: E402
from . import refresh  # noqa: E402
from .mcp import router as mcp_router  # noqa: E402
from . import seo  # noqa: E402
from .seo import router as seo_router  # noqa: E402
from .visits_api import router as visits_router  # noqa: E402

WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"

# prerender reads pages and nav.js from the same directory this serves.
prerender.WEB_DIR = WEB_DIR


class RevalidatedStatic(StaticFiles):
    """Static files that browsers must re-check on every visit.

    Without a Cache-Control header, browsers keep assets for a heuristic
    lifetime of their own choosing — after a deploy, a returning visitor can
    run a new page against a stale shared script (the buyback chart crashed
    exactly this way). ``no-cache`` means "keep a copy, but ask before using
    it": the ETag/Last-Modified pair FileResponse already sends makes that
    check a cheap 304, so unchanged files still never re-download.

    An HTML page is additionally rewritten on the way out, so that a
    crawler which does not run JavaScript still receives the site's links
    and the page's headline figures. See app/prerender.py for what is added
    and why; the ETag is recomputed over the rewritten body, since the
    file's own timestamp no longer describes what was sent.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return self._prerendered(response, scope)

    @staticmethod
    def _prerendered(response, scope):
        source_path = getattr(response, "path", None)
        if response.status_code != 200 or not source_path:
            return response
        if not str(source_path).endswith(".html"):
            return response
        try:
            with open(str(source_path), encoding="utf-8") as handle:
                original = handle.read()
        except OSError:
            return response
        query_string = scope.get("query_string", b"").decode("latin-1")
        body = prerender.inject(
            original, os.path.basename(str(source_path)),
            canonical=seo.canonical_url(scope.get("path", "/"), query_string),
            query_string=query_string)
        if body == original:
            return response

        etag = '"%s"' % hashlib.md5(body.encode("utf-8")).hexdigest()
        headers = {"Cache-Control": "no-cache", "ETag": etag}
        sent = Headers(scope=scope).get("if-none-match", "")
        if etag in [tag.strip() for tag in sent.split(",") if tag.strip()]:
            return Response(status_code=304, headers=headers)
        return Response(body, media_type="text/html; charset=utf-8",
                        headers=headers)


@contextlib.asynccontextmanager
async def lifespan(app):
    # Prime the cache before the port takes traffic, so no real visitor pays
    # the cost of building the large payloads from cold.
    # Every manifest's endpoints must resolve on this app. A card that
    # names a path that does not exist is quarantined and reported on
    # /catalog/health — never a reason for the port not to open.
    registry.bind(app)
    await cache.warm(app, api.warm_paths())
    # Watches ingest health for as long as we serve, and — only under
    # start.sh, which sets REFRESH_SUPERVISED — ends the process once a day so
    # the supervisor can re-run the ingests. See refresh.py.
    task = asyncio.ensure_future(refresh.run())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# The human reference is /api.html, rendered from this schema and the dataset
# manifests so it cannot drift from what the server serves; /api/docs keeps
# its old address and lands there. The framework's try-it-out console stays
# at /api/swagger for anyone who wants to poke an endpoint by hand.
OPENAPI_TAGS = [
    {"name": "Catalog", "description": "What is on the server: every dataset's card, the sections they sit in, and whether each one is current."},
    {"name": "Datasets", "description": "The same endpoints for every statistical dataset. `{dataset}` is a dataset id from the catalog; which endpoints a dataset offers is listed on its card."},
    {"name": "Company", "description": "One securities code across every dataset on the platform."},
    {"name": "Cross-shareholdings", "description": "Policy shareholdings (政策保有株式) as filed in each company's annual securities report."},
    {"name": "Shareholder register", "description": "The ten largest shareholders as filed in each annual report."},
    {"name": "5% filings", "description": "Large shareholding reports (大量保有報告書): who crossed 5% and when."},
    {"name": "Boards and pay", "description": "Directors, independence and officer pay as filed."},
    {"name": "AGM votes", "description": "Voting results from extraordinary reports (臨時報告書): director approval and proposal outcomes."},
    {"name": "Buybacks", "description": "Share repurchase programmes and monthly progress reports."},
    {"name": "Financials", "description": "Financial statements and the filer's five-year summary as tagged on EDINET, and ratios calculated from them."},
    {"name": "Segments and customers", "description": "Reportable segments, geographic revenue and named customers from each annual report, mapped to customs flows."},
    {"name": "Facilities", "description": "Major facilities and land as filed: sites, book value and rented floor space."},
    {"name": "Peer groups", "description": "Fixed and ad-hoc company cohorts, and one metric ranked across a cohort."},
    {"name": "Representation", "description": "Seats per elector in the House of Councillors, from the population register."},
]

app = FastAPI(title="Plover Analytics API", version="1",
              description="Japanese official statistics and company disclosures, read-only, "
                          "no key. Human reference: /api.html",
              docs_url="/api/swagger", redoc_url=None, openapi_url="/api/openapi.json",
              openapi_tags=OPENAPI_TAGS, lifespan=lifespan)


@app.get("/api/docs", include_in_schema=False)
def api_docs():
    return RedirectResponse("/api.html", status_code=302)


# Order matters, and add_middleware builds the stack inside out: the last one
# added is the outermost. GZip must be outside the cache so that everything
# else — the charting bundle above all — is compressed too, while the cache's
# own pre-compressed hits pass through it untouched.
# Stamped with EVERY database file: any of them can be swapped in by app/backfill.py
# while the server runs, and an entry must not outlive the file it came from.
app.add_middleware(cache.ResponseCache,
                   version=lambda: (db.file_version(), equity_api.file_version(),
                                    sec_api.file_version()))
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
# Outermost, so a reader served from the response cache is still counted: a
# cache hit never reaches the routers. See app/visits.py.
app.add_middleware(visits.VisitCounter)
# Outside even the counter: a reader arriving on the www spelling is bounced
# to the canonical host before anything else runs, so the visit is counted
# once, at the address it lands on. See app/seo.py.
app.add_middleware(seo.CanonicalHost)

# Equity first: its literal /api/v1/equity/ paths must win over the core
# router's /api/v1/{dataset}/ catch-alls. Governance and buyback ahead of
# holdings, so their longer /equity/… prefixes are matched before the shorter one.
# Cohorts before everything else under /equity: its literal
# /api/v1/equity/cohorts/... paths must beat /equity/company/{sec_code}.
app.include_router(cohorts_router)
app.include_router(governance_router)
app.include_router(ownership_router)
app.include_router(lvh_router)
app.include_router(short_router)
app.include_router(agm_router)
app.include_router(facility_router)
app.include_router(financials_router)
app.include_router(segments_router)
app.include_router(buyback_router)
app.include_router(equity_router)
# The US shelf's literal /api/v1/us/financials/… paths, ahead of the core
# router for the same reason as the equity ones.
app.include_router(sec_router)
# The catalog of manifests ahead of the core router, so its literal
# /api/v1/catalog/… paths can never be shadowed by /{dataset}/… catch-alls.
# /api/v1/company/{code} ahead of the core router, so it beats the
# /api/v1/{dataset}/... catch-alls. /api/v1/representation/… is a derived
# surface over the population datasets and sits ahead of them for the same
# reason.
app.include_router(company_router)
# /api/v1/visit/… is the page talking to the counter about itself, and sits
# ahead of the core router for the same reason: /{dataset}/… would swallow it.
app.include_router(visits_router)
app.include_router(catalog_router)
app.include_router(representation_router)
app.include_router(router)
# /mcp sits outside /api/v1 on purpose: the response cache only touches GETs
# under that prefix, so JSON-RPC POSTs can never be served stale.
app.include_router(mcp_router)
# /admin/api also sits outside /api/v1: authenticated responses must never be
# served from (or into) the shared response cache.
app.include_router(admin_router)
# robots.txt and sitemap.xml are generated from the pages in web/, so they
# have to be registered ahead of the static mount that serves those pages —
# the mount answers every remaining path and would 404 both.
app.include_router(seo_router)
app.mount("/", RevalidatedStatic(directory=str(WEB_DIR), html=True), name="web")
