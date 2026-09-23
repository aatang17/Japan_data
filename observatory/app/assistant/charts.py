"""Charts a specialist draws, from numbers a data tool returned in the same run.

The model never types a figure into a chart. `draw_chart` names a data call
made earlier in the run and which part of its result to plot; code reads the
numbers out of that result — the full result, not the shortened copy the model
was shown — and the chart carries the result's own credit line, document,
vintage and trust label, and the formula of any calculated measure.

Two shapes are plotted, because they are the two shapes the data tools return:

- a published series (get_series): `{"call": 3, "series": "0001"}` — the
  dated points of that series code, on a time axis;
- a table of rows (get_company, get_breakdown, compare_cohort…):
  `{"call": 5, "rows": "panel", "x": "fiscal_year_end", "y": "values.revenue",
  "where": {"basis": "consolidated"}, "unit": "¥"}` — one value per row, on
  a category axis in x order.

Series that cannot share an axis are refused, not drawn: two units on one
chart (an index level beside a percentage, yen beside a count) is the error
the house rules forbid, so the model is told to draw two charts instead.
"""
import json
import re

MAX_SERIES = 6          # the palette has six series colours
MAX_POINTS = 2000
MAX_BARS = 40           # more categories than this is a line, not a bar chart
KINDS = ("line", "bar")

SCHEMA = {
    "name": "draw_chart",
    "description": (
        "Draw a chart under your reply from data a tool returned earlier in THIS run. "
        "Never type numbers into a chart: point at the tool call and the data, and the "
        "numbers are read from its full result (which may hold more rows than you were "
        "shown). Every data result carries a `call` number; use it. "
        "A series from get_series: {\"call\": 3, \"series\": \"0001\"}. "
        "Rows from any other result: {\"call\": 5, \"rows\": \"panel\", \"x\": "
        "\"fiscal_year_end\", \"y\": \"values.revenue\", \"unit\": \"¥\", \"where\": "
        "{\"basis\": \"consolidated\"}} — `rows` is the key of the list, `x` and `y` are "
        "field names inside each row (dots for nested fields), `where` keeps rows whose "
        "fields equal the values given, and `unit` is required. At most six series, all "
        "in one unit: an index level, a percentage and a yen amount never share a chart. "
        "Use 'line' for a trend over time and 'bar' for a few periods or items compared. "
        "Chart only when the shape over time answers the question better than a "
        "sentence; then state the finding in words and do not list the numbers again."),
    "parameters": {"type": "object", "properties": {
        "title": {"type": "string", "description": "What is plotted, e.g. 'Toyota revenue, FY2018–FY2026'."},
        "kind": {"type": "string", "enum": list(KINDS)},
        "series": {"type": "array", "description": "One to six series.", "items": {
            "type": "object", "properties": {
                "call": {"type": "integer", "description": "The `call` number of the data result."},
                "series": {"type": "string", "description": "A series code in a get_series result."},
                "rows": {"type": "string", "description": "Key of a list of rows in the result."},
                "x": {"type": "string"},
                "y": {"type": "string"},
                "where": {"type": "object"},
                "unit": {"type": "string", "description": "Unit of y for rows: ¥, %, ¥ per share, people…"},
                "label": {"type": "string", "description": "Legend name; defaults to the series' own name."}},
            "required": ["call"]}}},
        "required": ["title", "kind", "series"]},
}


class ChartError(ValueError):
    pass


def _get(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None, False
    return cur, True


def _find_series(obj, code, ctx=None):
    """The {code, points} entry with this code, and the nearest enclosing dict
    that states a unit (get_series's `data`: measure, unit, trust)."""
    if isinstance(obj, dict):
        here = obj if "unit" in obj else ctx
        if isinstance(obj.get("points"), list) and str(obj.get("code")) == code:
            return obj, here
        for v in obj.values():
            hit = _find_series(v, code, here)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_series(v, code, ctx)
            if hit:
                return hit
    return None


def _find_rows(obj, key):
    if isinstance(obj, dict):
        v = obj.get(key)
        if isinstance(v, list) and v and all(isinstance(r, dict) for r in v):
            return v
        for vv in obj.values():
            hit = _find_rows(vv, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for vv in obj:
            hit = _find_rows(vv, key)
            if hit is not None:
                return hit
    return None


def _number(v):
    """A plotted value: a real number or missing. Booleans and strings are
    not numbers, and a missing value is never turned into zero."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ChartError("The y field holds %r, which is not a number. Pick a numeric field." % (v,))
    if v != v:  # NaN
        return None
    return v


def _source(call, result):
    prov = result.get("provenance") or {}
    vint = result.get("vintage") or {}
    return {"call": call["seq"], "tool": call["name"], "args": call["args"],
            "credit": prov.get("credit"), "document": prov.get("document"),
            "cite": result.get("cite"), "vintage": vint.get("label"),
            "as_of": vint.get("as_of") or vint.get("published_at")}


def _pick(p, calls):
    if not isinstance(p, dict):
        raise ChartError("Each series must be an object with a `call` number.")
    try:
        seq = int(p.get("call"))
    except (TypeError, ValueError):
        raise ChartError("Each series needs the `call` number of a data result from this run.")
    call = calls.get(seq)
    if call is None:
        raise ChartError("There is no data result numbered %s in this run. Charts can only use "
                         "data fetched in this run; fetch it first." % seq)
    result = call["result"]
    # calculated fields are listed at the top of a result, and for company
    # views inside `data` as well; either list makes a field calculated
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    calc = dict(data.get("calc") or {})
    calc.update(result.get("calc") or {})
    label = (p.get("label") or "").strip()[:80]

    if p.get("series"):
        code = str(p["series"])
        hit = _find_series(result.get("data", result), code)
        if not hit:
            raise ChartError("Call %d has no series with code %s." % (seq, code))
        entry, ctx = hit
        ctx = ctx or {}
        measure = ctx.get("measure")
        trust = ctx.get("trust") or (result.get("provenance") or {}).get("trust") or "official"
        points = []
        for pt in entry["points"]:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                continue
            points.append([str(pt[0]), _number(pt[1])])
        return {"name": label or entry.get("name_en") or entry.get("name") or code,
                "unit": ctx.get("unit") or "", "trust": trust,
                "formula": calc.get(measure) if trust == "derived" else None,
                "axis": "time", "points": points, "source": _source(call, result)}

    if p.get("rows"):
        x, y = p.get("x"), p.get("y")
        unit = (p.get("unit") or "").strip()[:20]
        if not x or not y:
            raise ChartError("A rows series needs both `x` and `y` field names.")
        if not unit:
            raise ChartError("A rows series needs a `unit` (¥, %, ¥ per share, people…).")
        rows, ok = _get(result, p["rows"])     # a full path: data.panel
        if not (ok and isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows)):
            rows = _find_rows(result, p["rows"].split(".")[-1])
        if rows is None:
            raise ChartError("Call %d has no list of rows called '%s'." % (seq, p["rows"]))
        where = p.get("where") or {}
        if not isinstance(where, dict):
            raise ChartError("`where` must be an object of field: value.")
        kept = [r for r in rows if all(_get(r, k)[0] == v for k, v in where.items())]
        if not kept:
            raise ChartError("No row in '%s' matches %s." % (p["rows"], json.dumps(where, ensure_ascii=False)))
        points = []
        seen = set()
        for r in kept:
            xv, ok = _get(r, x)
            if not ok or xv is None:
                continue
            yv, ok = _get(r, y)
            if not ok:
                raise ChartError("Rows in '%s' have no field '%s'." % (p["rows"], y))
            xs = str(xv)
            if xs in seen:
                # consolidated beside parent, two share classes: plotting both
                # on one x would draw a line through two different things
                raise ChartError("Two rows share %s = %s. Add `where` to keep one kind of row."
                                 % (x, xs))
            seen.add(xs)
            points.append([xs, _number(yv)])
        points.sort(key=lambda pt: pt[0])
        field = y.split(".")[-1]
        # any part of the path can be the calculated one: split_adjusted.values.eps
        hit = [part for part in y.split(".") if isinstance(calc.get(part), str)]
        trust = "derived" if hit else ((result.get("provenance") or {}).get("trust") or "official")
        return {"name": label or field.replace("_", " "), "unit": unit, "trust": trust,
                "formula": calc[hit[0]] if hit else None,
                "axis": "category", "x_field": x, "points": points,
                "source": _source(call, result)}

    raise ChartError("Each series needs either `series` (a series code) or `rows` (a list key).")


def summary(chart):
    """What was plotted, told back to the model: it was shown a shortened
    result, and must not describe the chart as missing years it holds."""
    out = []
    for s in chart["series"]:
        have = [pt for pt in s["points"] if pt[1] is not None]
        out.append({"name": s["name"], "points": len(have),
                    "from": have[0][0] if have else None, "to": have[-1][0] if have else None,
                    "latest": have[-1] if have else None,
                    "missing": len(s["points"]) - len(have)})
    return out


def build(args, calls):
    """The stored chart, or ChartError with a message the model can act on.

    `calls` maps a call number to {"seq", "name", "args", "result"} where
    result is the tool's full parsed JSON."""
    title = (args.get("title") or "").strip()[:140]
    kind = args.get("kind") or "line"
    picks = args.get("series") or []
    if not title:
        raise ChartError("A chart needs a title saying what is plotted.")
    if kind not in KINDS:
        raise ChartError("kind must be 'line' or 'bar'.")
    if not isinstance(picks, list) or not picks:
        raise ChartError("A chart needs at least one series.")
    if len(picks) > MAX_SERIES:
        raise ChartError("At most %d series fit one chart; draw a second chart." % MAX_SERIES)
    series = [_pick(p, calls) for p in picks]

    units = sorted(set(s["unit"] for s in series))
    if len(units) > 1:
        raise ChartError("These series are in different units (%s) and cannot share an axis. "
                         "Draw one chart per unit." % ", ".join(u or "none" for u in units))
    for s in series:
        if len(s["points"]) > MAX_POINTS:
            s["points"] = s["points"][-MAX_POINTS:]
        if not any(pt[1] is not None for pt in s["points"]):
            raise ChartError("'%s' has no values to plot." % s["name"])

    axis = "time" if all(s["axis"] == "time" for s in series) else "category"
    if axis == "category":
        # one shared, ordered set of categories; a series without a value
        # at a category shows a gap there, never a zero
        cats = sorted(set(pt[0] for s in series for pt in s["points"]))
        for s in series:
            have = dict((pt[0], pt[1]) for pt in s["points"])
            s["points"] = [[c, have.get(c)] for c in cats]
    if kind == "bar":
        n = len(set(pt[0] for s in series for pt in s["points"]))
        if n > MAX_BARS:
            raise ChartError("%d periods is too many bars; use kind 'line'." % n)

    sources = []
    for s in series:
        src = s.pop("source")
        if src not in sources:
            sources.append(src)
        s["source"] = sources.index(src)
    # A daily or monthly axis says which: fiscal-year categories are labelled
    # by the year they end, time axes by month unless the data is daily.
    daily = axis == "time" and any(
        re.match(r"^\d{4}-\d{2}-(?!01)\d{2}", pt[0]) for s in series for pt in s["points"])
    fiscal = axis == "category" and all(
        (s.get("x_field") or "").split(".")[-1].startswith("fiscal_year") for s in series)
    for s in series:
        s.pop("axis", None)
        s.pop("x_field", None)
    return {"title": title, "kind": kind, "axis": axis, "unit": units[0], "daily": daily,
            "fiscal": fiscal, "series": series, "sources": sources}
