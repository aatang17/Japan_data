# -*- coding: utf-8 -*-
"""Dead-man's-switch ping for the capture jobs.

The failure that actually hurts is a job that never runs: a cron that stops
firing produces no error, no log and no alert — the archive just quietly
stops growing. So each job pings a URL when it finishes; the monitoring
service alerts when a ping *fails to arrive*. Silence is the alarm.

Set HEARTBEAT_URL per service (healthchecks.io, Cronitor, Better Stack —
anything that exposes a ping URL). Unset = no-op, so local runs are silent.
A ping never raises: monitoring must not be able to break the capture.
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
            headers={"User-Agent": "observatory-capture/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read()
    except Exception as e:                      # a dead monitor is not a dead job
        print("heartbeat ping failed (ignored): %s" % e)
