# -*- coding: utf-8 -*-
u"""English labels for the standard EDINET taxonomy elements.

Why this file exists
--------------------
A filing's t1 package carries an English label linkbase, but only for the
filer's OWN extension elements -- the sixteen or so line items it invented.
Every standard element it uses (jppfs_cor:NetAssets, jpcrp_cor:NumberOfEmployees,
the whole five-year summary) is defined in the taxonomy the FSA publishes, and
its English label lives there, not in the filing.

So `eq_fin_elements` ended up with English for all 51,000 extension elements and
none for the 3,464 standard ones -- exactly backwards from what a reader needs,
because the standard ones are the statements themselves. `jppfs_cor:NetAssets`
alone appears on 98,422 statement lines.

Where the labels come from
--------------------------
The FSA's own element and account lists for each annual taxonomy edition:

    https://www.fsa.go.jp/search/<edition>/1e_ElementList.xlsx     all elements
    https://www.fsa.go.jp/search/<edition>/1f_AccountList.xlsx     line items,
                                                                   by industry
    https://www.fsa.go.jp/search/<edition>/1g_IFRS_ElementList.xlsx IFRS

Each row gives 名前空間プレフィックス (namespace), 要素名 (element) and
標準ラベル（英語）-- the FSA's published English label. Nothing is translated
here; the label is copied.

Editions are cumulative in practice but not identical: an element added in 2026
is absent from the 2025 list, and a label can be reworded. Later editions
therefore win, and every edition we have read is listed in EDITIONS so the file
can be rebuilt.

Rebuild after a new edition is published:

    ./.venv/bin/python -m equity.taxonomy_labels --edition 20261110

which downloads, merges with what is already in `taxonomy_en.csv`, and rewrites
it. `fin_extract.py` loads that CSV on every run and fills in any element whose
English label is still missing; it never overwrites a label a filer supplied for
its own extension element.
"""
import argparse
import csv
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.adapters import xlsx  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "taxonomy_en.csv")

# Annual editions read so far, oldest first. A later edition overrides an
# earlier one for the same element.
EDITIONS = ["20211109", "20221108", "20231211", "20241112", "20251111"]

BASE = "https://www.fsa.go.jp/search/%s/%s"
WORKBOOKS = ("1f_AccountList.xlsx", "1e_ElementList.xlsx", "1g_IFRS_ElementList.xlsx")

COL_ELEMENT = u"要素名"
COL_PREFIX = u"名前空間プレフィックス"
COL_LABEL_EN = u"標準ラベル（英語）"


def harvest(blob):
    u"""One FSA workbook -> {"jppfs_cor:NetAssets": "Net assets"}.

    Every sheet is scanned, because the account list splits line items across
    twenty-three industry sheets and the element list across sixty-eight form
    sheets. A sheet with no recognisable header is skipped rather than guessed
    at. Column letters are read from the header row: empty cells are absent
    from the parsed grid, so a positional read would silently shift.
    """
    z = zipfile.ZipFile(io.BytesIO(blob))
    shared = xlsx.shared_strings(z)
    italics = xlsx.italic_styles(z)
    out = {}
    for target in xlsx.sheet_targets(z).values():
        grid = xlsx.grid(z, shared, italics, target)
        header_row = columns = None
        for rn in sorted(grid)[:12]:
            names = dict((grid[rn][c][0] or "", c) for c in grid[rn])
            if COL_ELEMENT in names and COL_LABEL_EN in names and COL_PREFIX in names:
                header_row, columns = rn, names
                break
        if not columns:
            continue
        c_el, c_pf = columns[COL_ELEMENT], columns[COL_PREFIX]
        c_en = columns[COL_LABEL_EN]
        for rn in sorted(grid):
            if rn <= header_row:
                continue
            row = grid[rn]
            element = (row.get(c_el, ("",))[0] or "").strip()
            prefix = (row.get(c_pf, ("",))[0] or "").strip()
            label = (row.get(c_en, ("",))[0] or "").strip()
            if element and prefix and label:
                out.setdefault(prefix + ":" + element, label)
    return out


def load():
    u"""The committed CSV -> {element: label_en}. Empty if it is not there."""
    if not os.path.exists(CSV_PATH):
        return {}
    out = {}
    with io.open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.reader(l for l in f if not l.startswith("#")):
            if len(row) >= 2 and row[0] != "element":
                out[row[0]] = row[1]
    return out


def build(editions, existing=None):
    u"""Fetch and merge, oldest edition first so the newest label wins.

    An edition that is not on the FSA's site in this shape -- the older ones
    split their workbooks differently -- is reported and skipped rather than
    failing the build, because the run is still worth the editions that did
    load.
    """
    import urllib.error
    import urllib.request
    labels = dict(existing or {})
    for edition in editions:
        for name in WORKBOOKS:
            url = BASE % (edition, name)
            try:
                blob = urllib.request.urlopen(url, timeout=120).read()
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                sys.stderr.write("skip %s (%s)\n" % (url, exc))
                continue
            found = harvest(blob)
            labels.update(found)          # a later edition wins
            sys.stderr.write("  %s %s: %d labels\n" % (edition, name, len(found)))
    return labels


def write(labels, editions):
    rows = sorted(labels.items())
    with io.open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(u"# English labels for the standard EDINET taxonomy elements,\n")
        f.write(u"# copied from the FSA's published element and account lists:\n")
        for edition in editions:
            f.write(u"#   https://www.fsa.go.jp/search/%s/  (1e, 1f, 1g)\n" % edition)
        f.write(u"# Rebuild with: python -m equity.taxonomy_labels --edition <YYYYMMDD>\n")
        w = csv.writer(f)
        w.writerow(["element", "label_en"])
        for element, label in rows:
            w.writerow([element, label])
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--edition", action="append", default=None,
                    help="FSA edition path segment, e.g. 20251111. Repeatable. "
                         "Defaults to every edition in EDITIONS.")
    ap.add_argument("--merge", action="store_true",
                    help="keep labels already in taxonomy_en.csv")
    args = ap.parse_args()
    editions = args.edition or EDITIONS
    labels = build(editions, load() if args.merge else None)
    n = write(labels, sorted(set(EDITIONS) | set(editions)))
    print("wrote %d labels to %s" % (n, CSV_PATH))


if __name__ == "__main__":
    main()
