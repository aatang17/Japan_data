# -*- coding: utf-8 -*-
"""One-off: re-resolve held-company matches from the names already stored.

Why this exists
---------------
`extract.py` used to match a held company on a key that stripped ホールディングス
before comparing, so ヤマトホールディングス (9064, ~360mn shares) and
株式会社ヤマト (1967, ~27mn shares) — unrelated companies — shared one key, and
whichever EDINET listed first won. Every ownership percentage is
shares ÷ that company's own share count, so a wrong link published a wrong
stake: Toyota's Yamato Holdings holding read 25.7% instead of 1.8%, and
Sato Sho-ji's Resonac Holdings holding read 478,750% against a private
subsidiary's eight shares.

The resolver is fixed at source. This script applies the same fix to rows
already extracted, without re-reading the 21,084 archived filings: the held
name is stored exactly as filed in `held_name_raw`, which is all the resolver
ever consumed.

What it does and does not touch
-------------------------------
It rewrites three derived columns — `match_status`, `held_edinet_code`,
`held_sec_code` — on `eq_holdings` and `eq_reclassified`. It never touches a
filed figure: names, share counts, book values, purposes and reciprocity flags
are read-only here, and `parser_version` stays as recorded because the parsed
holdings are unchanged. The link from a position to a company is our inference
about the filing, not a number the filing states.

    cd equity && ../observatory/.venv/bin/python rematch.py
    ../observatory/.venv/bin/python rematch.py --dry-run   # report, change nothing
"""
import argparse
import os
import collections
import collections

import duckdb

import sys

# The extractors moved to observatory/equity/ so they ship inside the
# serving image; this maintenance tool stayed with the archive.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "observatory", "equity"))

import extract

TABLES = ("eq_holdings", "eq_reclassified")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=extract.DB_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, write nothing")
    args = ap.parse_args()

    tiers = extract.build_index(extract.load_codelist())
    con = duckdb.connect(args.db, read_only=args.dry_run)
    evidence = extract.filing_evidence(con)

    def resolve(nm, when):
        for tier, key in zip(tiers, (extract.norm(nm), extract.core_name(nm),
                                     extract.base_name(nm))):
            entries = tier.get(key)
            if entries:
                hit = extract.pick(entries, evidence, when)
                if hit:
                    return "matched", hit[0], hit[1] or None
        return ("foreign" if extract.is_foreign(nm) else "unmatched"), None, None
    for table in TABLES:
        # Which registration of a company was filing depends on the year, so a
        # name is resolved once per fiscal period rather than once overall.
        rows = con.execute(
            "SELECT r.held_name_raw, f.period_end, r.match_status, "
            "       r.held_edinet_code, r.held_sec_code, count(*) "
            "FROM %s r JOIN eq_filings f USING (doc_id) "
            "GROUP BY 1, 2, 3, 4, 5" % table).fetchall()
        moved = collections.Counter()
        gained = lost = same = 0
        for nm, when, mstat, ec, sc, n in rows:
            new = resolve(nm or "", when)
            if new == (mstat, ec, sc):
                same += n
                continue
            if new[1] and ec and new[1] != ec:
                moved[(nm, ec, new[1])] += n
            elif new[1] and not ec:
                gained += n
            elif ec and not new[1]:
                lost += n
            if not args.dry_run:
                con.execute(
                    "UPDATE %s SET match_status = ?, held_edinet_code = ?, "
                    "held_sec_code = ? WHERE rowid IN ("
                    "  SELECT r.rowid FROM %s r JOIN eq_filings f USING (doc_id) "
                    "  WHERE r.held_name_raw IS NOT DISTINCT FROM ? "
                    "    AND f.period_end IS NOT DISTINCT FROM ?)"
                    % (table, table), [new[0], new[1], new[2], nm, when])
        print("%s: %d name-periods, %d rows unchanged, %d re-pointed, "
              "%d newly matched, %d now unmatched" %
              (table, len(rows), same, sum(moved.values()), gained, lost))
        for (nm, old, new), n in moved.most_common(40):
            print("    %4d rows  %s  %s -> %s" % (n, nm, old, new))

    if not args.dry_run:
        # Match rate is a published figure; restate it from what is now stored.
        n, m = con.execute(
            "SELECT count(*), count(*) FILTER (WHERE match_status = 'matched') "
            "FROM eq_holdings WHERE match_status <> 'foreign'").fetchone()
        print("entity matching: %d/%d domestic (%.1f%%)" % (m, n, 100.0 * m / n))
    con.close()


if __name__ == "__main__":
    main()
