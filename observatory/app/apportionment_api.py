# -*- coding: utf-8 -*-
u"""Representation: what one vote is worth, by constituency.

Routes under ``/api/v1/representation``:

    GET  /councillors            the whole surface in one payload

One payload, deliberately. The ranking, the headline disparity, the
sensitivity of that headline to the choice of denominator and the fifty-year
drift are four views of one calculation, and a page that fetched them
separately could show four mutually inconsistent numbers while one of them
was still loading.

Nothing here is a new measurement. The counts are ``population-jp`` and
``population-jp-history`` exactly as those datasets publish them; the seat
table is law, held and self-checked in ``apportionment``; everything computed
on top is derived and travels with its formula, per the trust contract.

A prefecture with no count for the period asked for makes its district
incomplete. Such a district is returned with a null electorate and is excluded
from the totals, the extremes and the disparity — never imputed, never zero.
"""
import datetime

from fastapi import APIRouter, HTTPException, Query

from . import apportionment as ap
from .api import _con, _release, _series_map, _values_bulk
from .adapters import juki_population, ssds_population

router = APIRouter(prefix="/api/v1/representation", tags=["Representation"])

POP_DATASET = "population-jp"
HISTORY_DATASET = "population-jp-history"

# The historical drift is computed on registered Japanese residents (A2101),
# the only indicator on the fifty-year panel that is both a register count and
# nationality-restricted. It is all ages, so it is not the franchise — which is
# exactly why it is labelled as a drift measure and never as a vote-value level.
HISTORY_INDICATOR = "A2101"

HISTORY_CALC = (
    u"The seat table in force today, applied to each year's population: "
    u"max_disparity[year] = max(residents ÷ seats) ÷ min(residents ÷ seats) "
    u"over the 45 districts as they are drawn now, using registered Japanese "
    u"residents of all ages at 1 January. This is a counterfactual before "
    u"2019 and is meant as one — it measures how far the population has moved "
    u"under a fixed map, not what the disparity was at the time, which was "
    u"governed by whatever table was then in force."
)


def _age_lower_bound(item):
    """The first age in a band code, or None if the code is not a band."""
    parts = item.split("_")
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _population_by_base(values, period_index):
    """{base key: {prefecture: count}} for one period, from the served values.

    ``values`` is the ``{series code: [value per period]}`` shape the register
    dataset stores; codes are ``prefecture.segment.item``.
    """
    out = dict((key, {}) for key in ap.BASE_KEYS)
    for code, column in values.items():
        parts = code.split(".")
        if len(parts) != 3:
            continue
        pref, segment, item = parts
        if pref == juki_population.NATIONAL[0] or pref not in ap.PREF_EN:
            continue
        value = column[period_index]
        if value is None:
            continue
        if item == "population":
            if segment == "jp":
                out["japanese"][pref] = value
            elif segment == "all":
                out["residents"][pref] = value
            continue
        if segment != "jp" or not item.startswith("age_") or not item.endswith("_total"):
            continue
        if item == "age_total_total":
            continue
        low = _age_lower_bound(item)
        if low is None:
            continue
        if low >= 20:
            out["adults20"][pref] = out["adults20"].get(pref, 0.0) + value
            out["adults18"][pref] = out["adults18"].get(pref, 0.0) + value
        elif low == 15:
            out["adults18"][pref] = (out["adults18"].get(pref, 0.0)
                                     + ap.SHARE_18_19_OF_BAND * value)
    return out


def _history_points(con):
    """Max disparity per year under the current map, from the long panel."""
    smap = _series_map(con, HISTORY_DATASET)
    wanted = {}
    for s in smap:
        parts = s["code"].split(".")
        if len(parts) == 2 and parts[1] == HISTORY_INDICATOR and parts[0] in ap.PREF_EN:
            wanted[s["series_id"]] = parts[0]
    if not wanted:
        return []
    vals = _values_bulk(con, list(wanted))
    by_period = {}
    for sid, series in vals.items():
        pref = wanted[sid]
        for period, value in series.items():
            if value is not None:
                by_period.setdefault(period, {})[pref] = value

    points = []
    for period in sorted(by_period):
        pop = by_period[period]
        # Only a year with every prefecture present can be compared with
        # another year; a partial year would move the extremes for a reason
        # that has nothing to do with apportionment.
        if len(pop) != len(ap.PREF_EN):
            continue
        rows, summary = ap.build(pop)
        if not summary:
            continue
        points.append({
            "period": period.isoformat(),
            "max_disparity": summary["max_disparity"],
            "per_seat_national": summary["per_seat_national"],
            "worst_served": summary["worst_served"]["name_en"],
            "best_served": summary["best_served"]["name_en"],
        })
    return points


@router.get("/councillors")
def councillors(base: str = Query(ap.DEFAULT_BASE),
                period: str = Query(None)):
    """Seats per elector across the 45 prefectural constituencies."""
    if base not in ap.BASE_BY_KEY:
        raise HTTPException(400, "base must be one of: %s"
                            % ", ".join(ap.BASE_KEYS))
    problems = ap.check_table()
    if problems:  # pragma: no cover — the constant is checked in the suite
        raise HTTPException(500, "seat table failed its own check: %s"
                            % "; ".join(problems))
    if period is not None:
        try:
            datetime.date.fromisoformat(period)
        except ValueError:
            raise HTTPException(400, "period must be an ISO date (YYYY-MM-DD)")

    con = _con()
    try:
        rel = _release(con, POP_DATASET)
        smap = _series_map(con, POP_DATASET)
        vals = _values_bulk(con, [s["series_id"] for s in smap])
        periods = sorted(set(p for sid in vals for p in vals[sid]))
        if not periods:
            raise HTTPException(503, "no population release is published yet")
        position = dict((p, i) for i, p in enumerate(periods))

        values = {}
        for s in smap:
            column = [None] * len(periods)
            for p, v in vals.get(s["series_id"], {}).items():
                column[position[p]] = v
            values[s["code"]] = column

        chosen = periods[-1]
        if period:
            asked = datetime.date.fromisoformat(period)
            if asked not in position:
                raise HTTPException(
                    404, "population-jp has no period %s; it publishes %s"
                         % (period, ", ".join(p.isoformat() for p in periods)))
            chosen = asked
        index = position[chosen]

        by_base = _population_by_base(values, index)
        rows, summary = ap.build(by_base[base])

        # What the headline would be on each of the other denominators. This
        # is the disclosure that makes the one estimated base safe to lead
        # with: if 18+ and the exact 20+ base agree, the split band is not
        # carrying the finding.
        sensitivity = []
        for key, label, _ds, estimated, _formula in ap.BASES:
            _r, s = ap.build(by_base[key])
            sensitivity.append({
                "base": key, "label": label, "estimated": estimated,
                "max_disparity": s.get("max_disparity"),
                "electorate": s.get("electorate"),
                "worst_served": (s.get("worst_served") or {}).get("name_en"),
                "best_served": (s.get("best_served") or {}).get("name_en"),
            })

        key, label, dataset, estimated, formula = ap.BASE_BY_KEY[base]
        latest = datetime.date.fromisoformat(rel["latest_period"])
        stale = ((datetime.date.today() - latest).days
                 > juki_population.PRESENTATION["stale_after_days"])
        return {
            "chamber": "councillors",
            "chamber_label": u"House of Councillors — prefectural constituencies",
            "trust": "derived",
            "calc": ap.VOTE_WEIGHT_CALC,
            "share_calc": ap.SHARE_CALC,
            "base": {"key": key, "label": label, "dataset": dataset,
                     "estimated": estimated, "formula": formula},
            "bases": [{"key": b[0], "label": b[1], "estimated": b[3],
                       "formula": b[4]} for b in ap.BASES],
            "period": chosen.isoformat(),
            "periods": [p.isoformat() for p in periods],
            "release": rel,
            "stale": stale,
            "credit_line": juki_population.PRESENTATION.get("credit_line"),
            "seat_table": {
                "seats": ap.SEATS_TOTAL,
                "seats_proportional": ap.SEATS_PR,
                "districts": len(ap.DISTRICTS),
                "in_force_from": ap.SEATS_IN_FORCE_FROM,
                "law": ap.SEATS_LAW,
                "checked": ap.SEATS_CHECKED,
                "note": ap.SEATS_NOTE,
                "sources": ap.SEATS_SOURCES,
            },
            "summary": summary,
            "rows": rows,
            "sensitivity": sensitivity,
            "history": {
                "indicator": HISTORY_INDICATOR,
                "label": u"Registered Japanese residents, all ages",
                "dataset": HISTORY_DATASET,
                "credit_line": ssds_population.PRESENTATION.get("credit_line"),
                "calc": HISTORY_CALC,
                "points": _history_points(con),
            },
        }
    finally:
        con.close()
