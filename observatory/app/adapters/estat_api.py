"""Shared client for the e-Stat API (統計データの自動取得).

One place for the things every e-Stat API adapter needs: the application
ID, paging, and the fact that a response embeds the time it was served.

The application ID is free and per-user (https://www.e-stat.go.jp/mypage/view/api).
It is read from the environment, never committed, and is needed only for
the JSON API — e-Stat's file-download endpoint is keyless, which is why the
CPI adapters need no key at all.
"""
import json
import os
import urllib.parse
import urllib.request

BASE = "https://api.e-stat.go.jp/rest/3.0/app/json/"
USER_AGENT = "ObservatoryIngest/0.1 (data pipeline; contact: repo owner)"

# The API caps one response; a larger table is walked with NEXT_KEY.
PAGE_LIMIT = 100000


class ConfigError(Exception):
    pass


class ApiError(Exception):
    pass


def app_id():
    key = os.environ.get("ESTAT_APP_ID", "").strip()
    if not key:
        raise ConfigError(
            "ESTAT_APP_ID is not set. Get a free application ID at "
            "https://www.e-stat.go.jp/mypage/view/api and put it in .env.")
    return key


def call(operation, **params):
    """One API call, returned as parsed JSON. Raises on a non-zero status."""
    params["appId"] = app_id()
    url = BASE + operation + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    envelope = payload[list(payload)[0]]
    result = envelope.get("RESULT", {})
    # STATUS 0 is success; 1 means "succeeded but matched nothing", which for
    # a pinned table means the table moved and is a fault, not an empty day.
    if str(result.get("STATUS")) != "0":
        raise ApiError("%s returned status %s: %s"
                       % (operation, result.get("STATUS"),
                          result.get("ERROR_MSG")))
    return payload


def get_stats_data(stats_data_id, **params):
    """Every value of one table, following NEXT_KEY to the end.

    Returns the list of raw page payloads, so an adapter can archive what
    the API actually said rather than a reshaped version of it.
    """
    pages = []
    start = None
    while True:
        page_params = dict(params)
        page_params["statsDataId"] = stats_data_id
        page_params["limit"] = PAGE_LIMIT
        if start is not None:
            page_params["startPosition"] = start
        payload = call("getStatsData", **page_params)
        pages.append(payload)
        info = payload["GET_STATS_DATA"]["STATISTICAL_DATA"]["RESULT_INF"]
        next_key = info.get("NEXT_KEY")
        if not next_key:
            return pages
        start = next_key


def strip_timestamps(payload):
    """The same payload with every served-at timestamp removed.

    Each response carries RESULT.DATE, so two identical downloads never
    match byte for byte. Adapters expose this through canonical_bytes() so
    the ingest runner's "nothing new" check compares content, not clocks.
    """
    if isinstance(payload, dict):
        return dict((k, strip_timestamps(v)) for k, v in payload.items()
                    if k != "DATE")
    if isinstance(payload, list):
        return [strip_timestamps(v) for v in payload]
    return payload


def class_values(statistical_data, class_id):
    """{code: name} for one classification axis of a getStatsData response."""
    for obj in statistical_data["CLASS_INF"]["CLASS_OBJ"]:
        if obj["@id"] == class_id:
            entries = obj["CLASS"]
            if isinstance(entries, dict):
                entries = [entries]
            return dict((e["@code"], e["@name"]) for e in entries)
    return {}
