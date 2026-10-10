"""Shared reader for the Census and Statistics Department, Hong Kong (C&SD).

Every C&SD web table is served by one keyless JSON API in one layout:

    https://www.censtatd.gov.hk/api/get.php?id=<table>&lang=en&full_series=1

returns ``{"header": {...}, "dataSet": [row, ...]}`` where each row is one
figure: ``freq`` (M, Q, Y, or M3M for a rolling three-month period),
``period`` (YYYY, or YYYYMM — for a quarter, the quarter's LAST month),
``sv`` (the statistic's code), ``svDesc`` (its presentation: "Index",
"HK$ million", "Year-on-year % change" ...), at most one classification
(``SEX``, ``COICOP``, ``GDP_COMPONENT`` ... with a ``<dim>Desc`` beside
it), ``figure`` (a number, or "" when there is none) and ``sd_value`` (the
footnote flags: "p" provisional, "r" revised, "N.A." not available).

The API names no statistic: ``sv`` is a code. The names are in the table's
own label file, the one the C&SD web table loads,

    https://www.censtatd.gov.hk/data/en/table_<table>_lang.json

whose ``sv_list`` gives each code's name (``def_stat_desc``) and each
presentation's type ("Raw figure", "Rate", "Rate of change") and decimals.
Both files are fetched for every table and archived together, so the names a
release was stored under are kept with its numbers.

What is stored, by the platform's rule: published LEVELS and RATES — index
levels, HK$ amounts, head counts, unemployment rates — exactly as released.
The C&SD's own year-on-year and month-to-month % changes are not stored; the
platform calculates them from the levels and shows the formula, as it does
for Japan. The exceptions are rates the stored levels cannot reproduce:

- the seasonally adjusted CPI and trade series, which the C&SD publishes ONLY
  as a rate (a table opts in with ``rates_of_change``);
- the CPI's year-on-year rates, which across each rebasing year (Oct 2009 –
  Sep 2010, Oct 2014 – Sep 2015, Oct 2019 – Sep 2020) the C&SD computed on the
  old basket: from the linked index the same rate comes out up to 0.8 pp
  away (underlying inflation, June 2020: published 1.2%, calculated 2.0%).
  A table opts in with ``changes``, naming the presentations to keep.

They are stored as published, as rates in percent, in a dataset of their own:
a rate never sits in an index dataset, where the platform would take a
percentage change of it.

Annual rows are not stored: a dataset has one frequency, and the C&SD's
calendar-year figures are the year's months or quarters summed or averaged.

The "p" and "r" flags are not stored (the core schema carries values only);
a provisional figure that is later revised arrives as a new vintage, which is
what the point-in-time history is for.
"""
import datetime
import json
import re
import time
import urllib.error
import urllib.request


class ValidationError(Exception):
    pass


class FetchError(Exception):
    pass


AGENCY = "Census and Statistics Department, Hong Kong"
API = "https://www.censtatd.gov.hk/api/get.php?id=%s&lang=en&full_series=1"
LABELS = "https://www.censtatd.gov.hk/data/en/table_%s_lang.json"
WEB_TABLE = "https://www.censtatd.gov.hk/en/web_table.html?id=%s"
CREDIT = "Source: Census and Statistics Department, Hong Kong."
# The C&SD shares DATA.GOV.HK's terms: its statistics may be downloaded,
# reproduced and distributed free of charge, commercially or not, provided
# they are reproduced accurately and the source is acknowledged.
LICENSE_NOTE = ("Census and Statistics Department, Hong Kong, under the DATA.GOV.HK "
                "terms: free to reproduce and distribute, commercially or not, "
                "provided the data are reproduced accurately and the C&SD is "
                "acknowledged as the source.")
USER_AGENT = "PloverAnalytics/1.0 (+https://ploveranalytics.com; data@ploveranalytics.com)"
# One request at a time with a pause between them: the C&SD answers fast, and
# a burst is what gets a client blocked by a government firewall.
PAUSE_SECONDS = 1.0


def table_url(table_id):
    return API % table_id


def _get(url):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 404, 405):
                break              # a refusal does not heal on retry
        except (urllib.error.URLError, OSError) as e:
            last = e
        time.sleep(5 * (attempt + 1))
    raise FetchError("%s: %s" % (url, last))


def fetch(table_ids):
    """The API rows and the label file of every table, as one JSON bundle."""
    tables = {}
    for i, tid in enumerate(table_ids):
        if i:
            time.sleep(PAUSE_SECONDS)
        data = _get(API % tid)
        time.sleep(PAUSE_SECONDS)
        labels = _get(LABELS % tid)
        try:
            data_json = json.loads(data.decode("utf-8"))
            labels_json = json.loads(labels.decode("utf-8"))
        except ValueError as exc:
            raise FetchError("%s: not JSON (%s): %r" % (tid, exc, data[:80]))
        status = (data_json.get("header") or {}).get("status") or {}
        if status.get("code") != 0:
            raise FetchError("%s: API refused: %s" % (tid, status))
        tables[tid] = {"data": data_json, "labels": labels_json}
    return json.dumps({"tables": tables}, sort_keys=True, ensure_ascii=False).encode("utf-8")


def canonical_bytes(raw):
    """The bundle without the API's per-request timing (header.count.started,
    finished, durationSeconds), which changes on every fetch — so an unchanged
    table is recognised as unchanged and no empty release is published."""
    bundle = json.loads(raw.decode("utf-8"))
    for t in bundle.get("tables", {}).values():
        count = (t.get("data") or {}).get("header", {}).get("count")
        if isinstance(count, dict):
            for k in ("started", "finished", "durationSeconds"):
                count.pop(k, None)
    return json.dumps(bundle, sort_keys=True, ensure_ascii=False).encode("utf-8")


_TAG = re.compile(r"<[^>]+>")


def clean(text):
    """A C&SD label without its HTML (<u><i>Less:</i></u>, a blue <font>) and
    its leading-space indentation."""
    return re.sub(r"\s+", " ", _TAG.sub("", text or "").replace("&nbsp;", " ")).strip()


# Presentation (svDesc) -> stored unit. Anything else is refused: an unknown
# unit is a table that changed shape, not something to guess at.
UNITS = {
    "Index": "index",
    "Index (Year 2024=100)": "index",
    "HK$ million": "hkd_million",
    "HK$": "hkd",
    "No. ('000)": "persons_1000",
    "(%)": "percent",
}
KEEP_TYPES = ("Raw figure", "Rate")


def _period(freq, text):
    """A C&SD period as the platform's date: a month (or a rolling three-month
    period, dated by its LAST month, as the C&SD labels it) on its first day;
    a quarter, published as its last month, on its first month's first day."""
    if not re.match(r"^\d{6}$", text or ""):
        raise ValidationError("period %r is not YYYYMM" % text)
    y, m = int(text[:4]), int(text[4:])
    if not 1 <= m <= 12:
        raise ValidationError("period %r has month %d" % (text, m))
    if freq == "Q":
        if m % 3:
            raise ValidationError("quarter %r does not end a calendar quarter" % text)
        m -= 2
    return datetime.date(y, m, 1)


def _number(fig):
    if fig is None or fig == "":
        return None
    if isinstance(fig, bool):
        raise ValidationError("figure %r is not a number" % fig)
    if isinstance(fig, (int, float)):
        return float(fig)
    try:
        return float(str(fig).replace(",", ""))
    except ValueError:
        raise ValidationError("figure %r is not a number" % fig)


def parse(raw_bytes, tables, name_fn=None):
    """(series, observations) for the tables described by ``tables``:

        {"id": "510-60003", "freq": "M",
         "drop_total": True,         # the classification's Total repeats
                                     # another table's headline: not loaded twice
         "rates_of_change": False,   # keep the published rates of change
         "changes": {"Year-on-year % change": "yoy"},
                                     # read ONLY these published changes, each
                                     # coded <sv>.<suffix> (CC_CM_1920.yoy)
         "sv_order": [...]}          # display order of the statistics

    A series code is the C&SD's own: the ``sv`` code, then ``.`` and the
    classification code when there is one (``CC_CM_1920.7`` is the composite
    CPI for COICOP division 7, Transport; ``UR.F`` the female unemployment
    rate), so every figure can be found in the C&SD table under the same code.
    """
    try:
        bundle = json.loads(raw_bytes.decode("utf-8"))["tables"]
    except (ValueError, KeyError) as exc:
        raise ValidationError("not a C&SD bundle: %s" % exc)
    series, observations = [], []
    seen_codes = {}
    totals = []          # (table, sv, period, value) of each Total not loaded
    for spec in tables:
        tid = spec["id"]
        if tid not in bundle:
            raise ValidationError("table %s missing from the bundle" % tid)
        rows = bundle[tid]["data"].get("dataSet") or []
        sv_list = bundle[tid]["labels"].get("sv_list") or {}
        if not rows:
            raise ValidationError("table %s has no rows" % tid)
        # presentation description -> its type, per statistic
        types = {}
        for sv, meta in sv_list.items():
            for p in (meta.get("sp_list") or {}).values():
                types[(sv, p.get("def_stat_pres_desc"))] = p.get("def_stat_type") or ""
        dims = [k for k in rows[0] if k not in ("freq", "period", "sv", "svDesc", "figure",
                                                "sd_value") and not k.endswith("Desc")]
        if len(dims) > 1:
            raise ValidationError("table %s has %d classifications (%s); one is supported"
                                  % (tid, len(dims), dims))
        dim = dims[0] if dims else None
        for r in rows:
            if r.get("freq") != spec["freq"]:
                continue
            sv, desc = r.get("sv"), r.get("svDesc")
            kind = types.get((sv, desc))
            if kind is None:
                raise ValidationError("%s: %s/%r has no entry in the label file" % (tid, sv, desc))
            suffix = ""
            if spec.get("rates_of_change") and kind == "Rate of change":
                unit = "percent"
            elif desc in (spec.get("changes") or {}):
                unit, suffix = "percent", "." + spec["changes"][desc]
            elif spec.get("changes") is not None:
                continue           # a rates-only read of a table: its levels live elsewhere
            elif kind in KEEP_TYPES:
                unit = UNITS.get(desc)
                if unit is None:
                    raise ValidationError("%s: %s has an unknown unit %r" % (tid, sv, desc))
            else:
                continue           # a % change the platform calculates itself
            dval = str(r.get(dim) if dim else "") if dim else ""
            if dval == "None":
                dval = ""
            if dval == "" and dim and spec.get("drop_total"):
                value = _number(r.get("figure"))
                if value is not None:
                    totals.append((tid, sv, _period(spec["freq"], r.get("period")), value))
                continue
            code = sv + ("." + dval if dval else "") + suffix
            if code not in seen_codes:
                if sv not in sv_list:
                    raise ValidationError("%s: statistic %s is not in the label file" % (tid, sv))
                stat = clean(sv_list[sv].get("def_stat_desc"))
                part = clean(r.get(dim + "Desc")) if dim and dval else ""
                if part.startswith("Less: "):
                    part = part[len("Less: "):]
                name = name_fn(spec, sv, stat, part, desc) if name_fn else (
                    stat + (" — " + part if part else "") + (": " + desc if suffix else ""))
                seen_codes[code] = (tid, desc)
                order = spec.get("sv_order") or list(sv_list)
                rank = (tables.index(spec), order.index(sv) if sv in order else len(order),
                        (0, 0, "") if not dval else
                        (1, int(dval), "") if dval.isdigit() else (1, 0, dval))
                series.append({"code": code, "name_en": name, "name_ja": None, "unit": unit,
                               "weight_per_10000": None, "sort_order": rank})
            elif seen_codes[code] != (tid, desc):
                raise ValidationError("series %s appears in %s and %s/%r"
                                      % (code, seen_codes[code], tid, desc))
            value = _number(r.get("figure"))
            if value is None:
                continue           # not available: a gap, never a zero
            observations.append({"code": code, "period": _period(spec["freq"], r.get("period")),
                                 "value": value})
    # A statistic the table carries at another frequency only (per capita GDP
    # is annual) has rows here with no figures: it is not a series of this
    # dataset.
    have = set(o["code"] for o in observations)
    series = [x for x in series if x["code"] in have]
    # Display order: table, then the statistic (the C&SD's own label order
    # unless the table names one), then the classification code.
    series.sort(key=lambda x: x["sort_order"])
    for i, x in enumerate(series):
        x["sort_order"] = i
    # A Total that was not loaded must repeat a headline that was: same
    # statistic code, same value, in every period both carry.
    if totals:
        stored = dict(((o["code"], o["period"]), o["value"]) for o in observations)
        compared = 0
        for tid, sv, period, value in totals:
            if sv not in seen_codes:
                raise ValidationError("%s: its Total of %s repeats no loaded series" % (tid, sv))
            have = stored.get((sv, period))
            if have is None:
                continue
            if abs(have - value) > 1e-9:
                raise ValidationError("%s: Total of %s at %s is %r, the loaded headline %r"
                                      % (tid, sv, period, value, have))
            compared += 1
        if not compared:
            raise ValidationError("no Total could be checked against its headline")
    return series, observations


def cpi_short(text):
    """The C&SD's own short form of an index name: "Consumer Price Index (A)"
    becomes "CPI(A)", "Composite Consumer Price Index" "Composite CPI" — the
    way the C&SD writes them in its releases, and what a reader searches for."""
    return text.replace("Consumer Price Index (", "CPI(").replace("Consumer Price Index", "CPI")


def kinds(series, flows=()):
    """PRESENTATION["kinds"]: a series in percent is a rate (its change is in
    percentage points, never a percentage of itself); a series that crosses
    zero (a trade balance, the change in inventories) is a flow, which the
    API refuses a percentage change of."""
    out = {}
    for s in series:
        if s["code"] in flows:
            out[s["code"]] = "flow"
        elif s["unit"] == "percent":
            out[s["code"]] = "rate"
    return out


def check(series, observations, required, first_period, max_age_days, ranges=None):
    """The shared gates. ``ranges`` maps a unit to its (low, high) bounds — a
    figure outside them is a column read wrongly, not news."""
    ranges = ranges or {}
    codes = set(s["code"] for s in series)
    missing = [c for c in required if c not in codes]
    if missing:
        raise ValidationError("required series missing: %s (have %s)"
                              % (missing, sorted(codes)[:12]))
    unit = dict((s["code"], s["unit"]) for s in series)
    seen = set()
    latest = first = None
    per_series_latest = {}
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate %s %s" % key)
        seen.add(key)
        lo, hi = ranges.get(unit[o["code"]], (None, None))
        if (lo is not None and o["value"] < lo) or (hi is not None and o["value"] > hi):
            raise ValidationError("%s %s: %r out of range for %s"
                                  % (o["code"], o["period"], o["value"], unit[o["code"]]))
        p = o["period"]
        latest = p if latest is None or p > latest else latest
        first = p if first is None or p < first else first
        if p > per_series_latest.get(o["code"], datetime.date.min):
            per_series_latest[o["code"]] = p
    if latest is None:
        raise ValidationError("no observations")
    if first > first_period:
        raise ValidationError("history starts %s, expected by %s" % (first, first_period))
    # Every required series reaches the newest period: one that stops short
    # means a table was served truncated, or two tables are a release apart.
    for c in required:
        if per_series_latest.get(c) != latest:
            raise ValidationError("%s ends %s but the release runs to %s"
                                  % (c, per_series_latest.get(c), latest))
    if (datetime.date.today() - latest).days > max_age_days:
        raise ValidationError("newest period %s is implausibly old" % latest)
    return latest


def manifest(dataset, source, presentation, section, name, summary, page, history_from,
             measures, notes=(), cite=None):
    slug = dataset["slug"]
    return {
        "id": slug,
        "section": section,
        "name": name,
        "shape": "series",
        "summary": summary,
        "source": {
            "publisher": AGENCY,
            "publisher_ja": None,
            "document": source["name"],
            "url": source["url"],
            "credit": presentation["credit_line"],
            "license_note": source["license_note"],
        },
        "keys": ["series_code", "period"],
        "frequency": dataset["frequency"],
        "vintage": {
            "unit": "release", "as_of_basis": "release-in-force",
            "as_of_supported": True, "history_from": history_from,
            "stale_after_days": presentation["stale_after_days"],
        },
        "measures": measures,
        "endpoints": {
            "series": "/api/v1/%s/observations" % slug,
            "search": "/api/v1/%s/series" % slug,
            "summary": "/api/v1/%s/overview" % slug,
            "releases": "/api/v1/%s/releases" % slug,
            "revisions": "/api/v1/%s/revisions" % slug,
        },
        "capabilities": ["series", "search", "summary"],
        "cite": cite or page,
        "page": page,
        "notes": list(notes) + COMMON_NOTES,
    }


COMMON_NOTES = [
    "Series codes are the C&SD's own statistic codes, with the classification "
    "code after a dot (CC_CM_1920.7 is the composite CPI for COICOP division 7), "
    "so every figure can be found in the C&SD web table under the same code.",
    "Values are exactly as the C&SD publishes them. The C&SD's own percentage "
    "changes are not stored: the platform calculates changes from the published "
    "levels and shows the formula. A rate computed from published (rounded) "
    "levels can differ from the C&SD's own by ±0.1 pp.",
    "The C&SD's provisional (p) and revised (r) flags are not stored; a revision "
    "arrives as a new vintage, and the release history keeps every earlier value.",
    "Annual figures are not stored: they are the year's months or quarters, "
    "summed or averaged.",
]
