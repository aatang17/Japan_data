"""Shared client for the Bank of Japan Time-Series Data Search API.

Endpoint family: https://www.stat-search.boj.or.jp/api/v1/
    getDataCode  — observations for named series codes (used here)
    getMetadata  — series catalogue for a database
JSON, gzip supported, no API key or registration.

Terms (verified 2026-08-06): no redistribution restriction, but two
mandatory obligations — display CREDIT_LINE wherever the data is shown
(pages, CSV export headers), and notify the BOJ Research and Statistics
Department by email when a service using the API is released.

Adapters import from here so the wire format is handled in one place;
everything dataset-specific (which codes, validation gates,
presentation) stays in the adapter.
"""
import datetime
import gzip
import json
import urllib.request

USER_AGENT = "ObservatoryIngest/0.1 (data pipeline; contact: repo owner)"
BASE_URL = "https://www.stat-search.boj.or.jp/api/v1"

CREDIT_LINE = (
    "This service uses the API provided by the 'Bank of Japan Time-Series "
    "Data Search.' The Bank of Japan does not guarantee the content of the "
    "service."
)


class ValidationError(Exception):
    pass


def canonical_bytes(raw_bytes):
    """Content identity for the unchanged-file check.

    The BOJ envelope embeds the request timestamp ('DATE'), so two
    fetches of identical data never match byte-for-byte. Idempotency
    compares the document with that field removed; the archived
    artifact itself is always the pristine response.
    """
    doc = json.loads(raw_bytes.decode("utf-8"))
    doc.pop("DATE", None)
    return json.dumps(doc, sort_keys=True).encode("utf-8")


def data_code_url(db, codes):
    return "%s/getDataCode?format=json&lang=en&db=%s&code=%s" % (
        BASE_URL, db, ",".join(codes))


def fetch_bytes(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def parse_getdatacode(raw_bytes):
    """Raw getDataCode JSON -> {code: {name, unit, frequency, observations}}.

    observations is [(date, float)]; null values are omitted entirely —
    missing is never zero. Periods are YYYYMM, stored as the first of
    the month.
    """
    doc = json.loads(raw_bytes.decode("utf-8"))
    if doc.get("STATUS") != 200:
        raise ValidationError(
            "BOJ API status %s: %s" % (doc.get("STATUS"), doc.get("MESSAGE")))
    if doc.get("NEXTPOSITION"):
        raise ValidationError(
            "BOJ API paginated the response; request fewer series per call")

    out = {}
    for r in doc.get("RESULTSET", []):
        code = r.get("SERIES_CODE")
        values = r.get("VALUES") or {}
        dates, vals = values.get("SURVEY_DATES"), values.get("VALUES")
        if not code or dates is None or vals is None:
            raise ValidationError("malformed RESULTSET entry: %r" % (code,))
        if len(dates) != len(vals):
            raise ValidationError(
                "%s: %d dates but %d values" % (code, len(dates), len(vals)))
        if r.get("FREQUENCY") != "MONTHLY":
            raise ValidationError(
                "%s: unexpected frequency %r" % (code, r.get("FREQUENCY")))
        obs = []
        for p, v in zip(dates, vals):
            if v is None:
                continue
            p = str(p)
            if len(p) != 6 or not p.isdigit():
                raise ValidationError("%s: bad period %r" % (code, p))
            obs.append((datetime.date(int(p[:4]), int(p[4:6]), 1), float(v)))
        out[code] = {
            "name": r.get("NAME_OF_TIME_SERIES", ""),
            "unit": r.get("UNIT", ""),
            "frequency": r.get("FREQUENCY", ""),
            "observations": obs,
        }
    return out
