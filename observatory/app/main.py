"""Observatory app: JSON API + static frontend in one process.

Run:  ./.venv/bin/uvicorn app.main:app --port 8007
"""
import contextlib
import pathlib

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from . import cache, db, env

# Before .api, which resolves the /ask provider from the environment.
env.load()

from . import api  # noqa: E402 — must follow env.load()
from .api import router  # noqa: E402
from .buyback_api import router as buyback_router  # noqa: E402
from .equity_api import router as equity_router  # noqa: E402
from .governance_api import router as governance_router  # noqa: E402
from .mcp import router as mcp_router  # noqa: E402

WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"


@contextlib.asynccontextmanager
async def lifespan(app):
    # Prime the cache before the port takes traffic, so no real visitor pays
    # the cost of building the large payloads from cold.
    await cache.warm(app, api.warm_paths())
    yield


app = FastAPI(title="Observatory", docs_url="/api/docs", openapi_url="/api/openapi.json",
              lifespan=lifespan)

# Order matters, and add_middleware builds the stack inside out: the last one
# added is the outermost. GZip must be outside the cache so that everything
# else — the charting bundle above all — is compressed too, while the cache's
# own pre-compressed hits pass through it untouched.
app.add_middleware(cache.ResponseCache, version=db.file_version)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

# Equity first: its literal /api/v1/equity/ paths must win over the core
# router's /api/v1/{dataset}/ catch-alls. Governance and buyback ahead of
# holdings, so their longer /equity/… prefixes are matched before the shorter one.
app.include_router(governance_router)
app.include_router(buyback_router)
app.include_router(equity_router)
app.include_router(router)
# /mcp sits outside /api/v1 on purpose: the response cache only touches GETs
# under that prefix, so JSON-RPC POSTs can never be served stale.
app.include_router(mcp_router)
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
