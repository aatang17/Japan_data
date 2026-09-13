# -*- coding: utf-8 -*-
u"""Canaries — a fixed set of filings whose answers we already know.

WHAT THIS IS FOR
----------------
The validation gates inside each extractor check that a filing is internally
consistent. Freshness checks that the archive is still being read. Neither
notices the failure that actually happens when a source changes shape: the
parser keeps running, keeps reporting `clean`, and quietly stops finding one
field, or finds the wrong one.

Two real examples, both from the week these extractors were written:

  * The target board's opinion on a takeover moved to a different element name
    between taxonomy years. The parser read it on 4% of filings instead of 92%
    and raised no error at all.
  * A company left its next-year sales forecast blank. The forecast is written
    as a self-closing tag, the pattern ran past it, and the parser stored the
    number from two rows below: a forecast of 15.8 yen for a company with
    11.5bn yen of sales. Every gate passed.

A canary catches both on the night it happens. We take filings whose values a
human has read off the document, write those values down, and reparse the same
files every run. If the answer changes, either the source changed or we broke
the parser, and either way somebody needs to look. It is the cheapest honest
check there is, because the expected values are not computed by the code being
tested.

CHOOSING CANARIES
-----------------
One per parser is not enough and a hundred is maintenance. The set below holds
a handful per parser, chosen so that each one exercises a DIFFERENT shape:
a table-form filing and a prose-form filing, an issuer self-tender and a
third-party bid, a filing with a forecast range and one without. A canary that
duplicates another's shape costs a download and proves nothing new.

A canary is never "fixed" by editing the expected value to match new output.
If the source really did change, the filing is immutable, so the old value was
either right (and the parser is now broken) or wrong (and it was always
broken). Change an expected value only with the document open in front of you.

Usage (from observatory/equity/):
    ../.venv/bin/python canary.py                 # local archive
    ../.venv/bin/python canary.py --source s3     # the real archive
    ../.venv/bin/python canary.py --json          # machine-readable

Exit code is 1 if any canary fails, so the nightly refresh can ping a failure.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED = os.path.join(HERE, "canary_expected.json")


# ------------------------------------------------------------------ fetching

def read_edinet(source, day, doc_id, dl_type):
    if source == "local":
        from extract import ARCHIVE
        path = os.path.join(ARCHIVE, "docs", day,
                            "%s_t%s.zip" % (doc_id, dl_type))
        with open(path, "rb") as f:
            return f.read()
    from extract import S3Source
    src = S3Source(1)
    return src.c.get_object(
        Bucket=src.bucket,
        Key="docs/%s/%s_t%s.zip" % (day, doc_id, dl_type))["Body"].read()


def read_tdnet(source, day, name):
    if source == "local":
        import tdnet_extract
        return tdnet_extract.LocalTdnet().doc(day, name)
    import tdnet_extract
    return tdnet_extract.S3Tdnet().doc(day, name)


# ----------------------------------------------------------------- extracting

def value_of(parsed, path):
    u"""Pull one value out of a parser's result.

    `path` is a field name, or one of two addressed forms. `|` separates the
    parts because XBRL element names contain colons (`jppfs_cor:Assets`) and a
    colon-separated path splits them in the wrong place.

        fact|<element>|<context>      one fact from a long fact list
        list|<name>|<index>|<field>   one row of a detail list the parser built
    """
    if path.startswith("fact|"):
        _, element, context = path.split("|", 2)
        for tup in parsed:
            if len(tup) > 2 and tup[1] == element and tup[2] == context:
                return tup[-1]
        return None
    if path.startswith("list|"):
        _, name, idx, field = path.split("|", 3)
        rows = parsed.get(name) or []
        if int(idx) >= len(rows):
            return None
        row = rows[int(idx)]
        if isinstance(row, dict):
            return row.get(field)
        if isinstance(row, (list, tuple)):
            if field.isdigit():
                return row[int(field)] if int(field) < len(row) else None
            # a (role, {...}) pair, as the event parser builds for a party
            for part in row:
                if isinstance(part, dict) and field in part:
                    return part[field]
        return None
    return parsed.get(path)


def comparable(v):
    u"""Dates compare as their ISO text, so an expected value stays readable
    in the JSON and does not depend on the parser returning a date object."""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def run_one(case, source):
    u"""(ok, [(field, expected, got)]) for one canary."""
    parser = case["parser"]
    if parser == "tdnet":
        blob = read_tdnet(source, case["day"], case["doc"])
        import tdnet_extract
        facts, header = tdnet_extract.summary_facts(blob)
        parsed = facts
        header_get = header
    else:
        blob = read_edinet(source, case["day"], case["doc"],
                           case.get("dl_type", 1))
        header_get = None
        if parser == "toi":
            import toi_extract
            parsed = toi_extract.parse(blob, case["doc_type"])
        elif parser == "event":
            import event_extract
            parsed = event_extract.parse(blob, case["doc_type"])
        elif parser == "issue":
            import issue_extract
            parsed = issue_extract.parse(blob)
        elif parser == "ssr":
            import ssr_extract
            parsed = ssr_extract.parse_facts(blob)[0]
        else:
            raise ValueError("unknown parser %r" % parser)

    diffs = []
    for field, want in sorted(case["expect"].items()):
        if header_get is not None and field.startswith("header:"):
            got = header_get.get(field.split(":", 1)[1])
        else:
            got = value_of(parsed, field)
        got = comparable(got)
        if isinstance(want, float) or isinstance(got, float):
            same = (got is not None
                    and abs(float(got) - float(want)) <= abs(float(want)) * 1e-9)
        else:
            same = got == want
        if not same:
            diffs.append((field, want, got))
    return (not diffs), diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--only", help="run only canaries whose parser matches")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--file", default=EXPECTED)
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        cases = json.load(f)["canaries"]
    if args.only:
        cases = [c for c in cases if c["parser"] == args.only]

    results = []
    failed = 0
    for case in cases:
        try:
            ok, diffs = run_one(case, args.source)
            err = None
        except Exception as e:                                    # noqa: BLE001
            ok, diffs, err = False, [], "%s: %s" % (type(e).__name__, str(e)[:140])
        if not ok:
            failed += 1
        results.append({"name": case["name"], "parser": case["parser"],
                        "doc": case["doc"], "ok": ok, "error": err,
                        "diffs": [{"field": f, "expected": w, "got": g}
                                  for f, w, g in diffs]})

    if args.json:
        print(json.dumps({"total": len(results), "failed": failed,
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "ok  " if r["ok"] else "FAIL"
            print("%s %-10s %-34s %s" % (mark, r["parser"], r["name"], r["doc"]))
            if r["error"]:
                print("       error: %s" % r["error"])
            for d in r["diffs"]:
                print("       %-28s expected %r, got %r"
                      % (d["field"], d["expected"], d["got"]))
        print("\n%d canaries, %d failed" % (len(results), failed))
        if failed:
            print("A canary fails for one of two reasons: the source changed "
                  "shape, or we broke the parser. The filing itself cannot "
                  "have changed — do not edit the expected value to match.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
