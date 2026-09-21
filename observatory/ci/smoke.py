# -*- coding: utf-8 -*-
"""Ask a running site whether it is still serving fresh, sound numbers.

This is the tier that would have caught the two incidents no test suite could:
July CPI fetched, archived and never published while the site served June for
three weeks; and the 5% filings stopping on 2026-08-06 with nothing noticing
for four weeks. Both times every page rendered, every endpoint answered 200,
and the numbers were old.

Standard library only — no install step, so the watchdog workflow is a
checkout and a python call.

    python ci/smoke.py                                   # production
    python ci/smoke.py --base-url http://127.0.0.1:8007  # a local server
    python ci/smoke.py --post-deploy                     # staleness warns

Exit code 0 if every check passes, 1 with a list of what failed.

See docs/plans/PLAN-CI-CD.md §2.
"""
from __future__ import print_function

import argparse
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE = "https://ploveranalytics.com"
TIMEOUT = 30
UA = "plover-analytics-smoke/1.0 (+https://ploveranalytics.com)"


class Site(object):
    def __init__(self, base):
        self.base = base.rstrip("/")

    def get(self, path, tries=3):
        """(status, body). Retries a transport error, never a status."""
        url = self.base + path
        last = None
        for attempt in range(tries):
            try:
                r = urlopen(Request(url, headers={"User-Agent": UA}),
                            timeout=TIMEOUT)
                return r.getcode(), r.read().decode("utf-8", "replace")
            except HTTPError as exc:  # a status IS the answer; don't retry
                return exc.code, exc.read().decode("utf-8", "replace")
            except (URLError, OSError) as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
        raise SystemExit("%s is unreachable: %s" % (url, last))

    def json(self, path):
        status, body = self.get(path)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None


def check_catalog(site, problems, notes):
    status, body = site.json("/api/v1/catalog/datasets")
    if status != 200 or not body:
        problems.append("/api/v1/catalog/datasets answered %s" % status)
        return
    slugs = [d.get("slug") for d in body.get("datasets", [])]
    notes.append("catalog lists %d datasets" % len(slugs))
    for expected in ("cpi-jp", "jgb-yields", "boj-assets"):
        if expected not in slugs:
            problems.append("the catalog no longer lists %s" % expected)


def check_health(site, problems, notes, post_deploy):
    """The freshness contract. `strict=1` answers 503 once the refresh
    heartbeat passes REFRESH_MAX_AGE_HOURS or a dataset goes stale."""
    status, body = site.json("/api/v1/catalog/health?strict=1")
    if body is None:
        problems.append("/api/v1/catalog/health did not return JSON (%s)" % status)
        return
    notes.append("last ingest %s (%s hours ago), refresh_overdue=%s"
                 % (body.get("last_ingest_at"), body.get("hours_since_ingest"),
                    body.get("refresh_overdue")))
    complaints = []
    if body.get("refresh_overdue"):
        complaints.append("the refresh loop has not stamped a heartbeat for "
                          "%s hours (limit %s)"
                          % (body.get("hours_since_ingest"),
                             body.get("refresh_max_age_hours")))
    for d in body.get("datasets", []):
        if d.get("status") == "attention":
            complaints.append("%s: stale=%s unpublished_artifact=%s latest=%s"
                              % (d.get("dataset"), d.get("stale"),
                                 d.get("unpublished_artifact"),
                                 d.get("latest_period")))
    for d in body.get("equity_extractors", []):
        if d.get("status") == "attention":
            complaints.append("equity/%s: archive read only through %s (%s days "
                              "behind)" % (d.get("dataset"),
                                           d.get("archive_read_through"),
                                           d.get("days_behind")))
    if not complaints and status != 200:
        complaints.append("strict health answered %s with nothing marked "
                          "attention — read the report by hand" % status)
    for c in complaints:
        (notes if post_deploy else problems).append(
            ("stale (warning, --post-deploy): " if post_deploy else "") + c)


def check_numbers(site, problems, notes):
    """One real number, end to end, with the trust contract on it."""
    status, body = site.json("/api/v1/cpi-jp/overview")
    if status != 200 or not body:
        problems.append("/api/v1/cpi-jp/overview answered %s" % status)
        return
    release = body.get("release") or {}
    notes.append("cpi-jp latest period %s (release %s)"
                 % (release.get("latest_period"), release.get("label")))
    if not release.get("latest_period"):
        problems.append("cpi-jp serves no latest period")
    tiles = body.get("tiles") or []
    if not tiles:
        problems.append("cpi-jp serves no headline tiles")
    for tile in tiles:
        key, trust = tile.get("key"), tile.get("trust")
        if trust not in ("official", "derived", "model"):
            problems.append("tile %s carries an unknown trust value %r"
                            % (key, trust))
        # A calculated rate carries its formula. This is the trust contract,
        # and it is the one thing on the page a customer cannot verify for
        # themselves if it goes missing.
        if trust == "derived" and not (tile.get("calc") or "").strip():
            problems.append("tile %s is derived but carries no formula" % key)
        value = tile.get("value")
        if value is not None and not isinstance(value, (int, float)):
            problems.append("tile %s has a non-numeric value %r" % (key, value))
    headline = [t for t in tiles if t.get("key") == "headline_yoy"]
    if not headline:
        problems.append("cpi-jp has no headline_yoy tile")
    elif headline[0].get("value") is None:
        problems.append("cpi-jp headline YoY is missing — a gap is honest on a "
                        "chart, but not for the newest month of the headline")


def check_pages(site, problems, notes):
    for path, must in (("/cpi.html", "Latest reading"),
                       ("/company.html?code=7203", None),
                       ("/", None)):
        status, body = site.get(path)
        if status != 200:
            problems.append("%s answered %s" % (path, status))
            continue
        if not re.search(r'(?is)<meta[^>]+name=["\']description["\']', body):
            problems.append("%s is served with no meta description" % path)
        if must and must not in body:
            problems.append("%s no longer serves its prerendered figures "
                            "(%r absent) — a crawler sees an empty page"
                            % (path, must))
    notes.append("pages served with descriptions and prerendered figures")


def check_crawlable(site, problems, notes):
    for path in ("/sitemap.xml", "/sitemap-pages.xml", "/robots.txt"):
        status, body = site.get(path)
        if status != 200:
            problems.append("%s answered %s" % (path, status))
        elif path == "/robots.txt" and "Sitemap:" not in body:
            problems.append("robots.txt no longer names the sitemap")
    notes.append("robots.txt and both sitemaps answer")


CHECKS = (("catalog", check_catalog),
          ("numbers", check_numbers),
          ("pages", check_pages),
          ("crawlable", check_crawlable))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--post-deploy", action="store_true",
                    help="report staleness as a warning rather than a failure: "
                         "a container that has just booted may not have "
                         "stamped a heartbeat yet")
    args = ap.parse_args(argv)

    site = Site(args.base_url)
    problems, notes = [], []
    print("smoke: %s" % site.base)
    for name, fn in CHECKS:
        before = len(problems)
        fn(site, problems, notes)
        print("%-5s %s" % ("FAIL" if len(problems) > before else "ok", name))
    before = len(problems)
    check_health(site, problems, notes, args.post_deploy)
    print("%-5s %s" % ("FAIL" if len(problems) > before else "ok", "freshness"))

    print("")
    for n in notes:
        print("  %s" % n)
    if problems:
        print("")
        print("%d problem(s):" % len(problems))
        for p in problems:
            print("  %s" % p)
        return 1
    print("")
    print("the site is serving, fresh, and every number carries its provenance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
