"""Shared helpers for e-Stat long-run CPI CSV files.

Several Statistics Bureau CPI files share one layout:
    row 0  Japanese names          類・品目, 総合, ...
    row 1  English names           Group/Item, All items, ...
    row 2  item codes              類・品目符号(Group/Item code), 0001, ...
    row 3  serial numbers          含類総連番(Serial number), 001, ...
    row 4  raw weights             ウエイト(Weight), ...
    row 5  weights per 10000       ウエイト１万分比(Weight per 10000), ...
    row 6+ data                    YYYYMM, value, value, ...  (blank = not collected)

Adapters import from here so parsing lives in one place; everything
dataset-specific (source identity, validation gates, presentation)
stays in the adapter.
"""
import csv
import datetime
import io
import urllib.request

USER_AGENT = "ObservatoryIngest/0.1 (data pipeline; contact: repo owner)"


class ValidationError(Exception):
    pass


def fetch_bytes(url):
    """Download raw bytes from an e-Stat file-download URL."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_long_csv(raw_bytes):
    """Parse raw CSV bytes -> (series list, observations list).

    series:       [{code, name_en, name_ja, weight_per_10000, sort_order}]
    observations: [{code, period (date), value (float)}]
    Blank cells are omitted entirely — missing is never zero.
    """
    text = raw_bytes.decode("cp932")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 10:
        raise ValidationError("file too short to be a CPI table")

    ja_names, en_names, codes = rows[0], rows[1], rows[2]
    w10k = rows[5]
    if ja_names[0] != "類・品目":
        raise ValidationError("unexpected header row 0: %r" % ja_names[0][:40])
    if not codes[0].startswith("類・品目符号"):
        raise ValidationError("unexpected code row: %r" % codes[0][:40])
    if "１万分比" not in w10k[0]:
        raise ValidationError("unexpected weight row: %r" % w10k[0][:40])

    series = []
    col_code = {}
    for i in range(1, len(ja_names)):
        code = codes[i].strip() if i < len(codes) else ""
        if not code:
            continue
        weight = None
        if i < len(w10k) and w10k[i].strip():
            weight = float(w10k[i].replace(",", ""))
        series.append({
            "code": code,
            "name_en": (en_names[i].strip() if i < len(en_names) else "") or ja_names[i].strip(),
            "name_ja": ja_names[i].strip(),
            "weight_per_10000": weight,
            "sort_order": i,
        })
        col_code[i] = code

    seen = set()
    for s in series:
        if s["code"] in seen:
            raise ValidationError("duplicate series code %s" % s["code"])
        seen.add(s["code"])

    observations = []
    for row in rows[6:]:
        if not row or not row[0].strip():
            continue
        p = row[0].strip()
        if len(p) != 6 or not p.isdigit():
            continue  # trailing note rows
        period = datetime.date(int(p[:4]), int(p[4:6]), 1)
        for i, code in col_code.items():
            if i >= len(row):
                continue
            cell = row[i].strip()
            if not cell:
                continue
            try:
                value = float(cell.replace(",", ""))
            except ValueError:
                continue  # footnote markers etc.
            observations.append({"code": code, "period": period, "value": value})
    return series, observations


def check_common(series, observations, min_series, min_observations, required_ja):
    """Shared validation gates. Raises ValidationError; returns a summary dict."""
    if len(series) < min_series:
        raise ValidationError("only %d series parsed" % len(series))
    if len(observations) < min_observations:
        raise ValidationError("only %d observations parsed" % len(observations))

    by_ja = {s["name_ja"]: s["code"] for s in series}
    for required in required_ja:
        if required not in by_ja:
            raise ValidationError("required aggregate missing: %s" % required)

    latest = max(o["period"] for o in observations)
    if latest < datetime.date(2025, 1, 1):
        raise ValidationError("latest period %s implausibly old" % latest)

    headline = by_ja["総合"]
    head_latest = [o for o in observations if o["code"] == headline and o["period"] == latest]
    if not head_latest:
        raise ValidationError("headline has no value for latest period %s" % latest)
    v = head_latest[0]["value"]
    if not (50.0 < v < 300.0):
        raise ValidationError("headline index %s outside sanity range" % v)

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "headline_latest": v,
    }
