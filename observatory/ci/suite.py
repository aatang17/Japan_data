# -*- coding: utf-8 -*-
"""The test suite, with a policy about skipping.

Two modes, because there are two machines:

  --mode ci     No database anywhere: no volume, no DuckDB file, no source
                fetch. Ninety-nine tests skip. A skip is accepted ONLY if it
                carries a reason registered in tests/_data.py, so nothing can
                be switched off by inventing a new excuse.

  --mode full   The machine that holds data/observatory.duckdb and
                data/equity.duckdb. Here a data-absence skip is a FAILURE:
                these are the tests that exercise the numbers, and if they
                did not run, nothing did.

Both modes refuse a suite that has quietly shrunk. That is not paranoia: a
setUpClass raising SkipTest removes its tests from the run count without
removing them from the file (tests/test_sec.py does exactly this, and four
tests leave the tally when data/sec.duckdb is absent).

Run from observatory/:
    ./.venv/bin/python ci/suite.py --mode ci
    ./.venv/bin/python ci/suite.py --mode full

See docs/plans/PLAN-CI-CD.md §2.
"""
from __future__ import print_function

import argparse
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The floor. Raise it as the suite grows; never lower it to make a run pass.
# 219 tests are collected as of 2026-09-16.
MIN_TESTS = 210


def _ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            for inner in _ids(test):
                yield inner
        else:
            yield test


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("ci", "full"), required=True)
    ap.add_argument("--min-tests", type=int, default=MIN_TESTS)
    ap.add_argument("--strict", action="store_true",
                    help="in full mode, also fail on tests skipped because a "
                         "slice of local data was never built")
    args = ap.parse_args(argv)

    os.chdir(str(ROOT))
    sys.path.insert(0, str(ROOT))
    from tests import _data

    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    collected = list(_ids(suite))
    broken = [t.id() for t in collected if "_FailedTest" in type(t).__name__]

    print("mode=%s  python=%d.%d  collected=%d  macro=%s equity=%s sec=%s"
          % ((args.mode,) + sys.version_info[:2] + (len(collected),
             _data.MACRO, _data.EQUITY, _data.SEC)))
    print("")

    result = unittest.TextTestRunner(verbosity=1).run(suite)

    problems = []
    if broken:
        problems.append("%d test module(s) could not be imported: %s"
                        % (len(broken), ", ".join(broken)))
    if len(collected) < args.min_tests:
        problems.append("only %d tests collected, floor is %d — a module or a "
                        "class has gone missing" % (len(collected), args.min_tests))

    absent, partial, unregistered = [], [], []
    for test, reason in result.skipped:
        if reason in _data.ABSENT:
            absent.append((test.id(), reason))
        elif reason in _data.PARTIAL:
            partial.append((test.id(), reason))
        else:
            unregistered.append((test.id(), reason))

    # Neither mode tolerates a skip nobody registered. That is the whole
    # mechanism: a test can be excused for want of data, and for nothing else.
    for tid, reason in unregistered:
        problems.append("%s skipped for an unregistered reason: %r — register "
                        "it in tests/_data.py or fix the test" % (tid, reason))

    if args.mode == "full":
        for tid, reason in absent:
            problems.append("%s skipped: %r — this is supposed to be the "
                            "machine with the data" % (tid, reason))

    print("")
    print("ran %d, failures %d, errors %d, skipped %d "
          "(%d database absent, %d slice not built locally)"
          % (result.testsRun, len(result.failures), len(result.errors),
             len(result.skipped), len(absent), len(partial)))

    if partial:
        # Loud on every run, on purpose. These tests exist, they are not
        # running here, and the reason is one command away — which is exactly
        # the kind of gap that becomes permanent once it stops being printed.
        by_reason = {}
        for tid, reason in partial:
            by_reason.setdefault(reason, []).append(tid)
        print("")
        print("NOT RUN ON THIS MACHINE — a slice of local data was never built:")
        for reason, tids in sorted(by_reason.items()):
            print("  %d tests: %s" % (len(tids), reason))
            print("      fill it with: %s" % _data.PARTIAL[reason])
        if args.strict:
            problems.append("--strict: %d tests did not run for want of a "
                            "local data slice" % len(partial))

    if problems:
        print("")
        print("SKIP POLICY / SUITE SIZE:")
        for p in problems:
            print("  %s" % p)

    return 0 if (result.wasSuccessful() and not problems) else 1


if __name__ == "__main__":
    sys.exit(main())
