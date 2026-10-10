"""Adapter: job openings-to-applicants ratios, Japan (MHLW).

Source: 厚生労働省 一般職業紹介状況（職業安定業務統計）, long-run tables
第２表 新規求人倍率 and 第３表 有効求人倍率 — the ratio of job openings to job
seekers at Hello Work, the public employment offices, monthly from January
1963, original and seasonally adjusted. 有効求人倍率 (active openings per
active applicant) is the figure the press reports beside the unemployment
rate on the same morning; 新規求人倍率 (new openings per new application) is
the faster-moving lead.

**The file id moves every month.** The Ministry publishes each month's
tables as a new e-Stat dataset (「一般職業紹介状況_～令和8年8月_月次_2026年8
月」) with new statInfIds, so nothing here can be pinned. fetch() asks e-Stat's
file catalog (getDataCatalog, which needs the e-Stat application ID) for the
newest edition and takes its long-run tables 2 and 3. A month in which the
catalog shows nothing newer simply re-fetches the same edition and the
ingest skips it as unchanged.

Facts the parser and the gates rely on:

- Each workbook has three sheets: openings including part-time (パート
  含む, the headline), excluding part-time and part-time only. The last two
  start later; their early years are ``***``, which is missing, never zero.
- Rows are years; columns C–N are January–December of the original series
  and U–AF of the seasonally adjusted. The quarterly, annual and fiscal-year
  averages beside them are not taken — the platform does not store
  aggregates it can be asked to compute, and the Ministry's annual ratio is
  a ratio of averages, not an average of ratios.
- Ratios are published to two decimals; Excel keeps binary noise
  (0.579999999999), so every value is rounded to two decimals.
- Okinawa is included from 1973. Seasonal factors are re-estimated each
  January (the note in the file says so); revised history is a new vintage.

Ratios, not indices: ``weight_per_10000`` stays NULL.
"""
import datetime
import json

from . import bls_flat, estat_api, estat_csv, xlsx


class ValidationError(Exception):
    pass


STATS_CODE = "00450222"

DATASET = {
    "slug": "job-openings-jp",
    "title": "Job Openings-to-Applicants Ratio, Japan (MHLW Employment Referrals)",
    "country": "Japan",
    "agency": "Ministry of Health, Labour and Welfare",
    "agency_ja": "厚生労働省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Job openings per job seeker at Japan's public employment offices — the "
        "active openings-to-applicants ratio the press reports beside the "
        "unemployment rate, and the new openings-to-applications ratio — "
        "including part-time, excluding part-time and part-time only, original "
        "and seasonally adjusted, monthly from 1963, from the Ministry of Health, "
        "Labour and Welfare's employment referral statistics."
    ),
}

SOURCE = {
    "source_id": "e-stat:" + STATS_CODE,
    "name": ("Employment Referrals for General Workers — long-run tables 2 (new "
             "openings-to-applications ratio) and 3 (active openings-to-applicants ratio)"),
    "name_ja": "一般職業紹介状況（職業安定業務統計） 長期時系列表 第２表・第３表",
    "url": ("https://www.e-stat.go.jp/stat-search/files?toukei=" + STATS_CODE
            + "&tstat=000001020327"),
    "license_note": (
        "Government of Japan Standard Terms of Use: reuse permitted with "
        "attribution to the Ministry of Health, Labour and Welfare. Located "
        "through the e-Stat API, which requires a free application ID."
    ),
}

DOWNLOAD_URL = "https://www.e-stat.go.jp/stat-search/file-download"
RAW_SUFFIX = ".zip"

# (table number, key, English, the title the sheet must carry)
TABLES = [
    (3, "active", "Active openings-to-applicants ratio", "有効求人倍率"),
    (2, "new", "New openings-to-applications ratio", "新規求人倍率"),
]
# (sheet suffix, key, English, the phrase the sheet title must carry)
SCOPES = [
    ("１（パート含む）", "incl_part", "including part-time", "パートタイムを含む"),
    ("２（パート除く）", "excl_part", "excluding part-time", "パートタイムを除く"),
    ("３（パート）", "part", "part-time only", "パートタイム"),
]
NSA_COLS = ["C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N"]
SA_COLS = ["U", "V", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AE", "AF"]
ADJUSTMENTS = [("sa", "seasonally adjusted", "季節調整値", SA_COLS),
               ("nsa", "original", "実数", NSA_COLS)]
MONTHS_JA = ["１月", "２月", "３月", "４月", "５月", "６月", "７月", "８月", "９月",
             "10月", "11月", "12月"]


def _code(adj, table, scope):
    return "%s.%s.%s" % (adj, table, scope)


# --- fetch ------------------------------------------------------------------

# How far back the catalog is searched. A year without a new edition is a
# broken source, and the ingest should fail rather than quietly re-serve it.
CATALOG_WINDOW_DAYS = 400


def _newest_edition():
    """(survey month, {table number: download url}) of the newest edition."""
    today = datetime.date.today()
    since = today - datetime.timedelta(days=CATALOG_WINDOW_DAYS)
    payload = estat_api.call(
        "getDataCatalog", statsCode=STATS_CODE, searchWord="長期時系列表",
        updatedDate="%s-%s" % (since.strftime("%Y%m%d"), today.strftime("%Y%m%d")),
        limit=100)
    entries = payload["GET_DATA_CATALOG"]["DATA_CATALOG_LIST_INF"]["DATA_CATALOG_INF"]
    if isinstance(entries, dict):
        entries = [entries]
    best = None
    for entry in entries:
        title = entry["DATASET"]["TITLE"]
        if title.get("CYCLE") != "月次":
            continue
        resources = entry["RESOURCES"]["RESOURCE"]
        if isinstance(resources, dict):
            resources = [resources]
        urls = {}
        for r in resources:
            t = r["TITLE"]
            if t.get("TABLE_CATEGORY") == "長期時系列表" and t.get("TABLE_NO") in (2, 3):
                urls[t["TABLE_NO"]] = r["URL"]
        if len(urls) != 2:
            continue
        month = int(title["SURVEY_DATE"])
        if best is None or month > best[0]:
            best = (month, urls)
    if best is None:
        raise ValidationError("e-Stat's catalog lists no edition of long-run tables "
                              "2 and 3 in the last %d days" % CATALOG_WINDOW_DAYS)
    return best


def fetch():
    month, urls = _newest_edition()
    # Which edition and which files, inside the archived artifact itself:
    # the file ids change monthly, so the provenance travels with the data.
    files = {"edition.json": json.dumps(
        {"survey_month": month, "tables": dict((str(k), v) for k, v in sorted(urls.items()))},
        sort_keys=True).encode("utf-8")}
    for number, url in sorted(urls.items()):
        raw = estat_csv.fetch_bytes(url)
        if raw[:2] != b"PK":
            raise ValidationError("table %d is not an .xlsx workbook (got %r…)"
                                  % (number, raw[:16]))
        files["table%d.xlsx" % number] = raw
    return bls_flat.bundle(files)


# --- parse ------------------------------------------------------------------

def _text(row, col):
    cell = row.get(col)
    return xlsx.cell_text(cell).strip() if cell else ""


def _value(text):
    if not text or text in ("***", "-", "－", "…"):
        return None
    try:
        return round(float(text.replace(",", "")), 2)
    except ValueError:
        raise ValidationError("unreadable value %r" % text)


def _year(text):
    """'1963年' -> 1963, else None."""
    if text.endswith("年") and text[:-1].isdigit() and len(text) == 5:
        return int(text[:-1])
    return None


def _check_sheet(name, rows, table_title, scope_phrase):
    title = _text(rows.get(1, {}), "A")
    if table_title not in title or scope_phrase not in title:
        raise ValidationError("sheet %s is titled %r, expected %s / %s"
                              % (name, title, table_title, scope_phrase))
    for adj, _en, label, cols in ADJUSTMENTS:
        for i, col in enumerate(cols):
            if _text(rows.get(3, {}), col) != label:
                raise ValidationError("sheet %s column %s is not %s" % (name, col, label))
            if _text(rows.get(4, {}), col) != MONTHS_JA[i]:
                raise ValidationError("sheet %s column %s is %r, expected %s"
                                      % (name, col, _text(rows.get(4, {}), col), MONTHS_JA[i]))
            if _text(rows.get(5, {}), col) != "倍":
                raise ValidationError("sheet %s column %s is no longer in 倍" % (name, col))


def parse(raw_bytes):
    try:
        files = bls_flat.unbundle(raw_bytes)
    except Exception as exc:
        raise ValidationError("not a bundle: %s" % exc)
    series, observations = [], []
    order = 0
    for number, table, table_en, table_title in TABLES:
        name = "table%d.xlsx" % number
        if name not in files:
            raise ValidationError("bundle is missing %s" % name)
        sheets = xlsx.sheets(files[name])
        for suffix, scope, scope_en, phrase in SCOPES:
            sheet = "第%s表ー%s" % ("２" if number == 2 else "３", suffix)
            if sheet not in sheets:
                raise ValidationError("%s has no sheet %r (sheets: %s)"
                                      % (name, sheet, ", ".join(sheets)))
            rows = sheets[sheet]
            _check_sheet(sheet, rows, table_title, phrase)
            years = [(r, _year(_text(rows[r], "A"))) for r in sorted(rows) if r > 5]
            years = [(r, y) for r, y in years if y is not None]
            for adj, adj_en, _label, cols in ADJUSTMENTS:
                code = _code(adj, table, scope)
                n = 0
                for r, y in years:
                    for m, col in enumerate(cols):
                        v = _value(_text(rows[r], col))
                        if v is None:
                            continue
                        observations.append({"code": code,
                                             "period": datetime.date(y, m + 1, 1),
                                             "value": v})
                        n += 1
                if n:
                    series.append({
                        "code": code,
                        "name_en": "%s, %s, %s" % (table_en, scope_en, adj_en),
                        "name_ja": "%s（%s）%s" % (table_title, phrase.replace("パートタイムを", "パート"),
                                                  _label),
                        "unit": "ratio",
                        "weight_per_10000": None,
                        "sort_order": order,
                    })
                order += 1
    if not observations:
        raise ValidationError("no values parsed")
    return series, observations


# --- validate ---------------------------------------------------------------

STALE_AFTER_DAYS = 100   # published with the Labour Force Survey, ~4 weeks after the month
HEADLINE_FROM = datetime.date(1963, 1, 1)
MAX_MONTHLY_MOVE = 0.8


def validate(series, observations):
    col = {}
    for o in observations:
        c = col.setdefault(o["code"], {})
        if o["period"] in c:
            raise ValidationError("duplicate observation %s %s" % (o["code"], o["period"]))
        c[o["period"]] = o["value"]
    expected = set(_code(a[0], t[1], s[1]) for a in ADJUSTMENTS for t in TABLES for s in SCOPES)
    missing = expected - set(col)
    if missing:
        raise ValidationError("series missing: %s" % ", ".join(sorted(missing)))

    # 1. The headline ratios run unbroken from January 1963, and every
    #    series ends in the same, recent month.
    latest = None
    for code in ("sa.active.incl_part", "nsa.active.incl_part",
                 "sa.new.incl_part", "nsa.new.incl_part"):
        ps = sorted(col[code])
        span = (ps[-1].year - ps[0].year) * 12 + ps[-1].month - ps[0].month + 1
        if ps[0] != HEADLINE_FROM or len(ps) != span:
            raise ValidationError("%s runs %s–%s with %d of %d months"
                                  % (code, ps[0], ps[-1], len(ps), span))
        latest = ps[-1] if latest is None else latest
        if ps[-1] != latest:
            raise ValidationError("%s ends %s, others %s" % (code, ps[-1], latest))
    if (datetime.date.today() - latest).days > 400:
        raise ValidationError("newest month %s is implausibly old" % latest)
    for code in expected:
        if max(col[code]) != latest:
            raise ValidationError("%s ends %s, the release runs to %s"
                                  % (code, max(col[code]), latest))

    # 2. Ranges. The active ratio has run from 0.39 (2009) to 1.76 (1973);
    #    new-openings and part-time ratios run higher. A value outside this
    #    band is a shifted column or a count read as a ratio.
    for code, c in col.items():
        for p, v in c.items():
            if not (0.1 <= v <= 6.0):
                raise ValidationError("%s %s: %.2f out of range" % (code, p, v))

    # 3. A seasonally adjusted ratio moves smoothly. The largest monthly
    #    moves on record are December 1973 (the oil shock, 0.60 on the new
    #    openings ratio) and April 2020 (0.37); a jump past 0.8 is a column
    #    read from the wrong sheet or year, not an economy. Column slips
    #    within a year are caught by the month headers checked in parse.
    checked = 0
    for code in expected:
        if not code.startswith("sa."):
            continue
        ps = sorted(col[code])
        for prev, cur in zip(ps, ps[1:]):
            if abs(col[code][cur] - col[code][prev]) > MAX_MONTHLY_MOVE:
                raise ValidationError("%s %s: %.2f after %.2f — a jump no month on "
                                      "record has made" % (code, cur, col[code][cur],
                                                           col[code][prev]))
            checked += 1
    if checked < 3000:
        raise ValidationError("only %d monthly moves checked" % checked)

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "monthly_moves_checked": checked,
        "active_ratio_sa": col["sa.active.incl_part"][latest],
        "new_ratio_sa": col["sa.new.incl_part"][latest],
    }


# --- presentation -----------------------------------------------------------

PRESENTATION = {
    "credit_line": ("Source: Ministry of Health, Labour and Welfare, "
                    "Employment Referrals for General Workers."),
    "stale_after_days": STALE_AFTER_DAYS,
    "overview_tiles": [
        {"key": "active", "code": "sa.active.incl_part",
         "label": "Active openings ratio", "type": "level"},
        {"key": "new", "code": "sa.new.incl_part",
         "label": "New openings ratio", "type": "level"},
        {"key": "active_ft", "code": "sa.active.excl_part",
         "label": "Active ratio, excl. part-time", "type": "level"},
        {"key": "active_pt", "code": "sa.active.part",
         "label": "Active ratio, part-time", "type": "level"},
    ],
    "main_series": [
        {"role": "headline", "code": "sa.active.incl_part",
         "label": "Active openings-to-applicants ratio", "slot": 1},
        {"role": "new", "code": "sa.new.incl_part",
         "label": "New openings-to-applications ratio", "slot": 2},
    ],
    # A ratio of counts: its change is read in points, never as a
    # percentage of itself.
    "kind_default": "rate",
}


MANIFEST = {
    "id": DATASET["slug"],
    "section": "labour",
    "name": {"en": "Job openings-to-applicants ratio — Hello Work",
             "ja": "一般職業紹介状況 有効求人倍率・新規求人倍率"},
    "shape": "series",
    "summary": DATASET["description"],
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"],
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "1963-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published ratio (openings per applicant)",
         "unit": "x", "trust": "official"},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/labour.html?dataset=job-openings-jp",
    "page": "/labour.html",
    "notes": [
        "A ratio of 1.18 means 118 job openings for every 100 people looking "
        "for work through Hello Work, the public employment offices. Openings "
        "and seekers who never use Hello Work are not counted.",
        "Codes are adjustment.ratio.scope — sa/nsa; active (有効求人倍率) or new "
        "(新規求人倍率); incl_part (the headline), excl_part or part.",
        "Okinawa is included from 1973.",
        "Seasonally adjusted values are revised each January; each revision is "
        "a new vintage and the earlier figure stays retrievable with as_of.",
    ],
}
