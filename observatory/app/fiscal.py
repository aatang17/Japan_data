"""Fiscal-calendar roll-ups of monthly published values.

A modeller working on Tokyo Electron wants Japan's chip-equipment exports in
TEL's own fiscal quarters (April–March), beside TEL's reported number. Summing
twelve monthly customs values into four quarters and one year is arithmetic
on published figures; this module does exactly that and nothing else.

What it refuses to do is as important as what it does:

- Only *flows* are summed. A customs value, a physical quantity or a count of
  visitors is a monthly amount and adds up; a price index, a yen stock on a
  balance sheet or a yield does not. Callers pass the series unit and the
  roll-up declines units it does not know to be flows.
- Only *complete* periods are emitted. A quarter with two of its three months
  published is not a smaller quarter, it is not a quarter; emitting it as a
  sum would print a number that looks like a shortfall. The response says
  which months were left out.
- Months the source did not publish are missing, never zero. A quarter with a
  gap inside it is incomplete and dropped for the same reason.

Periods are labelled by the first day of the quarter's (or year's) LAST month,
so they sort with the monthly series and never claim a date that lies outside
the window they cover, and each carries a human label ("FY2025 Q1") built from
the fiscal year the filer would use: the calendar year in which the fiscal
year *starts* — the Japanese convention, where the year ending March 2026 is
FY2025.
"""
import datetime

# Series units that are monthly amounts and therefore add up.
FLOW_UNITS = ("jpy_1000", "persons", "ＮＯ", "ＫＧ")   # ＮＯ, ＫＧ

GRANULARITIES = ("fiscal_quarter", "fiscal_year")


class NotAFlow(ValueError):
    pass


def _fiscal_year_start(fy_end_month):
    """Calendar month in which the fiscal year begins (April for a March end)."""
    return fy_end_month % 12 + 1


def fiscal_label(period, fy_end_month, granularity):
    """'FY2025 Q1' or 'FY2025' for the period ending in `period`'s month."""
    start_month = _fiscal_year_start(fy_end_month)
    # months since the start of the fiscal year the period's month sits in
    offset = (period.month - start_month) % 12
    fy_start_year = period.year if period.month >= start_month or start_month == 1 else period.year - 1
    if start_month == 1:
        fy_start_year = period.year
    if granularity == "fiscal_year":
        return "FY%d" % fy_start_year
    return "FY%d Q%d" % (fy_start_year, offset // 3 + 1)


def roll_up(points, unit, fy_end_month, granularity):
    """Sum monthly (date, value) pairs into fiscal quarters or years.

    Returns (rolled, dropped): `rolled` is [(period_end_month_date, sum, label)]
    for every complete period, oldest first; `dropped` lists the months that
    fell in an incomplete period and were not summed, so the caller can say so.

    Raises NotAFlow for a unit that does not add up, and ValueError for a bad
    month or granularity — never silently sums the wrong thing.
    """
    if unit not in FLOW_UNITS:
        raise NotAFlow(
            "'%s' is not a monthly flow and cannot be summed into fiscal periods"
            % (unit or "unknown unit"))
    if granularity not in GRANULARITIES:
        raise ValueError("granularity must be one of %s" % ", ".join(GRANULARITIES))
    if not 1 <= int(fy_end_month) <= 12:
        raise ValueError("fy_end must be a month number 1-12")
    fy_end_month = int(fy_end_month)
    start_month = _fiscal_year_start(fy_end_month)
    span = 3 if granularity == "fiscal_quarter" else 12

    by_month = {}
    for p, v in points:
        if v is None:
            continue
        by_month[datetime.date(p.year, p.month, 1)] = v

    # Group months by the period they belong to: the period index counts
    # whole spans from the start of the fiscal year the month sits in.
    groups = {}
    for m in by_month:
        offset = (m.month - start_month) % 12
        fy_start_year = m.year if m.month >= start_month else m.year - 1
        if start_month == 1:
            fy_start_year = m.year
        idx = offset // span
        groups.setdefault((fy_start_year, idx), []).append(m)

    rolled, dropped = [], []
    for (fy_start_year, idx), months in sorted(groups.items()):
        first = _add_months(datetime.date(fy_start_year, start_month, 1), idx * span)
        expected = [_add_months(first, k) for k in range(span)]
        if all(e in by_month for e in expected):
            last = expected[-1]
            rolled.append((last, sum(by_month[e] for e in expected),
                           fiscal_label(last, fy_end_month, granularity)))
        else:
            dropped.extend(sorted(months))
    return rolled, sorted(dropped)


def _add_months(d, n):
    y, m = d.year, d.month + n
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return datetime.date(y, m, 1)


if __name__ == "__main__":     # a few checks, runnable on their own
    D = datetime.date
    pts = [(D(2025, m, 1), 1.0) for m in range(1, 13)] + [(D(2026, m, 1), 2.0) for m in range(1, 8)]
    q, dropped = roll_up(pts, "jpy_1000", 3, "fiscal_quarter")
    assert [x[2] for x in q] == ["FY2024 Q4", "FY2025 Q1", "FY2025 Q2", "FY2025 Q3",
                                 "FY2025 Q4", "FY2026 Q1"], [x[2] for x in q]
    assert q[0] == (D(2025, 3, 1), 3.0, "FY2024 Q4")
    assert q[-1] == (D(2026, 6, 1), 6.0, "FY2026 Q1")
    assert dropped == [D(2026, 7, 1)], dropped            # July 2026 alone is not a quarter
    y, dropped = roll_up(pts, "jpy_1000", 3, "fiscal_year")
    assert y == [(D(2026, 3, 1), 9.0 + 6.0, "FY2025")], y   # Apr25–Mar26 = 9×1 + 3×2
    y, _ = roll_up(pts, "jpy_1000", 12, "fiscal_year")
    assert y == [(D(2025, 12, 1), 12.0, "FY2025")], y
    gap = [p for p in pts if p[0] != D(2025, 5, 1)]
    q, dropped = roll_up(gap, "jpy_1000", 3, "fiscal_quarter")
    assert "FY2025 Q1" not in [x[2] for x in q] and D(2025, 4, 1) in dropped
    try:
        roll_up(pts, "index", 3, "fiscal_quarter")
        raise AssertionError("an index must not be summed")
    except NotAFlow:
        pass
    print("fiscal.py checks pass")
