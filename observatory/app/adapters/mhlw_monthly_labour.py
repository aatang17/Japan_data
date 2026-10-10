"""Adapter: Monthly Labour Survey — wages, hours and employment, Japan (MHLW).

Source: 厚生労働省 毎月勤労統計調査 全国調査, the long-run cumulative files
「実数・指数累積データ」 that e-Stat serves as CSV under two fixed statInfIds:
000032189776 (実数 — yen amounts, hours, days and headcounts) and
000032189777 (指数・伸び率 — the Ministry's indices, 2020 = 100, including
the real wage index). The Ministry replaces both in place when each month's
final figures (確報) are published, about eight weeks after the month; the
preliminary figures (速報) two weeks earlier are not in these files.

This is the source of Japan's monthly wage and real-wage numbers. What is
taken: all industries (調査産業計) and manufacturing (製造業); establishments
with five or more employees (the headline, from 1990) and thirty or more
(from 1970); all workers, full-time (一般労働者) and part-time
(パートタイム労働者). The codes in the files were verified against the
Ministry's labelled Excel tables before this adapter was written — July 2026's
real wage index reads 117.1 in both (table 25-1, 5+ employees, all workers).

Facts the parser and the gates rely on:

- **Wage growth is the Ministry's published figure, stored as published.**
  The 伸び率 rows of the index file carry the Ministry's year-on-year growth
  rates, and they are taken as official series (``real_wage_yoy`` and
  kin). They cannot be recomputed from the published indices everywhere:
  the index level steps up between December 2023 and January 2024, and in
  every month of 2024 growth computed from the index overstates the
  Ministry's published rate by 2 to 4 pp (June 2024 total cash earnings:
  +8.0% from the index, +4.5% published). Elsewhere the two agree to
  rounding — 95% of months since 2012 within 0.3 pp, which validate()
  gates on. The yen averages jump whenever the sample rotates, so yen,
  hours and days are marked as flows and the API refuses a percentage
  change of them.
- **The real wage index** is the nominal index deflated by the CPI excluding
  imputed rent (持家の帰属家賃を除く総合), the Ministry's long-standing
  headline deflator — verified against table 25-1, which names it.
- Yen amounts are monthly averages per worker in yen; hours are per worker
  per month; the employee count is the end-of-month count in persons.
  Nothing is rescaled.
- Only monthly rows are taken. Calendar-year rows (月 = CY) are read only to
  check that the indices average 100 in 2020; the growth-rate rows (伸び率)
  are not stored, because the platform calculates growth and shows the formula.
- Blank cells are missing, never zero: the 30+ file has no overtime or
  special pay before 1990, part-time splits start in 1993, and so on.

Levels and indices, not CPI weights: ``weight_per_10000`` stays NULL.
"""
import csv
import datetime
import http.client
import io
import time
import urllib.error

from . import bls_flat, estat_csv


class ValidationError(Exception):
    pass


LEVELS_ID = "000032189776"
INDEX_ID = "000032189777"

DATASET = {
    "slug": "wages-jp",
    "title": "Monthly Labour Survey — Wages, Hours and Employment, Japan (MHLW)",
    "country": "Japan",
    "agency": "Ministry of Health, Labour and Welfare",
    "agency_ja": "厚生労働省",
    "base": "2020 = 100",
    "frequency": "monthly",
    "description": (
        "What Japanese employees earn and work each month, from the Ministry of "
        "Health, Labour and Welfare's Monthly Labour Survey: the Ministry's "
        "published wage and real-wage growth rates; total, contractual, "
        "scheduled, overtime and special (bonus) pay in yen, hours and days "
        "worked, employment, and the Ministry's wage and real-wage indices "
        "(2020 = 100), for all industries and manufacturing, establishments with "
        "5+ employees (from 1990) and 30+ (from 1970), all, full-time and "
        "part-time workers. Final figures, as published."
    ),
}

SOURCE = {
    "source_id": "e-stat:%s+%s" % (LEVELS_ID, INDEX_ID),
    "name": ("Monthly Labour Survey, national — long-run cumulative data: "
             "actual figures, and indices and growth rates"),
    "name_ja": "毎月勤労統計調査 全国調査 長期時系列表 実数・指数累積データ",
    "url": "https://www.mhlw.go.jp/toukei/list/30-1a.html",
    "license_note": (
        "Government of Japan Standard Terms of Use: reuse permitted with "
        "attribution to the Ministry of Health, Labour and Welfare."
    ),
}

FILE_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=%s&fileKind=1"
DOWNLOAD_URL = FILE_URL % LEVELS_ID
RAW_SUFFIX = ".zip"

# Header row of each file, checked whole: a column added, dropped or moved
# would put a number under the wrong name.
LEVELS_HEADER = ["種別", "年", "月", "産業分類", "規模", "就業形態", "現金給与総額",
                 "きまって支給する給与", "所定内給与", "所定外給与", "特別給与",
                 "総実労働時間", "所定内労働時間", "所定外労働時間", "出勤日数",
                 "前月末労働者数", "増加労働者数", "減少労働者数", "本月末労働者数",
                 "パートタイム労働者数"]
INDEX_HEADER = ["種別", "年", "月", "産業分類", "規模", "就業形態", "現金給与総額",
                "きまって支給する給与", "所定内給与", "所定外給与", "特別給与",
                "実質賃金指数（現金給与総額）", "実質賃金指数（きまって支給する給与）",
                "総実労働時間", "所定内労働時間", "所定外労働時間", "出勤日数", "常用雇用",
                "パートタイム労働者比率", "入職率", "離職率"]

# (file, column, key, English, unit, kind)
MEASURES = [
    ("levels", "現金給与総額", "cash_earnings", "Total cash earnings", "jpy", "flow"),
    ("levels", "きまって支給する給与", "contractual_earnings", "Contractual earnings", "jpy", "flow"),
    ("levels", "所定内給与", "scheduled_earnings", "Scheduled earnings", "jpy", "flow"),
    ("levels", "所定外給与", "overtime_pay", "Overtime pay", "jpy", "flow"),
    ("levels", "特別給与", "special_earnings", "Special earnings (bonuses)", "jpy", "flow"),
    ("index", "実質賃金指数（現金給与総額）", "real_wage_index",
     "Real wage index (total cash earnings)", "index", "index"),
    ("index", "実質賃金指数（きまって支給する給与）", "real_contractual_index",
     "Real wage index (contractual earnings)", "index", "index"),
    ("index", "現金給与総額", "cash_earnings_index", "Total cash earnings index", "index", "index"),
    ("index", "きまって支給する給与", "contractual_earnings_index",
     "Contractual earnings index", "index", "index"),
    ("index", "所定内給与", "scheduled_earnings_index", "Scheduled earnings index", "index", "index"),
    ("levels", "総実労働時間", "hours_total", "Total hours worked", "hours", "flow"),
    ("levels", "所定内労働時間", "hours_scheduled", "Scheduled hours worked", "hours", "flow"),
    ("levels", "所定外労働時間", "hours_overtime", "Overtime hours worked", "hours", "flow"),
    ("levels", "出勤日数", "days_worked", "Days worked", "days", "flow"),
    ("index", "総実労働時間", "hours_total_index", "Total hours worked index", "index", "index"),
    ("index", "所定外労働時間", "hours_overtime_index", "Overtime hours index", "index", "index"),
    ("levels", "本月末労働者数", "employees", "Regular employees, end of month", "persons", "stock"),
    ("index", "常用雇用", "employment_index", "Regular employment index", "index", "index"),
    ("index", "パートタイム労働者比率", "part_time_share", "Part-time share of employees",
     "percent", "rate"),
    ("index", "入職率", "hiring_rate", "Accession rate (hires)", "percent", "rate"),
    ("index", "離職率", "separation_rate", "Separation rate", "percent", "rate"),
]
# The Ministry's own year-on-year growth rates (前年同月比, %), from the 伸び率
# rows of the index file: (index column, key, English). These are the wage
# growth figures the Ministry and the press report, and they are stored as
# published because they cannot be recomputed from the published indices
# across a break — see the docstring.
GROWTH = [
    ("実質賃金指数（現金給与総額）", "real_wage_yoy", "Real wages (total cash earnings)"),
    ("実質賃金指数（きまって支給する給与）", "real_contractual_yoy",
     "Real wages (contractual earnings)"),
    ("現金給与総額", "cash_earnings_yoy", "Total cash earnings"),
    ("きまって支給する給与", "contractual_earnings_yoy", "Contractual earnings"),
    ("所定内給与", "scheduled_earnings_yoy", "Scheduled earnings"),
    ("総実労働時間", "hours_total_yoy", "Total hours worked"),
    ("所定外労働時間", "hours_overtime_yoy", "Overtime hours"),
    ("常用雇用", "employment_yoy", "Regular employment"),
]
GROWTH_LABEL = "伸び率、日数差、ポイント差"

# (file code, key, English, Japanese)
INDUSTRIES = [("TL", "all", "all industries", "調査産業計"),
              ("E", "manufacturing", "manufacturing", "製造業")]
# Short English: the series name is a table cell and a chart legend. The
# full wording ("establishments with 5 or more employees") is in the notes.
SIZES = [("T", "5plus", "5+ employees", "5人以上"),
         ("0", "30plus", "30+ employees", "30人以上")]
FORMS = [("0", "all", "all workers", "就業形態計"),
         ("1", "fulltime", "full-time", "一般労働者"),
         ("2", "parttime", "part-time", "パートタイム労働者")]
INDUSTRY_BY = dict((i[0], i) for i in INDUSTRIES)
SIZE_BY = dict((s[0], s) for s in SIZES)
FORM_BY = dict((f[0], f) for f in FORMS)


def _code(measure, industry, size, form):
    return "%s.%s.%s.%s" % (measure, industry, size, form)


# --- fetch ------------------------------------------------------------------

# The two files are 20 MB and 16 MB, and e-Stat drops a large transfer
# part-way often enough to matter: the first local ingest died with
# IncompleteRead at 7 of 20 MB. A short pause and another try is enough.
FETCH_ATTEMPTS = 3


def _download(url):
    last = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            return estat_csv.fetch_bytes(url)
        except (http.client.IncompleteRead, urllib.error.URLError, ConnectionError) as exc:
            last = exc
            if attempt < FETCH_ATTEMPTS - 1:
                time.sleep(10 * (attempt + 1))
    raise last


def fetch():
    files = {}
    for name, sid, header in (("levels.csv", LEVELS_ID, LEVELS_HEADER),
                              ("index.csv", INDEX_ID, INDEX_HEADER)):
        raw = _download(FILE_URL % sid)
        # e-Stat answers a moved file with an HTML page and status 200;
        # archiving that as a data file would poison the next diff.
        if not raw[:40].decode("cp932", "replace").startswith(header[0]):
            raise ValidationError("%s is not the expected CSV (got %r…)" % (name, raw[:40]))
        files[name] = raw
    # Zipped: the two files are 37 MB of text that compresses about tenfold,
    # and the archive keeps every monthly vintage.
    return bls_flat.bundle(files)


# --- parse ------------------------------------------------------------------

def _rows(raw, header, name):
    text = raw.decode("cp932")
    reader = csv.reader(io.StringIO(text))
    got = [h.strip() for h in next(reader)]
    if got != header:
        raise ValidationError("%s header changed: %s" % (name, got))
    for row in reader:
        if row:
            yield [c.strip() for c in row]


def _value(text):
    if text == "":
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        raise ValidationError("unreadable value %r" % text)


def _read(files):
    """{(file, column, industry, size, form): {period: value}} for the
    selected cells, and the calendar-2020 index averages for the base gate."""
    cells = {}
    base_2020 = {}
    for name, header, kind_label in (("levels", LEVELS_HEADER, "実数"),
                                     ("index", INDEX_HEADER, "指数")):
        fname = name + ".csv"
        if fname not in files:
            raise ValidationError("bundle is missing %s" % fname)
        wanted = [m[1] for m in MEASURES if m[0] == name]
        positions = dict((col, header.index(col)) for col in wanted)
        growth_pos = dict((g[0], header.index(g[0])) for g in GROWTH) if name == "index" else {}
        for row in _rows(files[fname], header, fname):
            if row[0] == GROWTH_LABEL and growth_pos:
                ind, size, form = (INDUSTRY_BY.get(row[3]), SIZE_BY.get(row[4]),
                                   FORM_BY.get(row[5]))
                if ind is None or size is None or form is None or not row[2].isdigit():
                    continue
                period = datetime.date(int(row[1]), int(row[2]), 1)
                for col, pos in growth_pos.items():
                    v = _value(row[pos]) if pos < len(row) else None
                    if v is not None:
                        cells.setdefault(("growth", col, ind[1], size[1], form[1]), {})[period] = v
                continue
            if row[0] != kind_label:
                continue
            ind, size, form = INDUSTRY_BY.get(row[3]), SIZE_BY.get(row[4]), FORM_BY.get(row[5])
            if ind is None or size is None or form is None:
                continue
            year, month = row[1], row[2]
            if month == "CY":
                if name == "index" and year == "2020":
                    for col, pos in positions.items():
                        v = _value(row[pos]) if pos < len(row) else None
                        if v is not None:
                            base_2020[(col, ind[1], size[1], form[1])] = v
                continue
            if not (year.isdigit() and month.isdigit() and 1 <= int(month) <= 12):
                raise ValidationError("%s: unreadable period %r/%r" % (fname, year, month))
            period = datetime.date(int(year), int(month), 1)
            for col, pos in positions.items():
                v = _value(row[pos]) if pos < len(row) else None
                if v is None:
                    continue
                key = (name, col, ind[1], size[1], form[1])
                bucket = cells.setdefault(key, {})
                if period in bucket:
                    raise ValidationError("%s: two rows for %s %s" % (fname, key, period))
                bucket[period] = v
    return cells, base_2020


def _check_base(base):
    """The indices average 100 over 2020, the base the Ministry states. The
    calendar-year rows this reads are not stored, so the gate runs here
    rather than in validate()."""
    checked = 0
    index_cols = set(m[1] for m in MEASURES if m[0] == "index" and m[4] == "index")
    for (col, ind, size, form), v in sorted(base.items()):
        if col not in index_cols:
            continue
        if abs(v - 100.0) > 0.05:
            raise ValidationError("%s %s/%s/%s averages %.1f over 2020, not 100 — "
                                  "the index base moved" % (col, ind, size, form, v))
        checked += 1
    if checked < 50:
        raise ValidationError("only %d index bases checked" % checked)


def parse(raw_bytes):
    try:
        files = bls_flat.unbundle(raw_bytes)
    except Exception as exc:
        raise ValidationError("not a bundle: %s" % exc)
    cells, base = _read(files)
    _check_base(base)
    series, observations = [], []
    order = 0
    for _ic, ind, ind_en, ind_ja in INDUSTRIES:
        for _sc, size, size_en, size_ja in SIZES:
            for _fc, form, form_en, form_ja in FORMS:
                # The published growth rates lead each group: they are the
                # figures a reader comes for.
                rows = ([("growth", g[0], g[1], g[2] + ", YoY",
                          "percent", "rate") for g in GROWTH] + MEASURES)
                for fname, col, key, en, unit, _kind in rows:
                    values = cells.get((fname, col, ind, size, form))
                    order += 1
                    if not values:
                        continue
                    code = _code(key, ind, size, form)
                    series.append({
                        "code": code,
                        "name_en": "%s — %s, %s, %s" % (en, ind_en, size_en, form_en),
                        "name_ja": "%s%s %s %s %s" % (col, "（前年同月比）" if fname == "growth" else "",
                                                     ind_ja, size_ja, form_ja),
                        "unit": unit,
                        "weight_per_10000": None,
                        "sort_order": order,
                    })
                    for period in sorted(values):
                        observations.append({"code": code, "period": period,
                                             "value": values[period]})
    if not observations:
        raise ValidationError("no values parsed")
    return series, observations


# --- validate ---------------------------------------------------------------

# Final figures for a month arrive about eight weeks after it ends: a month
# dated by its first day is ~90 days old on arrival and ~120 the day before
# the next. Grace on top.
STALE_AFTER_DAYS = 130
HEADLINE = "real_wage_index.all.5plus.all"
COVERAGE = [  # (series, first month it must start in, unbroken to the newest)
    ("real_wage_index.all.5plus.all", datetime.date(1990, 1, 1)),
    ("cash_earnings.all.5plus.all", datetime.date(1990, 1, 1)),
    ("cash_earnings_index.all.30plus.all", datetime.date(1970, 1, 1)),
    ("cash_earnings.all.30plus.all", datetime.date(1970, 1, 1)),
]
# Bonus and overtime amounts are legitimately a few thousand yen, or a few
# hours, in a quiet month, so yen and hours floor at zero; the identities
# below are what catch a column read into the wrong measure.
RANGES = {"jpy": (0.0, 3000000.0), "hours": (0.0, 260.0), "days": (3.0, 31.0),
          "index": (0.5, 400.0), "percent": (0.0, 100.0), "persons": (1.0, 1e8)}


def _span(a, b):
    return (b.year - a.year) * 12 + b.month - a.month + 1


def validate(series, observations):
    unit_of = dict((s["code"], s["unit"]) for s in series)
    col = {}
    for o in observations:
        c = col.setdefault(o["code"], {})
        if o["period"] in c:
            raise ValidationError("duplicate observation %s %s" % (o["code"], o["period"]))
        c[o["period"]] = o["value"]

    # 1. Coverage: the headline lines run unbroken from where the Ministry's
    #    long-run file starts them, and end together in a recent month.
    latest = max(col[HEADLINE]) if HEADLINE in col else None
    if latest is None:
        raise ValidationError("no %s series" % HEADLINE)
    for code, start in COVERAGE:
        ps = sorted(col.get(code, {}))
        if not ps or ps[0] != start or ps[-1] != latest or len(ps) != _span(ps[0], ps[-1]):
            raise ValidationError("%s should run unbroken %s–%s; it has %d months %s–%s"
                                  % (code, start, latest, len(ps),
                                     ps[0] if ps else None, ps[-1] if ps else None))
    if (datetime.date.today() - latest).days > 400:
        raise ValidationError("newest month %s is implausibly old" % latest)
    stale = [c for c in col if c.endswith(".all") and max(col[c]) != latest
             and ".5plus." in c]
    if stale:
        raise ValidationError("5+ series ending before %s: %s" % (latest, ", ".join(stale[:5])))

    # 2. Ranges per unit: catches a yen amount read as hours, or a count as
    #    an index.
    growth_keys = set(g[1] for g in GROWTH)
    for code, c in col.items():
        # A growth rate can fall: overtime hours dropped by over a third
        # in 2009. The band catches a level read as a rate.
        lo, hi = ((-80.0, 150.0) if code.split(".")[0] in growth_keys
                  else RANGES[unit_of[code]])
        for p, v in c.items():
            if not (lo <= v <= hi):
                raise ValidationError("%s %s: %r out of range for %s"
                                      % (code, p, v, unit_of[code]))

    # 3. Identities on the yen and hours: total = contractual + special;
    #    contractual = scheduled + overtime pay; total hours = scheduled +
    #    overtime hours. Averages are rounded to the yen and to 0.1 hour.
    checked = 0
    for code in col:
        parts = code.split(".", 1)
        if parts[0] != "cash_earnings":
            continue
        rest = parts[1]
        tot, con = col[code], col.get("contractual_earnings." + rest, {})
        spe = col.get("special_earnings." + rest, {})
        sch, ovt = col.get("scheduled_earnings." + rest, {}), col.get("overtime_pay." + rest, {})
        ht, hs, ho = (col.get("hours_total." + rest, {}), col.get("hours_scheduled." + rest, {}),
                      col.get("hours_overtime." + rest, {}))
        for p, t in tot.items():
            if p in con and p in spe:
                if abs(t - (con[p] + spe[p])) > YEN_TOLERANCE:
                    raise ValidationError("%s %s: total %.0f ≠ contractual %.0f + special %.0f"
                                          % (rest, p, t, con[p], spe[p]))
                checked += 1
            if p in con and p in sch and p in ovt:
                if abs(con[p] - (sch[p] + ovt[p])) > YEN_TOLERANCE:
                    raise ValidationError("%s %s: contractual %.0f ≠ scheduled %.0f + "
                                          "overtime %.0f" % (rest, p, con[p], sch[p], ovt[p]))
                checked += 1
            if p in ht and p in hs and p in ho:
                if abs(ht[p] - (hs[p] + ho[p])) > HOURS_TOLERANCE:
                    raise ValidationError("%s %s: hours %.1f ≠ %.1f + %.1f"
                                          % (rest, p, ht[p], hs[p], ho[p]))
                checked += 1
    if checked < 10000:
        raise ValidationError("only %d identities checked" % checked)

    # 4. The published growth rates belong to the indices beside them: the
    #    rate computed from the index agrees with the Ministry's to within
    #    rounding in almost every month. It does not across a level break
    #    (every month of 2024 misses by 2 to 4 pp — the index steps up in
    #    January 2024 and the Ministry's rates bridge the step), so the gate
    #    asks for agreement in most months, not all; a growth column paired
    #    with the wrong index would agree in almost none.
    agree = compared = 0
    for col_ja, gkey, _en in GROWTH:
        ikey = dict((m[1], m[2]) for m in MEASURES if m[0] == "index")[col_ja]
        for code in col:
            if not code.startswith(gkey + "."):
                continue
            idx = col.get(ikey + code[len(gkey):], {})
            for p, g in col[code].items():
                if p.year < 2012:
                    continue
                a, b = idx.get(p), idx.get(datetime.date(p.year - 1, p.month, 1))
                if a is None or not b:
                    continue
                compared += 1
                if abs((a / b - 1) * 100 - g) <= GROWTH_AGREEMENT_PP:
                    agree += 1
    if compared < 5000 or agree < GROWTH_AGREEMENT_SHARE * compared:
        raise ValidationError("published growth agrees with its index in only %d of %d "
                              "months" % (agree, compared))

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "identities_checked": checked,
        "growth_months_agreeing": "%d of %d" % (agree, compared),
        "real_wage_yoy": col.get("real_wage_yoy.all.5plus.all", {}).get(latest),
        "real_wage_index": col[HEADLINE][latest],
        "cash_earnings_jpy": col["cash_earnings.all.5plus.all"][latest],
    }


YEN_TOLERANCE = 2.0
GROWTH_AGREEMENT_PP = 0.3
GROWTH_AGREEMENT_SHARE = 0.85
HOURS_TOLERANCE = 0.15


# --- presentation -----------------------------------------------------------

KINDS = dict((_code(m[2], i[1], s[1], f[1]), m[5])
             for m in MEASURES for i in INDUSTRIES for s in SIZES for f in FORMS)
# A published growth rate is a percentage: its change is read in points.
KINDS.update((_code(g[1], i[1], s[1], f[1]), "rate")
             for g in GROWTH for i in INDUSTRIES for s in SIZES for f in FORMS)

PRESENTATION = {
    "credit_line": "Source: Ministry of Health, Labour and Welfare, Monthly Labour Survey.",
    "stale_after_days": STALE_AFTER_DAYS,
    # The Ministry's published growth rates lead: they are the numbers the
    # press reports. The yen tile compares with the same month a year
    # earlier, because a month-on-month change in unadjusted pay is mostly
    # the bonus calendar.
    "overview_tiles": [
        {"key": "real", "code": "real_wage_yoy.all.5plus.all",
         "label": "Real wages, YoY", "type": "level"},
        {"key": "cash", "code": "cash_earnings_yoy.all.5plus.all",
         "label": "Total cash earnings, YoY", "type": "level"},
        {"key": "scheduled", "code": "scheduled_earnings_yoy.all.5plus.fulltime",
         "label": "Base pay, full-time, YoY", "type": "level"},
        {"key": "cash_yen", "code": "cash_earnings.all.5plus.all",
         "label": "Total cash earnings", "type": "level", "compare_months": 12},
    ],
    "main_series": [
        {"role": "real", "code": "real_wage_yoy.all.5plus.all",
         "label": "Real wages, change on a year earlier", "slot": 1},
        {"role": "nominal", "code": "cash_earnings_yoy.all.5plus.all",
         "label": "Total cash earnings, change on a year earlier", "slot": 2},
        {"role": "scheduled", "code": "scheduled_earnings_yoy.all.5plus.fulltime",
         "label": "Base pay, full-time, change on a year earlier", "slot": 3},
    ],
    "kinds": KINDS,
}


MANIFEST = {
    "id": DATASET["slug"],
    "section": "labour",
    "name": {"en": "Wages, hours and employment — Monthly Labour Survey",
             "ja": "毎月勤労統計調査 賃金・労働時間・雇用"},
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
        "as_of_supported": True, "history_from": "1970-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published value — the indices are 2020 = 100; yen, "
                                 "hours, days and persons series carry their own unit",
         "unit": "index", "trust": "official"},
        {"id": "yoy", "label": "Change on a year earlier", "unit": "%", "trust": "derived",
         "where": "index and employment series only (yen, hours and days are refused "
                  "it); across January 2024 it overstates the Ministry's published growth "
                  "by 2–4 pp — use the _yoy series, which are the Ministry's own rates",
         "calc": "(index[t] / index[t−12 months] − 1) × 100, from published index values."},
        {"id": "mom", "label": "Change on the month before", "unit": "%", "trust": "derived",
         "where": "index and employment series only; not seasonally adjusted, so "
                  "mostly the bonus calendar",
         "calc": "(index[t] / index[t−1 month] − 1) × 100, from published index values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/labour.html?dataset=wages-jp",
    "page": "/labour.html",
    "notes": [
        "Wage growth is the Ministry's published year-on-year rate "
        "(codes ending _yoy), stored as published. Do not compute it across "
        "January 2024 from the indices: the index level steps up there, and "
        "growth computed from it overstates the published rate by 2–4 pp in "
        "every month of 2024. Change on the yen amounts is never the "
        "Ministry's wage growth.",
        "The real wage index is deflated by the CPI excluding imputed rent "
        "(持家の帰属家賃を除く総合), as in the Ministry's table 25-1.",
        "Not seasonally adjusted. June, July and December carry the summer and "
        "winter bonuses; compare a month with the same month a year earlier.",
        "Final figures (確報) only; the preliminary release two weeks earlier is "
        "not in the Ministry's cumulative files.",
        "Codes are measure.industry.size.workers — industry all or "
        "manufacturing; size 5plus or 30plus, establishments with 5 or more "
        "(from 1990) or 30 or more (from 1970) employees; workers "
        "all, fulltime (一般労働者) or parttime.",
    ],
}
