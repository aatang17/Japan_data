"""Adapter: semiconductor inputs — HS-detail customs lines, by partner country.

The concept-commodity tables behind `trade-semis` stop at the level the
Ministry aggregates to for its monthly commentary, and silicon wafers — the
raw material of every chip — are not a line there at all. They are a line in
the HS-detail tables (品別国別表): the same monthly value and quantity by
partner, one level down, for 5,700-odd nine-digit tariff lines.

This adapter reads a **curated** handful of those lines, starting with wafers,
and shares everything it can with `mof_trade`: the year-block cache keyed on
the Ministry's own UPDATED_DATE, the partner table, the coverage rule for
months the table has not reached, and the series-code shape — so the same
`/trade` surface serves both datasets unchanged.

Two HS-table facts that differ from the concept tables and shaped this code:

- **The commodity axis carries no names.** e-Stat returns the nine-digit code
  as the label. Names here are curated from the Customs tariff schedule and
  must be added by hand for every line ingested; an uncurated line is refused
  at import rather than served as a bare number.
- **Quantity sits in the second unit column.** `cat02` has two unit slots
  (単位1/単位2) and, per month, 数量1 / 数量2 / 金額. For these lines 数量1 is
  empty and the kilogram figure is in 数量2. A parser reading the first slot
  produces a column of zeros — which is exactly what the zero-versus-missing
  rule exists to catch.

Wafers are HS 3818.00: "chemical elements doped for use in electronics, in
the form of discs, wafers or similar forms". Japan's tariff splits it into
-100 (silicon) and -900 (other); the residual is kept separate and never
added to the silicon line.
"""
import datetime
import gzip
import json

from . import estat_api, mof_trade
from .mof_trade import (PARTNER_EN, PARTNER_JA, PARTNERS, REGIONS, REGION_LABEL,  # noqa: F401
                        partner_region, _cached, _class_names, _number)


class ValidationError(Exception):
    pass


# e-Stat statsDataId per year-block — the HS-detail (品別国別表) siblings of the
# concept tables in mof_trade. Same 2001 start, for the same boot-time reason.
TABLES = [
    ("0003228116", "exp", "2001-2005"),
    ("0003228117", "exp", "2006-2010"),
    ("0003228118", "exp", "2011-2015"),
    ("0003313965", "exp", "2016-2020"),
    ("0003425293", "exp", "2021-2025"),
    ("0004049306", "exp", "2026-"),
    ("0003228183", "imp", "2001-2005"),
    ("0003228184", "imp", "2006-2010"),
    ("0003228185", "imp", "2011-2015"),
    ("0003313966", "imp", "2016-2020"),
    ("0003425294", "imp", "2021-2025"),
    ("0004049326", "imp", "2026-"),
]
LIST_SEARCH = "品別国別表"

# (HS statistical code, English label, Japanese label, sort order, level,
# chart label), per direction. Names come from the Customs tariff schedule
# (実行関税率表 / 輸出統計品目表), not from e-Stat, which has none for this axis.
# Japan's statistical codes split HS 3818.00 differently on the two schedules
# — export -100/-900, import -010/-020 — and the import split's silicon line
# was confirmed by its signature (¥48k/kg, 1.8m kg, China/US/Taiwan/Korea as
# sources) against the residual's (¥709k/kg, 48t: compound substrates).
COMMODITIES = {
    "exp": [
        ("381800100", "Silicon wafers (doped, for electronics)",
         "シリコンウエハー（電子工業用にドープ処理したもの）", 0, "item", "Silicon wafers"),
        ("381800900", "Other doped elements for electronics",
         "その他のドープ処理した化学元素（電子工業用）", 1, "item", "Other doped elements"),
    ],
    "imp": [
        ("381800010", "Silicon wafers (doped, for electronics)",
         "シリコンウエハー（電子工業用にドープ処理したもの）", 0, "item", "Silicon wafers"),
        ("381800020", "Other doped elements for electronics",
         "その他のドープ処理した化学元素（電子工業用）", 1, "item", "Other doped elements"),
    ],
}
CODES = dict((flow, [c for c, _e, _j, _o, _k, _s in rows]) for flow, rows in COMMODITIES.items())
FLAGSHIP = {"exp": "381800100", "imp": "381800010"}

# cat02: two unit slots, three year totals, then per month 数量1 / 数量2 / 金額
# starting at 150 and stepping by 30.
UNIT_FIELDS = {"100": 1, "110": 2}
MONTH_FIELDS = {}
for _m in range(1, 13):
    MONTH_FIELDS[str(150 + (_m - 1) * 30)] = (_m, "qty1")
    MONTH_FIELDS[str(160 + (_m - 1) * 30)] = (_m, "qty2")
    MONTH_FIELDS[str(170 + (_m - 1) * 30)] = (_m, "val")

VALUE_UNIT = mof_trade.VALUE_UNIT
FIRST_YEAR = 2001


DATASET = {
    "slug": "trade-inputs",
    "title": "Semiconductor Inputs — Wafers by Partner (HS detail)",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly Japanese exports and imports of silicon wafers (HS 3818.00) "
        "by partner country from January 2001, from the HS-detail commodity by "
        "country tables of the Trade Statistics of Japan. Value in thousands "
        "of yen and quantity in kilograms, exactly as released by the Ministry "
        "of Finance. The raw material one step upstream of the chips in "
        "trade-semis."
    ),
}

SOURCE = {
    "source_id": "estat:00350300:hinbetsu-semis",
    "name": ("Ministry of Finance — Trade Statistics of Japan, HS-detail commodity "
             "by country tables (semiconductor inputs)"),
    "name_ja": "財務省 普通貿易統計 品別国別表（半導体材料）",
    "url": mof_trade.SOURCE["url"],
    "license_note": mof_trade.SOURCE["license_note"],
}

DOWNLOAD_URL = ("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
                " (普通貿易統計 品別国別表)")

RAW_SUFFIX = ".json.gz"


def fetch():
    stamps = mof_trade._updated_dates(TABLES, LIST_SEARCH)
    envelope = {"tables": [mof_trade._table_payload(tid, flow, stamps[tid], ",".join(CODES[flow]))
                           for tid, flow, _era in TABLES]}
    return gzip.compress(
        json.dumps(envelope, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        6, mtime=0)


def parse(raw_bytes):
    envelope = json.loads(gzip.decompress(raw_bytes).decode("utf-8"))
    units = {}                          # (flow, code, slot) -> unit text
    cells = {}                          # (flow, code, area, measure) -> {(y, m): v}
    covered = {}                        # (flow, year) -> highest month with data
    area_en, area_ja = {}, {}

    for table in envelope["tables"]:
        flow = table["flow"]
        known = set(CODES[flow])
        area_en.update(_class_names(table["meta_en"], "area"))
        area_ja.update(_class_names(table["meta_ja"], "area"))
        for cell in mof_trade._values_of(table["data"]):
            code = cell["@cat01"]
            if code not in known:
                raise ValidationError(
                    "table %s returned HS line %s, which was not requested"
                    % (table["id"], code))
            field = cell["@cat02"]
            year = int(str(cell["@time"])[:4])
            if field in UNIT_FIELDS:
                text = (cell.get("$") or "").strip()
                if text:
                    units.setdefault((flow, code, UNIT_FIELDS[field]), text)
                continue
            slot = MONTH_FIELDS.get(field)
            if slot is None:
                continue                # year totals: recomputable, not stored
            month, measure = slot
            value = _number(cell.get("$"))
            if value is None:
                continue
            if value:
                key = (flow, year)
                if month > covered.get(key, 0):
                    covered[key] = month
            cells.setdefault((flow, code, cell["@area"], measure), {})[(year, month)] = value

    if not covered:
        raise ValidationError("no non-zero values in any table")

    # Which quantity slot carries the figure: the one with any non-zero value.
    # For wafers that is 数量2; the rule is measured per line rather than
    # assumed, so a line that uses the first slot still parses.
    qty_slot = {}
    for (flow, code, area, measure), got in cells.items():
        if measure in ("qty1", "qty2") and any(got.values()):
            qty_slot.setdefault((flow, code), measure)

    areas = sorted(set(k[2] for k in cells))
    area_pos = dict((code, i) for i, code in enumerate(areas))
    series, observations = [], []
    for flow in ("exp", "imp"):
        for code, name_en, name_ja, order, _kind, _short in COMMODITIES[flow]:
            slot = qty_slot.get((flow, code))
            unit_q = units.get((flow, code, 2 if slot == "qty2" else 1))
            for area in areas:
                for measure in ("val", "qty"):
                    source = "val" if measure == "val" else slot
                    got = cells.get((flow, code, area, source)) if source else None
                    if not got:
                        continue
                    points = [(datetime.date(y, m, 1), v) for (y, m), v in got.items()
                              if m <= covered.get((flow, y), 0)]
                    if not any(v for _p, v in points):
                        continue
                    scode = mof_trade.series_code(flow, code, area, measure)
                    series.append({
                        "code": scode,
                        "name_en": "%s — %s %s %s (%s)" % (
                            name_en, mof_trade.FLOW_LABEL[flow], mof_trade.FLOW_PREP[flow],
                            PARTNER_EN.get(area) or area_en.get(area, area),
                            "value" if measure == "val" else "quantity"),
                        "name_ja": "%s 対%s%s（%s）" % (
                            name_ja, PARTNER_JA.get(area) or area_ja.get(area, area),
                            "輸出" if flow == "exp" else "輸入",
                            "金額" if measure == "val" else "数量"),
                        "unit": VALUE_UNIT if measure == "val" else (unit_q or "unit"),
                        "weight_per_10000": None,
                        "sort_order": (0 if flow == "exp" else 1) * 1000000
                                      + order * 100000 + area_pos[area] * 2
                                      + (0 if measure == "val" else 1),
                    })
                    for period, value in sorted(points):
                        observations.append({"code": scode, "period": period, "value": value})
    return series, observations


MIN_OBSERVATIONS = 20_000
ANCHOR = {"exp": ("50106",), "imp": ("50304",)}       # Taiwan; United States


def validate(series, observations):
    codes = set(s["code"] for s in series)
    if not codes:
        raise ValidationError("no series parsed")
    if len(observations) < MIN_OBSERVATIONS:
        raise ValidationError(
            "only %d observations parsed, expected at least %d" % (len(observations), MIN_OBSERVATIONS))
    seen, periods = set(), set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        periods.add(o["period"])
        if o["value"] < 0:
            raise ValidationError("%s %s: negative value %s" % (o["code"], o["period"], o["value"]))
    ordered = sorted(periods)
    if ordered[0] != datetime.date(FIRST_YEAR, 1, 1):
        raise ValidationError("history starts %s, expected %s-01" % (ordered[0], FIRST_YEAR))
    expected, y, m = [], FIRST_YEAR, 1
    while datetime.date(y, m, 1) <= ordered[-1]:
        expected.append(datetime.date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    holes = sorted(set(expected) - periods)
    if holes:
        raise ValidationError("%d months missing, e.g. %s" % (len(holes), holes[0]))
    latest = ordered[-1]
    today = datetime.date.today()
    if latest > today or (today - latest).days > 200:
        raise ValidationError("latest month %s is implausible" % latest)
    latest_codes = set(o["code"] for o in observations if o["period"] == latest)
    for flow in ("exp", "imp"):
        for partner in ANCHOR[flow]:
            for measure in ("val", "qty"):
                code = mof_trade.series_code(flow, FLAGSHIP[flow], partner, measure)
                if code not in latest_codes:
                    raise ValidationError(
                        "no wafer %s %s for partner %s in %s"
                        % (mof_trade.FLOW_LABEL[flow], measure, partner, latest))
    # The quantity column must actually carry figures: a parser that read the
    # empty first slot would pass every other gate with a column of zeros.
    qty = [o for o in observations if o["code"].endswith(".qty") and o["period"] == latest]
    if not qty or not any(o["value"] for o in qty):
        raise ValidationError("no non-zero quantity in the latest month — wrong quantity slot?")
    world = {}
    for o in observations:
        flow, code, _area, measure = o["code"].split(".")
        if measure == "val" and code == FLAGSHIP[flow]:
            world.setdefault(flow, {}).setdefault(o["period"], 0.0)
            world[flow][o["period"]] += o["value"]
    return {
        "series": len(series), "observations": len(observations),
        "months": len(ordered), "partners": len(set(c.split(".")[2] for c in codes)),
        "latest_period": latest.isoformat(),
        "wafer_exports_latest_jpy_1000": world.get("exp", {}).get(latest),
        "wafer_imports_latest_jpy_1000": world.get("imp", {}).get(latest),
    }


PRESENTATION = {
    "credit_line": mof_trade.PRESENTATION["credit_line"],
    "stale_after_days": mof_trade.PRESENTATION["stale_after_days"],
    "trade": {
        "flows": mof_trade.PRESENTATION["trade"]["flows"],
        "commodities": dict(
            (flow, [{"code": c, "label": e, "label_ja": j, "short": sh, "level": k, "order": o}
                    for c, e, j, o, k, sh in COMMODITIES[flow]])
            for flow in ("exp", "imp")),
        "default_flow": "exp",
        "default_commodity": dict(FLAGSHIP),
        "feature_partners": ["50106", "50103", "50105", "50304", "50112", "50213"],
        "value_unit": VALUE_UNIT,
    },
}

MANIFEST = {
    "id": DATASET["slug"],
    "section": "trade",
    "name": {"en": "Semiconductor inputs — silicon wafers by partner (HS detail)",
             "ja": "半導体材料（シリコンウエハー）の輸出入（相手国別・HS9桁）"},
    "shape": "series",
    "summary": DATASET["description"],
    "source": {
        "publisher": DATASET["agency"], "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"], "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"], "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "2001-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [m for m in mof_trade.MANIFEST["measures"] if m["id"] != "balance"],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "trade": "/api/v1/%s/trade" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/semis.html?dataset=trade-inputs",
    "page": "/semis.html",
    "notes": [
        "HS-detail lines carry no names on e-Stat; the names here are curated from the "
        "Customs tariff schedule and a line without one is not ingested. The export and "
        "import schedules split HS 3818.00 differently (-100/-900 and -010/-020); the "
        "import silicon line was confirmed by its value-per-kilogram signature.",
        "Quantity is read from whichever of the table's two quantity slots carries "
        "figures (数量2 for wafers); the empty slot is never stored as zero.",
        "HS 3818.00-900 is the residual 'other doped elements' line and is never added "
        "to the silicon-wafer line.",
    ] + mof_trade.MANIFEST["notes"],
}
