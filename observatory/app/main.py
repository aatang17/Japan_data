"""Observatory app: JSON API + static frontend in one process.

Run:  ./.venv/bin/uvicorn app.main:app --port 8007
"""
import pathlib

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import router

WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Observatory", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(router)
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
