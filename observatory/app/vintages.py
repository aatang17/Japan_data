"""Point-in-time history: seeding it, and reading it back as of a date.

The `observation_vintages` table is append-only (see app/db.py). Ingest writes
to it on every publish; this module handles the two things around that — the
one-time seed of history that predates the table, and the as-of read the API
serves.

Usage:  python -m app.vintages seed     # backfill from the live observations
        python -m app.vintages status   # what history exists, per dataset
"""
import datetime
import sys

from . import db

# Live observations carry the release that produced them, so a dataset's first
# vintage can be reconstructed exactly from the table itself — no re-parsing
# needed.
#
# Strictly a first-vintage operation, and the dataset filter is what makes it
# one. A dataset that already has any history is skipped entirely: after a
# later release the live table holds *that* release's values, so re-seeding
# would restate the whole history as a change made by the newest release —
# thousands of phantom revisions, and change-only storage collapsing into a
# full copy per release. (It did exactly that once, before this filter.)
SEED_SQL = """
INSERT INTO observation_vintages (series_id, period, value, release_id)
SELECT o.series_id, o.period, o.value, o.release_id
FROM observations o
JOIN series s USING(series_id)
WHERE s.dataset NOT IN (
    SELECT DISTINCT s2.dataset FROM observation_vintages v
    JOIN series s2 ON s2.series_id = v.series_id
)
"""


def seed():
    con = db.connect()
    try:
        before = con.execute("SELECT count(*) FROM observation_vintages").fetchone()[0]
        con.execute(SEED_SQL)
        after = con.execute("SELECT count(*) FROM observation_vintages").fetchone()[0]
        if after == before:
            print("nothing to seed: every dataset already has vintage history")
        else:
            print("seeded %d vintage rows from live observations (%d -> %d)"
                  % (after - before, before, after))
    finally:
        con.close()
    return 0


# A recorded value identical to the one already in force says nothing: the
# as-of rule reads the newest row at or before a date, so a repeat is pure
# noise — and it makes the revisions endpoint report a revision that never
# happened. Ingest never writes one. This removes any that got in another way.
NOOP_SQL = """
DELETE FROM observation_vintages v
WHERE EXISTS (
    SELECT 1
    FROM observation_vintages p
    JOIN releases rp ON rp.release_id = p.release_id
    JOIN releases rv ON rv.release_id = v.release_id
    WHERE p.series_id = v.series_id AND p.period = v.period
      AND rp.ingested_at < rv.ingested_at
      AND p.value IS NOT DISTINCT FROM v.value
      -- p must be the row immediately preceding v, not merely an earlier one:
      -- a value that changed and then changed back is a real revision twice.
      AND NOT EXISTS (
          SELECT 1 FROM observation_vintages q
          JOIN releases rq ON rq.release_id = q.release_id
          WHERE q.series_id = v.series_id AND q.period = v.period
            AND rq.ingested_at > rp.ingested_at AND rq.ingested_at < rv.ingested_at
      )
)
"""


def compact():
    """Drop recorded values that restate the value already in force.

    Deleting from an append-only store needs justifying: these rows assert a
    revision that did not happen, so removing them restores the history rather
    than editing it. No row that carries information is touched — the as-of
    view is identical before and after.
    """
    con = db.connect()
    try:
        before = con.execute("SELECT count(*) FROM observation_vintages").fetchone()[0]
        con.execute(NOOP_SQL)
        after = con.execute("SELECT count(*) FROM observation_vintages").fetchone()[0]
        print("compacted %d no-op rows (%d -> %d)" % (before - after, before, after))
    finally:
        con.close()
    return 0


def status():
    con = db.connect(read_only=True)
    try:
        rows = con.execute(
            "SELECT s.dataset, count(DISTINCT v.release_id) AS vintages, count(*) AS rows, "
            "       min(r.ingested_at) AS first_known, max(r.ingested_at) AS last_known "
            "FROM observation_vintages v JOIN series s USING(series_id) "
            "JOIN releases r USING(release_id) GROUP BY 1 ORDER BY 1").fetchall()
        if not rows:
            print("no vintage history yet — run: python -m app.vintages seed")
        for dataset, vintages, n, first, last in rows:
            print("%-14s %2d vintage(s)  %8d rows  %s .. %s"
                  % (dataset, vintages, n, first.date(), last.date()))
        # A row restating the value already in force is noise the store should
        # never contain; if any appear, something wrote history it should not
        # have. Surfaced here rather than left to be discovered in a chart.
        noop = con.execute(
            "SELECT count(*) FROM observation_vintages v WHERE EXISTS ("
            "  SELECT 1 FROM observation_vintages p"
            "  JOIN releases rp ON rp.release_id = p.release_id"
            "  JOIN releases rv ON rv.release_id = v.release_id"
            "  WHERE p.series_id = v.series_id AND p.period = v.period"
            "    AND rp.ingested_at < rv.ingested_at"
            "    AND p.value IS NOT DISTINCT FROM v.value"
            "    AND NOT EXISTS ("
            "      SELECT 1 FROM observation_vintages q"
            "      JOIN releases rq ON rq.release_id = q.release_id"
            "      WHERE q.series_id = v.series_id AND q.period = v.period"
            "        AND rq.ingested_at > rp.ingested_at AND rq.ingested_at < rv.ingested_at))"
        ).fetchone()[0]
        if noop:
            print("WARNING: %d rows restate the value already in force — "
                  "run: python -m app.vintages compact" % noop)
    finally:
        con.close()
    return 0


def cutoff(as_of):
    """A date means the whole of that day.

    Releases carry a timestamp, so comparing them against a bare date would
    silently exclude anything published earlier the same morning — "as of 29
    August" must include the release that landed at 04:48 on the 29th.
    """
    if isinstance(as_of, datetime.datetime):
        return as_of
    return datetime.datetime.combine(as_of, datetime.time.max)


def values_as_of(con, dataset, as_of, codes=None):
    """{code: {period: value}} as the data stood at ``as_of`` (a date).

    The vintage table is change-only, so the value in force at a date is the
    newest row at or before it. A NULL there is a tombstone — the observation
    had been withdrawn by then — and is dropped rather than served as a gap of
    unknown origin.
    """
    params = [dataset, cutoff(as_of)]
    code_filter = ""
    if codes:
        code_filter = " AND s.code IN (%s)" % ",".join("?" * len(codes))
        params.extend(codes)
    rows = con.execute(
        "SELECT code, period, value FROM ("
        "  SELECT s.code AS code, v.period AS period, v.value AS value,"
        "         row_number() OVER (PARTITION BY v.series_id, v.period"
        "                            ORDER BY r.ingested_at DESC, v.release_id DESC) AS rn"
        "  FROM observation_vintages v"
        "  JOIN series s USING(series_id)"
        "  JOIN releases r USING(release_id)"
        "  WHERE s.dataset = ? AND r.ingested_at <= ?" + code_filter +
        ") WHERE rn = 1 AND value IS NOT NULL", params).fetchall()
    out = {}
    for code, period, value in rows:
        out.setdefault(code, {})[period] = value
    return out


def revisions(con, dataset, code, period=None):
    """Every recorded value for one series, in release order.

    One row per release that introduced or changed a value — an unchanged
    republish writes nothing, so consecutive rows are always a real revision.
    """
    params = [dataset, code]
    period_filter = ""
    if period is not None:
        period_filter = " AND v.period = ?"
        params.append(period)
    rows = con.execute(
        "SELECT v.period, v.value, v.release_id, r.label, r.ingested_at "
        "FROM observation_vintages v JOIN series s USING(series_id) "
        "JOIN releases r USING(release_id) "
        "WHERE s.dataset = ? AND s.code = ?" + period_filter +
        " ORDER BY v.period, r.ingested_at", params).fetchall()
    return rows


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "seed":
        sys.exit(seed())
    elif command == "status":
        sys.exit(status())
    elif command == "compact":
        sys.exit(compact())
    else:
        print("usage: python -m app.vintages [seed|status|compact]", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
