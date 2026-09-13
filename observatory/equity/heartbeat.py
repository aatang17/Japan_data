# -*- coding: utf-8 -*-
"""Dead-man's-switch ping for the nightly equity refresh.

The failure that actually hurts is silence: a job that stops running produces
no error, no log and no alert, and the data just quietly stops moving. So the
refresh pings a URL when it finishes, and the monitoring service alerts when a
ping FAILS TO ARRIVE. Silence is the alarm, which is the only way to catch a
job that is not running at all.

A deliberate second copy. The capture jobs deploy from `equity/` in the repo
root and this runs inside the observatory container, which ships only
`observatory/`. Two twenty-line copies of a stdlib POST is the honest cost of
two separately deployed images; importing across the boundary would work on a
laptop and fail in production, which is worse than duplication.

Set HEARTBEAT_URL (healthchecks.io, Cronitor, Better Stack, anything with a
ping URL). Unset is a no-op, so local runs are silent. A ping never raises:
monitoring must not be able to break the thing it monitors.
Python 3.9; stdlib only.
"""
import os
import urllib.request

TIMEOUT = 10


def ping(summary, failed=False):
    """POST `summary` to HEARTBEAT_URL (or its /fail variant). Never raises."""
    url = os.environ.get("HEARTBEAT_URL")
    if not url:
        return
    if failed:
        url = url.rstrip("/") + "/fail"
    try:
        req = urllib.request.Request(
            url, data=summary.encode("utf-8"),
            headers={"User-Agent": "observatory-refresh/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read()
    except Exception as e:                   # a dead monitor is not a dead job
        print("heartbeat ping failed (ignored): %s" % e)
