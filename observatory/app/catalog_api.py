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

router = APIRouter(prefix="/api/v1/catalog")


@router.get("/manifests")
def manifests():
    """Every dataset's manifest, in section order."""
    rows = registry.datasets()
    return {"count": len(rows), "sections": registry.by_section(), "datasets": rows}


@router.get("/manifests/{dataset_id}")
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


@router.get("/sections")
def sections():
    """The fixed section list, each with its dataset ids, in display order."""
    return {"sections": registry.by_section()}
