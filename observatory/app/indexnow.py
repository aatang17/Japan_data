# -*- coding: utf-8 -*-
"""Tell the search indexes a page changed, the moment it changes.

IndexNow (indexnow.org) is one HTTP call: "these URLs on this host changed".
Bing, and the engines that share its index — which is what ChatGPT search
draws on — act on it within hours instead of on their own crawl schedule.
Google does not take part; it reads the sitemap's ``lastmod`` instead, which
``seo.py`` writes from the same release dates.

The key is any string of 8–128 letters and digits, chosen by us and set as
``INDEXNOW_KEY``. Ownership is proven by serving that string at a URL on the
host; ours is ``/indexnow-key.txt`` and the call names it, so the key never
has to be a filename. No key set means nothing is sent, and nothing is
reported as sent.

Called from the ingest after a release is published. Fail-safe by
construction: a refused call, a timeout, no network — each is logged and the
ingest's exit code is unchanged. A ping is worth nothing next to the data.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

ENDPOINT = "https://api.indexnow.org/indexnow"
KEY_PATH = "/indexnow-key.txt"
_KEY_SHAPE = re.compile(r"^[A-Za-z0-9-]{8,128}$")


def key():
    """The configured key, or "" when unset or malformed (a malformed key
    would be refused upstream; better to send nothing than a 4xx)."""
    value = os.environ.get("INDEXNOW_KEY", "").strip()
    return value if _KEY_SHAPE.match(value) else ""


def urls_for_dataset(dataset):
    """The pages whose text changes when this dataset publishes: its data
    page, every answer page it feeds, and the landing page's counts."""
    from . import answers, registry
    from .seo import SITE_BASE_URL
    paths = ["/"]
    card = registry.get(dataset) or {}
    if card.get("page"):
        paths.append(card["page"])
    for page in answers.pages_for_dataset(dataset):
        paths.append("/" + page)
    seen, out = set(), []
    for p in paths:
        url = SITE_BASE_URL + p
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def submit(urls, timeout=10):
    """Send the URLs. True when the endpoint accepted them; False otherwise,
    including when no key is configured. Never raises."""
    k = key()
    if not k or not urls:
        return False
    from .seo import SITE_BASE_URL
    host = SITE_BASE_URL.split("://", 1)[-1].split("/", 1)[0]
    body = json.dumps({
        "host": host,
        "key": k,
        "keyLocation": SITE_BASE_URL + KEY_PATH,
        "urlList": list(urls)[:10000],
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        log.warning("indexnow refused %d urls: HTTP %s", len(urls), exc.code)
        return False
    except Exception as exc:  # noqa: BLE001 — a ping is never worth an error
        log.warning("indexnow not sent (%s)", exc)
        return False
    ok = status in (200, 202)
    (log.info if ok else log.warning)("indexnow: HTTP %s for %d urls", status, len(urls))
    return ok


def notify_dataset(dataset):
    """Convenience for the ingest: the dataset's pages, sent."""
    try:
        return submit(urls_for_dataset(dataset))
    except Exception:  # noqa: BLE001
        log.warning("indexnow not sent for %s", dataset, exc_info=True)
        return False
