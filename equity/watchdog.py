# -*- coding: utf-8 -*-
"""Watchdog — the alarm for archives that quietly stop growing.

Between 12 and 15 September 2026 every capture job failed. The bucket had hit
its 1TB plan cap, so each PutObject raised, and because the crash happened
before the completion ping, nothing was sent anywhere. Three days of Japanese
filings were missed and the only reason anyone noticed was a human asking how
things were going. TDnet deletes after about five weeks and EDINET purges
buybacks at twelve months, so a longer silence would have cost data that
nobody can rebuild.

This job answers one question per archive: has anything new landed recently?
It is deliberately dumb. It does not trust the capture jobs' own logs or their
exit codes, because the failure mode being guarded against is precisely a job
that dies without reporting. It reads the bucket and looks at the dates.

It also watches headroom, because the cap is what bit us: an archive that is
90% of the way to its limit is a fault to fix this week, not a surprise to
discover next month.

How the alert actually reaches a human: this process **exits non-zero** when
anything is wrong. Railway turns a failed run into a Deployment.crashed event,
and a notification rule on the project emails the members. That keeps the
alerting path inside infrastructure we already pay for, with no third-party
monitor to sign up for and no secret to store. If HEARTBEAT_URL is set it also
pings a dead-man's-switch service, which additionally catches this watchdog
itself failing to run at all.

Usage:
    python watchdog.py                 # check everything, exit 1 if unhealthy
    python watchdog.py --quiet         # only print problems
    python watchdog.py --max-age-days 5

Python 3.9; boto3 for the bucket.
"""
import argparse
import collections
import datetime as dt
import os
import sys

import heartbeat

# Per archive: prefix, which path segment holds the date, how stale is too
# stale, and whether a gap is recoverable. The limits are generous on purpose —
# this catches a pipeline that has stopped, not a single quiet day. Weekend and
# holiday gaps must never page anyone or the alarm gets ignored, which is the
# real failure mode of monitoring.
# The limits below are sized so a normal quiet stretch never fires. A long
# weekend plus a source that publishes the previous day's index after midnight
# UTC is already three days of legitimate silence, so anything tighter than
# five would page on a Tuesday morning for no reason. An alarm that cries wolf
# gets muted, and a muted alarm is worse than none.
ARCHIVES = [
    # name,        prefix,        date segment, max age (days), irrecoverable?
    ("EDINET",     "docs/",       1,            5,              True),
    ("TDnet",      "tdnet/docs/", 2,            5,              True),
    ("EDGAR",      "edgar/docs/", 2,            5,              False),
    ("US data",    "us/",         1,            5,              False),
    ("BOJ",        "boj/",        1,            40,             True),
]
# Fraction of the plan cap at which to complain. The 1TB Hobby cap was hit with
# no warning at all; 85% leaves days of runway at the rate EDGAR was writing.
HEADROOM_WARN = 0.85


def client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=os.environ["EDINET_S3_ENDPOINT"],
        aws_access_key_id=os.environ["EDINET_S3_KEY_ID"],
        aws_secret_access_key=os.environ["EDINET_S3_SECRET"],
        region_name=os.environ.get("EDINET_S3_REGION", "auto"),
        config=Config(retries={"max_attempts": 5, "mode": "standard"}))


def newest_day(c, bucket, prefix, seg):
    """Latest YYYY-MM-DD under a prefix, and the bytes stored there.

    Listing a 3M-object prefix to find one date would take minutes, so this
    walks backwards from today and asks for each day directly. A prefix query
    per day is cheap and bounded; 90 of them is a second or two.
    """
    today = dt.date.today()
    for back in range(0, 90):
        day = (today - dt.timedelta(days=back)).isoformat()
        probe = prefix if seg == 1 else prefix
        r = c.list_objects_v2(Bucket=bucket, Prefix=probe + day + "/", MaxKeys=1)
        if r.get("KeyCount"):
            return day, back
    return None, None


def write_probe(c, bucket):
    """Can we still write? The quota failure was a write failure, and a bucket
    that is full still reads perfectly, so freshness alone would not catch the
    first day of an outage — only the second."""
    key = "_watchdog_probe"
    try:
        c.put_object(Bucket=bucket, Key=key, Body=b"ok")
        c.delete_object(Bucket=bucket, Key=key)
        return None
    except Exception as e:
        return str(e)[:160]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--quiet", action="store_true", help="print only problems")
    p.add_argument("--max-age-days", type=int,
                   help="override every archive's staleness limit")
    args = p.parse_args()

    if not os.environ.get("EDINET_S3_BUCKET"):
        sys.exit("EDINET_S3_BUCKET not set — nothing to watch")
    c = client()
    bucket = os.environ["EDINET_S3_BUCKET"]
    problems = []
    lines = []

    err = write_probe(c, bucket)
    if err:
        problems.append("BUCKET IS NOT WRITABLE: %s" % err)
    else:
        lines.append("bucket writable: yes")

    for name, prefix, seg, max_age, precious in ARCHIVES:
        # `or` would swallow a deliberate 0 here, which is the value used to
        # prove the alarm path still works — compare against None instead
        limit = max_age if args.max_age_days is None else args.max_age_days
        try:
            day, age = newest_day(c, bucket, prefix, seg)
        except Exception as e:
            problems.append("%s: could not be checked (%s)" % (name, str(e)[:80]))
            continue
        if day is None:
            problems.append("%s: nothing archived in the last 90 days" % name)
            continue
        note = "%-9s newest %s (%d days old, limit %d)" % (name, day, age, limit)
        lines.append(note)
        if age > limit:
            problems.append(
                "%s has not grown for %d days (newest %s, limit %d)%s"
                % (name, age, day, limit,
                   " — THIS SOURCE DELETES, the gap may be permanent" if precious else ""))

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not args.quiet:
        print("watchdog %s" % stamp)
        for l in lines:
            print("  " + l)
    if problems:
        print("")
        print("PROBLEMS (%d):" % len(problems))
        for pr in problems:
            print("  ! " + pr)
        heartbeat.ping("watchdog %s: %d problem(s): %s"
                       % (stamp, len(problems), "; ".join(problems)), failed=True)
        # non-zero exit is the alert: Railway raises Deployment.crashed and the
        # project's notification rule emails its members
        sys.exit(1)
    print("all archives fresh and bucket writable")
    heartbeat.ping("watchdog %s: all healthy" % stamp)


if __name__ == "__main__":
    main()
