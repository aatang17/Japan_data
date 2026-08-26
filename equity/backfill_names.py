# -*- coding: utf-8 -*-
"""One-off: fill eq_filings.filer_name_en from each filer's latest filing.

Why this exists
---------------
Every 有価証券報告書 states the filer's own English name on its cover page
(`jpcrp_cor:CompanyNameInEnglishCoverPage`, 【英訳名】). EDINET's filer
registry also carries an English name, but leaves it blank for roughly one
listed filer in ten — Murata Manufacturing (E01914) among them, which is why
searching "Murata" found nothing while 232 filings name it as a holding.

The filing is the better source on both counts: it covers ~99.6% of the
registry's gaps, and it is *as filed* rather than a registry label.

Scope: one filing per filer — its latest. Every surface shows one name per
company, so that is complete for the product. `extract.py` captures the field
for every filing from here on, so history fills in on the next full run.

This never touches an extracted figure. It writes one new column on rows whose
holdings were parsed by an earlier parser version, from the same archived bytes
under the same SHA-256; `parser_version` therefore stays as recorded, since the
holdings it describes are unchanged.

    railway run --service edinet-capture-job -- \
        ../observatory/.venv/bin/python backfill_names.py --source s3
"""
import argparse
import io
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor

import duckdb

import extract

ELEMENT = "jpcrp_cor:CompanyNameInEnglishCoverPage"
SEED_DB = os.path.join(extract.HERE, "..", "observatory", "seed", "equity.duckdb")

# One rule for stripping the Japanese annotations filers append to the English
# name, shared with the extractor so a backfilled row and a freshly extracted
# one can never disagree.
clean = extract.clean_english_name


def english_name(blob):
    """Read only the cover-page English name out of a CSV package."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members = [m for m in z.namelist() if "jpcrp030000-asr" in m and m.endswith(".csv")]
        if not members:
            return None
        text = z.read(members[0]).decode("utf-16")
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith('"' + ELEMENT + '"'):
            fields = line.split("\t")
            if len(fields) == 9:
                return clean(fields[8])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="s3")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--db", default=SEED_DB)
    ap.add_argument("--limit", type=int, help="stop after N filings (smoke test)")
    args = ap.parse_args()

    con = duckdb.connect(os.path.abspath(args.db))
    cols = [r[1] for r in con.execute("PRAGMA table_info('eq_filings')").fetchall()]
    if "filer_name_en" not in cols:
        con.execute("ALTER TABLE eq_filings ADD COLUMN filer_name_en VARCHAR")
        print("added eq_filings.filer_name_en")

    # one filing per filer: the latest, which is the one every surface shows
    targets = con.execute("""
        SELECT doc_id, edinet_code, filed_date FROM (
            SELECT doc_id, edinet_code, filed_date, filer_name_en,
                   row_number() OVER (PARTITION BY edinet_code
                                      ORDER BY period_end DESC, filed_date DESC) AS rn
            FROM eq_filings
            WHERE status IN ('clean','partial') AND edinet_code IS NOT NULL)
        WHERE rn = 1 AND filer_name_en IS NULL
    """).fetchall()
    if args.limit:
        targets = targets[:args.limit]
    print("filers to read: %d (source=%s)" % (len(targets), args.source))
    if not targets:
        return

    src = extract.S3Source(args.workers) if args.source == "s3" else extract.LocalSource()
    index = src.filings()          # doc_id -> {"date": YYYY-MM-DD}, the archive's own layout

    def read_one(t):
        doc_id, ecode, filed = t
        rec = index.get(doc_id)
        date = rec["date"] if rec else (str(filed) if filed else None)
        if not date:
            return doc_id, None, "not in archive"
        try:
            return doc_id, english_name(src.read_zip(doc_id, date)), None
        except Exception as exc:
            return doc_id, None, "%s: %s" % (type(exc).__name__, exc)

    found = blank = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (doc_id, name, err) in enumerate(ex.map(read_one, targets), 1):
            if err:
                failed += 1
            elif name:
                con.execute("UPDATE eq_filings SET filer_name_en = ? WHERE doc_id = ?",
                            [name, doc_id])
                found += 1
            else:
                blank += 1
            if i % 250 == 0:
                print("  %d/%d  named:%d blank:%d failed:%d"
                      % (i, len(targets), found, blank, failed))
    print("done: named %d, no English name stated %d, unreadable %d"
          % (found, blank, failed))
    # Fold the write-ahead log into the database file before leaving. Without
    # this the updates can still be sitting in equity.duckdb.wal, and copying
    # the .duckdb alone — to seed/, into the image — silently ships the old
    # data with none of the names.
    con.execute("CHECKPOINT")
    con.close()


if __name__ == "__main__":
    main()
