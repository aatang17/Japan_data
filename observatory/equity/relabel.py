# -*- coding: utf-8 -*-
u"""Fill in the English labels the extractors now write, without re-extracting.

Two label gaps were fixed at their source, in `extract.py` and `fin_extract.py`.
Both fixes take effect when those extractors next run -- which for the nightly
refresh means the next night, but for a laptop copy means whenever someone
happens to run a full pass over five years of filings.

This command applies the same two fills to an existing database directly. It
touches nothing but label columns, reads no filing, and re-running it changes
nothing:

  * **eq_fin_elements.label_en** -- English for the 3,461 standard taxonomy
    elements that a filing's own label linkbase never covers, from the FSA's
    published element lists (`taxonomy_labels.py`). Those elements carry
    5.0 million statement lines between them, including net assets, profit and
    employees.

  * **eq_entities.name_en** -- the company's own English name off its annual
    report cover page, for the 525 filers EDINET's registry leaves blank, 391
    of them listed. The registry is still preferred where it has one; this only
    fills gaps.

Neither is a translation and neither invents a name: both copy a published
English string. Nothing else is written, so no stored figure and no vintage
changes.

    ./.venv/bin/python -m equity.relabel                 # the default DB
    ./.venv/bin/python -m equity.relabel --db /path/to/equity.duckdb
    ./.venv/bin/python -m equity.relabel --dry-run

One writer at a time: stop any local `uvicorn app.main:app` first, or point
`--db` at a copy and swap it in afterwards.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import duckdb  # noqa: E402

import taxonomy_labels  # noqa: E402


def default_db():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("EQUITY_DB_PATH",
                          os.path.join(here, "..", "data", "equity.duckdb"))


def fill_elements(con, dry_run):
    labels = taxonomy_labels.load()
    if not labels:
        print("element labels: no taxonomy_en.csv; run "
              "`python -m equity.taxonomy_labels` first")
        return 0
    gaps = [r[0] for r in con.execute(
        "SELECT element FROM eq_fin_elements "
        "WHERE label_en IS NULL OR trim(label_en) = ''").fetchall()]
    rows = [(labels[e], e) for e in gaps if e in labels]
    if rows and not dry_run:
        con.executemany(
            "UPDATE eq_fin_elements SET label_en = ? WHERE element = ?", rows)
    print("element labels: %d of %d gaps filled, %d have no published label"
          % (len(rows), len(gaps), len(gaps) - len(rows)))
    return len(rows)


def fill_entities(con, dry_run):
    n = con.execute("""
        SELECT count(*) FROM eq_entities e
         WHERE (e.name_en IS NULL OR trim(e.name_en) = '')
           AND EXISTS (SELECT 1 FROM eq_filings f
                        WHERE f.edinet_code = e.edinet_code
                          AND f.filer_name_en IS NOT NULL
                          AND trim(f.filer_name_en) <> '')""").fetchone()[0]
    if n and not dry_run:
        con.execute("""
            UPDATE eq_entities AS e
               SET name_en = (SELECT max(f.filer_name_en) FROM eq_filings f
                               WHERE f.edinet_code = e.edinet_code
                                 AND f.filer_name_en IS NOT NULL
                                 AND trim(f.filer_name_en) <> '')
             WHERE e.name_en IS NULL OR trim(e.name_en) = ''""")
    # Counted the same way whether or not the write happened: a listed company
    # with no registry name AND no cover-page name of its own.
    still = con.execute("""
        SELECT count(*) FROM eq_entities e
         WHERE e.listed
           AND (e.name_en IS NULL OR trim(e.name_en) = '')
           AND NOT EXISTS (SELECT 1 FROM eq_filings f
                            WHERE f.edinet_code = e.edinet_code
                              AND f.filer_name_en IS NOT NULL
                              AND trim(f.filer_name_en) <> '')""").fetchone()[0]
    print("company names: %d filled from their own cover page; "
          "%d listed companies still have no published English name anywhere"
          % (n, still))
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=default_db())
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()
    con = duckdb.connect(args.db, read_only=args.dry_run)
    try:
        fill_elements(con, args.dry_run)
        fill_entities(con, args.dry_run)
    finally:
        con.close()
    print(("would write to " if args.dry_run else "wrote ")
          + os.path.normpath(args.db))


if __name__ == "__main__":
    main()
