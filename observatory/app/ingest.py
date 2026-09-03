"""Ingestion runner: fetch -> archive -> parse -> validate -> publish.

Usage:  python -m app.ingest cpi-jp [--from-file path.csv]

Every run archives the raw artifact with its checksum before parsing.
If the checksum matches the newest artifact for the source, the run
stops (nothing new). A failed validation records nothing but the
artifact — the previous published release stays untouched.

Publishing replaces the dataset's live observations in one transaction
and marks the prior release 'superseded' — but it also appends what it
changed to observation_vintages, which is never rewritten. Series rows
are upserted so series_id stays stable across releases. Raw artifacts
are retained for every run.
"""
import argparse
import datetime
import hashlib
import json
import sys

from . import db, env

# Adapters that call a keyed API read their credential from the environment;
# .env is the local-development fallback the server already loads. Without
# this the ingest fails only for keyed sources, and only outside the server.
env.load()

from .adapters import (boj_assets, cpi_jp, cpi_jp_items, jnto_visitors,
                       juki_population, mof_jgb, mof_trade, ssds_population)

ADAPTERS = {"cpi-jp": cpi_jp, "cpi-jp-items": cpi_jp_items, "boj-assets": boj_assets,
            "jgb-yields": mof_jgb, "jnto-visitors": jnto_visitors,
            "population-jp": juki_population,
            "population-jp-history": ssds_population,
            "trade-semis": mof_trade}

# "this (series, period) had no prior value at all" — distinct from a prior
# value that happens to be None.
_ABSENT = object()


def _many(con, sql, rows):
    """executemany that tolerates nothing to do.

    DuckDB raises on an empty parameter list, and empty is the normal case
    here: a month where no series was added, none was retired, or nothing was
    revised is a successful ingest, not a failed one.
    """
    if rows:
        con.executemany(sql, rows)


def run(slug, from_file=None):
    adapter = ADAPTERS[slug]

    if from_file:
        raw = open(from_file, "rb").read()
        origin = "file://" + from_file
    else:
        print("fetching %s ..." % adapter.DOWNLOAD_URL)
        raw = adapter.fetch()
        origin = adapter.DOWNLOAD_URL
    sha = hashlib.sha256(raw).hexdigest()
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    con = db.connect()
    try:
        # Prefer UPDATE-then-INSERT over INSERT OR REPLACE / ON CONFLICT.
        # DuckDB ≥1.4 rejects REPLACE (and some upserts) when child rows still
        # reference the parent, and also rejects UPDATEs that touch a column
        # that is itself a foreign key (sources.dataset → datasets.slug) while
        # artifacts reference the source. Metadata that can change is updated;
        # identity columns (slug, source_id, dataset) are left alone.
        if con.execute("SELECT 1 FROM datasets WHERE slug=?", [slug]).fetchone():
            con.execute(
                "UPDATE datasets SET title=?, country=?, agency=?, agency_ja=?, "
                "base=?, frequency=?, description=? WHERE slug=?",
                [adapter.DATASET[k] for k in
                 ("title", "country", "agency", "agency_ja", "base", "frequency", "description")]
                + [slug],
            )
        else:
            con.execute(
                "INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?)",
                [adapter.DATASET[k] for k in
                 ("slug", "title", "country", "agency", "agency_ja", "base", "frequency", "description")],
            )
        source_id = adapter.SOURCE["source_id"]
        if con.execute("SELECT 1 FROM sources WHERE source_id=?", [source_id]).fetchone():
            con.execute(
                "UPDATE sources SET name=?, name_ja=?, url=?, license_note=? WHERE source_id=?",
                [adapter.SOURCE["name"], adapter.SOURCE["name_ja"],
                 adapter.SOURCE["url"], adapter.SOURCE["license_note"], source_id],
            )
        else:
            con.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?)",
                [source_id, slug, adapter.SOURCE["name"],
                 adapter.SOURCE["name_ja"], adapter.SOURCE["url"], adapter.SOURCE["license_note"]],
            )

        prior = con.execute(
            "SELECT a.sha256, a.path FROM source_artifacts a "
            "JOIN releases r ON r.artifact_id = a.artifact_id AND r.status = 'published' "
            "WHERE a.source_id=? ORDER BY a.retrieved_at DESC LIMIT 1",
            [adapter.SOURCE["source_id"]],
        ).fetchone()
        if prior and prior[0] == sha:
            print("unchanged: newest artifact already has sha256 %s..." % sha[:12])
            return 0
        # Sources whose response embeds a fetch timestamp never repeat
        # byte-for-byte; such adapters expose canonical_bytes() and the
        # unchanged check compares canonical content against the archived
        # copy of the newest published artifact.
        canonical = getattr(adapter, "canonical_bytes", None)
        if prior and canonical is not None:
            try:
                prior_raw = open(prior[1], "rb").read()
            except OSError:
                prior_raw = None
            if prior_raw is not None and canonical(prior_raw) == canonical(raw):
                print("unchanged: canonical content matches artifact %s..." % prior[0][:12])
                return 0

        # archive first, validate second — evidence is kept even for bad files
        db.RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        suffix = getattr(adapter, "RAW_SUFFIX", ".csv")
        path = db.RAW_DIR / ("%s-%s-%s%s" % (slug, stamp, sha[:12], suffix))
        path.write_bytes(raw)
        artifact_id = con.execute(
            "INSERT INTO source_artifacts (source_id, url, retrieved_at, sha256, path, bytes) "
            "VALUES (?,?,?,?,?,?) RETURNING artifact_id",
            [adapter.SOURCE["source_id"], origin, now, sha, str(path), len(raw)],
        ).fetchone()[0]

        series, observations = adapter.parse(raw)
        summary = adapter.validate(series, observations)
        print("validated: %s" % json.dumps(summary))

        latest = datetime.date.fromisoformat(summary["latest_period"])
        # A daily dataset gets daily vintages; a month-only label would give
        # many releases the same name, so the label carries the day.
        label_fmt = ("%d %B %Y" if adapter.DATASET.get("frequency") == "daily"
                     else "%B %Y")
        # The live values this release is about to replace. Read before the
        # transaction rewrites them: the vintage delta is the difference
        # between these and the incoming ones.
        previous = {(code, period): value for code, period, value in con.execute(
            "SELECT s.code, o.period, o.value FROM observations o "
            "JOIN series s USING(series_id) WHERE s.dataset=?", [slug]).fetchall()}
        existing_codes = set(
            c for (c,) in con.execute(
                "SELECT code FROM series WHERE dataset=?", [slug]).fetchall())

        con.execute("BEGIN")
        con.execute("UPDATE releases SET status='superseded' WHERE dataset=? AND status='published'", [slug])
        release_id = con.execute(
            "INSERT INTO releases (dataset, artifact_id, label, latest_period, ingested_at, status, validation) "
            "VALUES (?,?,?,?,?,?,?) RETURNING release_id",
            [slug, artifact_id, "Data through %s" % latest.strftime(label_fmt),
             latest, now, "published", json.dumps(summary)],
        ).fetchone()[0]

        # Series rows are upserted, never replaced. series_id is the stable
        # identity that observation_vintages — and any external reference —
        # hangs off; delete-and-reinsert would hand every series a fresh id
        # from the sequence on every ingest and orphan the history. Identity
        # columns are left alone: DuckDB rejects an UPDATE touching a column
        # that is itself a foreign key while child rows reference the parent.
        _many(con,
            "UPDATE series SET name_en=?, name_ja=?, unit=?, weight_per_10000=?, "
            "sort_order=?, active=TRUE WHERE dataset=? AND code=?",
            [[s["name_en"], s["name_ja"], s.get("unit", "index"),
              s["weight_per_10000"], s["sort_order"], slug, s["code"]]
             for s in series if s["code"] in existing_codes],
        )
        _many(con,
            "INSERT INTO series (dataset, code, name_en, name_ja, unit, weight_per_10000, sort_order) "
            "VALUES (?,?,?,?,?,?,?)",
            [[slug, s["code"], s["name_en"], s["name_ja"], s.get("unit", "index"),
              s["weight_per_10000"], s["sort_order"]]
             for s in series if s["code"] not in existing_codes],
        )
        # A series the source has stopped publishing is retired, not removed:
        # its history stays queryable at the vintages where it existed.
        retired = sorted(existing_codes - set(s["code"] for s in series))
        _many(con,
            "UPDATE series SET active=FALSE WHERE dataset=? AND code=?",
            [[slug, code] for code in retired],
        )
        code_to_id = dict(con.execute(
            "SELECT code, series_id FROM series WHERE dataset=?", [slug]).fetchall())

        con.execute(
            "DELETE FROM observations WHERE series_id IN (SELECT series_id FROM series WHERE dataset=?)",
            [slug],
        )
        _many(con,
            "INSERT INTO observations VALUES (?,?,?,?)",
            [[code_to_id[o["code"]], o["period"], o["value"], release_id] for o in observations],
        )

        # Point-in-time history: append what this release introduced or
        # changed. An unchanged value writes nothing — the value as of any
        # date is the newest row at or before it, so republishing the same
        # number carries no information. A value that has *gone* does, hence
        # the explicit NULL tombstone.
        vintage = []
        for o in observations:
            prior = previous.pop((o["code"], o["period"]), _ABSENT)
            if prior is _ABSENT or prior != o["value"]:
                vintage.append([code_to_id[o["code"]], o["period"], o["value"], release_id])
        withdrawn = sorted(previous)
        vintage.extend([code_to_id[code], period, None, release_id]
                       for code, period in withdrawn)
        _many(con, "INSERT INTO observation_vintages VALUES (?,?,?,?)", vintage)

        con.execute("COMMIT")
        print("published release %d: %d series, %d observations, latest %s"
              % (release_id, len(series), len(observations), latest))
        print("vintage: %d new or revised values, %d withdrawn%s"
              % (len(vintage) - len(withdrawn), len(withdrawn),
                 ", %d series retired" % len(retired) if retired else ""))
        return 0
    except adapter.ValidationError as exc:
        print("VALIDATION FAILED — nothing published: %s" % exc, file=sys.stderr)
        return 1
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description="Observatory ingestion")
    ap.add_argument("dataset", choices=sorted(ADAPTERS))
    ap.add_argument("--from-file", help="parse a local CSV instead of downloading")
    args = ap.parse_args()
    sys.exit(run(args.dataset, args.from_file))


if __name__ == "__main__":
    main()
