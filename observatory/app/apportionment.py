# -*- coding: utf-8 -*-
u"""Vote value in the House of Councillors: the seat map against the electorate.

The House of Councillors is the one national chamber whose constituencies are
*exactly* prefectures. That is what makes this surface possible without any
boundary file: 45 選挙区 covering all 47 prefectures — every prefecture on its
own, except two merged pairs (合区) — so a prefecture-level population count
maps onto a district with nothing left over and nothing double-counted. The
lower house cannot be done this way; its 289 single-member districts cut
through cities below the municipality level.

Three things are combined here, and they are different kinds of fact:

* **The seat table is law, not a statistic.** It comes from the Public Offices
  Election Act as amended in 2018, in force since the 2019 ordinary election:
  148 district seats, half of them up every three years. It has no vintage and
  no freshness — it changes when the Diet changes it, and ``SEATS_SOURCES``
  records where it was read and when it was last checked. It is small enough
  to hold as a checked constant and too consequential to scrape.
* **The population counts are official statistics**, taken from the datasets
  the platform already serves — never recomputed here.
* **Everything this module returns is derived**, and carries its formula.

The denominator is the argument, so the caller picks it rather than the module
assuming one. Four bases, in descending order of how close they sit to the
actual franchise:

``adults18``   Japanese residents aged 18 and over — the franchise as it has
               stood since 2016. The register publishes five-year age bands,
               so the 18–19 pair is the only estimated quantity on this
               surface: two of the five single years in the 15–19 band. It is
               disclosed as a formula and never as a published count.
``adults20``   Japanese residents aged 20 and over. Exact — no band is split —
               and the honest cross-check on ``adults18``: if the ranking and
               the disparity barely move between the two, the estimate is not
               carrying the result.
``japanese``   Japanese registered residents, all ages. Not the franchise, but
               the only base with fifty years of history behind it, which is
               what the drift series is computed on.
``residents``  Everyone on the register, foreign nationals and children
               included. Not an electorate at all: it is the base most often
               quoted in the apportionment argument, and the gap between it
               and ``adults18`` is itself a finding — a prefecture with many
               foreign residents is allocated representation for people who
               cannot vote in national elections.

Disparity is reported the way the courts and the press report it: the ratio of
the worst-served district to the best-served one (最大格差). Per district we
also serve the reciprocal — the weight of one vote cast there against one cast
in the best-served district — because that is the number a reader can feel.
"""

from .adapters.juki_population import PREFECTURES

PREF_EN = dict((code, en) for code, _ja, en in PREFECTURES)
PREF_JA = dict((code, ja) for code, ja, _en in PREFECTURES)

# ---------------------------------------------------------------------------
# The seat table (公職選挙法 別表第三), in force since the 2019 ordinary election
# ---------------------------------------------------------------------------
# (district id, English name, Japanese name, prefecture JIS codes, 定数).
# `定数` is the district's full complement; half is up at each election
# (改選数 = 定数 ÷ 2, exact for every district because every 定数 is even),
# so per-seat ratios are identical whichever of the two is used.
#
# The district id is the prefecture code, or the two codes joined by a hyphen
# for the merged pairs — stable, and sortable into the ministry's own order.
DISTRICTS = [
    ("01",    ("01",),      6),
    ("02",    ("02",),      2),
    ("03",    ("03",),      2),
    ("04",    ("04",),      2),
    ("05",    ("05",),      2),
    ("06",    ("06",),      2),
    ("07",    ("07",),      2),
    ("08",    ("08",),      4),
    ("09",    ("09",),      2),
    ("10",    ("10",),      2),
    ("11",    ("11",),      8),
    ("12",    ("12",),      6),
    ("13",    ("13",),     12),
    ("14",    ("14",),      8),
    ("15",    ("15",),      2),
    ("16",    ("16",),      2),
    ("17",    ("17",),      2),
    ("18",    ("18",),      2),
    ("19",    ("19",),      2),
    ("20",    ("20",),      2),
    ("21",    ("21",),      2),
    ("22",    ("22",),      4),
    ("23",    ("23",),      8),
    ("24",    ("24",),      2),
    ("25",    ("25",),      2),
    ("26",    ("26",),      4),
    ("27",    ("27",),      8),
    ("28",    ("28",),      6),
    ("29",    ("29",),      2),
    ("30",    ("30",),      2),
    # 合区, from the 2016 ordinary election: two prefectures, one district,
    # two seats between them. The reason this surface exists.
    ("31-32", ("31", "32"), 2),
    ("33",    ("33",),      2),
    ("34",    ("34",),      4),
    ("35",    ("35",),      2),
    ("36-39", ("36", "39"), 2),
    ("37",    ("37",),      2),
    ("38",    ("38",),      2),
    ("40",    ("40",),      6),
    ("41",    ("41",),      2),
    ("42",    ("42",),      2),
    ("43",    ("43",),      2),
    ("44",    ("44",),      2),
    ("45",    ("45",),      2),
    ("46",    ("46",),      2),
    ("47",    ("47",),      2),
]

SEATS_TOTAL = 148           # 選挙区 seats; the other 100 are 比例代表, nationwide
SEATS_PR = 100
SEATS_IN_FORCE_FROM = "2019-07-21"   # first ordinary election under this table
SEATS_LAW = u"公職選挙法 別表第三 (Public Offices Election Act, Appended Table 3)"
SEATS_CHECKED = "2026-09-08"
SEATS_SOURCES = [
    {"label": u"Ministry of Internal Affairs and Communications — 選挙の種類",
     "url": "https://www.soumu.go.jp/senkyo/senkyo_s/naruhodo/naruhodo03.html"},
    {"label": u"Ministry of Internal Affairs and Communications — "
              u"参議院選挙区選出議員の選挙区及び定数の改正等について",
     "url": "https://www.soumu.go.jp/senkyo/senkyo_s/news/senkyo/san_gouku/"},
]

SEATS_NOTE = (
    u"Seats are the district complement (定数) fixed by the Public Offices "
    u"Election Act as amended in 2018 and in force since the 2019 ordinary "
    u"election: 148 district seats across 45 districts, plus 100 elected from "
    u"a single nationwide proportional list which no prefecture's population "
    u"bears on. Half of each district's seats are contested every three years "
    u"(改選数 = 定数 ÷ 2, whole for every district), so the per-seat ratios "
    u"below are the same whichever complement is counted. Tottori with "
    u"Shimane, and Tokushima with Kochi, have been merged into single "
    u"two-seat districts since 2016; they are summed here and never shown as "
    u"four separate prefectures."
)


def _district_name(codes):
    if len(codes) == 1:
        return PREF_EN[codes[0]], PREF_JA[codes[0]]
    return (" & ".join(PREF_EN[c] for c in codes),
            u"・".join(PREF_JA[c] for c in codes))


def districts():
    """[{id, name_en, name_ja, prefectures, seats, seats_per_election}, ...]."""
    out = []
    for did, codes, seats in DISTRICTS:
        en, ja = _district_name(codes)
        out.append({
            "id": did, "name_en": en, "name_ja": ja,
            "prefectures": list(codes),
            "merged": len(codes) > 1,
            "seats": seats,
            "seats_per_election": seats // 2,
        })
    return out


def check_table():
    """Self-check the constant. Returns a list of problems; empty is good.

    A seat table that has drifted from the law is the one error on this
    surface that no downstream arithmetic could reveal, so it is checked
    rather than trusted: every prefecture covered exactly once, the district
    count and the seat total as enacted, and every complement even so that
    改選数 is a whole number.
    """
    problems = []
    seen = {}
    for did, codes, seats in DISTRICTS:
        for code in codes:
            if code in seen:
                problems.append("prefecture %s appears in %s and %s"
                                % (code, seen[code], did))
            seen[code] = did
        if seats % 2:
            problems.append("district %s has an odd complement (%d)" % (did, seats))
    missing = sorted(set(PREF_EN) - set(seen))
    if missing:
        problems.append("prefectures never assigned to a district: %s"
                        % ", ".join(missing))
    if len(DISTRICTS) != 45:
        problems.append("expected 45 districts, found %d" % len(DISTRICTS))
    total = sum(s for _d, _c, s in DISTRICTS)
    if total != SEATS_TOTAL:
        problems.append("seats sum to %d, expected %d" % (total, SEATS_TOTAL))
    return problems


# ---------------------------------------------------------------------------
# Electorate bases
# ---------------------------------------------------------------------------
# (key, label, dataset, formula shown wherever a number built on it is shown).
# `estimated` marks the one base that splits a published band.
BASES = [
    ("adults18", u"Japanese residents 18+", "population-jp", True,
     u"adults18[prefecture] = Σ Japanese residents in every five-year age band "
     u"from 20–24 upwards + 0.4 × the 15–19 band. The register publishes "
     u"five-year bands, so the two single years 18 and 19 are taken as "
     u"two-fifths of the band that contains them; every other year is a "
     u"published count added as published."),
    ("adults20", u"Japanese residents 20+", "population-jp", False,
     u"adults20[prefecture] = Σ Japanese residents in every five-year age band "
     u"from 20–24 upwards, each as published. No band is split."),
    ("japanese", u"Japanese residents, all ages", "population-jp", False,
     u"The ministry's published count of Japanese residents on the register at "
     u"1 January, as published."),
    ("residents", u"All residents, all ages", "population-jp", False,
     u"The ministry's published count of every resident on the register at "
     u"1 January — foreign nationals and children included — as published."),
]
BASE_KEYS = [b[0] for b in BASES]
BASE_BY_KEY = dict((b[0], b) for b in BASES)
DEFAULT_BASE = "adults18"

# The 15–19 band is five single years; 18 and 19 are two of them. Named so the
# assumption is one constant rather than a magic number in an expression.
SHARE_18_19_OF_BAND = 0.4

VOTE_WEIGHT_CALC = (
    u"per_seat[district] = electorate[district] ÷ seats[district]. "
    u"vote_weight[district] = min(per_seat over all 45 districts) ÷ "
    u"per_seat[district], so the best-served district is 1.00 and every other "
    u"district is the fraction of one of its votes that a vote cast there is "
    u"worth. disparity[district] = 1 ÷ vote_weight[district], the figure the "
    u"courts and the press quote. The headline 最大格差 is "
    u"max(per_seat) ÷ min(per_seat)."
)

SHARE_CALC = (
    u"seat_share[district] = seats[district] ÷ 148 × 100. "
    u"electorate_share[district] = electorate[district] ÷ Σ electorate over "
    u"the 45 districts × 100. over_representation[district] = "
    u"seat_share − electorate_share, in percentage points: how much of the "
    u"chamber a district holds beyond what its share of the electorate would "
    u"give it."
)


def _pct(part, whole):
    return None if not whole else part / whole * 100.0


def build(pop_by_pref, seats_scale=None):
    """The full cut, from {prefecture code: electorate count}.

    Returns (rows, summary). Rows are in descending per-seat order — worst
    served first — because that is the ranking the surface is about. A
    prefecture missing from the input makes its district incomplete: the
    district is returned with a null electorate rather than a wrong one, and
    is left out of every total and every extreme.
    """
    rows = []
    for d in districts():
        parts = [pop_by_pref.get(c) for c in d["prefectures"]]
        pop = None if any(p is None for p in parts) else sum(parts)
        row = dict(d)
        seats = d["seats"] if seats_scale is None else d[seats_scale]
        row["electorate"] = pop
        row["per_seat"] = None if pop is None else pop / float(seats)
        rows.append(row)

    complete = [r for r in rows if r["per_seat"] is not None]
    if not complete:
        return rows, {}
    # A district with nobody in it has a per-seat ratio of zero, which is a
    # real count and not a gap — but it cannot anchor a ratio, and dividing
    # by it would either crash or emit an infinity that is not JSON. Ratios
    # are taken over the districts that have someone in them; an empty
    # district keeps its zero and gets a null weight.
    peopled = [r for r in complete if r["per_seat"] > 0]
    if not peopled:
        return rows, {}
    best = min(r["per_seat"] for r in peopled)      # fewest voters per seat
    worst = max(r["per_seat"] for r in peopled)
    total_pop = sum(r["electorate"] for r in complete)
    total_seats = sum(r["seats"] for r in complete)

    for r in rows:
        if r["per_seat"] is None:
            r["vote_weight"] = r["disparity"] = None
            r["seat_share_pct"] = r["electorate_share_pct"] = None
            r["over_representation_pp"] = None
            continue
        if r["per_seat"] > 0:
            r["vote_weight"] = best / r["per_seat"]
            r["disparity"] = r["per_seat"] / best
        else:
            r["vote_weight"] = r["disparity"] = None
        r["seat_share_pct"] = _pct(r["seats"], total_seats)
        r["electorate_share_pct"] = _pct(r["electorate"], total_pop)
        r["over_representation_pp"] = (r["seat_share_pct"]
                                       - r["electorate_share_pct"])

    rows.sort(key=lambda r: (r["per_seat"] is None, -(r["per_seat"] or 0)))
    ranked = [r for r in rows if r["per_seat"] is not None and r["per_seat"] > 0]
    worst_row, best_row = ranked[0], ranked[-1]
    summary = {
        "districts": len(rows),
        "districts_complete": len(complete),
        "seats": total_seats,
        "electorate": total_pop,
        "per_seat_national": total_pop / float(total_seats),
        "max_disparity": worst / best,
        "worst_served": {"id": worst_row["id"], "name_en": worst_row["name_en"],
                         "per_seat": worst_row["per_seat"]},
        "best_served": {"id": best_row["id"], "name_en": best_row["name_en"],
                        "per_seat": best_row["per_seat"]},
        "districts_over_2x": sum(1 for r in peopled
                                 if r["per_seat"] / best >= 2.0),
        "districts_over_3x": sum(1 for r in peopled
                                 if r["per_seat"] / best >= 3.0),
    }
    return rows, summary
