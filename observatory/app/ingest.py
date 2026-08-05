"""Ingestion runner: fetch -> archive -> parse -> validate -> publish.

Usage:  python -m app.ingest cpi-jp [--from-file path.csv]

Every run archives the raw artifact with its checksum before parsing.
If the checksum matches the newest artifact for the source, the run
stops (nothing new). A failed validation records nothing but the
artifact — the previous published release stays untouched.

v1 keeps a single live vintage: publishing replaces the dataset's
series and observations in one transaction and marks the prior
release 'superseded'. Raw artifacts are retained for every run.
"""
import argparse
import datetime
import hashlib
import json
import sys

from . import db
from .adapters import cpi_jp, cpi_jp_items

ADAPTERS = {"cpi-jp": cpi_jp, "cpi-jp-items": cpi_jp_items}


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
        con.execute(
            "INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?,?)",
            [adapter.DATASET[k] for k in
             ("slug", "title", "country", "agency", "agency_ja", "base", "frequency", "description")],
        )
        con.execute(
            "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?)",
            [adapter.SOURCE["source_id"], slug, adapter.SOURCE["name"],
             adapter.SOURCE["name_ja"], adapter.SOURCE["url"], adapter.SOURCE["license_note"]],
        )

        prior = con.execute(
            "SELECT a.sha256 FROM source_artifacts a "
            "JOIN releases r ON r.artifact_id = a.artifact_id AND r.status = 'published' "
            "WHERE a.source_id=? ORDER BY a.retrieved_at DESC LIMIT 1",
            [adapter.SOURCE["source_id"]],
        ).fetchone()
        if prior and prior[0] == sha:
            print("unchanged: newest artifact already has sha256 %s..." % sha[:12])
            return 0

        # archive first, validate second — evidence is kept even for bad files
        db.RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        path = db.RAW_DIR / ("%s-%s-%s.csv" % (slug, stamp, sha[:12]))
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
        con.execute("BEGIN")
        con.execute("UPDATE releases SET status='superseded' WHERE dataset=? AND status='published'", [slug])
        release_id = con.execute(
            "INSERT INTO releases (dataset, artifact_id, label, latest_period, ingested_at, status, validation) "
            "VALUES (?,?,?,?,?,?,?) RETURNING release_id",
            [slug, artifact_id, "Data through %s" % latest.strftime("%B %Y"),
             latest, now, "published", json.dumps(summary)],
        ).fetchone()[0]

        con.execute(
            "DELETE FROM observations WHERE series_id IN (SELECT series_id FROM series WHERE dataset=?)",
            [slug],
        )
        con.execute("DELETE FROM series WHERE dataset=?", [slug])
        con.executemany(
            "INSERT INTO series (dataset, code, name_en, name_ja, unit, weight_per_10000, sort_order) "
            "VALUES (?,?,?,?, 'index', ?,?)",
            [[slug, s["code"], s["name_en"], s["name_ja"], s["weight_per_10000"], s["sort_order"]]
             for s in series],
        )
        code_to_id = dict(con.execute(
            "SELECT code, series_id FROM series WHERE dataset=?", [slug]).fetchall())
        con.executemany(
            "INSERT INTO observations VALUES (?,?,?,?)",
            [[code_to_id[o["code"]], o["period"], o["value"], release_id] for o in observations],
        )
        con.execute("COMMIT")
        print("published release %d: %d series, %d observations, latest %s"
              % (release_id, len(series), len(observations), latest))
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
